"""Deterministic worker selection for workspace analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import os

from .workspace import Project


@dataclass(frozen=True, slots=True)
class AdaptiveSchedule:
    workers: int
    maximum_parallelism: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "workers": self.workers,
            "maximum_parallelism": self.maximum_parallelism,
            "reason": self.reason,
        }


class AdaptiveWorkspaceScheduler:
    """Recommend a bounded worker count from topology and prior timings."""

    def recommend(
        self,
        projects: Iterable[Project],
        *,
        worker_cap: int,
        cpu_count: int | None = None,
        duration_ms: Mapping[str, float] | None = None,
        trivial_threshold_ms: float = 5.0,
    ) -> AdaptiveSchedule:
        if worker_cap < 1:
            raise ValueError("worker cap must be at least 1")
        if trivial_threshold_ms < 0:
            raise ValueError("trivial threshold must be non-negative")
        values = tuple(projects)
        names = {project.name for project in values}
        dependencies = {
            project.name: set(project.dependencies).intersection(names)
            for project in values
        }
        maximum = self._maximum_wave(dependencies)
        available = max(1, cpu_count if cpu_count is not None else (os.cpu_count() or 1))
        workers = min(worker_cap, available, max(1, maximum))
        known = duration_ms or {}
        relevant = [float(known[name]) for name in sorted(names) if name in known]
        if len(relevant) == len(names) and relevant and max(relevant) < trivial_threshold_ms:
            return AdaptiveSchedule(1, maximum, "historical-runs-are-trivial")
        if maximum <= 1:
            return AdaptiveSchedule(1, maximum, "dependency-chain-is-sequential")
        return AdaptiveSchedule(workers, maximum, "bounded-topology-parallelism")

    @staticmethod
    def _maximum_wave(dependencies: Mapping[str, set[str]]) -> int:
        pending = set(dependencies)
        completed: set[str] = set()
        maximum = 0
        while pending:
            ready = sorted(name for name in pending if dependencies[name] <= completed)
            if not ready:
                raise ValueError("workspace dependency graph contains a cycle")
            maximum = max(maximum, len(ready))
            completed.update(ready)
            pending.difference_update(ready)
        return maximum
