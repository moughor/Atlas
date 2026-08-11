from __future__ import annotations

from dataclasses import replace

from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    EngineeringChatContextBuilder,
)
from moughorai.ai_ask.models import (
    ChatCapabilityState,
    ChatContext,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


ROOT = "project:root"
DEPENDENT = "project:dependent"
IMPACT_QUESTION = "If I modify this project, what could be affected?"
REFACTORING_QUESTION = "How should I refactor this project?"
MIXED_QUESTION = "Explain the impact and recommend refactoring."
PROVIDER_PROSE = "Unsupported provider refactoring and security conclusions."


def _snapshot() -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                ROOT,
                KnowledgeKind.PROJECT,
                "root",
                qualified_name="root",
                project_id="root",
            ),
            KnowledgeNode(
                DEPENDENT,
                KnowledgeKind.PROJECT,
                "dependent",
                qualified_name="dependent",
                project_id="dependent",
            ),
        ),
        (
            KnowledgeEdge(
                DEPENDENT,
                ROOT,
                KnowledgeRelation.DEPENDS_ON,
                ("workspace.projects:dependent:dependencies:root",),
            ),
        ),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": ".",
                "projects": [
                    {"name": "dependent", "path": "dependent"},
                    {"name": "root", "path": "root"},
                ],
            },
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr155-multicapability-grounding",
        analyzer_version="test-pr155/1",
    )


def _context(question: str, capabilities: tuple[str, ...]) -> ChatContext:
    context = EngineeringChatContextBuilder().build(
        _snapshot(),
        question=question,
        subject=ROOT,
        kind="project",
        capabilities=capabilities,
        result_limit=1,
        token_budget=7_000,
    )
    if "refactoring" not in capabilities:
        return context
    refactoring = next(
        item
        for item in context.capabilities
        if item.name == "refactoring_advisor"
    )
    if refactoring.state in {
        ChatCapabilityState.AVAILABLE,
        ChatCapabilityState.PARTIAL,
    }:
        return context
    evidence_id = context.evidence_index.records[0].evidence_id
    normalized_capabilities = tuple(
        replace(item, state=ChatCapabilityState.PARTIAL)
        if item.name == "refactoring_advisor"
        else item
        for item in context.capabilities
    )
    normalized_sections = tuple(
        replace(item, evidence_ids=(evidence_id,))
        if item.capability == "refactoring_advisor"
        else item
        for item in context.sections
    )
    return ChatContext(
        context.snapshot_id,
        context.workspace_fingerprint,
        context.intent,
        context.question,
        context.subject_ids,
        normalized_capabilities,
        normalized_sections,
        context.evidence_index,
        context.selection,
        context.limitations,
        context.stale_history_count,
        context.history_message_count,
        producer_version=context.producer_version,
        schema_version=context.schema_version,
    )


class _StaticContextBuilder:
    def __init__(self, context: ChatContext) -> None:
        self.context = context

    def build(self, *_args: object, **_kwargs: object) -> ChatContext:
        return self.context


def _ask(
    question: str,
    capabilities: tuple[str, ...],
    *,
    provider_grounded: bool,
    context: ChatContext | None = None,
    memory: ConversationMemoryStore | None = None,
):
    selected = context or _context(question, capabilities)
    provider_answer = PROVIDER_PROSE
    if provider_grounded:
        provider_answer = "Grounded provider answer. " + " ".join(
            item.evidence_id for item in selected.evidence_index.records
        )
    return AskEngine(
        LlmClient(ScriptedLlmProvider((provider_answer,))),
        memory=memory,
        context_builder=_StaticContextBuilder(selected),
    ).ask(
        _snapshot(),
        AskRequest(
            question,
            subject=ROOT,
            kind="project",
            capabilities=capabilities,
            result_limit=1,
        ),
    )


def _statuses(result) -> dict[str, object]:
    assert result.grounding_summary is not None
    return {
        item.capability: item
        for item in result.grounding_summary.capability_statuses
    }


def test_pure_impact_provider_and_fallback_grounding_states_are_distinct() -> None:
    provider = _ask(
        IMPACT_QUESTION, ("impact",), provider_grounded=True
    )
    fallback_results = tuple(
        _ask(IMPACT_QUESTION, ("impact",), provider_grounded=False)
        for _ in range(2)
    )
    fallback = fallback_results[0]

    assert provider.grounded is True
    assert provider.grounding_summary is not None
    assert provider.grounding_summary.provider_grounded is True
    assert provider.grounding_summary.delivered_answer_grounded is True
    assert provider.grounding_summary.request_complete is True
    assert provider.grounding_summary.fallback_used is False

    assert fallback.grounded is True
    assert fallback.grounding_summary is not None
    assert fallback.grounding_summary.provider_grounded is False
    assert fallback.grounding_summary.delivered_answer_grounded is True
    assert fallback.grounding_summary.request_complete is True
    assert fallback.grounding_summary.fallback_used is True
    assert fallback.grounding_summary.delivered_capabilities == (
        "impact_prediction",
    )
    assert fallback.answer == fallback_results[1].answer
    assert (
        fallback.grounding_summary.to_dict()
        == fallback_results[1].grounding_summary.to_dict()
    )


