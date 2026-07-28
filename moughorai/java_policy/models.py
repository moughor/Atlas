"""Immutable models for deterministic Java architecture policies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ArchitectureLayer(str, Enum):
    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    ENTITY = "entity"
    ENDPOINT = "endpoint"
    OTHER = "other"


class PolicySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ArchitecturePolicy:
    """Configurable workspace architecture constraints."""

    allowed_layer_dependencies: tuple[tuple[ArchitectureLayer, ArchitectureLayer], ...] = (
        (ArchitectureLayer.CONTROLLER, ArchitectureLayer.SERVICE),
        (ArchitectureLayer.CONTROLLER, ArchitectureLayer.OTHER),
        (ArchitectureLayer.SERVICE, ArchitectureLayer.SERVICE),
        (ArchitectureLayer.SERVICE, ArchitectureLayer.REPOSITORY),
        (ArchitectureLayer.SERVICE, ArchitectureLayer.ENTITY),
        (ArchitectureLayer.SERVICE, ArchitectureLayer.OTHER),
        (ArchitectureLayer.REPOSITORY, ArchitectureLayer.ENTITY),
        (ArchitectureLayer.REPOSITORY, ArchitectureLayer.OTHER),
        (ArchitectureLayer.ENTITY, ArchitectureLayer.ENTITY),
        (ArchitectureLayer.OTHER, ArchitectureLayer.OTHER),
        (ArchitectureLayer.OTHER, ArchitectureLayer.SERVICE),
        (ArchitectureLayer.OTHER, ArchitectureLayer.REPOSITORY),
        (ArchitectureLayer.OTHER, ArchitectureLayer.ENTITY),
    )
    forbidden_project_dependencies: tuple[tuple[str, str], ...] = ()
    detect_controller_repository_shortcuts: bool = True
    detect_project_cycles: bool = True


@dataclass(frozen=True)
class PolicyViolation:
    rule: str
    severity: PolicySeverity
    message: str
    source_project: str
    source: str
    target_project: str = ""
    target: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchitecturePolicyReport:
    violations: tuple[PolicyViolation, ...] = ()
    checked_edges: int = 0
    checked_projects: int = 0

    @property
    def compliant(self) -> bool:
        return not self.violations

    def by_rule(self, rule: str) -> tuple[PolicyViolation, ...]:
        return tuple(item for item in self.violations if item.rule == rule)

    def by_severity(self, severity: PolicySeverity) -> tuple[PolicyViolation, ...]:
        return tuple(item for item in self.violations if item.severity is severity)
