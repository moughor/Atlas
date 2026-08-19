'''Deterministic story-anchor quality and role-diverse root discovery.'''

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import re

from moughorai.story_planning import StoryPlan, normalize_story_text

from .models import AgentDiscoveredRoot, StoryAnchor


_IDENTIFIER = re.compile(r'\b[A-Za-z_$][A-Za-z0-9_$]*\b')
_INVOCATION = re.compile(
    r'\b[A-Za-z_$][A-Za-z0-9_$]*'
    r'(?:\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*\([^;\n]*?\))+'
)
_GENERIC = re.compile(r'\b[A-Za-z_$][A-Za-z0-9_$]*\s*<[^>\n]{1,160}>')
_QUOTED = re.compile(
    r'(?P<quote>\x22|\x27)(?P<value>[A-Za-z][A-Za-z0-9 _-]{1,80})(?P=quote)'
)


_CAMEL = re.compile(r'[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+')
_UI_PHRASES = (
    'search field', 'search button', 'press enter', 'vertical scrolling',
    'one topic per row', 'selected topic', 'selected project', 'reset behavior',
    'list', 'grid', 'button', 'selection', 'scrolling', 'panel', 'view',
)
_COMMON = frozenset({
    'a', 'add', 'all', 'an', 'and', 'as', 'at', 'be', 'by', 'change', 'current', 'data',
    'for', 'from', 'in', 'into', 'is', 'it', 'jira', 'new', 'of', 'on',
    'enter', 'matching', 'one', 'or', 'press', 'request', 'requirement', 'reset',
    'search', 'story', 'technical', 'the', 'this', 'to',
    'use', 'using', 'when', 'with', 'without',
})
_GENERIC_TECHNICAL = frozenset({'getinstance', 'get', 'set', 'id', 'value'})
_ROLE_ORDER = (
    'ui', 'controller', 'service_interface', 'service', 'persistence',
    'domain', 'integration', 'test', 'unknown', 'external_symbol',
)


@dataclass(slots=True)
class _Candidate:
    canonical_id: str
    kind: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_path: str | None
    source_span: dict[str, object] | None
    role: str
    score: int = 0
    matched: dict[str, StoryAnchor] = field(default_factory=dict)
    reasons: set[str] = field(default_factory=set)
    modes: set[str] = field(default_factory=set)
    evidence_ids: set[str] = field(default_factory=set)
    resolved: bool = False
    authority: str = 'atlas-story-discovery'


@dataclass(slots=True)
class PreparedStoryDiscovery:
    anchors: tuple[StoryAnchor, ...]
    semantic_anchors: tuple[str, ...]
    desired_roles: tuple[str, ...]
    candidates: dict[str, _Candidate]
    symbols_by_id: dict[str, dict[str, object]]
    weak_matches_penalized: int
    exact_matches: int
    source_candidates_considered: int


@dataclass(frozen=True, slots=True)
class StoryDiscoveryResult:
    anchors: tuple[StoryAnchor, ...]
    roots: tuple[AgentDiscoveredRoot, ...]
    diagnostics: dict[str, object]
    limitations: tuple[str, ...]
    omitted_root_count: int


