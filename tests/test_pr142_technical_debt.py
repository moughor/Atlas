from __future__ import annotations

import json

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.risk_analysis import (
    RiskAnalysisService,
    RiskMetricInput,
    RiskMetricKind,
)
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import SubjectQuery
from moughorai.technical_debt import (
    DEPENDENCY_CYCLE_OBSERVATION,
    TechnicalDebtCapabilityKind,
    TechnicalDebtRequest,
    TechnicalDebtResponse,
    TechnicalDebtService,
    TechnicalDebtState,
    render_technical_debt,
)


PROJECTS = ("alpha", "beta", "gamma")


def _node(name: str) -> KnowledgeNode:
    return KnowledgeNode(
        f"project:{name}",
        KnowledgeKind.PROJECT,
        name,
        qualified_name=name,
        project_id=name,
        language="java",
    )


def _edge(source: str, target: str, *, authoritative: bool = True) -> KnowledgeEdge:
    return KnowledgeEdge(
        f"project:{source}",
        f"project:{target}",
        KnowledgeRelation.DEPENDS_ON,
        (
            f"workspace.projects:{source}:dependencies:{target}",
        ) if authoritative else ("unverified-cycle-claim",),
    )


def _graph(
    *,
    projects: tuple[str, ...] = PROJECTS,
    authoritative: bool = True,
    reverse: bool = False,
) -> KnowledgeGraph:
    edges = tuple(
        _edge(projects[index], projects[(index + 1) % len(projects)], authoritative=authoritative)
        for index in range(len(projects))
    )
    nodes = tuple(_node(name) for name in projects)
    return KnowledgeGraph(
        tuple(reversed(nodes)) if reverse else nodes,
        tuple(reversed(edges)) if reverse else edges,
    )


def _architecture(
    projects: tuple[str, ...] = PROJECTS,
    *,
    executed: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "findings": [],
        "dependency_directions": [
            {"source": projects[index], "target": projects[(index + 1) % len(projects)]}
            for index in range(len(projects))
        ],
        "dependency_cycles": [list(projects)],
        "bounded_contexts": [],
        "ports": [],
        "adapters": [],
        "infrastructure_layers": [],
        "dependency_analysis": {
            "executed": executed,
            "evidence_edge_count": len(projects),
        },
        "classification_conflicts": [],
    }


def _risk_report(graph: KnowledgeGraph) -> dict[str, object]:
    values = {"alpha": 10.0, "beta": 20.0, "gamma": 30.0}
    inputs = []
    for name in PROJECTS:
        subject_id = f"project:{name}"
        evidence = EvidenceRecord.create(
            EvidenceKind.SEMANTIC_FACT,
            subject_id,
            "test-complexity-producer/1",
            "risk-input-fixture",
            source_refs=(f"semantic-fact:{subject_id}:complexity",),
            detail={"metric": "complexity", "unit": "cyclomatic_complexity"},
            reliability=0.9,
            specificity=0.95,
        )
        inputs.append(RiskMetricInput(
            subject_id,
            RiskMetricKind.COMPLEXITY,
            values[name],
            "cyclomatic_complexity",
            "test-complexity-producer/1",
            (evidence,),
        ))
    summary = {
        "projects": [
            {
                "name": name,
                "classified_non_test_source_files": 1,
                "primary_language": "java",
            }
            for name in PROJECTS
        ],
    }
    return RiskAnalysisService().analyze(
        graph,
        repository_summary=summary,
        metric_inputs=tuple(inputs),
    ).to_dict()


