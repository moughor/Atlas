from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re

from moughorai.ai_memory import ConversationMessage
from moughorai.code_intelligence import CodeIntelligenceConfiguration
from moughorai.impact_analysis import ImpactPredictionRequest, ImpactPredictionService
from moughorai.knowledge_graph import KnowledgeKind
from moughorai.prompts import TokenEstimator
from moughorai.refactoring_advisor import RefactoringAdvisorService, RefactoringRequest
from moughorai.security_intelligence import (
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityScope,
)
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_search import SemanticSearchRequest
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.structured_explanation import ExplanationRequest
from moughorai.subject_resolution import SubjectQuery

from .models import (
    ChatCapability,
    ChatCapabilityState,
    ChatContext,
    ChatContextSection,
    ChatIntent,
    ChatSelection,
    CitationValidation,
)
from .safety import sanitize_chat_text


MAXIMUM_CHAT_TEXT = 4_096
MAXIMUM_HISTORY_TEXT = 1_024
MAXIMUM_ANSWER_TEXT = 16_384
MAXIMUM_SECTION_EVIDENCE = 64
DEFAULT_CHAT_RESULT_LIMIT = 8
MAXIMUM_SEARCH_HITS = 6
MAXIMUM_EXPLANATION_FACTS = 8
MAXIMUM_OPTIONAL_ITEMS = 1
MAXIMUM_OPTIONAL_CAPABILITIES = 3

_EVIDENCE_CITATION = re.compile(r"evidence:[0-9a-f]{64}")
_WORD = re.compile(r"[A-Za-z0-9_]+")

_CODE_IMPACT_WORDS = frozenset({
    'call', 'called', 'callee', 'callees', 'caller', 'callers', 'calls',
    'constructor', 'constructors', 'method', 'methods', 'modify', 'modifying',
})

_INTENT_WORDS = {
    ChatIntent.SECURITY: frozenset({
        "security", "secure", "vulnerability", "vulnerabilities", "secret",
        "injection", "crypto", "cryptography", "ssrf", "xss", "deserialization",
    }),
    ChatIntent.REFACTORING: frozenset({
        "refactor", "refactoring", "extract", "simplify", "modularize", "cleanup",
    }),
    ChatIntent.IMPACT: frozenset({
        "impact", "affected", "break", "breaking", "blast", "change",
    }),
    ChatIntent.REPOSITORY: frozenset({
        "repository", "workspace", "overview", "architecture", "codebase",
    }),
    ChatIntent.SEARCH: frozenset({
        "find", "where", "which", "locate", "search", "list", "show",
    }),
    ChatIntent.EXPLAIN: frozenset({"explain", "why", "how", "what"}),
}

_OPTIONAL_CAPABILITIES = (
    "impact_prediction",
    "refactoring_advisor",
    "security_intelligence",
    'code_impact',
)
_CAPABILITY_ALIASES = {
    'code_impact': 'code_impact',
    'java_code_intelligence': 'code_impact',
    "impact": "impact_prediction",
    "impact_prediction": "impact_prediction",
    "refactor": "refactoring_advisor",
    "refactoring": "refactoring_advisor",
    "refactoring_advisor": "refactoring_advisor",
    "security": "security_intelligence",
    "security_intelligence": "security_intelligence",
}


class ChatContextBudgetError(ValueError):
    """Raised when the mandatory source-free chat envelope cannot fit."""


@dataclass(frozen=True, slots=True)
class _CandidateSection:
    section: ChatContextSection
    records: tuple[EvidenceRecord, ...] = ()
    mandatory: bool = False


def classify_chat_intent(question: str) -> ChatIntent:
    words = {item.casefold() for item in _WORD.findall(question)}
    for intent in (
        ChatIntent.SECURITY,
        ChatIntent.REFACTORING,
        ChatIntent.IMPACT,
        ChatIntent.REPOSITORY,
        ChatIntent.SEARCH,
        ChatIntent.EXPLAIN,
    ):
        if words.intersection(_INTENT_WORDS[intent]):
            return intent
    return ChatIntent.UNKNOWN


def requested_chat_capabilities(
    question: str,
    explicit: Iterable[str] = (),
) -> tuple[str, ...]:
    result = set()
    for value in explicit:
        normalized = value.strip().casefold().replace("-", "_")
        try:
            result.add(_CAPABILITY_ALIASES[normalized])
        except KeyError as exc:
            raise ValueError(f"unsupported chat capability: {value}") from exc
    words = {item.casefold() for item in _WORD.findall(question)}
    if words.intersection(_INTENT_WORDS[ChatIntent.SECURITY]):
        result.add("security_intelligence")
    if words.intersection(_INTENT_WORDS[ChatIntent.REFACTORING]):
        result.add("refactoring_advisor")
    if words.intersection(_INTENT_WORDS[ChatIntent.IMPACT]):
        result.add("impact_prediction")
    return tuple(sorted(result))


def validate_citations(answer: str, available_evidence_ids: Iterable[str]) -> CitationValidation:
    cited = tuple(sorted(set(_EVIDENCE_CITATION.findall(answer))))
    available = set(available_evidence_ids)
    accepted = tuple(item for item in cited if item in available)
    unknown = tuple(item for item in cited if item not in available)
    return CitationValidation(
        cited,
        accepted,
        unknown,
        missing_required=bool(available) and not accepted,
    )


def strip_chat_citations(answer: str) -> str:
    """Remove citation authority from a materially redacted provider answer."""

    return _EVIDENCE_CITATION.sub("[citation omitted]", answer)


