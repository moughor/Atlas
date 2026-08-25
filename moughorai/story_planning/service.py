'''Bounded story decomposition and deterministic repository reconciliation.'''

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re

from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    CodeSubjectResolutionStatus,
)
from moughorai.llm import LlmClient, LlmMessage, LlmProviderError, LlmRequest
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_search import SemanticSearchRequest
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import ResolutionStatus, SubjectQuery

from .models import (
    StoryDiscoveryHit,
    StoryEvidence,
    StoryImplementationItem,
    StoryPlan,
    StoryPlanningConfiguration,
    StoryPlanningRequest,
    StoryRepresentedTest,
    StoryRequirement,
    StoryRequirementClassification,
    StoryRequirementStatus,
)


_logger = logging.getLogger(__name__)

_BULLET = re.compile(r'^\s*[-*]\s+(?P<text>\S.*)$')
_NUMBERED = re.compile(r'^\s*(?:R\s*)?\d+[.)]\s*(?P<text>\S.*)$', re.IGNORECASE)
_IDENTIFIER = re.compile(r'\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*\b')
_CALL = re.compile(r'\b(?:call|invoke)\s+([A-Za-z_$][A-Za-z0-9_$]*)', re.IGNORECASE)
_SOURCE_IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_POSTAMBLE = (
    'for each requirement, return',
    'also show the represented',
    'return exactly one status',
)
_ANCHOR_STOPWORDS = frozenset({
    'accept', 'accepted', 'against', 'all', 'also', 'and', 'against', 'are',
    'call', 'close', 'compare', 'current', 'date', 'exactly', 'files', 'fix',
    'for', 'from', 'identify', 'implementation', 'invalid', 'is', 'item',
    'jira', 'method', 'modification', 'need', 'not', 'one', 'only', 'or',
    'other', 'others', 'project', 'projects', 'represented', 'requirement',
    'requirements', 'return', 'set', 'show', 'source', 'status', 'the',
    'this', 'true', 'type', 'when', 'which', 'with', 'would',
})
_CLASSIFICATIONS = {item.value: item for item in StoryRequirementClassification}

_GENERIC_ACCESSOR_NAMES = frozenset({
    'exerciseid', 'sessionid', 'projectid', 'id', 'name', 'type',
    'status', 'state', 'value', 'key', 'code', 'description',
    'title', 'version', 'date', 'number', 'size', 'count',
    'ecasid', 'userid', 'scopeid', 'batchid',
})


@dataclass(frozen=True, slots=True)
class _RequirementSeed:
    text: str
    classification: StoryRequirementClassification
    source: str = 'deterministic'


@dataclass(frozen=True, slots=True)
class _SourceDocument:
    canonical_subject_id: str
    display_name: str
    project: str
    path: str
    start_line: int
    end_line: int
    text: str

    @property
    def source_ref(self) -> str:
        return f'{self.path}#L{self.start_line}-L{self.end_line}'


@dataclass(frozen=True, slots=True)
class _SourceFact:
    anchor: str
    canonical_subject_id: str
    display_name: str
    project: str
    source_ref: str
    line: int
    evidence: StoryEvidence