def extract_story_anchors(story: str, *, maximum: int = 48) -> tuple[StoryAnchor, ...]:
    text = normalize_story_text(story)
    values: dict[str, StoryAnchor] = {}

    def retain(
        raw: str,
        start: int,
        anchor_type: str,
        strength: int,
        specificity: int,
        *,
        technical: bool = False,
        identifier: bool = False,
        exact: bool = False,
        semantic: bool = True,
        penalty: int = 0,
        provenance: str,
    ) -> None:
        cleaned = ' '.join(raw.split())
        normalized = _normalize(cleaned)
        if not normalized:
            return
        candidate = StoryAnchor(
            cleaned,
            normalized,
            anchor_type,
            strength,
            specificity,
            {'start': start, 'end': start + len(raw)},
            technical,
            identifier,
            exact,
            semantic,
            penalty,
            provenance,
        )
        current = values.get(normalized)
        if current is None or _anchor_sort_key(candidate) < _anchor_sort_key(current):
            values[normalized] = candidate

    technical_ranges = []
    for expression in (*_INVOCATION.finditer(text), *_GENERIC.finditer(text)):
        raw = expression.group(0)
        technical_ranges.append((expression.start(), expression.end(), raw))
        retain(
            raw,
            expression.start(),
            'invocation_expression' if '.' in raw and '(' in raw else 'technical_note',
            100,
            100,
            technical=True, exact=False, semantic=False,
            provenance='technical-note-expression',
        )
        for token in _IDENTIFIER.finditer(raw):
            name = token.group(0)
            if name in {'Integer', 'String'}:
                continue
            folded = name.casefold()
            penalty = (
                55 if folded in _GENERIC_TECHNICAL
                else 50 if folded in {'cache', 'topic', 'project'}
                else 0
            )
            retain(
                name,
                expression.start() + token.start(),
                'exact_identifier',
                98 if penalty == 0 else 82,
                98 if penalty == 0 else 45,
                technical=True,
                identifier=True,
                exact=True,
                semantic=penalty < 50,
                penalty=penalty,
                provenance=raw,
            )

    folded = text.casefold()
    for phrase in _UI_PHRASES:
        offset = folded.find(phrase)
        if offset >= 0:
            retain(
                text[offset:offset + len(phrase)], offset, 'ui_behavior', 62, 58,
                semantic=False, penalty=12, provenance='ui-behavior-phrase',
            )

    for match in _QUOTED.finditer(text):
        value = match.group('value')
        retain(
            value, match.start('value'), 'generic_domain_term', 72, 70,
            exact=True, semantic=True, penalty=10, provenance='quoted-domain-term',
        )

    for match in _IDENTIFIER.finditer(text):
        value = match.group(0)
        key = value.casefold()
        if key in _COMMON or key in values:
            continue
        camel = any(a.islower() and b.isupper() for a, b in zip(value, value[1:]))
        identifier = '_' in value or camel or any(ch.isdigit() for ch in value)
        acronym = value.isupper()
        title = value[:1].isupper() and value[1:].islower()
        in_technical = any(
            left <= match.start() < right for left, right, _ in technical_ranges
        )
        if acronym and len(value) <= 3:
            retain(
                value, match.start(), 'weak_lexical', 12, 10,
                identifier=True, semantic=False, penalty=80,
                provenance='short-uppercase-token',
            )
        elif identifier:
            retain(
                value, match.start(), 'exact_identifier', 88, 88,
                technical=in_technical, identifier=True, exact=True,
                semantic=True, penalty=0, provenance='java-like-identifier',
            )
        elif title and len(value) >= 4:
            penalty = 38 if key in {'project', 'topic', 'service', 'cache'} else 18
            retain(
                value, match.start(), 'business_entity', 58, 54,
                identifier=False, exact=False, semantic=penalty < 30,
                penalty=penalty, provenance='capitalized-domain-term',
            )

    ordered = tuple(sorted(values.values(), key=_anchor_sort_key))
    return ordered[:maximum]


