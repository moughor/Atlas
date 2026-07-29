from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest

from moughorai.workspace import (
    FileEvent,
    FileEventKind,
    IncrementalWorkspacePlanner,
    ProjectRunStatus,
    WorkspaceAnalysisOrchestrator,
    WorkspaceEventKind,
    WorkspaceService,
)


def make_service(tmp_path: Path) -> WorkspaceService:
    for name in ("core", "api", "ui", "docs", "tools"):
        (tmp_path / name).mkdir()
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n"
        "  - name: api\n    path: api\n    dependencies: [core]\n"
        "  - name: ui\n    path: ui\n    dependencies: [api]\n"
        "  - name: docs\n    path: docs\n"
        "  - name: tools\n    path: tools\n",
        encoding="utf-8",
    )
    return WorkspaceService(tmp_path)


def test_parallel_execution_runs_independent_projects_together(tmp_path: Path) -> None:
    barrier = Barrier(3)
    seen: list[str] = []
    lock = Lock()

    def analyze(project, dependencies):
        if project.name in {"core", "docs", "tools"}:
            barrier.wait(timeout=2)
        with lock:
            seen.append(project.name)
        return project.name

    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyze, max_workers=3)
    assert report.succeeded
    assert set(seen[:3]) == {"core", "docs", "tools"}


def test_report_order_remains_topological_and_deterministic(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        lambda project, dependencies: project.name, max_workers=4
    )
    assert report.analysis_order == ("core", "api", "docs", "tools", "ui")
    assert tuple(run.project for run in report.runs) == report.analysis_order


def test_dependencies_wait_for_successful_completion(tmp_path: Path) -> None:
    completed: list[str] = []
    lock = Lock()

    def analyze(project, dependencies):
        if project.name == "core":
            sleep(0.03)
        with lock:
            completed.append(project.name)
        return project.name

    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyze, max_workers=5)
    assert completed.index("core") < completed.index("api") < completed.index("ui")


def test_dependency_results_are_passed_in_parallel_mode(tmp_path: Path) -> None:
    observed = {}

    def analyze(project, dependencies):
        observed[project.name] = dict(dependencies)
        return project.name

    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyze, max_workers=3)
    assert observed["api"] == {"core": "core"}
    assert observed["ui"] == {"api": "api"}


def test_failure_blocks_dependents_but_not_independent_projects(tmp_path: Path) -> None:
    calls: list[str] = []

    def analyze(project, dependencies):
        calls.append(project.name)
        if project.name == "core":
            raise RuntimeError("boom")
        return project.name

    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyze, max_workers=3)
    assert report.get("core").status is ProjectRunStatus.FAILED
    assert report.get("api").status is ProjectRunStatus.BLOCKED
    assert report.get("ui").status is ProjectRunStatus.BLOCKED
    assert {"docs", "tools"}.issubset(calls)


def test_fail_fast_cancels_projects_not_yet_scheduled(tmp_path: Path) -> None:
    def analyze(project, dependencies):
        if project.name == "core":
            raise RuntimeError("boom")
        sleep(0.02)
        return project.name

    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        analyze, projects=["core", "api", "ui"], max_workers=2, fail_fast=True
    )
    assert report.get("core").status is ProjectRunStatus.FAILED
    assert report.get("api").status is ProjectRunStatus.BLOCKED
    assert report.get("ui").status is ProjectRunStatus.BLOCKED


def test_external_cancellation_marks_unscheduled_projects_cancelled(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        lambda project, dependencies: project.name,
        max_workers=3,
        cancelled=lambda: True,
    )
    assert all(run.status in {ProjectRunStatus.CANCELLED, ProjectRunStatus.BLOCKED} for run in report.runs)


def test_invalid_worker_count_is_rejected(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    with pytest.raises(ValueError, match="max_workers"):
        orch.execute(lambda project, dependencies: project.name, max_workers=0)


def test_single_worker_preserves_sequential_execution(tmp_path: Path) -> None:
    calls: list[str] = []
    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        lambda project, dependencies: calls.append(project.name) or project.name, max_workers=1
    )
    assert calls == ["core", "api", "docs", "tools", "ui"]