class EngineeringChatContextBuilder:
    """Compose one bounded PR139 context from existing snapshot-backed services."""

    def __init__(
        self,
        *,
        estimator: TokenEstimator | None = None,
        runtime_session: RepositoryRuntimeSession | None = None,
    ) -> None:
        self.estimator = estimator or TokenEstimator()
        self.runtime_session = runtime_session or RepositoryRuntimeSession()

    def build(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        question: str,
        subject: str | None = None,
        kind: str | None = None,
        project: str | None = None,
        language: str | None = None,
        capabilities: Iterable[str] = (),
        result_limit: int = DEFAULT_CHAT_RESULT_LIMIT,
        token_budget: int = 5_500,
        history: Sequence[ConversationMessage] = (),
        history_total_count: int | None = None,
        prior_subject_ids: Iterable[str] = (),
    ) -> ChatContext:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("engineering chat requires an Atlas semantic snapshot")
        if not 1 <= result_limit <= 20:
            raise ValueError("chat result limit must be between 1 and 20")
        if token_budget < 256:
            raise ValueError("chat context token budget must be at least 256")
        safe_question = sanitize_chat_text(question)
        runtime = self.runtime_session.runtime_for(snapshot)
        intent = classify_chat_intent(safe_question)
        explicit_requested = requested_chat_capabilities('', capabilities)
        requested = requested_chat_capabilities(safe_question, capabilities)
        capability_map: dict[str, ChatCapability] = {
            name: ChatCapability(
                name,
                ChatCapabilityState.NOT_REQUESTED,
                limitations=(f"{name.replace('_', ' ').title()} was not requested.",),
            )
            for name in _OPTIONAL_CAPABILITIES
        }
        candidates: list[_CandidateSection] = []
        limitations: set[str] = set()

        search_response = None
        try:
            search_response = runtime.semantic_search.search_semantic(
                SemanticSearchRequest(
                    safe_question,
                    project=project,
                    language=language,
                    limit=result_limit,
                )
            )
            search_candidate, search_capability = self._search_section(
                search_response, result_limit
            )
            candidates.append(search_candidate)
            capability_map[search_capability.name] = search_capability
        except (KeyError, TypeError, ValueError, OverflowError):
            capability_map["semantic_search"] = ChatCapability(
                "semantic_search",
                ChatCapabilityState.INCOMPATIBLE,
                producer_ids=("atlas-pr135/1",),
                limitations=("Structured semantic search is unavailable or incompatible with this snapshot.",),
            )
            limitations.add("Structured semantic search could not be loaded from the current snapshot.")

        selected_subject = sanitize_chat_text(subject) if subject and subject.strip() else None
        resolution_origin = "explicit" if selected_subject is not None else "none"
        selected_kind = kind.strip() if kind and kind.strip() else None
        if selected_subject is None and _is_follow_up(safe_question):
            selected_subject = next(iter(sorted(set(prior_subject_ids))), None)
            if selected_subject is not None:
                resolution_origin = "conversation"
        if selected_subject is None and intent is ChatIntent.REPOSITORY:
            selected_subject, selected_kind = "repository", KnowledgeKind.REPOSITORY.value
            resolution_origin = "repository"
        if selected_subject is None and search_response is not None:
            selected_subject, selected_kind = _select_search_subject(search_response)
            if selected_subject is not None:
                resolution_origin = "semantic_search"

        explanation = None
        resolved_subject_ids: tuple[str, ...] = ()
        resolved_subject = None
        try:
            if selected_subject is not None:
                explanation = runtime.structured_explanation(
                    include_code_intelligence=False,
                ).explain(
                    ExplanationRequest(
                        selected_subject,
                        kind=selected_kind,
                        project=project,
                        language=language,
                    ),
                    token_budget=max(512, min(4_000, token_budget // 2)),
                )
                explanation_candidate, explanation_capability = self._explanation_section(
                    explanation, result_limit, resolution_origin=resolution_origin
                )
                candidates.append(explanation_candidate)
                capability_map[explanation_capability.name] = explanation_capability
                if explanation.subject is not None:
                    resolved_subject = explanation.subject
                    resolved_subject_ids = (explanation.subject.subject_id,)
            else:
                capability_map["canonical_explanation"] = ChatCapability(
                    "canonical_explanation",
                    ChatCapabilityState.AMBIGUOUS if search_response and search_response.interpretation.ambiguous else ChatCapabilityState.UNAVAILABLE,
                    producer_ids=("atlas-pr134/1",),
                    limitations=("No single canonical subject was resolved for this turn.",),
                )
        except (KeyError, TypeError, ValueError, OverflowError):
            capability_map["canonical_explanation"] = ChatCapability(
                "canonical_explanation",
                ChatCapabilityState.INCOMPATIBLE,
                producer_ids=("atlas-pr134/1",),
                limitations=("Canonical explanation is unavailable or incompatible with this snapshot.",),
            )
            limitations.add("Canonical explanation could not be built from the current snapshot.")

        report_capability = next(
            (
                item for item in explanation.capabilities
                if item.name == "repository_report"
            ),
            None,
        ) if explanation is not None else None
        capability_map["repository_report"] = ChatCapability(
            "repository_report",
            _chat_state(report_capability.availability.value)
            if report_capability is not None
            else ChatCapabilityState.UNAVAILABLE,
            producer_ids=report_capability.producer_ids
            if report_capability is not None else (),
            limitations=report_capability.limitations
            if report_capability is not None else (
                "The optional structured repository report is unavailable; chat uses snapshot facts directly.",
            ),
        )

        if (
            resolved_subject is not None
            and resolved_subject.kind == 'method'
            and (
                'impact_prediction' in requested
                or {
                    item.casefold() for item in _WORD.findall(safe_question)
                }.intersection(_CODE_IMPACT_WORDS)
            )
        ):
            requested = tuple(sorted({*requested, 'code_impact'}))
            if 'impact_prediction' not in explicit_requested:
                requested = tuple(
                    item for item in requested
                    if item != 'impact_prediction'
                )

        for capability in requested:
            if capability == 'code_impact':
                candidate, value = self._code_impact_section(
                    runtime, resolved_subject, result_limit,
                )
                candidates.append(candidate)
                capability_map[capability] = value
                continue
            if capability == "impact_prediction":
                impact_candidates, value = self._impact_section(
                    runtime, resolved_subject, result_limit
                )
                candidates.extend(impact_candidates)
            elif capability == "refactoring_advisor":
                candidate, value = self._refactoring_section(
                    snapshot, resolved_subject, result_limit
                )
                candidates.append(candidate)
            else:
                candidate, value = self._security_section(
                    snapshot,
                    resolved_subject,
                    result_limit,
                    repository_scope=(
                        intent is ChatIntent.REPOSITORY
                        or _explicit_repository_scope(safe_question)
                    ),
                )
                candidates.append(candidate)
            capability_map[capability] = value

        history_candidate = self._history_section(
            snapshot,
            history,
            history_total_count if history_total_count is not None else len(history),
        )
        if history_candidate is not None:
            candidates.append(history_candidate)

        return self._select(
            snapshot,
            safe_question,
            intent,
            resolved_subject_ids,
            tuple(capability_map.values()),
            tuple(candidates),
            tuple(limitations),
            token_budget,
        )

    def _search_section(self, response, result_limit: int) -> tuple[_CandidateSection, ChatCapability]:
        selected_hits = response.hits[: min(result_limit, MAXIMUM_SEARCH_HITS)]
        raw_hits = [item.to_dict() for item in selected_hits]
        evidence_ids = _bounded_evidence_ids(raw_hits)
        records = _records(response.evidence_index, evidence_ids)
        content = {
            "producer": response.producer,
            "index_id": response.index_id,
            "interpretation": response.interpretation.to_dict(),
            "hits": _filter_evidence(raw_hits, set(evidence_ids)),
            "total_candidate_count": response.total_candidate_count,
            "included_hit_count": len(selected_hits),
            "omitted_hit_count": max(0, response.total_candidate_count - len(selected_hits)),
            "capabilities": [item.to_dict() for item in response.capabilities],
            "limitations": list(response.limitations),
        }
        state = (
            ChatCapabilityState.AMBIGUOUS
            if response.interpretation.ambiguous
            else ChatCapabilityState.AVAILABLE
            if response.hits
            else ChatCapabilityState.PARTIAL
        )
        section = ChatContextSection(
            "semantic_search",
            "semantic_search",
            "Deterministic semantic search",
            content,
            evidence_ids,
            30,
            response.total_candidate_count,
            len(selected_hits),
            max(0, response.total_candidate_count - len(selected_hits)),
        )
        return _CandidateSection(section, records), ChatCapability(
            "semantic_search", state, (response.producer,), tuple(response.limitations)
        )

    def _explanation_section(
        self,
        response,
        result_limit: int,
        *,
        resolution_origin: str,
    ) -> tuple[_CandidateSection, ChatCapability]:
        selected_facts = response.facts[: min(
            MAXIMUM_EXPLANATION_FACTS, max(1, result_limit)
        )]
        raw_facts = [item.to_dict() for item in selected_facts]
        evidence_ids = _bounded_evidence_ids(raw_facts)
        records = _records(response.evidence_index, evidence_ids)
        total = response.selection.total_fact_count if response.selection.applied else len(response.facts)
        content = {
            "producer_version": response.producer_version,
            "availability": response.availability.value,
            "subject": response.subject.to_dict() if response.subject is not None else None,
            "candidates": [item.to_dict() for item in response.candidates[:12]],
            "facts": _filter_evidence(raw_facts, set(evidence_ids)),
            "capabilities": [item.to_dict() for item in response.capabilities],
            "limitations": list(response.limitations),
            "input_fingerprint": response.input_fingerprint,
            "lineage": response.lineage,
            "resolution_origin": resolution_origin,
        }
        state = _chat_state(response.availability.value)
        section = ChatContextSection(
            "canonical_explanation",
            "canonical_explanation",
            "Canonical subject explanation",
            content,
            evidence_ids,
            10,
            total,
            len(selected_facts),
            max(0, total - len(selected_facts)),
        )
        return _CandidateSection(section, records), ChatCapability(
            "canonical_explanation",
            state,
            (response.producer_version,),
            tuple(response.limitations),
        )

    def _code_impact_section(self, runtime, subject, result_limit):
        if subject is None:
            return _unavailable_section(
                'code_impact',
                'Java code impact',
                'atlas-pr159/1',
                'Java code impact requires one unambiguous canonical callable.',
                4,
            )
        if subject.kind != 'method':
            return _unavailable_section(
                'code_impact',
                'Java code impact',
                'atlas-pr159/1',
                'PR159 supports exact Java method and constructor subjects only.',
                4,
                ChatCapabilityState.UNSUPPORTED,
            )
        try:
            result = runtime.java_code_intelligence.query(
                subject.subject_id,
                project=subject.project,
                configuration=CodeIntelligenceConfiguration(
                    max_depth=6,
                    max_nodes=1_024,
                    max_direct_relationships=max(1, min(2, result_limit)),
                    max_paths_per_section=max(1, min(2, result_limit)),
                    max_limitation_representatives=1,
                    max_candidates_per_call_site=1,
                ),
            )
            report = result.report
            if report is None:
                candidate, capability = _unavailable_section(
                    'code_impact',
                    'Java code impact',
                    'atlas-pr159/1',
                    'Compatible PR156, PR157, and PR158 callable evidence is unavailable.',
                    4,
                    _chat_state(result.resolution.status.value),
                )
                return candidate, capability
            records = _code_impact_records(runtime.snapshot, report)
            evidence_ids = tuple(item.evidence_id for item in records)
            content = {
                'producer': report.producer_version,
                'input_fingerprint': report.input_fingerprint,
                'report': _compact_code_impact_report(
                    report.to_dict(),
                    conservative_callers=(
                        report.direct_caller_conservative_groups.to_dict()
                    ),
                    conservative_callees=(
                        report.direct_callee_conservative_groups.to_dict()
                    ),
                ),
            }
            section = ChatContextSection(
                'code_impact',
                'code_impact',
                'Evidence-backed Java code impact',
                content,
                evidence_ids,
                4,
                1,
                1,
                0,
            )
            capability = ChatCapability(
                'code_impact',
                _chat_state(result.availability.value),
                ('atlas-pr159/1',),
                tuple(report.general_limitations[:2]),
            )
            return _CandidateSection(section, records, mandatory=True), capability
        except (KeyError, TypeError, ValueError, OverflowError):
            return _unavailable_section(
                'code_impact',
                'Java code impact',
                'atlas-pr159/1',
                'Structured Java code impact is unavailable or incompatible with this snapshot.',
                4,
                ChatCapabilityState.INCOMPATIBLE,
            )

    def _impact_section(self, runtime, subject, result_limit):
        if subject is None:
            candidate, capability = _unavailable_section(
                "impact_prediction", "Impact prediction", "atlas-pr136/1",
                "Impact analysis requires one unambiguous canonical subject.", 20,
            )
            return (candidate,), capability
        try:
            analysis = runtime.impact_prediction.analyze(
                ImpactPredictionRequest(
                    SubjectQuery(
                        subject.subject_id,
                        kind=KnowledgeKind(subject.kind),
                        project=subject.project,
                        language=subject.language,
                    ),
                    max_depth=4,
                    limit=result_limit,
                )
            )
            response = analysis.response
            representative, capability = _response_section(
                "impact_prediction", "Impact prediction", response,
                "findings", result_limit, 20,
                producer=response.producer_version,
                extra_keys=(
                    "resolution", "capabilities", "unavailable_analyses",
                    "breaking_change", "limitations", "visited_node_count",
                    "visited_edge_count", "truncated",
                ),
            )
            aggregate = analysis.aggregate
            raw_aggregate = aggregate.to_dict()
            raw_capabilities = raw_aggregate.get("capabilities", ())
            compact_capabilities = {
                str(item.get("name")): {
                    "state": item.get("state"),
                    "coverage": item.get("coverage"),
                }
                for item in raw_capabilities
                if isinstance(item, Mapping) and item.get("name")
            } if isinstance(raw_capabilities, Sequence) else {}
            aggregate_content = _selected_mapping(raw_aggregate, (
                "producer_version", "input_fingerprint", "graph_digest",
                "lineage", "total_impact_count",
                "unique_affected_project_count",
                "direct_affected_project_count",
                "transitive_affected_project_count", "category_counts",
                "depth_histogram", "configured_max_depth",
                "maximum_observed_depth", "visited_node_count",
                "visited_edge_count", "traversal_complete",
                "traversal_truncated", "representative_total_count",
                "representative_included_count",
                "representative_omitted_count", "representative_complete",
                "evidence_ids", "limitations",
            ), additions={
                "capabilities": compact_capabilities,
                "relationship_semantics": "declared_or_observed_static_relationships",
                "runtime_usage_proven": False,
            })
            aggregate_section = ChatContextSection(
                "impact_aggregate",
                "impact_prediction",
                "Complete deterministic impact aggregate",
                {"aggregate": aggregate_content},
                aggregate.evidence_ids,
                5,
                1,
                1,
                0,
            )
            aggregate_candidate = _CandidateSection(
                aggregate_section,
                aggregate.evidence_index.records,
                mandatory=True,
            )
            return (aggregate_candidate, representative), capability
        except (KeyError, TypeError, ValueError, OverflowError):
            candidate, capability = _unavailable_section(
                "impact_prediction", "Impact prediction", "atlas-pr136/1",
                "Structured impact analysis is unavailable or incompatible with this snapshot.", 20,
                ChatCapabilityState.INCOMPATIBLE,
            )
            return (candidate,), capability

    def _refactoring_section(self, snapshot, subject, result_limit):
        if subject is None:
            return _unavailable_section(
                "refactoring_advisor", "Refactoring advice", "atlas-pr137/1",
                "Refactoring advice requires one unambiguous canonical subject.", 21,
            )
        try:
            response = RefactoringAdvisorService.from_snapshot(snapshot).advise(
                RefactoringRequest(
                    SubjectQuery(
                        subject.subject_id,
                        kind=KnowledgeKind(subject.kind),
                        project=subject.project,
                        language=subject.language,
                    ),
                    limit=result_limit,
                    include_impact=True,
                    impact_depth=4,
                )
            )
            return _response_section(
                "refactoring_advisor", "Refactoring advice", response,
                "advice", result_limit, 21,
                producer=response.producer_version,
                extra_keys=(
                    "resolution", "capabilities", "limitations",
                    "visited_node_count", "visited_edge_count", "truncated",
                ),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return _unavailable_section(
                "refactoring_advisor", "Refactoring advice", "atlas-pr137/1",
                "Structured refactoring advice is unavailable or incompatible with this snapshot.", 21,
                ChatCapabilityState.INCOMPATIBLE,
            )

    def _security_section(self, snapshot, subject, result_limit, *, repository_scope):
        try:
            if subject is not None:
                kind = KnowledgeKind(subject.kind)
                if kind is KnowledgeKind.REPOSITORY:
                    request = SecurityIntelligenceRequest(limit=result_limit)
                elif kind is KnowledgeKind.PROJECT:
                    request = SecurityIntelligenceRequest(
                        scope=SecurityScope.PROJECT,
                        projects=(subject.project or subject.name,),
                        limit=result_limit,
                    )
                else:
                    request = SecurityIntelligenceRequest(
                        scope=SecurityScope.SYMBOL,
                        canonical_subject_ids=(subject.subject_id,),
                        limit=result_limit,
                    )
            elif repository_scope:
                request = SecurityIntelligenceRequest(limit=result_limit)
            else:
                return _unavailable_section(
                    "security_intelligence", "Security intelligence", "atlas-pr138/1",
                    "Security analysis requires an unambiguous subject or an explicit repository scope.", 22,
                )
            response = SecurityIntelligenceService.from_snapshot(snapshot).analyze(request)
            return _response_section(
                "security_intelligence", "Security intelligence", response,
                "findings", result_limit, 22,
                producer=response.producer,
                extra_keys=("request", "capabilities", "limitations", "truncated"),
                total_key="total_finding_count",
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return _unavailable_section(
                "security_intelligence", "Security intelligence", "atlas-pr138/1",
                "Structured security intelligence is unavailable or incompatible with this snapshot.", 22,
                ChatCapabilityState.INCOMPATIBLE,
            )

    def _history_section(
        self,
        snapshot: AtlasSemanticSnapshot,
        history: Sequence[ConversationMessage],
        total_count: int,
    ) -> _CandidateSection | None:
        if not history:
            return None
        messages = []
        for item in history:
            referenced_snapshot = item.references.get("snapshot")
            messages.append({
                "role": item.role.value,
                "content": sanitize_chat_text(item.content, maximum=MAXIMUM_HISTORY_TEXT),
                "stale": referenced_snapshot != snapshot.snapshot_id,
            })
        total = max(total_count, len(messages))
        return _CandidateSection(ChatContextSection(
            "conversation_history",
            "conversation_memory",
            "Untrusted bounded conversation history",
            {"messages": messages},
            (),
            60,
            total,
            len(messages),
            total - len(messages),
        ))

    def _select(
        self,
        snapshot,
        question,
        intent,
        subject_ids,
        capabilities,
        candidates,
        limitations,
        token_budget,
    ) -> ChatContext:
        ordered = tuple(sorted(candidates, key=lambda item: (
            item.section.priority, item.section.section_id
        )))
        retained: list[_CandidateSection] = []
        omitted = 0
        for candidate in ordered:
            trial = (*retained, candidate)
            if self._estimate(
                snapshot, question, intent, subject_ids, capabilities, trial,
                limitations, token_budget, len(ordered) - len(trial),
            ) <= token_budget:
                retained.append(candidate)
            elif candidate.mandatory:
                raise ChatContextBudgetError(
                    f"mandatory engineering-chat section {candidate.section.section_id} exceeds its token budget"
                )
            else:
                omitted += 1
        if omitted:
            limitations = (*limitations, f"{omitted} chat context section(s) were omitted by the token budget.")
        while True:
            context = self._context(
                snapshot, question, intent, subject_ids, capabilities,
                tuple(retained), limitations, token_budget, omitted, estimated=0,
            )
            estimated = self.estimator.estimate(context.to_json())
            if estimated <= token_budget:
                for _ in range(4):
                    context = self._context(
                        snapshot, question, intent, subject_ids, capabilities,
                        tuple(retained), limitations, token_budget, omitted,
                        estimated=estimated,
                    )
                    updated = self.estimator.estimate(context.to_json())
                    if updated == estimated:
                        return context
                    estimated = updated
                    if estimated > token_budget:
                        break
                if estimated <= token_budget:
                    return context
            removable = next(
                (
                    index
                    for index in range(len(retained) - 1, -1, -1)
                    if not retained[index].mandatory
                ),
                None,
            )
            if removable is None:
                raise ChatContextBudgetError(
                    "mandatory engineering-chat context exceeds its token budget"
                )
            retained.pop(removable)
            omitted += 1
            limitations = tuple(item for item in limitations if "context section(s)" not in item)
            limitations = (*limitations, f"{omitted} chat context section(s) were omitted by the token budget.")

    def _estimate(
        self, snapshot, question, intent, subject_ids, capabilities, candidates,
        limitations, token_budget, omitted,
    ) -> int:
        context = self._context(
            snapshot, question, intent, subject_ids, capabilities,
            tuple(candidates), limitations, token_budget, omitted, estimated=0,
        )
        return self.estimator.estimate(context.to_json())

    @staticmethod
    def _context(
        snapshot, question, intent, subject_ids, capabilities, candidates,
        limitations, token_budget, omitted, *, estimated,
    ) -> ChatContext:
        evidence = EvidenceIndex()
        for candidate in candidates:
            for record in candidate.records:
                evidence.add(record)
        sections = tuple(item.section for item in candidates)
        history = next((item for item in sections if item.section_id == "conversation_history"), None)
        stale = 0
        history_count = 0
        if history is not None:
            messages = history.content.get("messages", ())
            if isinstance(messages, Sequence):
                history_count = len(messages)
                stale = sum(
                    1 for item in messages
                    if isinstance(item, Mapping) and item.get("stale") is True
                )
        truncated = bool(omitted) or any(item.truncated for item in sections)
        return ChatContext(
            snapshot.snapshot_id,
            snapshot.workspace_fingerprint,
            intent,
            question,
            tuple(subject_ids),
            tuple(capabilities),
            sections,
            evidence.freeze(),
            ChatSelection(
                token_budget,
                estimated,
                tuple(item.section_id for item in sections),
                omitted,
                truncated=truncated,
            ),
            tuple(limitations),
            stale,
            history_count,
        )


def _chat_state(value: str) -> ChatCapabilityState:
    normalized = value.casefold()
    if normalized in {"available", "analyzed", "resolved"}:
        return ChatCapabilityState.AVAILABLE
    if normalized == "partial":
        return ChatCapabilityState.PARTIAL
    if normalized == "ambiguous":
        return ChatCapabilityState.AMBIGUOUS
    if normalized == "incompatible":
        return ChatCapabilityState.INCOMPATIBLE
    if normalized == "unsupported":
        return ChatCapabilityState.UNSUPPORTED
    return ChatCapabilityState.UNAVAILABLE


def _select_search_subject(response) -> tuple[str | None, str | None]:
    if response.interpretation.ambiguous or not response.hits:
        return None, None
    first = response.hits[0]
    exact = any(
        item.name == "exact_identity" and item.available and item.value > 0.0
        for item in first.score_components
    )
    if len(response.hits) == 1 or exact:
        return first.canonical_subject_id, first.kind.value
    return None, None


def _is_follow_up(question: str) -> bool:
    words = {item.casefold() for item in _WORD.findall(question)}
    return bool(words.intersection({"it", "its", "this", "that", "those", "them", "same"}))


def _explicit_repository_scope(question: str) -> bool:
    words = {item.casefold() for item in _WORD.findall(question)}
    return bool(words.intersection({
        "repository", "workspace", "codebase", "overall", "overview", "all",
    }))


def _bounded_evidence_ids(value: object) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key == "evidence_ids" and isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
                    found.update(
                        value for value in nested
                        if isinstance(value, str) and _EVIDENCE_CITATION.fullmatch(value)
                    )
                else:
                    visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(sorted(found)[:MAXIMUM_SECTION_EVIDENCE])


def _filter_evidence(value: object, allowed: set[str]) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): (
                sorted(item for item in nested if isinstance(item, str) and item in allowed)
                if key == "evidence_ids" and isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray))
                else _filter_evidence(nested, allowed)
            )
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_filter_evidence(item, allowed) for item in value]
    return value


