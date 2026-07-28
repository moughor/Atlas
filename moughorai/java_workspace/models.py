"""Immutable models for workspace-wide Java intelligence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeNode


@dataclass(frozen=True)
class WorkspaceProject:
    key: str
    name: str
    root: Path | None = None
    modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceNode:
    project_key: str
    module: str
    node: KnowledgeNode

    @property
    def key(self) -> str:
        return self.node.key


@dataclass(frozen=True)
class WorkspaceEdge:
    source_project: str
    target_project: str
    edge: KnowledgeEdge

    @property
    def is_cross_project(self) -> bool:
        return self.source_project != self.target_project


@dataclass(frozen=True)
class RenameImpact:
    subject: WorkspaceNode
    direct_references: tuple[WorkspaceNode, ...] = ()
    transitive_references: tuple[WorkspaceNode, ...] = ()
    exposed_endpoints: tuple[WorkspaceNode, ...] = ()
    affected_projects: tuple[str, ...] = ()


@dataclass(frozen=True)
class EndpointEntityTrace:
    endpoint: WorkspaceNode
    entities: tuple[WorkspaceNode, ...] = ()
    paths: tuple[tuple[str, ...], ...] = ()
