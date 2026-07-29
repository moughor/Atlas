from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import sleep
from typing import Any

from .execution import WorkspaceAnalysisOrchestrator, WorkspaceRunReport
from .models import Project
from .watcher import WatchSnapshot, WorkspaceWatcher


@dataclass(frozen=True, slots=True)
class WatchRun:
    snapshot: WatchSnapshot
    reports: tuple[WorkspaceRunReport, ...]
    polls: int


class WorkspaceWatchManager:
    """Continuously translate debounced file changes into incremental analyses."""

    def __init__(
        self,
        watcher: WorkspaceWatcher,
        orchestrator: WorkspaceAnalysisOrchestrator,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        interval_seconds: float = 0.5,
        max_workers: int = 1,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.watcher = watcher
        self.orchestrator = orchestrator
        self.analyzer = analyzer
        self.interval_seconds = interval_seconds
        self.max_workers = max_workers
        self.sleeper = sleeper

    def run(
        self,
        *,
        iterations: int | None = None,
        stopped: Callable[[], bool] | None = None,
        on_report: Callable[[WorkspaceRunReport], None] | None = None,
    ) -> WatchRun:
        if iterations is not None and iterations < 0:
            raise ValueError("iterations must be non-negative")
        snapshot = self.watcher.start()
        reports: list[WorkspaceRunReport] = []
        polls = 0
        while iterations is None or polls < iterations:
            if stopped is not None and stopped():
                break
            self.sleeper(self.interval_seconds)
            events = self.watcher.poll(flush=True)
            polls += 1
            if not events:
                continue
            plan = self.orchestrator.planner.plan(events)
            if not plan.analysis_order:
                continue
            report = self.orchestrator.execute_plan(
                plan,
                self.analyzer,
                max_workers=self.max_workers,
            )
            reports.append(report)
            if on_report is not None:
                on_report(report)
        return WatchRun(snapshot, tuple(reports), polls)