def test_refactoring_provider_is_conservative_when_grounding_fails() -> None:
    grounded = _ask(
        REFACTORING_QUESTION,
        ("refactoring",),
        provider_grounded=True,
    )
    ungrounded = _ask(
        REFACTORING_QUESTION,
        ("refactoring",),
        provider_grounded=False,
    )

    assert grounded.grounded is True
    assert grounded.grounding_summary is not None
    assert grounded.grounding_summary.provider_grounded is True
    assert grounded.grounding_summary.delivered_answer_grounded is True
    assert grounded.grounding_summary.request_complete is True

    assert ungrounded.answer == PROVIDER_PROSE
    assert ungrounded.grounded is False
    assert ungrounded.grounding_summary is not None
    assert ungrounded.grounding_summary.provider_grounded is False
    assert ungrounded.grounding_summary.delivered_answer_grounded is False
    assert ungrounded.grounding_summary.request_complete is False
    assert ungrounded.grounding_summary.fallback_used is False
    status = _statuses(ungrounded)["refactoring_advisor"]
    assert status.computed is True
    assert status.delivered is False
    assert status.grounded is False


def test_fully_grounded_mixed_provider_covers_every_requested_dimension() -> None:
    result = _ask(
        MIXED_QUESTION,
        ("refactoring", "impact"),
        provider_grounded=True,
    )

    assert result.grounded is True
    assert result.grounding_summary is not None
    assert result.grounding_summary.provider_grounded is True
    assert result.grounding_summary.delivered_answer_grounded is True
    assert result.grounding_summary.request_complete is True
    assert result.grounding_summary.fallback_used is False
    assert result.grounding_summary.delivered_capabilities == (
        "impact_prediction",
        "refactoring_advisor",
    )
    assert result.grounding_summary.omitted_requested_capabilities == ()
    assert all(
        item.delivered and item.grounded
        for item in result.grounding_summary.capability_statuses
    )


def test_mixed_fallback_reports_grounded_impact_and_incomplete_request() -> None:
    results = tuple(
        _ask(
            MIXED_QUESTION,
            ("refactoring", "impact"),
            provider_grounded=False,
        )
        for _ in range(2)
    )
    result = results[0]
    statuses = _statuses(result)

    assert result.grounded is False
    assert result.grounding_summary is not None
    assert result.grounding_summary.provider_grounded is False
    assert result.grounding_summary.delivered_answer_grounded is True
    assert result.grounding_summary.request_complete is False
    assert result.grounding_summary.fallback_used is True
    assert result.grounding_summary.delivered_capabilities == (
        "impact_prediction",
    )
    assert result.grounding_summary.omitted_requested_capabilities == (
        "refactoring_advisor",
    )
    assert statuses["impact_prediction"].computed is True
    assert statuses["impact_prediction"].delivered is True
    assert statuses["impact_prediction"].grounded is True
    assert statuses["refactoring_advisor"].computed is True
    assert statuses["refactoring_advisor"].delivered is False
    assert statuses["refactoring_advisor"].grounded is False
    assert PROVIDER_PROSE not in result.answer
    assert "refactoring conclusions" not in result.answer
    assert result.answer == results[1].answer
    assert result.to_json() == results[1].to_json()


def test_impact_fallback_does_not_promote_unavailable_security() -> None:
    base = _context(
        "Explain impact and security.",
        ("impact", "security"),
    )
    capabilities = tuple(
        replace(item, state=ChatCapabilityState.UNAVAILABLE)
        if item.name == "security_intelligence"
        else item
        for item in base.capabilities
    )
    context = ChatContext(
        base.snapshot_id,
        base.workspace_fingerprint,
        base.intent,
        base.question,
        base.subject_ids,
        capabilities,
        base.sections,
        base.evidence_index,
        base.selection,
        base.limitations,
        base.stale_history_count,
        base.history_message_count,
        producer_version=base.producer_version,
        schema_version=base.schema_version,
    )

    result = _ask(
        context.question,
        ("impact", "security"),
        provider_grounded=False,
        context=context,
    )
    statuses = _statuses(result)

    assert result.grounding_summary is not None
    assert result.grounding_summary.delivered_answer_grounded is True
    assert result.grounding_summary.request_complete is False
    assert statuses["impact_prediction"].delivered is True
    assert statuses["security_intelligence"].computed is False
    assert statuses["security_intelligence"].delivered is False
    assert result.grounding_summary.omitted_requested_capabilities == (
        "security_intelligence",
    )


def test_conversation_references_preserve_legacy_and_add_bounded_truth(
    tmp_path,
) -> None:
    memory = ConversationMemoryStore(tmp_path)
    result = _ask(
        MIXED_QUESTION,
        ("impact", "refactoring"),
        provider_grounded=False,
        memory=memory,
    )

    assert result.conversation_id is not None
    message = memory.messages(result.conversation_id)[-1]
    assert message.references["citation_status"] == "invalid"
    assert message.references["delivered_answer_grounded"] == "true"
    assert message.references["request_complete"] == "false"
    assert message.references["fallback_used"] == "true"
    assert message.references["delivered_capabilities"] == "impact_prediction"
    assert message.references["omitted_requested_capabilities"] == (
        "refactoring_advisor"
    )
    reopened = ConversationMemoryStore(tmp_path)
    assert reopened.messages(result.conversation_id)[-1].references == (
        message.references
    )