class StoryPlanningService:
    '''Build a deterministic plan from existing runtime authorities and bounded source spans.'''

    def __init__(
        self,
        runtime_session: RepositoryRuntimeSession,
        *,
        workspace_root: str | Path,
        llm_client: LlmClient | None = None,
    ) -> None:
        if not isinstance(runtime_session, RepositoryRuntimeSession):
            raise TypeError('story planner requires a repository runtime session')
        self._session = runtime_session
        self._workspace_root = Path(workspace_root).resolve()
        self._client = llm_client

    def plan(
        self,
        snapshot: AtlasSemanticSnapshot,
        request: StoryPlanningRequest,
    ) -> StoryPlan:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError('story planner requires a validated semantic snapshot')
        if not isinstance(request, StoryPlanningRequest):
            raise TypeError('story planner requires a StoryPlanningRequest')
        if request.snapshot_id != snapshot.snapshot_id:
            raise ValueError('story planning request belongs to another snapshot')

        seeds, provider_used, extraction_limitations = _extract_requirements(
            request.story_text,
            request.configuration,
            self._client,
        )
        runtime = self._session.runtime_for(snapshot)
        java = runtime.java_code_intelligence
        index = java.callable_index
        entries = {
            item.canonical_subject_id: item
            for item in (index.entries if index is not None else ())
        }

        selected_result = None
        report = None
        subject_status = 'not_selected'
        if request.subject is not None:
            selected_result = java.query(
                request.subject,
                kind='method',
                project=request.project,
                configuration=_code_configuration(request.configuration),
            )
            subject_status = selected_result.resolution.status.value
            report = selected_result.report

        selected_name = (
            report.subject.name if report is not None else None
        )
        anchors = request.discovery_anchors or _story_anchors(
            request.story_text,
            request.configuration.max_anchors,
            selected_name=selected_name,
        )
        discovery, discovery_limitations = _discover(
            runtime,
            anchors,
            request.project,
            request.configuration,
            entries,
        )

        if request.subject is None:
            selected_result, report = _autoselect_anchor_subject(
                java,
                discovery,
                request.project,
                request.configuration,
            )
            if selected_result is not None:
                subject_status = selected_result.resolution.status.value

        documents, source_limitations = _source_documents(
            self._workspace_root,
            report,
            entries,
            request.project,
            request.configuration,
        )
        source_facts = _source_facts(
            snapshot.snapshot_id,
            anchors,
            documents,
        )
        relationship_evidence = _relationship_evidence(report, entries)
        requirements = _reconcile_requirements(
            seeds,
            anchors,
            discovery,
            source_facts,
            relationship_evidence,
            report is not None,
        )
        surface = _implementation_surface(
            report,
            entries,
            discovery,
            request.configuration,
        )
        represented_tests, test_limitations = _represented_tests(
            report,
            entries,
            request.configuration,
        )
        remediation = tuple(
            item.requirement_id
            for item in requirements
            if item.classification is StoryRequirementClassification.REMEDIATION
        )
        unresolved = _unresolved_questions(requirements, report is not None)
        limitations = {
            *extraction_limitations,
            *discovery_limitations,
            *source_limitations,
            *test_limitations,
        }
        if report is None:
            limitations.add(
                'No exact authoritative Java anchor subject was resolved; '
                'implementation and TEST projections remain fail-closed.'
            )
        else:
            limitations.update(report.general_limitations)
        if documents:
            limitations.add(
                'Source text was read only from ASS-indexed workspace-relative '
                'callable spans. The ASS does not bind source content bytes, so '
                'lexical source matches alone do not prove business behavior.'
            )
        limitations.add(
            'Represented TEST roots are inspection/run candidates, not runtime coverage '
            'or behavioral proof.'
        )

        anchor_subjects = (
            (report.subject.canonical_id,) if report is not None else ()
        )
        return StoryPlan(
            request.story_fingerprint,
            request.plan_fingerprint,
            snapshot.snapshot_id,
            request.story_text,
            requirements,
            anchors,
            discovery,
            anchor_subjects,
            surface,
            represented_tests,
            unresolved,
            remediation,
            tuple(limitations),
            provider_used,
            subject_status,
        )


def _code_configuration(
    configuration: StoryPlanningConfiguration,
) -> CodeIntelligenceConfiguration:
    relationships = max(
        configuration.max_implementation_items,
        configuration.max_represented_tests,
    )
    return CodeIntelligenceConfiguration(
        max_depth=8,
        max_nodes=4_096,
        max_direct_relationships=relationships,
        max_paths_per_section=configuration.max_represented_tests,
        max_limitation_representatives=8,
        max_resolution_candidates=8,
        max_candidates_per_call_site=8,
    )


