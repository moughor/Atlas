from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter_ns
from types import MappingProxyType
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class PassMetric:
    pass_name: str
    duration_ns: int
    produced: tuple[str, ...] = ()

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1_000_000


@dataclass(slots=True)
class PassContext:
    configuration: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    feature_flags: frozenset[str] = frozenset()
    logger: Callable[[str], None] | None = None
    cancelled: Callable[[], bool] | None = None
    metrics: list[PassMetric] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.configuration = MappingProxyType(dict(self.configuration))
        self.feature_flags = frozenset(self.feature_flags)

    def is_cancelled(self) -> bool:
        return bool(self.cancelled and self.cancelled())

    def emit(self, message: str) -> None:
        if self.logger is not None:
            self.logger(message)

    def timer(self) -> int:
        return perf_counter_ns()

    def record(self, pass_name: str, started_ns: int, produced: tuple[str, ...]) -> None:
        self.metrics.append(PassMetric(pass_name, perf_counter_ns() - started_ns, produced))
