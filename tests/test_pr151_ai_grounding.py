from __future__ import annotations

import json
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    AskResult,
    CitationValidation,
    EngineeringChatContextBuilder,
    validate_citations,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.impact_analysis import ImpactPredictionRequest, ImpactPredictionService
from moughorai.impact_analysis.models import (
    ImpactAggregate,
    ImpactPredictionAnalysis,
    ImpactPredictionResponse,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import SubjectQuery


ROOT = "project:root"
DIRECT = tuple(f"project:direct-{index}" for index in range(5))
TRANSITIVE = tuple(f"project:transitive-{index}" for index in range(2))
QUESTION = "If I modify this project, what parts could be affected?"


def _snapshot(*, reverse: bool = False) -> AtlasSemanticSnapshot:
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
                f"workspace.projects:{identifier.removeprefix('project:')}:dependencies:root",
            ),
        )
        for identifier in DIRECT
    ) + tuple(
        KnowledgeEdge(
            identifier,
            DIRECT[0],
            KnowledgeRelation.DEPENDS_ON,
            (
                f"workspace.projects:{identifier.removeprefix('project:')}:dependencies:direct-0",
            ),
        )
        for identifier in TRANSITIVE
    )
    graph = KnowledgeGraph(
        tuple(reversed(nodes)) if reverse else nodes,
        tuple(reversed(edges)) if reverse else edges,
    )
    projects = [
        {"name": identifier.removeprefix("project:"), "path": identifier.removeprefix("project:")}
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


def _analysis(limit: int, *, reverse: bool = False) -> ImpactPredictionAnalysis:
    return ImpactPredictionService.from_snapshot(_snapshot(reverse=reverse)).analyze(
        ImpactPredictionRequest(
            SubjectQuery(ROOT),
            max_depth=4,
            limit=limit,
        )
    )


def _impact_context(*, token_budget: int = 7_000):
    return EngineeringChatContextBuilder().build(
        _snapshot(),
        question=QUESTION,
        subject=ROOT,
        result_limit=1,
        token_budget=token_budget,
    )


def _section(context, section_id: str):
    return next(
        section for section in context.sections if section.section_id == section_id
    )


def test_complete_aggregate_is_independent_of_representative_limit() -> None:
    one = _analysis(1)
    seven = _analysis(7)

    assert one.aggregate.total_impact_count == 7
    assert one.aggregate.unique_affected_project_count == 7
    assert one.aggregate.direct_affected_project_count == 5
    assert one.aggregate.transitive_affected_project_count == 2
    assert one.aggregate.category_counts == seven.aggregate.category_counts
    assert one.aggregate.depth_histogram == ((1, 5), (2, 2))
    assert one.aggregate.visited_node_count == 8
    assert one.aggregate.visited_edge_count == 7
    assert one.aggregate.traversal_complete is True
    assert one.aggregate.maximum_observed_depth == 2
    assert one.response.total_candidate_count == 7
    assert len(one.response.findings) == 1
    assert one.aggregate.representative_total_count == 7
    assert one.aggregate.representative_included_count == 1
    assert one.aggregate.representative_omitted_count == 6
    assert one.aggregate.representative_complete is False
    assert seven.aggregate.representative_complete is True


def test_aggregate_provenance_and_new_analysis_round_trip_exactly() -> None:
    analysis = _analysis(1)
    aggregate = analysis.aggregate

    assert len(aggregate.evidence_index) == 1
    assert aggregate.evidence_ids[0].startswith("evidence:")
    record = aggregate.evidence_index.records[0]
    detail = dict(record.detail)
    assert detail["derivation"] == "deduplicated_impact_plans"
    assert detail["total_impact_count"] == "7"
    assert detail["traversal_complete"] == "true"
    assert "runtime" in " ".join(aggregate.limitations).casefold()
    assert ImpactAggregate.from_dict(aggregate.to_dict()).to_dict() == (
        aggregate.to_dict()
    )
    assert ImpactPredictionAnalysis.from_dict(analysis.to_dict()).to_dict() == (
        analysis.to_dict()
    )

    tampered = deepcopy(aggregate.to_dict())
    tampered["direct_affected_project_count"] = 4
    tampered["transitive_affected_project_count"] = 3
    with pytest.raises(ValueError, match="does not bind"):
        ImpactAggregate.from_dict(tampered)

    legacy = analysis.response
    assert ImpactPredictionResponse.from_dict(legacy.to_dict()).to_dict() == (
        legacy.to_dict()
    )
    assert ImpactPredictionService.from_snapshot(_snapshot()).predict(
        ImpactPredictionRequest(SubjectQuery(ROOT), limit=1)
    ).to_dict() == legacy.to_dict()


def test_aggregate_order_and_identity_are_stable_for_reordered_graphs() -> None:
    forward = _analysis(1)
    reverse = _analysis(1, reverse=True)

    assert forward.aggregate.to_json() == reverse.aggregate.to_json()
    assert forward.aggregate.evidence_ids == reverse.aggregate.evidence_ids
    assert forward.response.to_json() == reverse.response.to_json()


def test_impact_context_retains_complete_aggregate_and_bounded_details() -> None:
    context = _impact_context()
    aggregate = _section(context, "impact_aggregate")
    representatives = _section(context, "impact_prediction")
    payload = aggregate.content["aggregate"]

    assert payload["total_impact_count"] == 7
    assert payload["direct_affected_project_count"] == 5
    assert payload["transitive_affected_project_count"] == 2
    assert payload["depth_histogram"] == {"1": 5, "2": 2}
    assert payload["runtime_usage_proven"] is False
    assert {"dependencies", "risk", "tests"}.issubset(payload["capabilities"])
    assert aggregate.included_item_count == aggregate.total_item_count == 1
    assert aggregate.omitted_item_count == 0
    assert representatives.total_item_count == 7
    assert representatives.included_item_count == 1
    assert representatives.omitted_item_count == 6
    assert representatives.truncated is True


def test_mandatory_aggregate_survives_when_representatives_are_omitted() -> None:
    selected = None
    for budget in range(1_500, 6_001, 250):
        try:
            context = _impact_context(token_budget=budget)
        except ValueError:
            continue
        section_ids = {section.section_id for section in context.sections}
        if "impact_aggregate" in section_ids and "impact_prediction" not in section_ids:
            selected = context
            break

    assert selected is not None
    aggregate = _section(selected, "impact_aggregate")
    assert aggregate.content["aggregate"]["total_impact_count"] == 7
    assert aggregate.evidence_ids


def test_prompt_contract_prohibits_exhaustive_language_for_bounded_lists() -> None:
    prompt = SemanticPromptBuilder.ENGINEERING_CHAT_TEMPLATE.system

    assert "aggregates" in prompt
    assert "total, included, omitted, and complete" in prompt
    assert "Never describe a bounded list as only, all, complete, exhaustive" in prompt
    assert "do not prove runtime usage" in prompt
    assert "exact evidence:<sha256>" in prompt


def test_strict_citations_and_explicit_subject_grounding_require_aggregate() -> None:
    context = _impact_context()
    aggregate = _section(context, "impact_aggregate")
    aggregate_evidence = aggregate.evidence_ids[0]
    bare = aggregate_evidence.removeprefix("evidence:")
    unknown = "evidence:" + "f" * 64

    assert validate_citations(aggregate_evidence, (aggregate_evidence,)).valid
    assert not validate_citations(bare, (aggregate_evidence,)).valid
    assert not validate_citations(unknown, (aggregate_evidence,)).valid

    grounded = AskResult(
        f"Deterministic impact aggregate. {aggregate_evidence}",
        context.snapshot_id,
        None,
        context,
        CitationValidation(
            (aggregate_evidence,),
            (aggregate_evidence,),
        ),
    )
    assert grounded.grounded is True

    explanation = _section(context, "canonical_explanation")
    explanation_evidence = explanation.evidence_ids[0]
    missing_impact = AskResult(
        f"Explanation evidence. {explanation_evidence}",
        context.snapshot_id,
        None,
        context,
        CitationValidation(
            (explanation_evidence,),
            (explanation_evidence,),
        ),
    )
    assert missing_impact.grounded is False


def test_failed_provider_is_replaced_by_identical_grounded_fallback() -> None:
    outputs = []
    for _ in range(2):
        provider = ScriptedLlmProvider(("Ungrounded provider prose.",))
        result = AskEngine(LlmClient(provider)).ask(
            _snapshot(),
            AskRequest(QUESTION, subject=ROOT, result_limit=1),
        )
        outputs.append(result.answer)
        assert result.grounded is True
        assert result.answer.startswith("Atlas deterministic impact answer")
        assert "Ungrounded provider prose" not in result.answer
        assert "7 impact classifications" in result.answer
        assert "5 direct and 2 transitive" in result.answer
        assert "included 1 of 7, omitted 6, complete: false" in result.answer
        assert "do not prove runtime usage" in result.answer
        assert any(
            "Provider grounding failed" in limitation
            for limitation in result.limitations
        )
        assert result.citations.valid
        assert result.citations.accepted_evidence_ids

    assert outputs[0] == outputs[1]


def test_cli_leads_with_deterministic_fallback_not_provider_prose(
    tmp_path, monkeypatch
) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(
        atlas_cli, "_load_ai_snapshot", lambda _root, _path: snapshot
    )
    monkeypatch.setattr(
        atlas_cli,
        "_ai_provider_factory",
        lambda: ScriptedLlmProvider(("Ungrounded provider prose.",)),
    )

    result = CliRunner().invoke(
        app,
        [
            "ai", "ask", QUESTION, str(tmp_path),
            "--subject", ROOT,
            "--limit", "1",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.startswith("Atlas deterministic impact answer")
    assert "Ungrounded provider prose" not in result.stdout
    assert "7 impact classifications" in result.stdout
    assert result.stderr == ""


def test_snapshot_and_legacy_response_remain_unchanged_by_analysis() -> None:
    snapshot = _snapshot()
    before = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"))

    analysis = ImpactPredictionService.from_snapshot(snapshot).analyze(
        ImpactPredictionRequest(SubjectQuery(ROOT), limit=1)
    )

    assert json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":")) == before
    assert "aggregate" not in analysis.response.to_dict()
