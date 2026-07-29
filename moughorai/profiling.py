"""Low-overhead, thread-safe Atlas performance profiling."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
from threading import RLock
from time import perf_counter_ns
from typing import Any

from .workspace import Project


@dataclass(frozen=True, slots=True)
class ProfileMetric:
    name: str
    calls: int
    total_ms: float
    minimum_ms: float
    maximum_ms: float
    average_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "calls": self.calls,
            "total_ms": self.total_ms,
            "minimum_ms": self.minimum_ms,
            "maximum_ms": self.maximum_ms,
            "average_ms": self.average_ms,
        }


@dataclass(frozen=True, slots=True)
class ProfileReport:
    metrics: tuple[ProfileMetric, ...]

    def to_dict(self) -> dict[str, object]:
        return {"metrics": [metric.to_dict() for metric in self.metrics]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


class PerformanceProfiler:
    """Collect elapsed timings safely across concurrent project workers."""

    def __init__(self, *, clock: Callable[[], int] = perf_counter_ns) -> None:
        self._clock = clock
        self._samples: dict[str, list[int]] = defaultdict(list)
        self._lock = RLock()

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        normalized = name.strip()
        if not normalized:
            raise ValueError("profile metric name must not be empty")
        started = self._clock()
        try:
            yield
        finally:
            elapsed = max(0, self._clock() - started)
            with self._lock:
                self._samples[normalized].append(elapsed)

    def wrap_analyzer(
        self,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
    ) -> Callable[[Project, Mapping[str, Any]], Any]:
        def profiled(project: Project, dependencies: Mapping[str, Any]) -> Any:
            with self.measure(f"project:{project.name}"):
                return analyzer(project, dependencies)

        return profiled

    def report(self) -> ProfileReport:
        with self._lock:
            snapshot = {name: tuple(values) for name, values in self._samples.items()}
        metrics = []
        for name in sorted(snapshot):
            values = snapshot[name]
            total = sum(values)
            metrics.append(
                ProfileMetric(
                    name,
                    len(values),
                    self._ms(total),
                    self._ms(min(values)),
                    self._ms(max(values)),
                    self._ms(total / len(values)),
                )
            )
        return ProfileReport(tuple(metrics))

    def clear(self) -> int:
        with self._lock:
            count = sum(len(values) for values in self._samples.values())
            self._samples.clear()
            return count

    @staticmethod
    def _ms(value: float) -> float:
        return round(value / 1_000_000, 3)
