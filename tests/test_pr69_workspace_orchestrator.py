from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.workspace import (
    FileEvent,
    FileEventKind,
    IncrementalWorkspacePlanner,
    ProjectRunStatus,
    WorkspaceAnalysisOrchestrator,
    WorkspaceService,
)


def make_service(tmp_path: Path) -> WorkspaceService:
    for name in ("core", "api", "ui", "docs"):
        (tmp_path / name).mkdir()
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n"
        "  - name: api\n    path: api\n    dependencies: [core]\n"
        "  - name: ui\n    path: ui\n    dependencies: [api]\n"
        "  - name: docs\n    path: docs\n",
        encoding="utf-8",
    )
    return WorkspaceService(tmp_path)


def analyzer(calls: list[str]):
    def run(project, dependencies):
        calls.append(project.name)
        return {"name": project.name, "deps": sorted(dependencies)}
    return run


def test_execute_all_in_dependency_order(tmp_path: Path) -> None:
    calls: list[str] = []
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyzer(calls))
    assert calls == ["core", "api", "docs", "ui"]
    assert report.analysis_order == tuple(calls)
    assert report.succeeded


def test_execute_subset_includes_dependencies(tmp_path: Path) -> None:
    calls: list[str] = []
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyzer(calls), projects=["ui"])
    assert calls == ["core", "api", "ui"]
    assert report.requested == ("ui",)


def test_execute_subset_can_exclude_dependencies(tmp_path: Path) -> None:
    calls: list[str] = []
    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(analyzer(calls), projects=["ui"], include_dependencies=False)
    assert calls == ["ui"]


def test_success_results_are_cached(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda project, deps: project.name)
    assert orch.cached_projects == ("api", "core", "docs", "ui")
    assert orch.result("api") == "api"


def test_second_run_reuses_valid_results(tmp_path: Path) -> None:
    calls: list[str] = []
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(analyzer(calls))
    calls.clear()
    report = orch.execute(analyzer(calls))
    assert calls == []
    assert all(run.status is ProjectRunStatus.REUSED for run in report.runs)


def test_force_reanalyzes(tmp_path: Path) -> None:
    calls: list[str] = []
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(analyzer(calls))
    calls.clear()
    orch.execute(analyzer(calls), force=True)
    assert calls == ["core", "api", "docs", "ui"]


def test_dependency_results_passed_to_analyzer(tmp_path: Path) -> None:
    seen = {}
    def run(project, dependencies):
        seen[project.name] = dict(dependencies)
        return project.name
    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(run)
    assert seen["api"] == {"core": "core"}
    assert seen["ui"] == {"api": "api"}


def test_failure_is_captured(tmp_path: Path) -> None:
    def run(project, dependencies):
        if project.name == "api":
            raise RuntimeError("boom")
        return project.name
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(run)
    failed = report.get("api")
    assert failed.status is ProjectRunStatus.FAILED
    assert failed.error == "RuntimeError: boom"
    assert not report.succeeded


def test_dependent_is_blocked_after_failure(tmp_path: Path) -> None:
    def run(project, dependencies):
        if project.name == "api":
            raise ValueError("bad")
        return project.name
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(run)
    assert report.get("ui").status is ProjectRunStatus.BLOCKED
    assert report.get("ui").blocked_by == ("api",)


def test_independent_project_runs_after_failure(tmp_path: Path) -> None:
    calls: list[str] = []
    def run(project, dependencies):
        calls.append(project.name)
        if project.name == "api":
            raise RuntimeError("x")
        return project.name
    WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(run)
    assert "docs" in calls


def test_failed_and_blocked_project_lists(tmp_path: Path) -> None:
    def run(project, dependencies):
        if project.name == "core":
            raise RuntimeError("x")
        return project.name
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(run)
    assert report.failed_projects == ("core",)
    assert report.blocked_projects == ("api", "ui")


def test_cancelled_callback_skips_projects(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, cancelled=lambda: True)
    assert all(run.status is ProjectRunStatus.CANCELLED for run in report.runs)


def test_cancelled_dependency_blocks_dependent(tmp_path: Path) -> None:
    count = 0
    def cancelled():
        nonlocal count
        count += 1
        return count == 1
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, projects=["api"], cancelled=cancelled)
    assert report.get("core").status is ProjectRunStatus.CANCELLED
    assert report.get("api").status is ProjectRunStatus.BLOCKED


