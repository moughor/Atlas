from __future__ import annotations

import json

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
)
from moughorai.measurement import MeasurementConfig, MeasurementSession, MetricStatus
from moughorai.repository_evolution import (
    RepositoryEvolutionRequest,
    RepositoryEvolutionService,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


_EXPECTED_PHASES = {
    "repository_evolution.prepare",
    "repository_evolution.compare_nodes",
    "repository_evolution.compare_relations",
}


def _session() -> MeasurementSession:
    return MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_process_memory=False,
        capture_python_memory=False,
        capture_filesystem=False,
    ))


def _snapshot(extra_nodes: int, *, reverse: bool = False) -> AtlasSemanticSnapshot:
    nodes = [
        KnowledgeNode(
            "project:core",
            KnowledgeKind.PROJECT,
            "core",
            qualified_name="core",
            project_id="core",
        )
    ]
    nodes.extend(
        KnowledgeNode(
            f"type:item-{index:05d}",
            KnowledgeKind.TYPE,
            f"demo.Item{index:05d}",
            qualified_name=f"demo.Item{index:05d}",
            project_id="core",
            language="java",
        )
        for index in range(extra_nodes)
    )
    if reverse:
        nodes.reverse()
    graph = KnowledgeGraph(nodes)
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": "C:/controlled/pr141",
                "projects": [{"name": "core", "path": "."}],
            },
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint=f"pr141-{extra_nodes}",
        analyzer_version="test-pr141/1",
    )


def _compare(extra_nodes: int, *, reverse: bool = False):
    base = _snapshot(0)
    head = _snapshot(extra_nodes, reverse=reverse)
    session = _session()
    response = RepositoryEvolutionService(measurement=session).compare(
        base,
        head,
        RepositoryEvolutionRequest(10, 10),
    )
    return base, head, response, session.report()


def test_repository_evolution_records_linear_measurement_phases() -> None:
    _base, _head, response, report = _compare(25)
    by_phase = {sample.phase_id: sample for sample in report.samples}

    assert set(by_phase) == _EXPECTED_PHASES
    assert all(sample.succeeded for sample in report.samples)
    assert all(sample.consumer == "repository-evolution" for sample in report.samples)
    assert by_phase["repository_evolution.prepare"].metric(
        "units_processed"
    ).value == 2
    node_units = by_phase["repository_evolution.compare_nodes"].metric(
        "units_processed"
    )
    assert node_units.status is MetricStatus.MEASURED
    assert node_units.value == 26  # 25 additions plus one unchanged project.
    assert response.total_node_change_count == 25
    assert len(response.node_changes) == 10
    assert response.omitted_node_change_count == 15
    assert "wall_time_ns" not in response.to_json()


def test_repository_evolution_is_ephemeral_and_snapshot_growth_is_zero() -> None:
    base = _snapshot(2)
    head = _snapshot(3)
    before_base = json.dumps(base.to_dict(), sort_keys=True).encode("utf-8")
    before_head = json.dumps(head.to_dict(), sort_keys=True).encode("utf-8")

    first = RepositoryEvolutionService().compare(base, head)
    second = RepositoryEvolutionService().compare(base, head)

    assert first.to_json() == second.to_json()
    assert json.dumps(base.to_dict(), sort_keys=True).encode("utf-8") == before_base
    assert json.dumps(head.to_dict(), sort_keys=True).encode("utf-8") == before_head
    assert "repository_evolution" not in base.semantic_context
    assert "repository_evolution" not in head.semantic_context


def test_large_change_cohort_retains_constant_bounded_response_prefix() -> None:
    sizes = {}
    prefixes = {}
    for count in (10, 100, 1_000):
        _base, _head, response, _report = _compare(count)
        sizes[count] = len(response.to_json().encode("utf-8"))
        prefixes[count] = tuple(item.subject_id for item in response.node_changes)
        assert len(response.node_changes) == 10
        assert response.total_node_change_count == count
        assert response.omitted_node_change_count == count - 10

    assert prefixes[10] == prefixes[100] == prefixes[1_000]
    assert max(sizes.values()) - min(sizes.values()) < 1_024

    _base, _head, reordered, _report = _compare(1_000, reverse=True)
    _base, _head, canonical, _report = _compare(1_000)
    assert reordered.to_json() == canonical.to_json()
