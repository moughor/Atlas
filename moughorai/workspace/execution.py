from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from threading import Lock, current_thread, get_ident
from time import monotonic, monotonic_ns
from typing import Any

from moughorai.measurement import MeasurementPhase

from .incremental import IncrementalPlan, IncrementalWorkspacePlanner
from .event_bus import WorkspaceEventKind
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
            report_value = getattr(self.value, "to_report_value", None)
            data["value"] = report_value() if callable(report_value) else self.value
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
        max_workers: int = 1,
        fail_fast: bool = False,
    ) -> WorkspaceRunReport:
        requested = tuple(sorted(set(projects or self.service.workspace.names())))
        order = self.service.analysis_order(requested, include_dependencies=include_dependencies)
        self.service.events.emit(
            WorkspaceEventKind.ANALYSIS_STARTED,
            source="workspace.execution",
            payload={"requested": list(requested), "analysis_order": [project.name for project in order]},
        )
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_workers == 1:
            report = self._execute_order(order, requested, analyzer, force=force, cancelled=cancelled)
        else:
            report = self._execute_concurrent(
                order, requested, analyzer, force=force, cancelled=cancelled, max_workers=max_workers, fail_fast=fail_fast
            )
        self.service.events.emit(
            WorkspaceEventKind.ANALYSIS_COMPLETED,
            source="workspace.execution",
            payload=report.to_dict(),
        )
        return report

    def execute_plan(
        self,
        plan: IncrementalPlan,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        cancelled: Callable[[], bool] | None = None,
        max_workers: int = 1,
        fail_fast: bool = False,
    ) -> WorkspaceRunReport:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.invalidate(plan.invalidated)
        if max_workers == 1:
            report = self._execute_order(plan.analysis_order, plan.directly_changed, analyzer, force=True, cancelled=cancelled)
        else:
            report = self._execute_concurrent(
                plan.analysis_order, plan.directly_changed, analyzer, force=True, cancelled=cancelled, max_workers=max_workers, fail_fast=fail_fast
            )
        if report.succeeded:
            self.planner.mark_plan_valid(plan)
        else:
            for run in report.runs:
                if run.successful:
                    self.planner.mark_valid(run.project)
        return report


    def _execute_concurrent(
        self,
        order: tuple[Project, ...],
        requested: tuple[str, ...],
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        force: bool,
        cancelled: Callable[[], bool] | None,
        max_workers: int,
        fail_fast: bool,
    ) -> WorkspaceRunReport:
        projects = {project.name: project for project in order}
        order_names = tuple(project.name for project in order)
        selected = set(order_names)
        status: dict[str, ProjectRunStatus] = {}
        runs: dict[str, ProjectRun] = {}
        values: dict[str, Any] = dict(self._results)
        pending = set(order_names)
        abort = False
        measurement = self.service.measurement
        measurement_enabled = measurement.config.enabled
        worker_state_lock = Lock()
        queued_count = 0
        worker_last_finished: dict[int, int] = {}

        def dependency_statuses(project: Project) -> tuple[str, ...]:
            return tuple(
                dependency
                for dependency in project.dependencies
                if dependency in selected
                and status.get(dependency)
                in {ProjectRunStatus.FAILED, ProjectRunStatus.BLOCKED, ProjectRunStatus.CANCELLED}
            )

        def dependencies_finished(project: Project) -> bool:
            return all(dependency not in selected or dependency in status for dependency in project.dependencies)

        def finish_without_worker(project: Project) -> bool:
            nonlocal abort
            blocked_by = dependency_statuses(project)
            if blocked_by:
                run = ProjectRun(project.name, ProjectRunStatus.BLOCKED, blocked_by=blocked_by)
                runs[project.name] = run
                status[project.name] = run.status
                pending.remove(project.name)
                self.service.events.emit(
                    WorkspaceEventKind.PROJECT_BLOCKED, project=project.name, source="workspace.execution", payload=run.to_dict()
                )
                return True
            if abort or (cancelled is not None and cancelled()):
                run = ProjectRun(project.name, ProjectRunStatus.CANCELLED)
                runs[project.name] = run
                status[project.name] = run.status
                pending.remove(project.name)
                return True
            if not force and project.name in self._results and project.name in self.planner.valid_projects:
                run = ProjectRun(project.name, ProjectRunStatus.REUSED, value=self._results[project.name])
                runs[project.name] = run
                status[project.name] = run.status
                pending.remove(project.name)
                return True
            return False

        def analyze(
            project: Project,
            dependency_results: Mapping[str, Any],
            queued_at_ns: int,
        ) -> ProjectRun:
            nonlocal queued_count
            started = monotonic()
            if not measurement_enabled:
                try:
                    value = analyzer(project, dependency_results)
                except Exception as exc:  # analyzer boundary
                    elapsed = (monotonic() - started) * 1000
                    return ProjectRun(
                        project.name, ProjectRunStatus.FAILED, error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed
                    )
                elapsed = (monotonic() - started) * 1000
                return ProjectRun(project.name, ProjectRunStatus.SUCCEEDED, value=value, duration_ms=elapsed)

            worker_started_ns = monotonic_ns()
            thread_id = get_ident()
            with worker_state_lock:
                queued_count -= 1
                queue_depth = queued_count
                previous_finish = worker_last_finished.get(thread_id)
            worker_id = current_thread().name.lower().replace("_", "-")
            try:
                try:
                    with measurement.scope(
                        MeasurementPhase.PROJECT_ANALYSIS,
                        consumer="workspace-execution",
                        worker_id=worker_id,
                        sample_key=project.name,
                        worker_metrics=True,
                    ) as scope:
                        scope.set_queue_wait_ns(max(0, worker_started_ns - queued_at_ns))
                        scope.set_queue_depth(queue_depth)
                        if previous_finish is not None:
                            scope.set_idle_time_ns(max(0, worker_started_ns - previous_finish))
                        scope.add_units(1)
                        value = analyzer(project, dependency_results)
                except Exception as exc:  # analyzer boundary
                    elapsed = (monotonic() - started) * 1000
                    return ProjectRun(
                        project.name,
                        ProjectRunStatus.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                        duration_ms=elapsed,
                    )
                elapsed = (monotonic() - started) * 1000
                return ProjectRun(
                    project.name,
                    ProjectRunStatus.SUCCEEDED,
                    value=value,
                    duration_ms=elapsed,
                )
            finally:
                with worker_state_lock:
                    worker_last_finished[thread_id] = monotonic_ns()

        futures: dict[Future[ProjectRun], str] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="atlas-workspace") as executor:
            while pending or futures:
                made_progress = True
                while made_progress:
                    made_progress = False
                    for name in order_names:
                        if name not in pending or len(futures) >= max_workers:
                            continue
                        project = projects[name]
                        if not dependencies_finished(project):
                            continue
                        self.service.events.emit(
                            WorkspaceEventKind.PROJECT_STARTED,
                            project=project.name,
                            source="workspace.execution",
                            payload={"dependencies": list(project.dependencies)},
                        )
                        if finish_without_worker(project):
                            made_progress = True
                            continue
                        dependency_results = {dep: values[dep] for dep in project.dependencies if dep in values}
                        pending.remove(name)
                        queued_at_ns = monotonic_ns() if measurement_enabled else 0
                        if measurement_enabled:
                            with worker_state_lock:
                                queued_count += 1
                        futures[
                            executor.submit(
                                analyze,
                                project,
                                dependency_results,
                                queued_at_ns,
                            )
                        ] = name
                        made_progress = True

                if not futures:
                    if not pending:
                        break
                    # Remaining projects become reachable only through a failed/cancelled dependency.
                    continue

                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    name = futures.pop(future)
                    run = future.result()
                    runs[name] = run
                    status[name] = run.status
                    if run.status is ProjectRunStatus.SUCCEEDED:
                        self._results[name] = run.value
                        values[name] = run.value
                        self.planner.mark_valid(name)
                        event_kind = WorkspaceEventKind.PROJECT_COMPLETED
                    else:
                        self._results.pop(name, None)
                        self.planner.invalidate((name,))
                        event_kind = WorkspaceEventKind.PROJECT_FAILED
                        if fail_fast:
                            abort = True
                    self.service.events.emit(event_kind, project=name, source="workspace.execution", payload=run.to_dict())

        return WorkspaceRunReport(
            tuple(runs[name] for name in order_names),
            requested,
            order_names,
        )

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
            self.service.events.emit(
                WorkspaceEventKind.PROJECT_STARTED,
                project=project.name,
                source="workspace.execution",
                payload={"dependencies": list(project.dependencies)},
            )
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
                self.service.events.emit(
                    WorkspaceEventKind.PROJECT_BLOCKED, project=project.name, source="workspace.execution", payload=run.to_dict()
                )
                continue

            if not force and project.name in self._results and project.name in self.planner.valid_projects:
                run = ProjectRun(project.name, ProjectRunStatus.REUSED, value=self._results[project.name])
                runs.append(run)
                status[project.name] = run.status
                continue

            dependency_results = {name: values[name] for name in project.dependencies if name in values}
            started = monotonic()
            try:
                with self.service.measurement.scope(
                    MeasurementPhase.PROJECT_ANALYSIS,
                    consumer="workspace-execution",
                    sample_key=project.name,
                ) as scope:
                    value = analyzer(project, dependency_results)
                    scope.add_units(1)
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
            event_kind = WorkspaceEventKind.PROJECT_FAILED if run.status is ProjectRunStatus.FAILED else WorkspaceEventKind.PROJECT_COMPLETED
            self.service.events.emit(event_kind, project=project.name, source="workspace.execution", payload=run.to_dict())

        return WorkspaceRunReport(
            tuple(runs),
            requested,
            tuple(project.name for project in order),
        )