def prepare_story_discovery(
    snapshot,
    entries,
    story: str,
    project: str | None,
    workspace_root: Path,
) -> PreparedStoryDiscovery:
    anchors = extract_story_anchors(story)
    desired_roles = _desired_roles(story, anchors)
    candidates: dict[str, _Candidate] = {}
    semantic_anchors = tuple(
        item.text for item in anchors
        if item.semantic_search_allowed and _effective_strength(item) >= 45
    )[:20]
    symbols = tuple(
        item for item in snapshot.semantic_context.get('symbols', ())
        if isinstance(item, dict)
    )
    symbols_by_id = {
        str(item.get('id')): item for item in symbols if item.get('id')
    }
    exact_matches = 0

    for anchor in anchors:
        if not anchor.exact_match_preferred or _effective_strength(anchor) < 35:
            continue
        key = anchor.normalized_text
        member_exact = (
            anchor.ambiguity_penalty < 25
            or (anchor.text[:1].islower() and len(anchor.text) >= 6)
        )
        matched_ids = set()
        for entry in entries.values():
            if project is not None and entry.project_id != project:
                continue
            name_match = member_exact and key == entry.identity.name.casefold()
            owner_match = (
                anchor.ambiguity_penalty < 25
                and key == _owner_simple_name(entry.identity.owner_type).casefold()
            )
            if not (name_match or owner_match):
                continue
            candidate = _candidate_from_entry(entry)
            _merge(
                candidates, candidate, anchor,
                440 + _effective_strength(anchor), 'exact_callable',
            )
            matched_ids.add(candidate.canonical_id)
        for symbol in symbols:
            if project is not None and symbol.get('project_id') != project:
                continue
            if str(symbol.get('name', '')).casefold() != key:
                continue
            symbol_kind = str(symbol.get('kind'))
            if symbol_kind not in {
                'type', 'method', 'field', 'constructor'
            }:
                continue
            if symbol_kind != 'type' and not member_exact:
                continue
            candidate = _candidate_from_symbol(symbol)
            if candidate is None:
                continue
            _merge(
                candidates, candidate, anchor,
                430 + _effective_strength(anchor), 'exact_symbol',
            )
            matched_ids.add(candidate.canonical_id)
        exact_matches += len(matched_ids)

    source_records = _snapshot_source_records(snapshot, workspace_root, project)
    type_symbols = tuple(
        item for item in symbols
        if item.get('kind') == 'type'
        and (project is None or item.get('project_id') == project)
        and _production_symbol(item)
    )
    for symbol in type_symbols:
        candidate = _candidate_from_symbol(symbol)
        if candidate is not None:
            _retain_role_candidate(candidates, candidate, anchors, desired_roles)
    for record in source_records:
        _retain_role_candidate(
            candidates,
            _candidate_from_source(record),
            anchors,
            desired_roles,
        )
    _retain_owner_member_matches(candidates, entries.values(), anchors)

    exact_by_anchor: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates.values():
        if candidate.modes & {'exact_callable', 'exact_symbol'}:
            for key in candidate.matched:
                exact_by_anchor[key].add(candidate.canonical_id)
    for ids in exact_by_anchor.values():
        if len(ids) == 1:
            candidate = candidates[next(iter(ids))]
            candidate.reasons.add(
                'Exact identity is unique in the bounded candidate set; PR172 '
                'authority is still required before it is classified as resolved.'
            )

    return PreparedStoryDiscovery(
        anchors,
        semantic_anchors,
        desired_roles,
        candidates,
        symbols_by_id,
        sum(item.anchor_type == 'weak_lexical' for item in anchors),
        exact_matches,
        len(type_symbols) + len(source_records),
    )


def complete_story_discovery(
    prepared: PreparedStoryDiscovery,
    plan: StoryPlan,
    entries,
    *,
    root_limit: int,
) -> StoryDiscoveryResult:
    candidates = prepared.candidates
    anchor_by_key = {
        item.normalized_text: item for item in prepared.anchors
    }
    for hit in plan.discovery:
        anchor = anchor_by_key.get(_normalize(hit.anchor))
        if anchor is None or not anchor.semantic_search_allowed:
            continue
        entry = entries.get(hit.canonical_subject_id)
        candidate = (
            _candidate_from_entry(entry) if entry is not None
            else _candidate_from_symbol(
                prepared.symbols_by_id.get(hit.canonical_subject_id)
            )
        )
        if candidate is None:
            continue
        _merge(
            candidates,
            candidate,
            anchor,
            80 + _effective_strength(anchor),
            'semantic_search',
            evidence_ids=hit.evidence_ids,
        )

    for item in plan.implementation_surface:
        if item.role != 'primary':
            continue
        candidate = candidates.get(item.canonical_subject_id)
        entry = entries.get(item.canonical_subject_id)
        if candidate is None and entry is not None:
            candidate = _candidate_from_entry(entry)
            candidates[candidate.canonical_id] = candidate
        if candidate is not None:
            candidate.resolved = True
            candidate.score += 600
            candidate.modes.add('pr172_authoritative_primary')
            candidate.reasons.add('PR172 resolved this exact represented callable.')

    _retain_represented_references(candidates, prepared.symbols_by_id.values())
    _retain_external_anchors(candidates, prepared.anchors)
    eligible = tuple(
        item for item in candidates.values()
        if item.resolved or item.role == 'external_symbol' or item.score >= 100
    )
    selected, suppressed = _diverse_selection(
        eligible, prepared.desired_roles, root_limit
    )
    roots = tuple(
        AgentDiscoveredRoot(
            item.canonical_id,
            item.kind,
            item.qualified_name,
            item.simple_name,
            item.project,
            item.source_path,
            item.source_span,
            rank,
            'resolved' if item.resolved else 'candidate',
            _confidence(item),
            item.authority,
            tuple(anchor.text for anchor in sorted(
                item.matched.values(), key=_anchor_sort_key
            )),
            tuple(sorted(item.reasons)),
            tuple(sorted(item.evidence_ids))[:12],
            item.role,
            item.score,
            tuple(sorted(item.reasons))[:12],
            tuple(sorted(item.modes)),
        )
        for rank, item in enumerate(selected, start=1)
    )
    omitted = max(0, len(eligible) - len(selected))
    limitations = []
    if any(item.role == 'external_symbol' for item in selected):
        limitations.append(
            'External/unresolved technical anchors are story evidence, not local '
            'repository definitions or resolved dependencies.'
        )
    diagnostics = {
        'anchor_count': len(prepared.anchors),
        'exact_matches': prepared.exact_matches,
        'semantic_searches': len(prepared.semantic_anchors),
        'root_candidates_considered': len(eligible),
        'selected_root_count': len(roots),
        'role_diversity': sorted({item.role for item in roots}),
        'weak_matches_penalized': prepared.weak_matches_penalized,
        'near_duplicates_suppressed': suppressed,
        'source_candidates_considered': prepared.source_candidates_considered,
        'external_unresolved_count': sum(
            item.role == 'external_symbol' for item in roots
        ),
        'omitted_results': omitted,
        'search_modes_used': sorted({
            mode for item in roots for mode in item.search_modes
        }),
        'search_stage_order': [
            'strong_anchor_extraction',
            'exact_identity',
            'represented_source_name',
            'semantic_search',
            'role_diversity',
            'graph_expansion',
        ],
        'top_roots': [
            {
                'canonical_subject_id': item.canonical_subject_id,
                'qualified_name': item.qualified_name,
                'role': item.role,
                'score': item.score,
                'classification': item.classification,
            }
            for item in roots
        ],
    }
    return StoryDiscoveryResult(
        prepared.anchors,
        roots,
        diagnostics,
        tuple(limitations),
        omitted,
    )


