from __future__ import annotations

import json

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.architecture_detection import ArchitectureDetectionService
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.measurement import MeasurementConfig, MeasurementSession
from moughorai.refactoring_advisor.models import (
    RefactoringFamily,
    RefactoringOperation,
    RefactoringRequest,
    RefactoringResponse,
    RefactoringCapabilityState as RefactoringState,
)
from moughorai.refactoring_advisor.service import RefactoringAdvisorService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver, SubjectQuery


PROJECTS = ("alpha", "beta", "gamma")
PROJECT_IDS = tuple(f"project:{name}" for name in PROJECTS)


def _node(name: str) -> KnowledgeNode:
    return KnowledgeNode(
        f"project:{name}",
        KnowledgeKind.PROJECT,
        name,
        qualified_name=name,
        project_id=name,
        language="java",
    )


def _cycle_edges(*, authoritative: bool = True) -> tuple[KnowledgeEdge, ...]:
    evidence = (
        lambda source, target: (
            f"workspace.projects:{source}:dependencies:{target}",
        )
        if authoritative
        else ("synthetic-dependency",)
    )
    return tuple(
        KnowledgeEdge(
            f"project:{source}",
            f"project:{target}",
            KnowledgeRelation.DEPENDS_ON,
            evidence(source, target),
        )
        for source, target in (
            ("alpha", "beta"),
            ("beta", "gamma"),
            ("gamma", "alpha"),
        )
    )


def _graph(
    *,
    edges: tuple[KnowledgeEdge, ...] | None = None,
    reverse: bool = False,
) -> KnowledgeGraph:
    nodes = tuple(_node(name) for name in PROJECTS)
    selected_edges = _cycle_edges() if edges is None else edges
    if reverse:
        nodes = tuple(reversed(nodes))
        selected_edges = tuple(reversed(selected_edges))
    return KnowledgeGraph(nodes, selected_edges)


def _architecture(
    cycles: object = (("alpha", "beta", "gamma"),),
    *,
    executed: bool = True,
    evidence_edge_count: int = 3,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "findings": [],
        "dependency_directions": [
            {"source": "alpha", "target": "beta"},
            {"source": "beta", "target": "gamma"},
            {"source": "gamma", "target": "alpha"},
        ],
        "dependency_cycles": [list(item) for item in cycles],
        "bounded_contexts": [],
        "ports": [],
        "adapters": [],
        "infrastructure_layers": [],
        "dependency_analysis": {
            "executed": executed,
            "evidence_edge_count": evidence_edge_count,
        },
        "classification_conflicts": [],
    }


def _context(
    graph: KnowledgeGraph | None = None,
    *,
    architecture: object = None,
    additions: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_graph = graph or _graph()
    value: dict[str, object] = {
        "schema_version": 1,
        "workspace": {
            "root": ".",
            "projects": [
                {"name": name, "path": name, "dependencies": []}
                for name in PROJECTS
            ],
        },
        "semantic_graph": selected_graph.to_dict(),
        "architecture": _architecture() if architecture is None else architecture,
        "symbols": [],
    }
    value.update(additions or {})
    return value


def _snapshot(
    graph: KnowledgeGraph | None = None,
    *,
    architecture: object = None,
    additions: dict[str, object] | None = None,
) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(_context(
            graph,
            architecture=architecture,
            additions=additions,
        )),
        workspace_fingerprint="pr137-cycle-fixture",
        analyzer_version="test-pr137/1",
    )


def _request(
    *,
    limit: int = 20,
    include_impact: bool = False,
) -> RefactoringRequest:
    return RefactoringRequest(
        SubjectQuery("project:alpha", KnowledgeKind.PROJECT),
        families=(RefactoringFamily.CYCLE_BREAKING,),
        limit=limit,
        include_impact=include_impact,
        impact_depth=4,
    )


def _advise(
    *,
    snapshot: AtlasSemanticSnapshot | None = None,
    request: RefactoringRequest | None = None,
    measurement: MeasurementSession | None = None,
) -> RefactoringResponse:
    selected = snapshot or _snapshot()
    return RefactoringAdvisorService.from_snapshot(
        selected,
        measurement=measurement,
    ).advise(request or _request())


def _capability(response: RefactoringResponse, family: RefactoringFamily):
    return next(item for item in response.capabilities if item.family is family)


def test_verified_three_project_cycle_produces_traceable_ranked_seams() -> None:
    response = _advise()

    assert response.total_candidate_count == 3
    assert response.omitted_count == 0
    assert response.truncated is False
    assert len(response.advice) == 3
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.AVAILABLE
    assert all(
        item.family is RefactoringFamily.CYCLE_BREAKING
        and item.operation is RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM
        and len(item.subjects) == 2
        and item.expected_gain.level.value == "unknown"
        and item.expected_gain.score is None
        and item.effort.level.value == "unknown"
        and item.evidence_ids
        and item.preconditions
        and item.verification
        for item in response.advice
    )
    available_evidence = {
        record.evidence_id for record in response.evidence_index.records
    }
    assert available_evidence == {
        evidence_id
        for item in response.advice
        for evidence_id in item.evidence_ids
    }
    assert all(
        record.snapshot_id == response.lineage
        for record in response.evidence_index.records
    )


