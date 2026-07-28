"""Immutable architecture-baseline and regression models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegressionSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, order=True)
class BaselineNode:
    project: str
    key: str
    kind: str
    facets: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class BaselineEdge:
    source_project: str
    source: str
    target_project: str
    target: str
    kind: str


@dataclass(frozen=True, order=True)
class BaselineViolation:
    rule: str
    severity: str
    source_project: str
    source: str
    target_project: str = ""
    target: str = ""


@dataclass(frozen=True)
class ArchitectureBaseline:
    nodes: tuple[BaselineNode, ...] = ()
    edges: tuple[BaselineEdge, ...] = ()
    unresolved: tuple[str, ...] = ()
    violations: tuple[BaselineViolation, ...] = ()


@dataclass(frozen=True)
class ArchitectureRegression:
    category: str
    severity: RegressionSeverity
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchitectureRegressionReport:
    regressions: tuple[ArchitectureRegression, ...] = ()
    resolved: tuple[ArchitectureRegression, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.regressions

    def by_category(self, category: str) -> tuple[ArchitectureRegression, ...]:
        return tuple(item for item in self.regressions if item.category == category)