def test_cached_results_are_reused_in_parallel_mode(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda project, dependencies: project.name, max_workers=3)
    calls: list[str] = []
    report = orch.execute(lambda project, dependencies: calls.append(project.name), max_workers=3)
    assert calls == []
    assert all(run.status is ProjectRunStatus.REUSED for run in report.runs)


def test_force_reanalyzes_cached_projects_in_parallel_mode(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda project, dependencies: project.name, max_workers=3)
    calls: list[str] = []
    orch.execute(lambda project, dependencies: calls.append(project.name) or project.name, max_workers=3, force=True)
    assert set(calls) == {"core", "api", "ui", "docs", "tools"}


def test_successful_parallel_results_are_cached(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda project, dependencies: {"project": project.name}, max_workers=4)
    assert orch.result("ui") == {"project": "ui"}


def test_failed_parallel_result_is_removed_from_cache(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda project, dependencies: project.name, max_workers=3)

    def analyze(project, dependencies):
        if project.name == "docs":
            raise ValueError("bad")
        return project.name

    orch.execute(analyze, max_workers=3, force=True)
    with pytest.raises(KeyError):
        orch.result("docs")


def test_subset_still_includes_dependencies_in_parallel_mode(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        lambda project, dependencies: project.name, projects=["ui"], max_workers=4
    )
    assert report.analysis_order == ("core", "api", "ui")


def test_subset_can_exclude_dependencies_in_parallel_mode(tmp_path: Path) -> None:
    seen = {}

    def analyze(project, dependencies):
        seen[project.name] = dict(dependencies)
        return project.name

    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        analyze, projects=["ui"], include_dependencies=False, max_workers=2
    )
    assert report.analysis_order == ("ui",)
    assert seen["ui"] == {}


def test_parallel_incremental_plan_executes_impacted_graph(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    orch = WorkspaceAnalysisOrchestrator(service, planner=planner)
    orch.execute(lambda project, dependencies: project.name, max_workers=3)
    plan = planner.plan((FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "x.py", project="core"),))
    report = orch.execute_plan(plan, lambda project, dependencies: "new-" + project.name, max_workers=3)
    assert report.analysis_order == ("core", "api", "ui")
    assert report.succeeded


def test_parallel_incremental_plan_rejects_invalid_worker_count(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    plan = planner.plan(())
    with pytest.raises(ValueError, match="max_workers"):
        WorkspaceAnalysisOrchestrator(service, planner=planner).execute_plan(
            plan, lambda project, dependencies: project.name, max_workers=-1
        )


def test_project_events_are_emitted_for_parallel_runs(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    events = []
    service.events.subscribe(events.append)
    WorkspaceAnalysisOrchestrator(service).execute(lambda project, dependencies: project.name, max_workers=3)
    kinds = [event.kind for event in events]
    assert WorkspaceEventKind.ANALYSIS_STARTED in kinds
    assert WorkspaceEventKind.PROJECT_STARTED in kinds
    assert WorkspaceEventKind.PROJECT_COMPLETED in kinds
    assert WorkspaceEventKind.ANALYSIS_COMPLETED in kinds


def test_parallel_failure_event_contains_error(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    events = []
    service.events.subscribe(events.append, kinds=[WorkspaceEventKind.PROJECT_FAILED])

    def analyze(project, dependencies):
        if project.name == "docs":
            raise RuntimeError("failure")
        return project.name

    WorkspaceAnalysisOrchestrator(service).execute(analyze, max_workers=3)
    assert events[0].project == "docs"
    assert events[0].payload["error"] == "RuntimeError: failure"


def test_report_serialization_is_stable_in_parallel_mode(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(
        lambda project, dependencies: project.name, max_workers=3
    )
    data = report.to_dict()
    assert [run["project"] for run in data["runs"]] == list(report.analysis_order)
    assert data["succeeded"] is True


def test_analyzer_never_exceeds_worker_limit(tmp_path: Path) -> None:
    active = 0
    peak = 0
    lock = Lock()

    def analyze(project, dependencies):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.02)
        with lock:
            active -= 1
        return project.name

    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyze, max_workers=2)
    assert peak <= 2


def test_empty_order_returns_empty_parallel_report(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    report = WorkspaceAnalysisOrchestrator(service, planner=planner).execute_plan(
        planner.plan(()), lambda project, dependencies: project.name, max_workers=4
    )
    assert report.runs == ()
    assert report.succeeded
