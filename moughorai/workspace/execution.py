from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Any

from .incremental import IncrementalPlan, IncrementalWorkspacePlanner
from .models import Project
from .persistence import WorkspaceRestoreReport, WorkspaceStateStore
from .service import WorkspaceService


class ProjectRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    REUSED = "reused"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProjectRun:
    project: str
    status: ProjectRunStatus
    value: Any = None
    error: str | None = None
    blocked_by: tuple[str, ...] = ()
    duration_ms: float = 0.0

    @property
    def successful(self) -> bool:
        return self.status in {ProjectRunStatus.SUCCEEDED, ProjectRunStatus.REUSED}

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "project": self.project,
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 3),
        }
        if self.value is not None:
            data["value"] = self.value
        if self.error is not None:
            data["error"] = self.error
        if self.blocked_by:
            data["blocked_by"] = list(self.blocked_by)
        return data


@dataclass(frozen=True, slots=True)
class WorkspaceRunReport:
    runs: tuple[ProjectRun, ...]
    requested: tuple[str, ...]
    analysis_order: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return all(run.successful for run in self.runs)

    @property
    def failed_projects(self) -> tuple[str, ...]:
        return tuple(run.project for run in self.runs if run.status is ProjectRunStatus.FAILED)

    @property
    def blocked_projects(self) -> tuple[str, ...]:
        return tuple(run.project for run in self.runs if run.status is ProjectRunStatus.BLOCKED)

    def get(self, project: str) -> ProjectRun:
        for run in self.runs:
            if run.project == project:
                return run
        raise KeyError(project)

    def to_dict(self) -> dict[str, object]:
        return {
            "succeeded": self.succeeded,
            "requested": list(self.requested),
            "analysis_order": list(self.analysis_order),
            "runs": [run.to_dict() for run in self.runs],
        }


class WorkspaceAnalysisOrchestrator:
    def __init__(self, service: WorkspaceService, *, planner: IncrementalWorkspacePlanner | None = None) -> None:
        self.service = service
        self.planner = planner or IncrementalWorkspacePlanner(service)
        self._results: dict[str, Any] = {}

    @property
    def cached_projects(self) -> tuple[str, ...]:
        return tuple(sorted(self._results))

    def result(self, project: str) -> Any:
        return self._results[project]

    def save_state(self, store: WorkspaceStateStore | None = None):
        target = store or WorkspaceStateStore(self.service)
        return target.save(target.capture(self._results, self.planner.valid_projects))

    def restore_state(self, store: WorkspaceStateStore | None = None) -> WorkspaceRestoreReport:
        target = store or WorkspaceStateStore(self.service)
        results, report = target.restore(target.load())
        self._results = results
        all_projects = set(self.service.workspace.names())
        self.planner.invalidate(all_projects.difference(results))
        for project in results:
            self.planner.mark_valid(project)
        return report

    def invalidate(self, projects: Iterable[str]) -> tuple[str, ...]:
        names = tuple(sorted(set(projects)))
        self.planner.invalidate(names)
        removed = tuple(name for name in names if name in self._results)
        for name in removed:
            del self._results[name]
        return removed

    def execute(
        self,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        projects: Iterable[str] | None = None,
        include_dependencies: bool = True,
        force: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> WorkspaceRunReport:
        requested = tuple(sorted(set(projects or self.service.workspace.names())))
        order = self.service.analysis_order(requested, include_dependencies=include_dependencies)
        return self._execute_order(order, requested, analyzer, force=force, cancelled=cancelled)

    def execute_plan(
        self,
        plan: IncrementalPlan,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> WorkspaceRunReport:
        self.invalidate(plan.invalidated)
        report = self._execute_order(plan.analysis_order, plan.directly_changed, analyzer, force=True, cancelled=cancelled)
        if report.succeeded:
            self.planner.mark_plan_valid(plan)
        else:
            for run in report.runs:
                if run.successful:
                    self.planner.mark_valid(run.project)
        return report

    def _execute_order(
        self,
        order: tuple[Project, ...],
        requested: tuple[str, ...],
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        force: bool,
        cancelled: Callable[[], bool] | None,
    ) -> WorkspaceRunReport:
        runs: list[ProjectRun] = []
        status: dict[str, ProjectRunStatus] = {}
        values: dict[str, Any] = dict(self._results)

        for project in order:
            if cancelled is not None and cancelled():
                run = ProjectRun(project.name, ProjectRunStatus.CANCELLED)
                runs.append(run)
                status[project.name] = run.status
                continue

            blocked_by = tuple(
                dependency
                for dependency in project.dependencies
                if status.get(dependency) in {ProjectRunStatus.FAILED, ProjectRunStatus.BLOCKED, ProjectRunStatus.CANCELLED}
            )
            if blocked_by:
                run = ProjectRun(project.name, ProjectRunStatus.BLOCKED, blocked_by=blocked_by)
                runs.append(run)
                status[project.name] = run.status
                continue

            if not force and project.name in self._results and project.name in self.planner.valid_projects:
                run = ProjectRun(project.name, ProjectRunStatus.REUSED, value=self._results[project.name])
                runs.append(run)
                status[project.name] = run.status
                continue

            dependency_results = {name: values[name] for name in project.dependencies if name in values}
            started = monotonic()
            try:
                value = analyzer(project, dependency_results)
            except Exception as exc:  # analyzer boundary
                elapsed = (monotonic() - started) * 1000
                run = ProjectRun(project.name, ProjectRunStatus.FAILED, error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed)
                self._results.pop(project.name, None)
                self.planner.invalidate((project.name,))
            else:
                elapsed = (monotonic() - started) * 1000
                self._results[project.name] = value
                values[project.name] = value
                self.planner.mark_valid(project.name)
                run = ProjectRun(project.name, ProjectRunStatus.SUCCEEDED, value=value, duration_ms=elapsed)
            runs.append(run)
            status[project.name] = run.status

        return WorkspaceRunReport(
            tuple(runs),
            requested,
            tuple(project.name for project in order),
        )