def test_invalidate_removes_cached_result(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda p, d: p.name)
    assert orch.invalidate(["api"]) == ("api",)
    with pytest.raises(KeyError):
        orch.result("api")


def test_invalidate_is_deterministic(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda p, d: p.name)
    assert orch.invalidate(["ui", "core", "missing"]) == ("core", "ui")


def test_unknown_result_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        WorkspaceAnalysisOrchestrator(make_service(tmp_path)).result("missing")


def test_report_get_unknown_raises(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name)
    with pytest.raises(KeyError):
        report.get("missing")


def test_report_serialization(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, projects=["core"])
    data = report.to_dict()
    assert data["succeeded"] is True
    assert data["requested"] == ["core"]
    assert data["runs"][0]["status"] == "succeeded"


def test_run_serialization_omits_empty_optional_fields(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: None, projects=["core"])
    data = report.runs[0].to_dict()
    assert "value" not in data and "error" not in data and "blocked_by" not in data


def test_successful_property_for_reused(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    orch.execute(lambda p, d: p.name, projects=["core"])
    run = orch.execute(lambda p, d: p.name, projects=["core"]).runs[0]
    assert run.status is ProjectRunStatus.REUSED and run.successful


def test_failed_result_is_not_cached(tmp_path: Path) -> None:
    orch = WorkspaceAnalysisOrchestrator(make_service(tmp_path))
    report = orch.execute(lambda p, d: (_ for _ in ()).throw(RuntimeError("x")), projects=["core"])
    assert report.failed_projects == ("core",)
    assert orch.cached_projects == ()


def test_incremental_plan_reanalyzes_impacted_projects(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    orch = WorkspaceAnalysisOrchestrator(service, planner=planner)
    orch.execute(lambda p, d: p.name)
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "x.py", project="core")
    plan = planner.plan((event,))
    calls: list[str] = []
    report = orch.execute_plan(plan, analyzer(calls))
    assert calls == ["core", "api", "ui"]
    assert report.analysis_order == ("core", "api", "ui")


def test_incremental_success_marks_plan_valid(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    orch = WorkspaceAnalysisOrchestrator(service, planner=planner)
    plan = planner.plan((FileEvent(FileEventKind.MODIFIED, tmp_path / "api" / "x.py", project="api"),))
    orch.execute_plan(plan, lambda p, d: p.name)
    assert "api" in planner.valid_projects and "ui" in planner.valid_projects


def test_incremental_failure_keeps_failed_project_invalid(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    orch = WorkspaceAnalysisOrchestrator(service, planner=planner)
    plan = planner.plan((FileEvent(FileEventKind.MODIFIED, tmp_path / "api" / "x.py", project="api"),))
    orch.execute_plan(plan, lambda p, d: (_ for _ in ()).throw(RuntimeError("x")) if p.name == "api" else p.name)
    assert "api" not in planner.valid_projects


def test_incremental_invalidates_old_cached_values(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    orch = WorkspaceAnalysisOrchestrator(service, planner=planner)
    orch.execute(lambda p, d: "old-" + p.name)
    plan = planner.plan((FileEvent(FileEventKind.MODIFIED, tmp_path / "api" / "x.py", project="api"),))
    orch.execute_plan(plan, lambda p, d: "new-" + p.name)
    assert orch.result("api") == "new-api"
    assert orch.result("ui") == "new-ui"
    assert orch.result("core") == "old-core"


def test_empty_incremental_plan_produces_empty_report(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    report = WorkspaceAnalysisOrchestrator(service, planner=planner).execute_plan(planner.plan(()), lambda p, d: p.name)
    assert report.runs == () and report.succeeded


def test_requested_projects_are_sorted(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, projects=["ui", "core"])
    assert report.requested == ("core", "ui")


def test_duplicate_requested_projects_are_removed(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, projects=["core", "core"])
    assert report.requested == ("core",)


def test_duration_is_non_negative(tmp_path: Path) -> None:
    run = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: p.name, projects=["core"]).runs[0]
    assert run.duration_ms >= 0


def test_error_serialization_contains_type(tmp_path: Path) -> None:
    report = WorkspaceAnalysisOrchestrator(make_service(tmp_path)).execute(lambda p, d: 1 / 0, projects=["core"])
    assert report.runs[0].to_dict()["error"].startswith("ZeroDivisionError:")