def _mixed_risk_report(graph: KnowledgeGraph) -> dict[str, object]:
    specifications = (
        (
            "project:alpha",
            RiskMetricKind.CHANGE_FREQUENCY,
            100.0,
            "commits",
        ),
        (
            "project:beta",
            RiskMetricKind.COMPLEXITY,
            5.0,
            "cyclomatic_complexity",
        ),
    )
    inputs = []
    for subject_id, kind, value, unit in specifications:
        evidence = EvidenceRecord.create(
            EvidenceKind.SEMANTIC_FACT,
            subject_id,
            "test-mixed-risk/1",
            "mixed-risk-input",
            source_refs=(f"semantic-fact:{subject_id}:{kind.value}",),
            detail={"metric": kind.value, "unit": unit},
            reliability=0.9,
            specificity=0.95,
        )
        inputs.append(RiskMetricInput(
            subject_id,
            kind,
            value,
            unit,
            "test-mixed-risk/1",
            (evidence,),
        ))
    return RiskAnalysisService().analyze(
        graph,
        repository_summary={
            "projects": [
                {
                    "name": name,
                    "classified_non_test_source_files": 1,
                    "primary_language": "java",
                }
                for name in PROJECTS
            ],
        },
        metric_inputs=tuple(inputs),
    ).to_dict()


def _snapshot(
    graph: KnowledgeGraph | None = None,
    *,
    architecture: object | None = None,
    risk_analysis: object | None = None,
    additions: dict[str, object] | None = None,
) -> AtlasSemanticSnapshot:
    selected = graph or _graph()
    context: dict[str, object] = {
        "schema_version": 1,
        "workspace": {
            "root": ".",
            "projects": [
                {"name": name, "path": name, "dependencies": []}
                for name in PROJECTS
            ],
        },
        "semantic_graph": selected.to_dict(),
        "architecture": _architecture() if architecture is None else architecture,
        "symbols": [],
    }
    if risk_analysis is not None:
        context["risk_analysis"] = risk_analysis
    context.update(additions or {})
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr142-cycle-fixture",
        analyzer_version="test-pr142/1",
    )


def _request(
    *,
    limit: int = 20,
    candidate_limit: int = 100,
    impact_depth: int = 4,
) -> TechnicalDebtRequest:
    return TechnicalDebtRequest(
        SubjectQuery("project:alpha", KnowledgeKind.PROJECT),
        limit,
        candidate_limit,
        impact_depth,
    )


def _analyze(
    snapshot: AtlasSemanticSnapshot | None = None,
    request: TechnicalDebtRequest | None = None,
) -> TechnicalDebtResponse:
    return TechnicalDebtService.from_snapshot(snapshot or _snapshot()).analyze(
        request or _request()
    )


def _capability(
    response: TechnicalDebtResponse,
    kind: TechnicalDebtCapabilityKind,
):
    return next(item for item in response.capabilities if item.capability is kind)


def test_verified_cycle_is_ranked_only_from_revalidated_pr137_advice() -> None:
    response = _analyze()

    assert response.total_candidate_count == response.evaluated_count == 3
    assert response.returned_count == response.ranked_count == 3
    assert response.unranked_count == response.omitted_count == 0
    assert [item.rank for item in response.items] == [1, 2, 3]
    assert all(
        item.observation == DEPENDENCY_CYCLE_OBSERVATION
        and item.impact.state is TechnicalDebtState.PARTIAL
        and item.impact.affected_count == 1
        and item.refactoring_advice_ids
        and all(
            advice_id.startswith("refactoring-advice:")
            for advice_id in item.refactoring_advice_ids
        )
        and len(item.subjects) == 2
        and item.evidence_ids
        for item in response.items
    )
    assert _capability(
        response, TechnicalDebtCapabilityKind.CYCLE_EVIDENCE
    ).state is TechnicalDebtState.AVAILABLE
    available = {record.evidence_id for record in response.evidence_index.records}
    assert available == {
        evidence_id for item in response.items for evidence_id in item.evidence_ids
    }
    assert all(
        record.snapshot_id == response.lineage
        for record in response.evidence_index.records
    )


def test_response_round_trip_and_repeated_execution_are_exact() -> None:
    snapshot = _snapshot()
    first = _analyze(snapshot)
    second = _analyze(snapshot)
    payload = first.to_dict()

    assert TechnicalDebtResponse.from_dict(payload).to_dict() == payload
    assert json.loads(first.to_json()) == payload
    assert first.to_json() == second.to_json()
    assert TechnicalDebtRequest.from_dict(first.request.to_dict()) == first.request


