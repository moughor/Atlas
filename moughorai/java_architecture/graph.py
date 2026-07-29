"""Immutable queryable Java architecture graph."""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType
from typing import Iterable, Mapping

from moughorai.java_architecture.models import (
    ArchitectureEdge,
    ArchitectureEdgeKind,
    ArchitectureNode,
    UnresolvedArchitectureReference,
)


class JavaArchitectureGraph:
    """A deterministic directed graph of Java type relationships."""

    def __init__(
        self,
        nodes: Iterable[ArchitectureNode] = (),
        edges: Iterable[ArchitectureEdge] = (),
        unresolved: Iterable[UnresolvedArchitectureReference] = (),
    ) -> None:
        ordered_nodes = tuple(nodes)
        ordered_edges = tuple(edges)
        node_map = {node.qualified_name: node for node in ordered_nodes}

        outgoing: dict[str, list[ArchitectureEdge]] = defaultdict(list)
        incoming: dict[str, list[ArchitectureEdge]] = defaultdict(list)
        for edge in ordered_edges:
            outgoing[edge.source].append(edge)
            incoming[edge.target].append(edge)

        self._nodes = ordered_nodes
        self._edges = ordered_edges
        self._node_map: Mapping[str, ArchitectureNode] = MappingProxyType(node_map)
        self._outgoing: Mapping[str, tuple[ArchitectureEdge, ...]] = MappingProxyType(
            {key: tuple(value) for key, value in outgoing.items()}
        )
        self._incoming: Mapping[str, tuple[ArchitectureEdge, ...]] = MappingProxyType(
            {key: tuple(value) for key, value in incoming.items()}
        )
        self._unresolved = tuple(unresolved)

    @property
    def nodes(self) -> tuple[ArchitectureNode, ...]:
        return self._nodes

    @property
    def edges(self) -> tuple[ArchitectureEdge, ...]:
        return self._edges

    @property
    def unresolved(self) -> tuple[UnresolvedArchitectureReference, ...]:
        return self._unresolved

    def node(self, qualified_name: str) -> ArchitectureNode | None:
        return self._node_map.get(qualified_name)

    def outgoing(
        self,
        qualified_name: str,
        kind: ArchitectureEdgeKind | None = None,
    ) -> tuple[ArchitectureEdge, ...]:
        edges = self._outgoing.get(qualified_name, ())
        if kind is None:
            return edges
        return tuple(edge for edge in edges if edge.kind is kind)

    def incoming(
        self,
        qualified_name: str,
        kind: ArchitectureEdgeKind | None = None,
    ) -> tuple[ArchitectureEdge, ...]:
        edges = self._incoming.get(qualified_name, ())
        if kind is None:
            return edges
        return tuple(edge for edge in edges if edge.kind is kind)

    def dependencies(self, qualified_name: str) -> tuple[ArchitectureNode, ...]:
        names = dict.fromkeys(edge.target for edge in self.outgoing(qualified_name))
        return tuple(self._node_map[name] for name in names if name in self._node_map)

    def dependents(self, qualified_name: str) -> tuple[ArchitectureNode, ...]:
        names = dict.fromkeys(edge.source for edge in self.incoming(qualified_name))
        return tuple(self._node_map[name] for name in names if name in self._node_map)