def _records(index: EvidenceIndex, evidence_ids: Iterable[str]) -> tuple[EvidenceRecord, ...]:
    result = []
    for evidence_id in sorted(set(evidence_ids)):
        record = index.get(evidence_id)
        if record is not None:
            result.append(record)
    return tuple(result)


def _code_impact_records(snapshot, report) -> tuple[EvidenceRecord, ...]:
    trace = report.traceability

    def refs(values) -> tuple[str, ...]:
        return tuple(sorted(set(str(item) for item in values if str(item))))[:64]

    relationships = (
        *report.direct_callers_high_confidence.items,
        *report.direct_callers_conservative.items,
        *report.direct_caller_method_references.items,
        *report.direct_callees_high_confidence.items,
        *report.direct_callees_conservative.items,
        *report.direct_callee_method_references.items,
        *report.direct_test_callers.items,
    )
    paths = (
        *report.upstream_direct.items,
        *report.upstream_transitive.items,
    )
    test_paths = (
        *report.high_confidence_test_paths.items,
        *report.possible_test_paths.items,
    )
    summary = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        report.subject.canonical_id,
        'atlas-pr159/1',
        snapshot.snapshot_id,
        source_refs=refs((
            report.subject.source.compact,
            trace.callable_index_fingerprint,
            trace.code_graph_fingerprint,
            trace.test_evidence_fingerprint,
        )),
        scope=f'project:{report.subject.project}',
        language='java',
        detail={
            'capability': 'java_code_intelligence',
            'runtime_execution_proven': False,
        },
        limitations=(),
        reliability=0.95,
        specificity=1.0,
    )
    producer_sites: dict[str, dict[str, object]] = {}

    def add_site(item) -> None:
        retained = producer_sites.setdefault(item.producer_evidence_id, {
            'subject_id': item.canonical_source,
            'project': item.project,
            'source_refs': set(),
            'reliability': 1.0,
        })
        retained['source_refs'].update((
            item.location.compact,
            trace.code_graph_fingerprint,
        ))
        retained['reliability'] = min(
            float(retained['reliability']),
            0.98 if item.confidence.value.startswith('high_') else 0.70,
        )

    for item in relationships:
        add_site(item)
    for group in (
        *report.direct_caller_conservative_groups.items,
        *report.direct_callee_conservative_groups.items,
    ):
        retained = producer_sites.setdefault(group.producer_evidence_id, {
            'subject_id': group.canonical_source,
            'project': group.project,
            'source_refs': set(),
            'reliability': 1.0,
        })
        retained['source_refs'].update((
            group.location.compact,
            trace.code_graph_fingerprint,
        ))
        retained['reliability'] = min(
            float(retained['reliability']), 0.70,
        )
    for path in (*paths, *test_paths):
        for item in path.steps:
            add_site(item)
    producer_records = []
    for evidence_id, item in sorted(producer_sites.items()):
        producer_records.append(EvidenceRecord(
            evidence_id,
            EvidenceKind.GRAPH_EDGE,
            str(item['subject_id']),
            'atlas-pr157/1',
            snapshot.snapshot_id,
            tuple(sorted(item['source_refs'])),
            f"project:{item['project']}",
            'java',
            (),
            (),
            float(item['reliability']),
            1.0,
        ))

    roots: dict[str, object] = {}
    for path in test_paths:
        if path.root_evidence_id is not None:
            roots[path.root_evidence_id] = path
    root_records = tuple(
        EvidenceRecord(
            evidence_id,
            EvidenceKind.GRAPH_NODE,
            path.consumer_subject_id,
            'atlas-pr158/1',
            snapshot.snapshot_id,
            (trace.test_evidence_fingerprint,),
            f'project:{report.subject.project}',
            'java',
            (),
            (),
            0.95,
            1.0,
        )
        for evidence_id, path in sorted(roots.items())
    )
    return (summary, *producer_records, *root_records)


