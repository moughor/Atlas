"""Immutable models for deterministic Java change-impact analysis."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from moughorai.java_callflow.models import FlowPath
from moughorai.java_workspace.models import WorkspaceNode


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RiskFactor:
    name: str
    points: int
    detail: str


@dataclass(frozen=True)
class ChangeImpactReport:
    subject: WorkspaceNode
    score: int
    level: RiskLevel
    direct_dependents: tuple[WorkspaceNode, ...] = ()
    transitive_dependents: tuple[WorkspaceNode, ...] = ()
    exposed_endpoints: tuple[WorkspaceNode, ...] = ()
    reachable_entities: tuple[WorkspaceNode, ...] = ()
    affected_projects: tuple[str, ...] = ()
    cycles: tuple[FlowPath, ...] = ()
    factors: tuple[RiskFactor, ...] = ()
    truncated: bool = False

    @property
    def blast_radius(self) -> int:
        identities = {
            (node.project_key, node.key)
            for node in (*self.direct_dependents, *self.transitive_dependents)
        }
        return len(identities)
