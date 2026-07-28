"""Immutable models for deterministic Java workspace call-flow analysis."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from moughorai.java_workspace.models import WorkspaceNode


class FlowDirection(str, Enum):
    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"


@dataclass(frozen=True)
class FlowStep:
    node: WorkspaceNode
    relation: str = ""
    depth: int = 0


@dataclass(frozen=True)
class FlowPath:
    steps: tuple[FlowStep, ...]
    cycle: bool = False

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(step.node.key for step in self.steps)


@dataclass(frozen=True)
class FlowAnalysis:
    subject: WorkspaceNode
    direction: FlowDirection
    paths: tuple[FlowPath, ...] = ()
    reachable: tuple[WorkspaceNode, ...] = ()
    cycles: tuple[FlowPath, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class EndpointFlow:
    endpoint: WorkspaceNode
    paths: tuple[FlowPath, ...] = ()
    services: tuple[WorkspaceNode, ...] = ()
    repositories: tuple[WorkspaceNode, ...] = ()
    entities: tuple[WorkspaceNode, ...] = ()
