from __future__ import annotations

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import KnowledgeKind
from moughorai.measurement import MeasurementConfig, MeasurementSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import SubjectQuery
from moughorai.technical_debt import TechnicalDebtRequest, TechnicalDebtService

from test_pr142_technical_debt import _architecture, _graph, _request, _snapshot


def _session() -> MeasurementSession:
    return MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_process_memory=False,
        capture_python_memory=False,
        capture_filesystem=False,
    ))


def _cycle_snapshot(size: int) -> tuple[AtlasSemanticSnapshot, tuple[str, ...]]:
    projects = tuple(f"project-{index:03d}" for index in range(size))
    graph = _graph(projects=projects)
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": ".",
            "projects": [
                {"name": name, "path": name, "dependencies": []}
                for name in projects
            ],
        },
        "semantic_graph": graph.to_dict(),
        "architecture": _architecture(projects),
        "symbols": [],
    })
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint=f"pr142-bounded-{size}",
        analyzer_version="test-pr142/1",
    ), projects


def test_measurement_is_semantically_inert_and_records_owned_boundaries() -> None:
    snapshot = _snapshot()
    baseline = TechnicalDebtService.from_snapshot(snapshot).analyze(_request())
    session = _session()
    measured = TechnicalDebtService.from_snapshot(
        snapshot,
        measurement=session,
    ).analyze(_request())

    assert measured.to_dict() == baseline.to_dict()
    phases = {sample.phase_id for sample in session.report().samples}
    assert {
        "technical_debt.prepare",
        "technical_debt.query",
        "technical_debt.cycle_candidates",
        "technical_debt.impact",
    }.issubset(phases)
    assert any(name.startswith("refactoring_advisor.") for name in phases)
    assert any(name.startswith("impact_prediction.") for name in phases)


@pytest.mark.parametrize("size", (3, 12, 40))
def test_small_medium_and_larger_cycles_remain_deterministic_and_bounded(
    size: int,
) -> None:
    snapshot, projects = _cycle_snapshot(size)
    request = TechnicalDebtRequest(
        SubjectQuery(f"project:{projects[0]}", KnowledgeKind.PROJECT),
        limit=min(size, 10),
        candidate_limit=min(size, 16),
        impact_depth=4,
    )
    session = _session()
    first = TechnicalDebtService.from_snapshot(
        snapshot,
        measurement=session,
    ).analyze(request)
    second = TechnicalDebtService.from_snapshot(snapshot).analyze(request)

    assert first.to_json() == second.to_json()
    assert first.total_candidate_count == size
    assert first.evaluated_count == min(size, 16)
    assert first.returned_count == min(size, 10)
    assert first.omitted_count == size - min(size, 10)
    assert len(first.evidence_index.records) <= first.returned_count * (size + 3)
    report = session.report()
    assert report.samples
    assert all(
        sample.metric("units_processed").value >= 0
        for sample in report.samples
        if sample.phase_id.startswith("technical_debt.")
    )


def test_candidate_bound_limits_individual_impact_work_before_materialization() -> None:
    snapshot, projects = _cycle_snapshot(40)
    session = _session()
    response = TechnicalDebtService.from_snapshot(
        snapshot,
        measurement=session,
    ).analyze(TechnicalDebtRequest(
        SubjectQuery(f"project:{projects[0]}", KnowledgeKind.PROJECT),
        limit=5,
        candidate_limit=8,
        impact_depth=2,
    ))

    impact_phase = next(
        sample
        for sample in session.report().samples
        if sample.phase_id == "technical_debt.impact"
    )
    assert response.total_candidate_count == 40
    assert (
        response.evaluated_count
        == impact_phase.metric("units_processed").value
        == 8
    )
    assert response.returned_count == 5
    assert response.omitted_count == 35
