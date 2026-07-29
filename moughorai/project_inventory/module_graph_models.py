"""Immutable models for deterministic Maven module graphs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ModuleEdgeKind(str, Enum):
    """Relationship types between Maven modules."""

    DECLARES_MODULE = "declares_module"
    PARENT = "parent"
    DEPENDS_ON = "depends_on"


@dataclass(frozen=True)
class ModuleNode:
    """One Maven project represented as a graph node."""

    identifier: str
    pom_path: Path
    group_id: str
    artifact_id: str
    version: str | None
    packaging: str
    name: str | None = None


@dataclass(frozen=True)
class ModuleEdge:
    """A directed relationship between two Maven modules."""

    source: str
    target: str
    kind: ModuleEdgeKind
    scope: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class UnresolvedModuleReference:
    """A declared relationship whose target is not in the parsed reactor."""

    source: str
    reference: str
    kind: ModuleEdgeKind
    source_pom: Path


@dataclass(frozen=True)
class ModuleCycle:
    """One deterministic dependency cycle."""

    modules: tuple[str, ...]


@dataclass(frozen=True)
class MavenModuleGraph:
    """Complete graph representation of parsed Maven projects."""

    nodes: tuple[ModuleNode, ...]
    edges: tuple[ModuleEdge, ...]
    unresolved: tuple[UnresolvedModuleReference, ...]
    dependency_cycles: tuple[ModuleCycle, ...]

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.identifier for node in self.nodes)

    def get_node(self, identifier: str) -> ModuleNode | None:
        normalized = identifier.casefold()
        for node in self.nodes:
            if node.identifier.casefold() == normalized:
                return node
        return None

    def outgoing(
        self,
        identifier: str,
        kind: ModuleEdgeKind | None = None,
    ) -> tuple[ModuleEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.source == identifier
            and (kind is None or edge.kind is kind)
        )

    def incoming(
        self,
        identifier: str,
        kind: ModuleEdgeKind | None = None,
    ) -> tuple[ModuleEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.target == identifier
            and (kind is None or edge.kind is kind)
        )

    @property
    def roots(self) -> tuple[ModuleNode, ...]:
        """Return nodes with no incoming reactor-parent relationship."""

        child_ids = {
            edge.target
            for edge in self.edges
            if edge.kind in {
                ModuleEdgeKind.DECLARES_MODULE,
                ModuleEdgeKind.PARENT,
            }
        }
        return tuple(
            node for node in self.nodes
            if node.identifier not in child_ids
        )

    @property
    def leaves(self) -> tuple[ModuleNode, ...]:
        """Return nodes that declare no child modules."""

        parent_ids = {
            edge.source
            for edge in self.edges
            if edge.kind is ModuleEdgeKind.DECLARES_MODULE
        }
        return tuple(
            node for node in self.nodes
            if node.identifier not in parent_ids
        )
