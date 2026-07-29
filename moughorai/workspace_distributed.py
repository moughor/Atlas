"""Distributed worker coordination for workspace projects."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .incremental_analysis.distributed import (
    DistributedAnalysisCoordinator,
    DistributedExecutionRun,
    DistributedJob,
)
from .workspace import Project, ProjectRun, ProjectRunStatus, WorkspaceRunReport, WorkspaceService


WorkspaceWorker = Callable[[Project, Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class DistributedWorkspaceRun:
    report: WorkspaceRunReport
    execution: DistributedExecutionRun


class DistributedWorkspaceCoordinator:
    """Adapt workspace projects to PR58 transport-neutral leases."""

    def __init__(
        self,
        service: WorkspaceService,
        coordinator: DistributedAnalysisCoordinator | None = None,
    ) -> None:
        self.service = service
        self.coordinator = coordinator or DistributedAnalysisCoordinator()

    def submit(
        self,
        projects: Iterable[str] | None = None,
        *,
        max_attempts: int = 1,
    ) -> tuple[str, ...]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        requested = tuple(sorted(set(projects or self.service.workspace.names())))
        ordered = self.service.analysis_order(requested)
        selected = {project.name for project in ordered}
        jobs = [
            DistributedJob(
                Path(project.name),
                self._fingerprint(project),
                tuple(Path(name) for name in project.dependencies if name in selected),
                self._capabilities(project),
                max_attempts,
            )
            for project in ordered
        ]
        self.coordinator.submit(jobs)
        return tuple(project.name for project in ordered)

    def execute_locally(
        self,
        workers: Mapping[str, WorkspaceWorker],
        *,
        capabilities: Mapping[str, Iterable[str]] | None = None,
        fail_fast: bool = False,
    ) -> DistributedWorkspaceRun:
        if not workers:
            raise ValueError("at least one workspace worker is required")
        for worker_id in sorted(workers):
            self.coordinator.register_worker(
                worker_id,
                capabilities=tuple((capabilities or {}).get(worker_id, ())),
                now=0,
            )

        projects = {project.name: project for project in self.service.workspace.projects}

        def adapter(worker_id: str) -> Callable[[Path], Any]:
            def analyze(path: Path) -> Any:
                project = projects[path.as_posix()]
                completed = {
                    record.job.path.as_posix(): record.result
                    for record in self.coordinator.snapshot().jobs
                    if record.result is not None
                }
                dependencies = {
                    name: completed[name]
                    for name in project.dependencies
                    if name in completed
                }
                return workers[worker_id](project, dependencies)

            return analyze

        execution = self.coordinator.execute_locally(
            {worker_id: adapter(worker_id) for worker_id in sorted(workers)},
            fail_fast=fail_fast,
            now=0,
        )
        requested = tuple(
            record.job.path.as_posix()
            for record in self.coordinator.snapshot().jobs
            if record.job.path.as_posix() in projects
        )
        results = execution.result_map()
        failures = {item.path: item for item in execution.failures}
        cancelled = set(execution.cancelled)
        runs = []
        for name in requested:
            path = Path(name)
            if path in results:
                runs.append(ProjectRun(name, ProjectRunStatus.SUCCEEDED, results[path]))
            elif path in failures:
                failure = failures[path]
                runs.append(ProjectRun(name, ProjectRunStatus.FAILED, error=f"{failure.error_type}: {failure.message}"))
            elif path in cancelled:
                dependencies = tuple(dep for dep in projects[name].dependencies if Path(dep) in failures or Path(dep) in cancelled)
                runs.append(ProjectRun(name, ProjectRunStatus.BLOCKED, blocked_by=dependencies))
        report = WorkspaceRunReport(tuple(runs), requested, requested)
        return DistributedWorkspaceRun(report, execution)

    def _fingerprint(self, project: Project) -> str:
        payload = project.to_dict(root=self.service.workspace.root)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _capabilities(project: Project) -> tuple[str, ...]:
        language = project.option_map.get("language")
        return () if language is None else (f"language:{language}",)