def test_risk_and_complexity_are_context_only_and_tie_break_equal_impact() -> None:
    graph = _graph()
    response = _analyze(_snapshot(graph, risk_analysis=_risk_report(graph)))

    assert response.total_candidate_count == 3
    assert [item.risk_context.rank for item in response.items] == [1, 1, 2]
    assert all(
        item.complexity_observed
        and item.risk_context is not None
        and item.risk_subject_id in {
            participant.canonical_id for participant in item.subjects
        }
        and "complexity" in item.risk_context.signals
        for item in response.items
    )
    assert _capability(
        response, TechnicalDebtCapabilityKind.RISK_CONTEXT
    ).state is TechnicalDebtState.PARTIAL
    assert _capability(
        response, TechnicalDebtCapabilityKind.STRUCTURED_COMPLEXITY
    ).state is TechnicalDebtState.PARTIAL
    sort_components = [
        (
            -item.impact.affected_count,
            -item.impact.direct_count,
            -item.risk_context.score,
            item.item_id,
        )
        for item in response.items
    ]
    assert sort_components == sorted(sort_components)
    for item in response.items:
        risk_records = [
            record
            for record in response.evidence_index.records
            if record.evidence_id in item.risk_context.evidence_ids
        ]
        assert len(risk_records) == 1
        assert risk_records[0].subject_id == item.risk_subject_id
    rendered = render_technical_debt(response)
    assert all(
        f"risk-subject={item.risk_subject_id}" in rendered
        for item in response.items
    )


def test_complexity_evidence_is_preserved_independently_of_highest_risk_subject() -> None:
    graph = _graph()
    response = _analyze(_snapshot(
        graph,
        risk_analysis=_mixed_risk_report(graph),
    ))
    item = next(
        candidate for candidate in response.items
        if candidate.source.canonical_id == "project:alpha"
        and candidate.target.canonical_id == "project:beta"
    )

    assert item.risk_subject_id == "project:alpha"
    assert item.risk_context is not None
    assert "complexity" not in item.risk_context.signals
    assert item.complexity_subject_ids == ("project:beta",)
    assert item.complexity_evidence_ids
    complexity_records = [
        record
        for record in response.evidence_index.records
        if record.evidence_id in item.complexity_evidence_ids
    ]
    assert complexity_records
    assert {record.subject_id for record in complexity_records} == {
        "project:beta"
    }
    assert set(item.complexity_evidence_ids).issubset(item.evidence_ids)
    rendered = render_technical_debt(response)
    assert "risk-subject=project:alpha" in rendered
    assert "complexity-subjects=project:beta" in rendered


def test_bounds_preserve_exact_total_evaluated_and_omitted_counts() -> None:
    response = _analyze(request=_request(limit=1, candidate_limit=2))

    assert response.total_candidate_count == 3
    assert response.evaluated_count == 2
    assert response.unique_evaluated_count == 2
    assert response.equivalent_observation_count == 0
    assert response.returned_count == 1
    assert response.omitted_count == 2
    assert response.truncated is True
    assert response.ranked_count == 1
    assert any("bounds omitted" in item for item in response.limitations)
    impact = _capability(
        response, TechnicalDebtCapabilityKind.ENGINEERING_IMPACT
    )
    assert impact.coverage == pytest.approx(2 / 3)


def test_risk_only_and_raw_unrevalidated_cycle_claims_create_no_item() -> None:
    acyclic = KnowledgeGraph(tuple(_node(name) for name in PROJECTS), ())
    risk_only = _analyze(_snapshot(
        acyclic,
        architecture=_architecture(),
        risk_analysis=_risk_report(acyclic),
    ))
    raw_graph = _graph(authoritative=False)
    raw = _analyze(_snapshot(raw_graph, architecture=_architecture()))

    assert risk_only.items == ()
    assert raw.items == ()
    assert risk_only.total_candidate_count == raw.total_candidate_count == 0
    assert _capability(
        risk_only, TechnicalDebtCapabilityKind.CYCLE_EVIDENCE
    ).state in {
        TechnicalDebtState.INSUFFICIENT,
        TechnicalDebtState.UNAVAILABLE,
    }