def test_normal_pr128_producer_and_cross_project_imports_create_advice() -> None:
    project_nodes = tuple(_node(name) for name in PROJECTS)
    type_nodes = tuple(
        KnowledgeNode(
            f"type:{name}",
            KnowledgeKind.TYPE,
            name.title(),
            qualified_name=f"example.{name.title()}",
            project_id=name,
            language="java",
        )
        for name in PROJECTS
    )
    graph = KnowledgeGraph(
        (*project_nodes, *type_nodes),
        tuple(
            KnowledgeEdge(
                f"type:{source}",
                f"type:{target}",
                KnowledgeRelation.IMPORTS,
                ("imports",),
            )
            for source, target in (
                ("alpha", "beta"),
                ("beta", "gamma"),
                ("gamma", "alpha"),
            )
        ),
    )
    architecture = ArchitectureDetectionService().detect(
        {}, graph.to_dict(),
    ).to_dict()
    snapshot = _snapshot(graph=graph, architecture=architecture)

    response = _advise(snapshot=snapshot)

    assert architecture["dependency_cycles"] == [["alpha", "beta", "gamma"]]
    assert len(response.advice) == 3
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.AVAILABLE
    assert {
        item["relations"]
        for record in response.evidence_index.records
        if record.kind.value == "graph_edge"
        for item in (dict(record.detail),)
    } == {"imports"}


def test_response_round_trip_json_and_request_normalization_are_exact() -> None:
    response = _advise()
    encoded = response.to_dict()

    assert RefactoringResponse.from_dict(encoded).to_dict() == encoded
    assert json.loads(response.to_json()) == encoded
    request = RefactoringRequest(
        SubjectQuery("project:alpha", KnowledgeKind.PROJECT),
        families=(
            RefactoringFamily.CYCLE_BREAKING,
            RefactoringFamily.CYCLE_BREAKING,
        ),
        include_impact=False,
    )
    assert RefactoringRequest.from_dict(request.to_dict()) == request
    assert request.families == (RefactoringFamily.CYCLE_BREAKING,)


def test_rotated_duplicate_cycles_and_reordered_graph_are_byte_deterministic() -> None:
    graph = _graph()
    reversed_graph = _graph(reverse=True)
    resolver = CanonicalSubjectResolver(graph)
    reversed_resolver = CanonicalSubjectResolver(reversed_graph)
    first_context = _context(
        graph,
        architecture=_architecture((("alpha", "beta", "gamma"),)),
    )
    second_context = _context(
        reversed_graph,
        architecture=_architecture((
            ("gamma", "alpha", "beta"),
            ("beta", "gamma", "alpha"),
        )),
    )
    first = RefactoringAdvisorService(
        resolver,
        snapshot_id="same-pr137-lineage",
        analyzer_version="test-pr137/1",
        semantic_context=first_context,
    ).advise(_request())
    second = RefactoringAdvisorService(
        reversed_resolver,
        snapshot_id="same-pr137-lineage",
        analyzer_version="test-pr137/1",
        semantic_context=second_context,
    ).advise(_request())

    assert graph.stable_digest() == reversed_graph.stable_digest()
    assert first.to_json() == second.to_json()


def test_limit_is_exact_and_truncation_never_hides_total_candidates() -> None:
    response = _advise(request=_request(limit=1))

    assert len(response.advice) == 1
    assert response.total_candidate_count == 3
    assert response.omitted_count == 2
    assert response.truncated is True
    assert any("bounded" in item.casefold() for item in response.limitations)


def test_every_unsupported_family_remains_explicit() -> None:
    response = _advise()
    states = {item.family: item.state for item in response.capabilities}

    assert states[RefactoringFamily.DUPLICATE_CONSOLIDATION] is RefactoringState.UNAVAILABLE
    assert states[RefactoringFamily.EXTRACTION] is RefactoringState.INSUFFICIENT
    assert states[RefactoringFamily.PACKAGE_RESTRUCTURING] is RefactoringState.INSUFFICIENT
    assert states[RefactoringFamily.DEPENDENCY_CLEANUP] is RefactoringState.INSUFFICIENT
    assert states[RefactoringFamily.LAYER_VIOLATION] is RefactoringState.UNAVAILABLE


def test_measurement_is_semantically_inert_and_records_real_boundaries() -> None:
    snapshot = _snapshot()
    baseline = _advise(snapshot=snapshot)
    measurement = MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_process_memory=False,
        capture_python_memory=False,
        capture_filesystem=False,
    ))
    measured = _advise(snapshot=snapshot, measurement=measurement)

    assert measured.to_dict() == baseline.to_dict()
    assert {
        "refactoring_advisor.resolver_index",
        "refactoring_advisor.query",
        "refactoring_advisor.resolve",
        "refactoring_advisor.cycle_validate",
        "refactoring_advisor.impact",
        "refactoring_advisor.materialize",
    }.issubset({sample.phase_id for sample in measurement.report().samples})