def _compact_code_relationship(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    location = value.get('location')
    source_ref = location.get('source_ref') if isinstance(location, Mapping) else None
    return _selected_mapping(value, (
        'canonical_source',
        'canonical_target',
        'relation',
        'subject_relative_role',
        'edge_kind',
        'producer_evidence_id',
        'confidence',
        'execution_eligible',
        'runtime_invocation_proven',
    ), additions={'source_ref': source_ref})


def _compact_code_relationships(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    raw_items = value.get('items', ())
    items = (
        [
            _compact_code_relationship(item)
            for item in raw_items
            if isinstance(item, Mapping)
        ]
        if isinstance(raw_items, Sequence)
        and not isinstance(raw_items, (str, bytes, bytearray))
        else []
    )
    return _selected_mapping(value, (
        'total_count', 'included_count', 'omitted_count',
    ), additions={'items': items})


def _compact_ambiguous_call_groups(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    raw_items = value.get('items', ())
    items = []
    if isinstance(raw_items, Sequence) and not isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            items.append(_selected_mapping(item, (
                'canonical_source',
                'source_ref',
                'producer_evidence_id',
                'resolution_state',
                'total_candidate_count',
                'omitted_candidate_count',
                'included_candidate_ids',
            )))
    return _selected_mapping(value, (
        'call_site_count',
        'omitted_call_site_count',
        'candidate_projection_count',
        'omitted_candidate_count',
    ), additions={
        'confidence': 'conservative_represented_path',
        'limitation': 'Runtime target remains unproven.',
        'items': items,
    })


def _compact_code_relationship_groups(
    value: object,
    *,
    conservative_groups: object = None,
) -> object:
    if not isinstance(value, Mapping):
        return None
    compact = {
        str(name): _compact_code_relationships(section)
        for name, section in sorted(value.items())
        if isinstance(section, Mapping) and name != 'conservative'
    }
    if conservative_groups is None:
        conservative = value.get('conservative')
        if isinstance(conservative, Mapping):
            compact['conservative'] = _compact_code_relationships(conservative)
    else:
        compact['conservative_call_sites'] = _compact_ambiguous_call_groups(
            conservative_groups
        )
    return dict(sorted(compact.items()))


def _compact_code_path_section(
    value: object,
    *,
    include_steps: bool = True,
) -> object:
    if not isinstance(value, Mapping):
        return None
    raw_items = value.get('items', ())
    items = []
    if isinstance(raw_items, Sequence) and not isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            raw_steps = item.get('steps', ())
            steps = (
                [
                    _selected_mapping(step, (
                        'canonical_source',
                        'canonical_target',
                        'edge_kind',
                        'producer_evidence_id',
                    ))
                    for step in raw_steps
                    if isinstance(step, Mapping)
                ]
                if isinstance(raw_steps, Sequence)
                and not isinstance(raw_steps, (str, bytes, bytearray))
                else []
            )
            items.append(_selected_mapping(item, (
                'consumer_subject_id',
                'subject_id',
                'depth',
                'confidence',
                'traversal_direction',
                'canonical_direction',
                'canonical_relation',
                'root_evidence_id',
                'producer_evidence_ids',
                'runtime_execution_proven',
            ), additions={'steps': steps} if include_steps else None))
    return _selected_mapping(value, (
        'total_count', 'included_count', 'omitted_count',
    ), additions={'items': items})


def _compact_code_impact_report(
    value: Mapping[str, object],
    *,
    conservative_callers: object = None,
    conservative_callees: object = None,
) -> dict[str, object]:
    subject = value.get('subject')
    compact_subject = _selected_mapping(subject, (
        'canonical_id',
        'project',
        'kind',
        'owner_type',
        'name',
        'display_name',
        'source_classification',
    ))
    if isinstance(compact_subject, dict) and isinstance(subject, Mapping):
        source = subject.get('source')
        compact_subject['source_ref'] = (
            source.get('source_ref') if isinstance(source, Mapping) else None
        )
    upstream = value.get('upstream_change_impact')
    compact_upstream = None
    if isinstance(upstream, Mapping):
        compact_upstream = {
            'direct': _compact_code_path_section(
                upstream.get('direct'), include_steps=False,
            ),
            'transitive': _compact_code_path_section(upstream.get('transitive')),
            'traversal': _selected_mapping(upstream.get('traversal'), (
                'traversal_direction',
                'canonical_direction',
                'configured_max_depth',
                'configured_max_nodes',
                'visited_node_count',
                'visited_edge_count',
                'depth_histogram',
                'truncated',
            )),
        }
    tests = value.get('represented_test_intelligence')
    compact_tests = None
    if isinstance(tests, Mapping):
        compact_tests = {
            'direct_test_callers': _compact_code_relationships(
                tests.get('direct_test_callers')
            ),
            'high_confidence_paths': _compact_code_path_section(
                tests.get('high_confidence_paths'), include_steps=False,
            ),
            'possible_paths': _compact_code_path_section(
                tests.get('possible_paths'), include_steps=False,
            ),
            'negative_statement': tests.get('negative_statement'),
            'runtime_test_coverage_proven': False,
        }
    raw_limitations = value.get('limitations', ())
    compact_limitations = []
    if isinstance(raw_limitations, Sequence) and not isinstance(
        raw_limitations, (str, bytes, bytearray)
    ):
        for item in raw_limitations[:8]:
            if not isinstance(item, Mapping):
                continue
            compact_limitations.append(_selected_mapping(item, (
                'category', 'total_count', 'included_count', 'omitted_count',
            )))
    raw_capabilities = value.get('capability_availability', ())
    capabilities = (
        [
            _selected_mapping(item, (
                'name', 'availability',
            ))
            for item in raw_capabilities
            if isinstance(item, Mapping)
        ]
        if isinstance(raw_capabilities, Sequence)
        and not isinstance(raw_capabilities, (str, bytes, bytearray))
        else []
    )
    return {
        'subject': compact_subject,
        'direction_contract': value.get('direction_contract'),
        'direct_callers': _compact_code_relationship_groups(
            value.get('direct_callers'),
            conservative_groups=conservative_callers,
        ),
        'direct_callees': _compact_code_relationship_groups(
            value.get('direct_callees'),
            conservative_groups=conservative_callees,
        ),
        'upstream_change_impact': compact_upstream,
        'represented_test_intelligence': compact_tests,
        'limitations': compact_limitations,
        'general_limitations': list(value.get('general_limitations', ()))[:12],
        'capability_availability': capabilities,
        'traceability': value.get('traceability'),
    }


def _response_section(
    section_id,
    heading,
    response,
    item_key,
    result_limit,
    priority,
    *,
    producer,
    extra_keys,
    total_key="total_candidate_count",
):
    raw = response.to_dict()
    raw_items = raw.get(item_key, ())
    maximum_items = min(result_limit, MAXIMUM_OPTIONAL_ITEMS)
    items = [
        _compact_response_item(section_id, item)
        for item in raw_items[:maximum_items]
        if isinstance(item, Mapping)
    ] if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes, bytearray)) else []
    extras = {
        key: _compact_response_extra(key, raw[key])
        for key in extra_keys
        if key in raw
    }
    evidence_ids = _bounded_evidence_ids((items, extras))
    records = _records(response.evidence_index, evidence_ids)
    total = raw.get(total_key, len(items))
    if isinstance(total, bool) or not isinstance(total, int) or total < len(items):
        total = len(items)
    content = {
        "producer": producer,
        item_key: _filter_evidence(items, set(evidence_ids)),
        "total_item_count": total,
        "included_item_count": len(items),
        "omitted_item_count": max(0, total - len(items)),
    }
    for key, value in extras.items():
        content[key] = _filter_evidence(value, set(evidence_ids))
    limitations = {
        str(item) for item in raw.get("limitations", ()) if isinstance(item, str)
    }
    resolution = raw.get("resolution")
    resolution_status = resolution.get("status") if isinstance(resolution, Mapping) else "resolved"
    state = _chat_state(str(resolution_status))
    raw_capabilities = raw.get("capabilities", ())
    if isinstance(raw_capabilities, Sequence) and not isinstance(
        raw_capabilities, (str, bytes, bytearray)
    ):
        states = {
            str(item.get("state", "unavailable"))
            for item in raw_capabilities
            if isinstance(item, Mapping)
        }
        mapped = {_chat_state(item) for item in states}
        for item in raw_capabilities:
            if not isinstance(item, Mapping):
                continue
            values = item.get("limitations", ())
            if isinstance(values, Sequence) and not isinstance(
                values, (str, bytes, bytearray)
            ):
                limitations.update(
                    str(value) for value in values if isinstance(value, str)
                )
    else:
        mapped = set()
    if state is ChatCapabilityState.AVAILABLE and mapped:
        if ChatCapabilityState.AVAILABLE in mapped:
            state = (
                ChatCapabilityState.PARTIAL
                if mapped.difference({ChatCapabilityState.AVAILABLE})
                else ChatCapabilityState.AVAILABLE
            )
        elif ChatCapabilityState.PARTIAL in mapped:
            state = ChatCapabilityState.PARTIAL
        elif ChatCapabilityState.INCOMPATIBLE in mapped:
            state = ChatCapabilityState.INCOMPATIBLE
        elif mapped:
            state = ChatCapabilityState.UNAVAILABLE
    if state is ChatCapabilityState.AVAILABLE and any(
        value for value in raw.get("unavailable_analyses", ())
    ):
        state = ChatCapabilityState.PARTIAL
    section = ChatContextSection(
        section_id,
        section_id,
        heading,
        content,
        evidence_ids,
        priority,
        total,
        len(items),
        max(0, total - len(items)),
    )
    return _CandidateSection(section, records), ChatCapability(
        section_id, state, (producer,), tuple(limitations)
    )


def _compact_response_item(section_id: str, value: Mapping[str, object]) -> dict[str, object]:
    if section_id == "impact_prediction":
        path = value.get("path")
        score = value.get("score")
        return _selected_mapping(value, (
            "category", "strength", "direct", "confidence", "coverage",
            "evidence_ids", "explanation", "module", "package",
            "capability_state", "limitations",
        ), additions={
            "subject": _compact_subject(value.get("subject")),
            "path": _compact_impact_path(path),
            "score": _selected_mapping(score, (
                "value", "evidence_ids", "explanation",
            )),
            "risk_context": _selected_mapping(value.get("risk_context"), (
                "score", "tier", "evidence_ids", "limitations",
            )),
            "breaking_change": _selected_mapping(value.get("breaking_change"), (
                "state", "change_kind", "explanation", "evidence_ids",
                "external_consumers_possible", "limitations",
            )),
        })
    if section_id == "refactoring_advisor":
        subjects = value.get("subjects")
        return _selected_mapping(value, (
            "advice_id", "family", "operation", "confidence", "evidence_ids",
            "rationale", "preconditions", "limitations", "verification",
            "attributes",
        ), additions={
            "subjects": [
                _compact_subject(item) for item in subjects[:8]
                if isinstance(item, Mapping)
            ] if isinstance(subjects, Sequence) and not isinstance(subjects, (str, bytes, bytearray)) else [],
            "expected_gain": _selected_mapping(value.get("expected_gain"), (
                "level", "score", "evidence_ids", "limitations",
            )),
            "effort": _selected_mapping(value.get("effort"), (
                "level", "score", "evidence_ids", "limitations",
            )),
            "impact": _selected_mapping(value.get("impact"), (
                "state", "affected_count", "direct_count", "transitive_count",
                "possible_breaking_count", "omitted_count", "truncated",
                "breaking_state", "evidence_ids", "limitations",
            )),
        })
    if section_id == "security_intelligence":
        return _selected_mapping(value, (
            "finding_id", "category", "rule_id", "severity", "cwe", "owasp",
            "project_id", "language", "location", "canonical_subject_id",
            "canonical_subject_kind", "canonical_subject_name", "confidence",
            "priority", "evidence_ids", "limitations",
        ))
    return _selected_mapping(value, tuple(sorted(value)))


def _compact_impact_path(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    changed_subject = value.get("source_subject_id")
    raw_steps = value.get("steps", ())
    steps = []
    if isinstance(raw_steps, Sequence) and not isinstance(
        raw_steps, (str, bytes, bytearray)
    ):
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                continue
            traversal_source = raw_step.get("source_subject_id")
            traversal_target = raw_step.get("target_subject_id")
            relation = raw_step.get("relation")
            reverse = raw_step.get("reverse") is True
            additions: dict[str, object] = {
                "traversal_source_subject_id": traversal_source,
                "traversal_target_subject_id": traversal_target,
                "traversal": "reverse" if reverse else "forward",
                "canonical_source_subject_id": (
                    traversal_target if reverse else traversal_source
                ),
                "canonical_target_subject_id": (
                    traversal_source if reverse else traversal_target
                ),
                "canonical_relation": relation,
            }
            if relation == "depends_on" and reverse:
                additions["affected_subject_role"] = (
                    "DEPENDENT_OF_CHANGED_SUBJECT"
                    if traversal_source == changed_subject
                    else "DEPENDENT_OF_TRAVERSAL_SOURCE"
                )
            step = _selected_mapping(
                raw_step,
                ("strength", "evidence_ids"),
                additions=additions,
            )
            if step is not None:
                steps.append(step)
    return _selected_mapping(value, (
        "source_subject_id", "target_subject_id", "length",
        "relationships", "evidence_ids", "truncated", "limitations",
    ), additions={"steps": steps})


def _compact_response_extra(key: str, value: object) -> object:
    if key == "resolution":
        return _selected_mapping(value, (
            "status", "total_candidate_count", "omitted_candidate_count",
            "match_basis", "limitations",
        ), additions={
            "subject": _compact_subject(value.get("subject"))
            if isinstance(value, Mapping) else None,
            "candidates": [
                _compact_subject(item)
                for item in value.get("candidates", ())[:12]
                if isinstance(item, Mapping)
            ] if isinstance(value, Mapping)
            and isinstance(value.get("candidates"), Sequence)
            and not isinstance(value.get("candidates"), (str, bytes, bytearray))
            else [],
        })
    if key == "capabilities" and isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        capabilities = [
            _selected_mapping(item, (
                "name", "family", "category", "state", "coverage",
                "finding_count", "evidence_ids", "limitations",
            ))
            for item in value
            if isinstance(item, Mapping)
        ]
        capabilities.sort(key=_compact_capability_key)
        selected = capabilities[:MAXIMUM_OPTIONAL_CAPABILITIES]
        return {
            "items": selected,
            "total_item_count": len(capabilities),
            "included_item_count": len(selected),
            "omitted_item_count": max(0, len(capabilities) - len(selected)),
        }
    if key in {"limitations", "unavailable_analyses"} and isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value[:16])
    if key == "breaking_change":
        return _selected_mapping(value, (
            "state", "change_kind", "explanation", "evidence_ids",
            "external_consumers_possible", "limitations",
        ))
    if key == "request":
        return _selected_mapping(value, (
            "scope", "projects", "languages", "categories", "severities",
            "limit", "canonical_subject_ids",
        ))
    return value


def _compact_subject(value: object) -> object:
    return _selected_mapping(value, (
        "canonical_id", "subject_id", "kind", "name", "qualified_name",
        "project", "language", "match_basis",
    ))


def _compact_capability_key(value: Mapping[str, object]) -> tuple[object, ...]:
    state = str(value.get("state", "unavailable")).casefold()
    state_rank = {
        "available": 0,
        "analyzed": 0,
        "partial": 1,
        "resolved": 1,
        "incompatible": 2,
        "unsupported": 3,
        "not_analyzed": 4,
        "unavailable": 4,
    }.get(state, 5)
    finding_count = value.get("finding_count", 0)
    if isinstance(finding_count, bool) or not isinstance(finding_count, int):
        finding_count = 0
    return (
        state_rank,
        -finding_count,
        str(value.get("category", "")),
        str(value.get("family", "")),
        str(value.get("name", "")),
    )


def _selected_mapping(
    value: object,
    keys: Sequence[str],
    *,
    additions: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    result = {key: value[key] for key in keys if key in value}
    result.update(additions or {})
    return result


def _unavailable_section(
    section_id,
    heading,
    producer,
    limitation,
    priority,
    state=ChatCapabilityState.UNAVAILABLE,
):
    section = ChatContextSection(
        section_id,
        section_id,
        heading,
        {"status": state.value, "limitations": [limitation]},
        (),
        priority,
    )
    return _CandidateSection(section), ChatCapability(
        section_id, state, (producer,), (limitation,)
    )