def _candidate_from_entry(entry) -> _Candidate:
    owner = entry.identity.owner_type
    return _Candidate(
        entry.canonical_subject_id,
        entry.identity.kind.value,
        entry.identity.normalized_key,
        entry.identity.name,
        entry.project_id,
        entry.source.path,
        entry.source.declaration.to_dict(),
        _implementation_role(
            _owner_simple_name(owner), entry.source.path, entry.type_kind,
            entry.source_classification.value,
        ),
        authority='atlas-java-callable-index',
    )


def _candidate_from_symbol(symbol) -> _Candidate | None:
    if not isinstance(symbol, dict) or not symbol.get('id'):
        return None
    source = symbol.get('source')
    metadata = symbol.get('metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    classification = str(metadata.get('source_classification', 'production'))
    if classification not in {'production', 'test'}:
        return None
    name = str(symbol.get('name', '')).strip()
    qualified = str(symbol.get('qualified_name', '')).strip()
    if not name or not qualified:
        return None
    return _Candidate(
        str(symbol['id']),
        str(symbol.get('kind', 'symbol')),
        qualified,
        name,
        str(symbol['project_id']) if symbol.get('project_id') else None,
        str(source).replace('\\', '/') if source else None,
        None,
        _implementation_role(
            _owner_name(qualified, str(symbol.get('kind'))),
            str(source or ''),
            str(metadata.get('type_kind', '')),
            classification,
        ),
        authority='atlas-global-symbol-index',
    )


def _candidate_from_source(record: dict[str, str]) -> _Candidate:
    path = record['path']
    project = record['project']
    simple = PurePosixPath(path).stem
    digest = hashlib.sha256(
        f'{project}\0{path}'.encode('utf-8')
    ).hexdigest()[:24]
    return _Candidate(
        f'source_file:{digest}',
        'source_file',
        _qualified_from_source(path),
        simple,
        project,
        path,
        None,
        _implementation_role(simple, path, '', record['classification']),
        authority='atlas-snapshot-diagnostic-source',
    )


def _snapshot_source_records(snapshot, workspace_root: Path, project: str | None):
    root = workspace_root.resolve()
    values: dict[tuple[str, str], dict[str, str]] = {}
    for diagnostic in snapshot.semantic_context.get('diagnostics', ()):
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get('code') != 'ATLAS-JAVA-PARSE':
            continue
        owner = str(diagnostic.get('project', '')).strip()
        if not owner or (project is not None and owner != project):
            continue
        location = str(diagnostic.get('location', '')).strip()
        relative = _confined_source_path(location, root)
        if relative is None or not relative.casefold().endswith('.java'):
            continue
        classification = (
            'test' if '/src/test/' in f'/{relative.casefold()}' else 'production'
        )
        values[(owner, relative)] = {
            'project': owner,
            'path': relative,
            'classification': classification,
        }
    return tuple(values[key] for key in sorted(values))


def _confined_source_path(value: str, root: Path) -> str | None:
    if not value:
        return None
    candidate = Path(value.replace('/', '\\'))
    try:
        if candidate.is_absolute():
            relative = candidate.resolve().relative_to(root)
        else:
            posix = PurePosixPath(value.replace('\\', '/'))
            if any(part in {'', '.', '..'} for part in posix.parts):
                return None
            relative = Path(*posix.parts)
    except (OSError, ValueError):
        return None
    return relative.as_posix()


def _qualified_from_source(path: str) -> str:
    marker = '/src/main/java/'
    folded = path.casefold()
    offset = folded.find(marker)
    if offset < 0:
        marker = '/src/test/java/'
        offset = folded.find(marker)
    tail = path[offset + len(marker):] if offset >= 0 else PurePosixPath(path).name
    return tail.removesuffix('.java').replace('/', '.')


def _production_symbol(symbol: dict[str, object]) -> bool:
    metadata = symbol.get('metadata')
    return not isinstance(metadata, dict) or metadata.get(
        'source_classification', 'production'
    ) == 'production'


def _retain_owner_member_matches(candidates, entries, anchors) -> None:
    by_source = defaultdict(list)
    for entry in entries:
        by_source[entry.source.path].append(entry)
    for candidate in tuple(candidates.values()):
        if candidate.kind not in {'type', 'source_file'} or not candidate.source_path:
            continue
        for anchor in anchors:
            if anchor.anchor_type not in {'business_entity', 'exact_identifier'}:
                continue
            parts = set(_identifier_parts(anchor.text))
            if not parts:
                continue
            matching = [
                entry for entry in by_source.get(candidate.source_path, ())
                if parts.issubset(set(_identifier_parts(entry.identity.name)))
                and entry.identity.name.casefold().startswith(('get', 'is', 'find', 'search'))
            ]
            if not matching:
                continue
            _merge(candidates, candidate, anchor, 130, 'represented_member_name')
            candidates[candidate.canonical_id].reasons.add(
                'Represented member naming connects this owner to a strong story entity.'
            )


def _retain_role_candidate(candidates, candidate, anchors, desired_roles) -> None:
    components = set(_identifier_parts(candidate.simple_name))
    components.update(_path_components(candidate.source_path or ''))
    contributions = []
    for anchor in anchors:
        if anchor.anchor_type in {
            'weak_lexical', 'invocation_expression', 'technical_note',
        }:
            continue
        anchor_parts = set(_identifier_parts(anchor.text))
        if not anchor_parts:
            continue
        if anchor.anchor_type == 'ui_behavior':
            structural = anchor_parts & {
                'controller', 'form', 'page', 'panel', 'presenter', 'view',
            }
            if not structural or not structural.issubset(components):
                continue
            anchor_parts = structural
        if candidate.simple_name.casefold() == anchor.normalized_text:
            contributions.append((anchor, 420 + _effective_strength(anchor), 'exact_source_name'))
            continue
        overlap = len(anchor_parts & components)
        if not overlap:
            continue
        if anchor.identifier_like and not anchor_parts.issubset(components):
            continue
        weight = max(0, _effective_strength(anchor))
        score = max(12, (weight * overlap * 2) // len(anchor_parts))
        contributions.append((anchor, score, 'source_name_role'))
    if not contributions:
        return
    role_score = 125 if candidate.role in desired_roles else 0
    evidence_score = 12 * _role_evidence_count(
        candidate.simple_name, candidate.source_path or '', candidate.role
    )
    role_surface_bonus = _role_surface_bonus(candidate, anchors)
    source_container_bonus = (
        160 if candidate.kind == 'source_file' and candidate.role in desired_roles
        else 0
    )
    nested_penalty = 0
    if candidate.kind == 'type' and candidate.source_path:
        if PurePosixPath(candidate.source_path).stem != candidate.simple_name:
            nested_penalty = 180
    total = (
        sum(item[1] for item in contributions)
        + role_score + evidence_score + role_surface_bonus
        + source_container_bonus - nested_penalty
    )
    if total < 100:
        return
    current = candidates.get(candidate.canonical_id)
    if current is None:
        candidate.score += (
            role_score + evidence_score + role_surface_bonus + source_container_bonus
        )
        candidate.score -= nested_penalty
        candidates[candidate.canonical_id] = candidate
        current = candidate
    else:
        current.score += (
            role_score + evidence_score + role_surface_bonus + source_container_bonus
        )
        current.score -= nested_penalty
    if role_score:
        current.reasons.add(
            f'Story behavior requests the {candidate.role} implementation layer.'
        )
        current.modes.add('implementation_role')
    if source_container_bonus:
        current.reasons.add(
            'Validated snapshot source container matches the requested implementation role.'
        )
    if role_surface_bonus:
        current.reasons.add(
            'Repository naming provides a high-specificity implementation-surface role signal.'
        )
    if nested_penalty:
        current.reasons.add(
            'Nested/helper type was penalized relative to its source container.'
        )
    for anchor, score, mode in contributions:
        _merge(candidates, candidate, anchor, score, mode)


def _implementation_role(name: str, path: str, type_kind: str, classification: str):
    tokens = set(_identifier_parts(name)) | set(_path_components(path))
    if classification == 'test' or tokens & {'test', 'tests', 'spec'}:
        return 'test'
    if tokens & {'criteria', 'query', 'vo'}:
        return 'persistence'
    if type_kind == 'interface' or (
        name.startswith('I') and len(name) > 1 and name[1].isupper()
        and tokens & {'service', 'bean', 'search'}
    ):
        return 'service_interface'
    if tokens & {'controller', 'presenter'}:
        return 'controller'
    if tokens & {'gui', 'ui', 'portal', 'panel', 'page', 'view', 'window', 'form'}:
        return 'ui'
    if tokens & {'dao', 'repository', 'persistence', 'query'}:
        return 'persistence'
    if tokens & {'domain', 'entity', 'model', 'summary'}:
        return 'domain'
    if tokens & {'service', 'bean', 'ejb'}:
        return 'service'
    if tokens & {'component', 'locator', 'adapter', 'gateway', 'client', 'integration'}:
        return 'integration'
    return 'unknown'


def _desired_roles(story: str, anchors) -> tuple[str, ...]:
    folded = story.casefold()
    values = []
    if any(phrase in folded for phrase in _UI_PHRASES):
        values.append('ui')
    if any(term in folded for term in (
        'search', 'retrieve', 'service', 'cache', 'call ', 'invoke'
    )):
        values.extend(('service_interface', 'service', 'persistence'))
    if any(item.anchor_type == 'business_entity' for item in anchors):
        values.append('domain')
    if any(item.technical_note for item in anchors):
        values.append('integration')
    return tuple(dict.fromkeys(values))


def _role_evidence_count(name: str, path: str, role: str) -> int:
    tokens = set(_identifier_parts(name)) | set(_path_components(path))
    evidence = {
        'ui': {'gui', 'ui', 'portal', 'panel', 'page', 'view', 'web'},
        'controller': {'controller', 'presenter'},
        'service_interface': {'interface', 'service', 'bean', 'search'},
        'service': {'service', 'bean', 'ejb', 'impl'},
        'persistence': {'dao', 'repository', 'persistence', 'query', 'search'},
        'domain': {'domain', 'entity', 'model', 'summary'},
        'integration': {'component', 'locator', 'adapter', 'gateway', 'client'},
        'test': {'test', 'tests', 'spec'},
    }.get(role, set())
    return len(tokens & evidence)


def _role_surface_bonus(candidate, anchors) -> int:
    tokens = set(_identifier_parts(candidate.simple_name))
    tokens.update(_path_components(candidate.source_path or ''))
    if candidate.role == 'ui':
        return 32 * len(tokens & {'portal', 'panel', 'content', 'scope', 'page', 'view'})
    if candidate.role in {'service_interface', 'service', 'persistence'}:
        story_search = any(
            item.anchor_type == 'ui_behavior' and 'search' in item.normalized_text
            for item in anchors
        )
        return 260 if story_search and 'search' in tokens else 0
    if candidate.role == 'domain':
        return 100 if tokens & {'summary', 'entity'} else 0
    return 0


def _identifier_parts(value: str) -> tuple[str, ...]:
    values = []
    for lexical in re.split(r'[^A-Za-z0-9]+', value):
        for item in _CAMEL.findall(lexical):
            folded = item.casefold()
            if len(folded) > 1:
                values.append(folded)
    return tuple(values)


def _path_components(path: str) -> tuple[str, ...]:
    values = []
    for part in PurePosixPath(path.replace('\\', '/')).parts:
        values.extend(_identifier_parts(part.removesuffix('.java')))
    return tuple(values)


def _merge(
    candidates,
    proposed,
    anchor,
    score,
    mode,
    *,
    evidence_ids=(),
) -> None:
    current = candidates.get(proposed.canonical_id)
    if current is None:
        candidates[proposed.canonical_id] = proposed
        current = proposed
    current.score += score
    current.matched[anchor.normalized_text] = anchor
    current.modes.add(mode)
    current.evidence_ids.update(evidence_ids)
    descriptions = {
        'exact_callable': 'Exact story identifier matched a represented Java callable.',
        'exact_symbol': 'Exact story identifier matched a represented repository symbol.',
        'exact_source_name': 'Exact story identifier matched a validated snapshot source name.',
        'source_name_role': 'Story concepts matched full source/type name components.',
        'semantic_search': 'Bounded Atlas semantic search connected this represented subject.',
    }
    current.reasons.add(descriptions.get(mode, mode))


def _retain_represented_references(candidates, symbols) -> None:
    ranked_targets = sorted(
        (
            item for item in candidates.values()
            if item.kind in {'source_file', 'type'}
            and item.role in {'service_interface', 'service', 'domain'}
            and item.score >= 100
        ),
        key=_candidate_sort_key,
    )[:32]
    targets = {}
    for item in ranked_targets:
        targets.setdefault(item.simple_name.casefold(), item)
    if not targets:
        return
    proposals = {}
    for symbol in symbols:
        metadata = symbol.get('metadata')
        if not isinstance(metadata, dict):
            continue
        identifiers = {
            match.group(0).casefold()
            for value in metadata.values()
            for match in _IDENTIFIER.finditer(str(value))
        }
        matched = sorted(identifiers & targets.keys())
        if not matched:
            continue
        proposed = _candidate_from_symbol(symbol)
        if proposed is None or proposed.role not in {
            'controller', 'integration', 'service', 'service_interface', 'ui',
        }:
            continue
        source = targets[matched[0]]
        if not source.matched:
            continue
        if proposed.canonical_id == source.canonical_id or (
            proposed.source_path and proposed.source_path == source.source_path
        ):
            continue
        anchor = sorted(source.matched.values(), key=_anchor_sort_key)[0]
        reference_score = 220 + min(300, source.score // 2)
        same_project = bool(proposed.project and proposed.project == source.project)
        if same_project:
            reference_score += 160
        proposal_key = (
            0 if same_project else 1,
            -reference_score,
            proposed.qualified_name.casefold(),
            proposed.canonical_id,
        )
        current_proposal = proposals.get(proposed.canonical_id)
        if current_proposal is None or proposal_key < current_proposal[0]:
            proposals[proposed.canonical_id] = (
                proposal_key, proposed, source, anchor, reference_score,
            )

    for _, proposed, source, anchor, reference_score in sorted(
        proposals.values(), key=lambda item: item[0]
    )[:64]:
        prior_score = candidates.get(proposed.canonical_id)
        prior_score = prior_score.score if prior_score is not None else 0
        _merge(
            candidates, proposed, anchor, reference_score,
            'represented_type_reference',
        )
        current = candidates[proposed.canonical_id]
        current.score = max(prior_score, reference_score)
        current.reasons.add(
            f'Represented member metadata references discovered type {source.simple_name}.'
        )


def _retain_external_anchors(candidates, anchors) -> None:
    locally_resolved = {
        key
        for candidate in candidates.values()
        if candidate.modes & {'exact_callable', 'exact_symbol', 'exact_source_name'}
        for key in candidate.matched
    }
    for anchor in anchors:
        key = anchor.normalized_text
        if (
            not anchor.technical_note
            or not anchor.identifier_like
            or not anchor.exact_match_preferred
            or _effective_strength(anchor) < 45
            or key in locally_resolved
            or key in _GENERIC_TECHNICAL
        ):
            continue
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
        candidate = _Candidate(
            f'external_symbol:{digest}',
            'external_symbol',
            anchor.text,
            anchor.text,
            None,
            None,
            None,
            'external_symbol',
            260 + _effective_strength(anchor),
            authority='story-technical-anchor+validated-snapshot-non-resolution',
        )
        candidate.matched[key] = anchor
        candidate.modes.add('external_unresolved')
        candidate.reasons.add(
            'Strong technical-note identifier has no exact represented local definition; '
            'repository absence is not asserted.'
        )
        candidates[candidate.canonical_id] = candidate


def _diverse_selection(candidates, desired_roles, limit):
    ordered = tuple(sorted(candidates, key=_candidate_sort_key))
    selected = []
    selected_ids = set()
    selected_sources = set()
    suppressed = 0

    def add(candidate, *, allow_same_source=False):
        nonlocal suppressed
        if candidate.canonical_id in selected_ids:
            return False
        source_key = _near_duplicate_key(candidate)
        if source_key and source_key in selected_sources and not allow_same_source:
            suppressed += 1
            return False
        selected.append(candidate)
        selected_ids.add(candidate.canonical_id)
        if source_key:
            selected_sources.add(source_key)
        return True

    for candidate in ordered:
        if candidate.resolved:
            add(candidate, allow_same_source=True)
            if len(selected) >= limit:
                return tuple(selected), suppressed
    for role in _ROLE_ORDER:
        if role not in desired_roles:
            continue
        candidate = next((
            item for item in ordered
            if item.role == role and item.score >= 140
            and item.canonical_id not in selected_ids
        ), None)
        if candidate is not None:
            add(candidate)
            if len(selected) >= limit:
                return tuple(selected), suppressed

    for candidate in (
        item for item in ordered if item.role == 'external_symbol'
    ):
        if sum(item.role == 'external_symbol' for item in selected) >= 2:
            break
        add(candidate)
        if len(selected) >= limit:
            return tuple(selected), suppressed

    role_counts = defaultdict(int)
    for item in selected:
        role_counts[item.role] += 1
    remaining = list(ordered)
    while len(selected) < limit:
        available = [
            item for item in remaining
            if item.canonical_id not in selected_ids
            and role_counts[item.role] < (3 if item.role == 'external_symbol' else 2)
        ]
        if not available:
            break
        available.sort(key=lambda item: (
            -(item.score - role_counts[item.role] * 90),
            _ROLE_ORDER.index(item.role) if item.role in _ROLE_ORDER else 99,
            item.qualified_name.casefold(),
            item.canonical_id,
        ))
        before = len(selected)
        for candidate in available:
            if add(candidate):
                role_counts[candidate.role] += 1
                break
        if len(selected) == before:
            break
    return tuple(selected), suppressed


def _candidate_sort_key(item):
    return (
        0 if item.resolved else 1,
        -item.score,
        _ROLE_ORDER.index(item.role) if item.role in _ROLE_ORDER else 99,
        item.qualified_name.casefold(),
        item.qualified_name,
        item.canonical_id,
    )


def _near_duplicate_key(item):
    if not item.source_path:
        return None
    if item.kind in {'method', 'constructor'}:
        owner = item.qualified_name.partition('#')[0]
        return item.project, item.source_path, owner
    return item.project, item.source_path


def _confidence(item) -> str:
    if item.resolved:
        return 'authoritative_unique_exact_identity'
    if item.role == 'external_symbol':
        return 'unresolved_external_source'
    if 'exact_source_name' in item.modes:
        return 'candidate_snapshot_source_exact_name'
    if 'exact_symbol' in item.modes or 'exact_callable' in item.modes:
        return 'candidate_exact_represented_identity'
    if 'implementation_role' in item.modes:
        return 'candidate_story_role_and_source_match'
    return 'candidate_semantic_repository_match'


def _anchor_sort_key(item: StoryAnchor):
    return (
        -_effective_strength(item),
        -item.specificity,
        item.source_location_in_story['start'],
        item.normalized_text,
        item.text,
    )


def _effective_strength(item: StoryAnchor) -> int:
    return max(0, item.strength - item.ambiguity_penalty)


def _normalize(value: str) -> str:
    return ' '.join(value.casefold().split())


def _owner_simple_name(owner: str) -> str:
    return owner.rpartition('.')[2].rpartition('$')[2]


def _owner_name(qualified: str, kind: str) -> str:
    if kind == 'type':
        return qualified.rpartition('.')[2]
    owner = qualified.partition('#')[0]
    if owner == qualified:
        owner = qualified.rpartition('.')[0]
    return owner.rpartition('.')[2]
