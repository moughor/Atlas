from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    AskResult,
    EngineeringChatContextBuilder,
    validate_citations,
)
from moughorai.ai_ask.engine import (
    _eligible_for_deterministic_impact_fallback,
)
from moughorai.ai_ask.models import (
    ChatCapabilityState,
    ChatContext,
    ChatIntent,
    ChatSelection,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.atlas_cli import app
from moughorai.impact_analysis import (
    ImpactPredictionRequest,
    ImpactPredictionService,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_evidence import EvidenceIndex
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import SubjectQuery


ROOT = "project:root"
DIRECT = tuple(f"project:direct-{index}" for index in range(5))
TRANSITIVE = tuple(f"project:transitive-{index}" for index in range(2))
IMPACT_QUESTION = "If I modify this project, what parts could be affected?"
MIXED_QUESTION = (
    "Explain the impact of changing this project and recommend refactoring."
)
PROVIDER_PROSE = "Ungrounded provider prose."
PR151_FALLBACK_SHA256 = (
    "d54b88859b3e357ca4369ca27efbd13ae10b6f84d4ffd12ea315fa4ace7cfb91"
)
PR151_AGGREGATE_SHA256 = (
    "b81fddd1242a8819a86dfc9f6064c6d9af8c9c4c5d3e734ea72271e4255e83dd"
)
PR151_RESPONSE_SHA256 = (
    "0c44f0b63765a8a35c2368af28df5ad3fdae07fe83dfb709ceeb5fa34e01e0eb"
)
SNAPSHOT_ID = "ead4c238a179d71b1a28030febd1b35db7d635d50344a5c26c33254f0b626342"
GRAPH_DIGEST = "0ad81b230397e22de28e93c856258b9b14531741cff8c9f4ee705402eb68695a"


def _snapshot() -> AtlasSemanticSnapshot:
    identifiers = (ROOT, *DIRECT, *TRANSITIVE)
    nodes = tuple(
        KnowledgeNode(
            identifier,
            KnowledgeKind.PROJECT,
            identifier.removeprefix("project:"),
            qualified_name=identifier.removeprefix("project:"),
            project_id=identifier.removeprefix("project:"),
        )
        for identifier in identifiers
    )
    edges = tuple(
        KnowledgeEdge(
            identifier,
            ROOT,
            KnowledgeRelation.DEPENDS_ON,
            (
                "workspace.projects:"
                + identifier.removeprefix("project:")
                + ":dependencies:root",
            ),
        )
        for identifier in DIRECT
    ) + tuple(
        KnowledgeEdge(
            identifier,
            DIRECT[0],
            KnowledgeRelation.DEPENDS_ON,
            (
                "workspace.projects:"
                + identifier.removeprefix("project:")
                + ":dependencies:direct-0",
            ),
        )
        for identifier in TRANSITIVE
    )
    graph = KnowledgeGraph(nodes, edges)
    projects = [
        {
            "name": identifier.removeprefix("project:"),
            "path": identifier.removeprefix("project:"),
        }
        for identifier in identifiers
    ]
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {"root": ".", "projects": projects},
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr151-impact-grounding",
        analyzer_version="test-pr151/1",
    )


def _analysis(limit: int = 1):
    return ImpactPredictionService.from_snapshot(_snapshot()).analyze(
        ImpactPredictionRequest(SubjectQuery(ROOT), max_depth=4, limit=limit)
    )


def _context(
    question: str = IMPACT_QUESTION,
    *,
    capabilities: tuple[str, ...] = (),
) -> ChatContext:
    return EngineeringChatContextBuilder().build(
        _snapshot(),
        question=question,
        subject=ROOT,
        kind="project",
        capabilities=capabilities,
        result_limit=1,
        token_budget=7_000,
    )


def _section(context: ChatContext, section_id: str):
    return next(
        section for section in context.sections if section.section_id == section_id
    )


def _capability(context: ChatContext, name: str):
    return next(item for item in context.capabilities if item.name == name)


def _ask(
    question: str,
    *,
    capabilities: tuple[str, ...] = (),
) -> AskResult:
    return AskEngine(
        LlmClient(ScriptedLlmProvider((PROVIDER_PROSE,)))
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


class _StaticContextBuilder:
    def __init__(self, context: ChatContext) -> None:
        self.context = context

    def build(self, *_args: object, **_kwargs: object) -> ChatContext:
        return self.context


def _rebuild_context(
    context: ChatContext,
    sections: tuple,
) -> ChatContext:
    evidence_ids = {
        evidence_id
        for section in sections
        for evidence_id in section.evidence_ids
    }
    evidence = EvidenceIndex(
        record
        for record in context.evidence_index.records
        if record.evidence_id in evidence_ids
    ).freeze()
    selection = ChatSelection(
        context.selection.token_budget,
        context.selection.estimated_tokens,
        tuple(section.section_id for section in sections),
        context.selection.omitted_section_count,
        context.selection.truncated,
        context.selection.policy,
    )
    return ChatContext(
        snapshot_id=context.snapshot_id,
        workspace_fingerprint=context.workspace_fingerprint,
        intent=context.intent,
        question=context.question,
        subject_ids=context.subject_ids,
        capabilities=context.capabilities,
        sections=sections,
        evidence_index=evidence,
        selection=selection,
        limitations=context.limitations,
        stale_history_count=context.stale_history_count,
        history_message_count=context.history_message_count,
        producer_version=context.producer_version,
        schema_version=context.schema_version,
    )


def _ask_with_context(context: ChatContext, question: str) -> AskResult:
    return AskEngine(
        LlmClient(ScriptedLlmProvider((PROVIDER_PROSE,))),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        _snapshot(),
        AskRequest(question, subject=ROOT, kind="project", capabilities=("impact",)),
    )


def test_pure_impact_preserves_pr151_fixed_vectors_and_is_deterministic() -> None:
    snapshot = _snapshot()
    snapshot_before = json.dumps(
        snapshot.to_dict(), sort_keys=True, separators=(",", ":")
    )
    analysis = _analysis()
    results = tuple(_ask(IMPACT_QUESTION) for _ in range(2))

    assert snapshot.snapshot_id == SNAPSHOT_ID
    graph = KnowledgeGraph.from_dict(snapshot.semantic_context["semantic_graph"])
    assert graph.stable_digest() == GRAPH_DIGEST
    assert tuple(
        (edge.source, edge.relation, edge.target)
        for edge in graph.outgoing(DIRECT[0])
        if edge.target == ROOT
    ) == ((DIRECT[0], KnowledgeRelation.DEPENDS_ON, ROOT),)
    assert hashlib.sha256(analysis.aggregate.to_json().encode()).hexdigest() == (
        PR151_AGGREGATE_SHA256
    )
    assert hashlib.sha256(analysis.response.to_json().encode()).hexdigest() == (
        PR151_RESPONSE_SHA256
    )
    assert results[0].answer == results[1].answer
    assert hashlib.sha256(results[0].answer.encode()).hexdigest() == (
        PR151_FALLBACK_SHA256
    )
    assert results[0].grounded is True
    assert PROVIDER_PROSE not in results[0].answer
    assert json.dumps(
        snapshot.to_dict(), sort_keys=True, separators=(",", ":")
    ) == snapshot_before


def test_pure_refactoring_without_impact_does_not_trigger_impact_fallback() -> None:
    result = _ask(
        "How should I refactor this project?",
        capabilities=("refactoring",),
    )

    assert result.context is not None
    assert result.context.intent is ChatIntent.REFACTORING
    assert _capability(
        result.context, "impact_prediction"
    ).state is ChatCapabilityState.NOT_REQUESTED
    assert all(
        section.section_id != "impact_aggregate"
        for section in result.context.sections
    )
    assert result.answer == PROVIDER_PROSE


def test_mixed_refactoring_primary_uses_scoped_deterministic_impact_fallback() -> None:
    results = tuple(
        _ask(MIXED_QUESTION, capabilities=("impact", "refactoring"))
        for _ in range(2)
    )
    result = results[0]

    assert result.context is not None
    assert result.context.intent is ChatIntent.REFACTORING
    assert _capability(result.context, "impact_prediction").state in {
        ChatCapabilityState.AVAILABLE,
        ChatCapabilityState.PARTIAL,
    }
    assert _capability(
        result.context, "refactoring_advisor"
    ).state is not ChatCapabilityState.NOT_REQUESTED
    assert _section(result.context, "impact_aggregate").evidence_ids
    assert result.answer.startswith("Atlas deterministic impact answer")
    assert "authoritative deterministic impact dimension" in result.answer
    assert (
        "Other requested dimensions were not deterministically synthesized by this fallback: "
        "refactoring_advisor."
    ) in result.answer
    assert PROVIDER_PROSE not in result.answer
    assert "refactoring advice" not in result.answer.casefold()
    assert result.answer == results[1].answer


def test_explicit_and_inferred_impact_are_equally_fallback_eligible() -> None:
    explicit = _ask("Assess this project.", capabilities=("impact",))
    inferred = _ask(IMPACT_QUESTION)

    assert explicit.context is not None
    assert explicit.context.intent is ChatIntent.UNKNOWN
    assert _section(explicit.context, "impact_aggregate").evidence_ids
    assert explicit.answer.startswith("Atlas deterministic impact answer")
    assert PROVIDER_PROSE not in explicit.answer
    assert inferred.context is not None
    assert inferred.context.intent is ChatIntent.IMPACT
    assert inferred.answer.startswith("Atlas deterministic impact answer")


def test_unavailable_or_incomplete_impact_context_never_fabricates_fallback() -> None:
    snapshot = _snapshot()
    unavailable = EngineeringChatContextBuilder().build(
        snapshot,
        question="Assess this project.",
        subject="project:missing",
        kind="project",
        capabilities=("impact",),
        result_limit=1,
        token_budget=7_000,
    )
    complete = _context()
    without_aggregate = _rebuild_context(
        complete,
        tuple(
            section
            for section in complete.sections
            if section.section_id != "impact_aggregate"
        ),
    )
    aggregate = _section(complete, "impact_aggregate")
    empty_aggregate = replace(aggregate, evidence_ids=())
    without_aggregate_evidence = _rebuild_context(
        complete,
        tuple(
            empty_aggregate if section.section_id == "impact_aggregate" else section
            for section in complete.sections
        ),
    )

    assert _capability(
        unavailable, "impact_prediction"
    ).state is ChatCapabilityState.UNAVAILABLE
    for context in (unavailable, without_aggregate, without_aggregate_evidence):
        assert _eligible_for_deterministic_impact_fallback(context) is False
        result = _ask_with_context(context, context.question)
        assert result.answer == PROVIDER_PROSE


def test_already_grounded_provider_response_is_never_replaced() -> None:
    context = _context()
    aggregate_evidence = _section(context, "impact_aggregate").evidence_ids[0]
    explanation_evidence = _section(
        context, "canonical_explanation"
    ).evidence_ids[0]
    provider_answer = (
        "Grounded provider answer. "
        + aggregate_evidence
        + " "
        + explanation_evidence
    )
    result = AskEngine(
        LlmClient(ScriptedLlmProvider((provider_answer,))),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        _snapshot(),
        AskRequest(IMPACT_QUESTION, subject=ROOT, kind="project"),
    )

    assert result.grounded is True
    assert result.answer == provider_answer
    assert not result.answer.startswith("Atlas deterministic impact answer")
    bare = aggregate_evidence.removeprefix("evidence:")
    unknown = "evidence:" + "f" * 64
    assert validate_citations(aggregate_evidence, (aggregate_evidence,)).valid
    assert not validate_citations(bare, (aggregate_evidence,)).valid
    assert not validate_citations(unknown, (aggregate_evidence,)).valid


def test_conversation_and_ask_serialization_remain_compatible(tmp_path) -> None:
    memory = ConversationMemoryStore(tmp_path)
    request = AskRequest(
        MIXED_QUESTION,
        subject=ROOT,
        kind="project",
        capabilities=("impact", "refactoring"),
        result_limit=1,
    )
    result = AskEngine(
        LlmClient(ScriptedLlmProvider((PROVIDER_PROSE,))),
        memory=memory,
    ).ask(_snapshot(), request)

    assert AskRequest.from_dict(request.to_dict()).to_dict() == request.to_dict()
    assert AskResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    assert result.conversation_id is not None
    turn = memory.turns(result.conversation_id)[0]
    messages = memory.messages(result.conversation_id)
    assert turn.intent == ChatIntent.REFACTORING.value
    assert turn.context_digest == result.context.context_digest
    assert messages[-1].content == result.answer
    assert PROVIDER_PROSE not in messages[-1].content
    assert set(result.to_dict()) == {
        "answer",
        "snapshot_id",
        "conversation_id",
        "context",
        "citations",
        "provider",
        "model",
        "limitations",
        "grounded",
    }


def test_cli_json_shape_and_mixed_fallback_remain_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_cli, "_load_ai_snapshot", lambda *_args: _snapshot())
    monkeypatch.setattr(
        atlas_cli,
        "_ai_provider_factory",
        lambda: ScriptedLlmProvider((PROVIDER_PROSE,)),
    )

    result = CliRunner().invoke(
        app,
        [
            "ai",
            "ask",
            MIXED_QUESTION,
            str(tmp_path),
            "--subject",
            ROOT,
            "--kind",
            "project",
            "--capability",
            "impact",
            "--capability",
            "refactoring",
            "--limit",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "answer",
        "snapshot_id",
        "conversation_id",
        "context",
        "citations",
        "provider",
        "model",
        "limitations",
        "grounded",
    }
    assert payload["context"]["intent"] == "refactoring"
    assert payload["answer"].startswith("Atlas deterministic impact answer")
    assert "authoritative deterministic impact dimension" in payload["answer"]
    assert PROVIDER_PROSE not in payload["answer"]