def _extract_requirements(
    story: str,
    configuration: StoryPlanningConfiguration,
    client: LlmClient | None,
) -> tuple[tuple[_RequirementSeed, ...], bool, tuple[str, ...]]:
    body = _story_body(story)
    structured = _structured_requirement_texts(body)
    if structured:
        limited = structured[:configuration.max_requirements]
        limitations = (
            (
                f'Requirement extraction reached the deterministic '
                f'{configuration.max_requirements}-requirement bound.'
            ),
        ) if len(structured) > len(limited) else ()
        return tuple(
            _RequirementSeed(text, _classify_requirement(text))
            for text in limited
        ), False, limitations

    provider_limitation: str | None = None
    if client is not None:
        try:
            proposed = _provider_requirement_quotes(
                client,
                body,
                configuration,
            )
        except (LlmProviderError, TimeoutError, TypeError, ValueError, json.JSONDecodeError) as exc:
            proposed = ()
            provider_limitation = (
                f'Provider requirement decomposition was unavailable '
                f'({type(exc).__name__}); deterministic fallback retained the story.'
            )
        if proposed:
            return proposed, True, ()
        if provider_limitation is None:
            provider_limitation = (
                'Provider requirement decomposition returned no validated story '
                'quotes; deterministic fallback retained the story.'
            )

    fallback = ' '.join(body.split())
    limitations = (
        provider_limitation or
        'No explicit requirement-list structure was detected; the story is retained '
        'as one unresolved deterministic requirement.',
    )
    return (
        _RequirementSeed(fallback, _classify_requirement(fallback)),
    ), False, limitations


def _story_body(story: str) -> str:
    lines = story.splitlines()
    retained = []
    for line in lines:
        folded = ' '.join(line.casefold().split())
        if any(folded.startswith(marker) for marker in _POSTAMBLE):
            break
        retained.append(line)
    body = '\n'.join(retained).strip()
    return body or story


def _structured_requirement_texts(body: str) -> tuple[str, ...]:
    lines = body.splitlines()
    numbered_mode = any(_NUMBERED.match(line) for line in lines)
    values: list[str] = []
    current: list[str] = []
    for line in lines:
        match = _NUMBERED.match(line) if numbered_mode else _BULLET.match(line)
        if match is not None:
            if current:
                values.append(' '.join(current))
            current = [match.group('text').strip()]
            continue
        if current and line.strip():
            current.append(line.strip())
        elif current and not line.strip():
            current.append(' ')
    if current:
        values.append(' '.join(current))
    return tuple(' '.join(item.split()) for item in values if item.strip())


def _provider_requirement_quotes(
    client: LlmClient,
    body: str,
    configuration: StoryPlanningConfiguration,
) -> tuple[_RequirementSeed, ...]:
    response = client.complete(LlmRequest(
        (
            LlmMessage(
                'system',
                'Decompose the supplied story only. Return strict JSON with one '
                'requirements array. Each item may contain only source_quote and '
                'classification. source_quote must be an exact story excerpt. '
                'Do not claim repository facts, files, methods, or implementation status.',
            ),
            LlmMessage('user', body),
        ),
        temperature=0.0,
        maximum_output_tokens=configuration.provider_output_tokens,
        metadata={'consumer': 'story-planning-requirement-decomposition'},
    ))
    raw = response.text.strip()
    if not raw or len(raw) > 16_384:
        return ()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping) or set(payload) != {'requirements'}:
        return ()
    items = payload['requirements']
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return ()
    collapsed = ' '.join(body.split())
    folded = collapsed.casefold()
    proposed: list[tuple[int, _RequirementSeed]] = []
    for item in items[:configuration.max_requirements]:
        if not isinstance(item, Mapping) or not set(item).issubset({
            'source_quote', 'classification'
        }) or 'source_quote' not in item:
            continue
        quote = item['source_quote']
        if not isinstance(quote, str):
            continue
        normalized_quote = ' '.join(quote.split())
        if len(normalized_quote) < 8:
            continue
        offset = folded.find(normalized_quote.casefold())
        if offset < 0:
            continue
        exact_story_text = collapsed[offset:offset + len(normalized_quote)]
        raw_classification = item.get('classification')
        classification = (
            _CLASSIFICATIONS.get(str(raw_classification).strip().casefold())
            if raw_classification is not None else None
        ) or _classify_requirement(exact_story_text)
        proposed.append((offset, _RequirementSeed(
            exact_story_text,
            classification,
            'provider_proposed_story_quote',
        )))
    unique: dict[str, tuple[int, _RequirementSeed]] = {}
    for offset, item in proposed:
        unique.setdefault(item.text.casefold(), (offset, item))
    return tuple(item for _, item in sorted(unique.values(), key=lambda value: value[0]))


def _classify_requirement(text: str) -> StoryRequirementClassification:
    folded = text.casefold()
    if any(term in folded for term in (
        'drm', 'remediation', 'production deployment', 'production fix',
        'data repair', 'operational',
    )):
        return StoryRequirementClassification.REMEDIATION
    if re.search(r'\b(call|invoke)\b', folded):
        return StoryRequirementClassification.COLLABORATION
    if any(term in folded for term in (
        'status', 'state', 'close ', 'closed', 'signed', 'current date',
    )):
        return StoryRequirementClassification.STATE_TRANSITION
    if any(term in folded for term in ('accept', 'eligible', 'agreementtype', 'callcasetype')):
        return StoryRequirementClassification.ELIGIBILITY
    if any(term in folded for term in ('reject', 'invalid', 'throw', 'error')):
        return StoryRequirementClassification.VALIDATION
    if any(term in folded for term in (' test', 'test ', 'verify')):
        return StoryRequirementClassification.TEST
    return StoryRequirementClassification.OTHER


def _story_anchors(
    story: str,
    maximum: int,
    *,
    selected_name: str | None,
) -> tuple[str, ...]:
    body = _story_body(story)
    values: list[str] = []
    if selected_name:
        values.append(selected_name)
    for match in _IDENTIFIER.finditer(body):
        value = match.group(0)
        folded = value.casefold()
        code_shaped = (
            '_' in value
            or (value.isupper() and len(value) >= 3)
            or any(left.islower() and right.isupper() for left, right in zip(value, value[1:]))
            or (
                len(value) >= 4
                and len(value) - len(value.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')) >= 2
                and any(character.islower() for character in value)
            )
        )
        if code_shaped and folded not in _ANCHOR_STOPWORDS:
            values.append(value)
    return tuple(dict.fromkeys(values))[:maximum]


def _discover(
    runtime,
    anchors: tuple[str, ...],
    project: str | None,
    configuration: StoryPlanningConfiguration,
    entries: Mapping[str, object],
) -> tuple[tuple[StoryDiscoveryHit, ...], tuple[str, ...]]:
    hits: list[StoryDiscoveryHit] = []
    limitations: set[str] = set()
    service = runtime.semantic_search
    for anchor in anchors:
        try:
            response = service.search_semantic(SemanticSearchRequest(
                anchor,
                project=project,
                limit=configuration.max_hits_per_anchor,
            ))
        except (TypeError, ValueError) as exc:
            limitations.add(
                f'Bounded discovery for {anchor} was unavailable ({type(exc).__name__}).'
            )
            continue
        if response.omitted_count:
            limitations.add(
                f'Bounded discovery for {anchor} omitted {response.omitted_count} candidate(s).'
            )
        for hit in response.hits:
            if project is not None and hit.project != project:
                continue
            entry = entries.get(hit.canonical_subject_id)
            source_ref = None
            if entry is not None:
                source_ref = _entry_source_ref(entry)
            else:
                resolution = runtime.resolver.resolve(SubjectQuery(
                    hit.canonical_subject_id,
                    project=project,
                ))
                if (
                    resolution.status is ResolutionStatus.RESOLVED
                    and resolution.subject is not None
                    and (project is None or resolution.subject.project == project)
                ):
                    source_ref = resolution.subject.path
            hits.append(StoryDiscoveryHit(
                anchor,
                hit.canonical_subject_id,
                hit.qualified_name,
                hit.kind.value,
                hit.project,
                source_ref,
                tuple(hit.evidence_ids),
            ))
    return tuple(hits), tuple(limitations)


def _autoselect_anchor_subject(
    java,
    discovery: tuple[StoryDiscoveryHit, ...],
    project: str | None,
    configuration: StoryPlanningConfiguration,
):
    for anchor in dict.fromkeys(item.anchor for item in discovery):
        candidates = []
        for hit in discovery:
            simple = hit.display_name.rpartition('#')[2].partition('(')[0].rpartition('.')[2]
            if (
                hit.anchor != anchor
                or hit.kind != 'method'
                or simple.casefold() != anchor.casefold()
            ):
                continue
            if simple.casefold() in _GENERIC_ACCESSOR_NAMES:
                continue
            try:
                result = java.query(
                    hit.canonical_subject_id,
                    kind='method',
                    project=project or hit.project,
                    configuration=_code_configuration(configuration),
                )
            except (ValueError, TypeError) as exc:
                _logger.debug(
                    'Skipping malformed code graph edge during anchor '
                    'auto-selection for %s: %s',
                    hit.canonical_subject_id,
                    exc,
                )
                continue
            if result.resolution.status is CodeSubjectResolutionStatus.RESOLVED:
                candidates.append(result)
        unique = {item.resolution.subject.canonical_id: item for item in candidates}
        if len(unique) == 1:
            result = next(iter(unique.values()))
            return result, result.report
    return None, None


def _source_documents(
    root: Path,
    report,
    entries: Mapping[str, object],
    project: str | None,
    configuration: StoryPlanningConfiguration,
) -> tuple[tuple[_SourceDocument, ...], tuple[str, ...]]:
    if report is None:
        return (), ()
    subject_ids = [report.subject.canonical_id]
    subject_ids.extend(
        item.canonical_target
        for item in report.direct_callees_high_confidence.items
    )
    subject_ids.extend(
        candidate
        for group in report.direct_callee_conservative_groups.items
        for candidate in group.included_candidate_ids
    )
    documents: list[_SourceDocument] = []
    limitations: set[str] = set()
    for subject_id in tuple(dict.fromkeys(subject_ids))[:configuration.max_source_subjects]:
        entry = entries.get(subject_id)
        if entry is None or entry.source_classification.value != 'production':
            continue
        if project is not None and entry.project_id != project:
            continue
        try:
            document = _read_entry_source(root, entry, configuration)
        except (OSError, UnicodeError, ValueError) as exc:
            limitations.add(
                f'Indexed source span for {subject_id} was unavailable '
                f'({type(exc).__name__}).'
            )
        else:
            documents.append(document)
    if len(tuple(dict.fromkeys(subject_ids))) > configuration.max_source_subjects:
        limitations.add(
            f'Source inspection reached the deterministic '
            f'{configuration.max_source_subjects}-subject bound.'
        )
    return tuple(documents), tuple(limitations)


def _read_entry_source(
    root: Path,
    entry,
    configuration: StoryPlanningConfiguration,
) -> _SourceDocument:
    relative = Path(*entry.source.path.split('/'))
    candidate = (root / relative).resolve()
    candidate.relative_to(root)
    metadata = candidate.stat()
    if not candidate.is_file() or metadata.st_size > configuration.max_source_file_bytes:
        raise ValueError('indexed source file is unavailable or oversized')
    payload = candidate.read_bytes()
    if len(payload) > configuration.max_source_file_bytes:
        raise ValueError('indexed source file is oversized')
    text = payload.decode('utf-8-sig')
    source_range = entry.source.declaration
    start = source_range.start.line
    end = source_range.end.line
    if end - start + 1 > configuration.max_source_lines_per_subject:
        raise ValueError('indexed source span exceeds the planning line bound')
    lines = text.splitlines()
    if start < 1 or end > len(lines):
        raise ValueError('indexed source span lies outside the current source file')
    return _SourceDocument(
        entry.canonical_subject_id,
        f'{entry.identity.owner_type}#{entry.identity.name}',
        entry.project_id,
        entry.source.path,
        start,
        end,
        '\n'.join(lines[start - 1:end]),
    )


def _source_facts(
    snapshot_id: str,
    anchors: tuple[str, ...],
    documents: tuple[_SourceDocument, ...],
) -> tuple[_SourceFact, ...]:
    facts: list[_SourceFact] = []
    for document in documents:
        for anchor in anchors:
            for offset in _anchor_lines(document.text, anchor):
                line = document.start_line + offset
                source_ref = f'{document.path}#L{line}'
                evidence_id = _evidence_id(
                    'source-anchor', snapshot_id, document.canonical_subject_id,
                    anchor, source_ref,
                )
                evidence = StoryEvidence(
                    evidence_id,
                    'indexed_source_anchor',
                    f'{anchor} occurs in the indexed source span for {document.display_name}.',
                    document.canonical_subject_id,
                    document.project,
                    source_ref,
                )
                facts.append(_SourceFact(
                    anchor,
                    document.canonical_subject_id,
                    document.display_name,
                    document.project,
                    source_ref,
                    line,
                    evidence,
                ))
    return tuple(facts)


def _anchor_lines(text: str, anchor: str) -> tuple[int, ...]:
    expected = _identifier_key(anchor)
    matches = []
    for offset, line in enumerate(text.splitlines()):
        for token in _SOURCE_IDENTIFIER.findall(line):
            actual = _identifier_key(token)
            if actual == expected or (
                len(expected) >= 8 and actual.endswith(expected)
            ):
                matches.append(offset)
                break
        if len(matches) == 8:
            break
    return tuple(matches)


def _identifier_key(value: str) -> str:
    return ''.join(character for character in value.casefold() if character.isalnum())


def _relationship_evidence(report, entries: Mapping[str, object]):
    if report is None:
        return {}
    result: dict[str, tuple[object, StoryEvidence]] = {}
    for relationship in report.direct_callees_high_confidence.items:
        entry = entries.get(relationship.canonical_target)
        if entry is None:
            continue
        result[entry.identity.name.casefold()] = (
            relationship,
            StoryEvidence(
                relationship.producer_evidence_id,
                'represented_direct_call',
                f'Represented direct call to {entry.identity.owner_type}#{entry.identity.name}.',
                entry.canonical_subject_id,
                entry.project_id,
                relationship.location.compact,
            ),
        )
    return result


def _reconcile_requirements(
    seeds: tuple[_RequirementSeed, ...],
    anchors: tuple[str, ...],
    discovery: tuple[StoryDiscoveryHit, ...],
    source_facts: tuple[_SourceFact, ...],
    relationships: Mapping[str, tuple[object, StoryEvidence]],
    subject_resolved: bool,
) -> tuple[StoryRequirement, ...]:
    facts_by_anchor: dict[str, list[_SourceFact]] = {}
    for fact in source_facts:
        facts_by_anchor.setdefault(fact.anchor.casefold(), []).append(fact)
    discovery_by_anchor: dict[str, list[StoryDiscoveryHit]] = {}
    for hit in discovery:
        discovery_by_anchor.setdefault(hit.anchor.casefold(), []).append(hit)

    requirements = []
    for ordinal, seed in enumerate(seeds, start=1):
        matched_anchors = tuple(
            anchor for anchor in anchors
            if _text_has_anchor(seed.text, anchor)
        )
        facts = tuple(
            fact
            for anchor in matched_anchors
            for fact in facts_by_anchor.get(anchor.casefold(), ())
        )
        candidate_ids = tuple(
            hit.canonical_subject_id
            for anchor in matched_anchors
            for hit in discovery_by_anchor.get(anchor.casefold(), ())
        )
        evidence = [fact.evidence for fact in facts]
        uncertainty: list[str] = []
        status = StoryRequirementStatus.NOT_PROVEN

        call_match = _CALL.search(seed.text)
        if seed.classification is StoryRequirementClassification.REMEDIATION:
            uncertainty.append(
                'Repository discovery cannot prove deployment timing, affected data, '
                'or an executable remediation procedure.'
            )
        elif call_match is not None and subject_resolved:
            target = call_match.group(1)
            represented = relationships.get(target.casefold())
            if represented is not None:
                relationship, call_evidence = represented
                evidence.append(call_evidence)
                qualifier_anchors = tuple(
                    anchor for anchor in matched_anchors
                    if anchor.casefold() != target.casefold()
                )
                qualifiers = tuple(
                    fact for fact in facts
                    if fact.anchor.casefold() != target.casefold()
                    and fact.canonical_subject_id == relationship.canonical_source
                )
                proven_qualifiers = {
                    item.anchor.casefold()
                    for item in qualifiers
                    if abs(
                        item.line - relationship.location.source_range.start.line
                    ) <= 3
                }
                if not qualifier_anchors or all(
                    anchor.casefold() in proven_qualifiers
                    for anchor in qualifier_anchors
                ):
                    status = StoryRequirementStatus.IMPLEMENTED
                else:
                    status = StoryRequirementStatus.PARTIAL
                    uncertainty.append(
                        'The represented call is proven, but its stated business '
                        'qualifier is not proven at the same bounded source site.'
                    )
            elif any(fact.anchor.casefold() == target.casefold() for fact in facts):
                status = StoryRequirementStatus.PARTIAL
                uncertainty.append(
                    'The target name occurs in inspected source, but no resolved direct '
                    'call relationship proves the invocation.'
                )
            elif source_facts:
                status = StoryRequirementStatus.MISSING
                uncertainty.append(
                    'No target occurrence or represented direct call was found in the '
                    'bounded selected implementation surface.'
                )
        elif facts and subject_resolved:
            status = StoryRequirementStatus.PARTIAL
            uncertainty.append(
                'Lexical source evidence is represented, but Atlas has no deterministic '
                'business-condition/state-transition semantic model for this claim.'
            )
        elif not subject_resolved:
            uncertainty.append(
                'No authoritative anchor subject was resolved in the requested project.'
            )
        else:
            uncertainty.append(
                'No sufficient represented source or call evidence proves this requirement.'
            )

        requirements.append(StoryRequirement(
            f'R{ordinal}',
            seed.text,
            seed.classification,
            status,
            tuple(evidence),
            candidate_ids,
            tuple(uncertainty),
            seed.source,
        ))
    return tuple(requirements)


def _implementation_surface(
    report,
    entries: Mapping[str, object],
    discovery: tuple[StoryDiscoveryHit, ...],
    configuration: StoryPlanningConfiguration,
) -> tuple[StoryImplementationItem, ...]:
    if report is None:
        return ()
    items: dict[str, StoryImplementationItem] = {}
    subject = report.subject
    items[subject.canonical_id] = StoryImplementationItem(
        subject.canonical_id,
        subject.display_name,
        'primary',
        subject.project,
        subject.source.compact,
        (_evidence_id('selected-subject', report.traceability.snapshot_id, subject.canonical_id),),
        True,
    )
    relationship_ids: dict[str, list[str]] = {}
    for relationship in report.direct_callees_high_confidence.items:
        relationship_ids.setdefault(relationship.canonical_target, []).append(
            relationship.producer_evidence_id
        )
    for target, evidence_ids in relationship_ids.items():
        entry = entries.get(target)
        if entry is None:
            continue
        items[target] = StoryImplementationItem(
            target,
            f'{entry.identity.owner_type}#{entry.identity.name}',
            'collaborator',
            entry.project_id,
            _entry_source_ref(entry),
            tuple(evidence_ids),
            True,
        )
    for group in report.direct_callee_conservative_groups.items:
        for target in group.included_candidate_ids:
            if target in items:
                continue
            entry = entries.get(target)
            if entry is None:
                continue
            items[target] = StoryImplementationItem(
                target,
                f'{entry.identity.owner_type}#{entry.identity.name}',
                'ambiguous collaborator candidate',
                entry.project_id,
                _entry_source_ref(entry),
                (group.producer_evidence_id,),
                False,
            )
    for hit in discovery:
        if hit.canonical_subject_id in items or hit.project is None:
            continue
        items[hit.canonical_subject_id] = StoryImplementationItem(
            hit.canonical_subject_id,
            hit.display_name,
            'repository candidate',
            hit.project,
            hit.source_ref,
            hit.evidence_ids,
            False,
        )
        if len(items) >= configuration.max_implementation_items:
            break
    return tuple(items.values())


def _represented_tests(
    report,
    entries: Mapping[str, object],
    configuration: StoryPlanningConfiguration,
) -> tuple[tuple[StoryRepresentedTest, ...], tuple[str, ...]]:
    if report is None:
        return (), ()
    relationships = report.direct_test_callers
    tests = []
    for relationship in relationships.items[:configuration.max_represented_tests]:
        entry = entries.get(relationship.canonical_source)
        if entry is None:
            continue
        tests.append(StoryRepresentedTest(
            entry.canonical_subject_id,
            entry.identity.name,
            entry.project_id,
            relationship.location.compact,
            relationship.producer_evidence_id,
        ))
    omitted = relationships.total_count - len(tests)
    limitations = (
        f'{omitted} represented TEST caller(s) were omitted by the '
        f'{configuration.max_represented_tests}-test planning bound.',
    ) if omitted else ()
    return tuple(tests), limitations


def _unresolved_questions(
    requirements: tuple[StoryRequirement, ...],
    subject_resolved: bool,
) -> tuple[str, ...]:
    questions = []
    if not subject_resolved:
        questions.append(
            'Which exact represented production method and project should anchor this story?'
        )
    for item in requirements:
        if item.status is StoryRequirementStatus.NOT_PROVEN:
            questions.append(
                f'{item.requirement_id}: what authoritative source or domain evidence '
                'establishes the requested behavior?'
            )
        elif item.status is StoryRequirementStatus.PARTIAL:
            questions.append(
                f'{item.requirement_id}: confirm the business semantics beyond the '
                'bounded lexical/call evidence.'
            )
        elif item.status is StoryRequirementStatus.MISSING:
            questions.append(
                f'{item.requirement_id}: confirm the intended implementation owner '
                'before changing code.'
            )
    return tuple(questions)


def _entry_source_ref(entry) -> str:
    source_range = entry.source.declaration
    return (
        f'{entry.source.path}#L{source_range.start.line}C{source_range.start.column}'
        f'-L{source_range.end.line}C{source_range.end.column}'
    )


def _text_has_anchor(text: str, anchor: str) -> bool:
    expected = _identifier_key(anchor)
    return any(
        _identifier_key(token) == expected
        for token in _IDENTIFIER.findall(text)
    )


def _evidence_id(kind: str, *parts: str) -> str:
    payload = json.dumps(
        (kind, *parts),
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'story-evidence:' + hashlib.sha256(payload).hexdigest()
