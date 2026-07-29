"""Queryable enterprise Java knowledge graph."""
from __future__ import annotations

from collections import defaultdict, deque
from types import MappingProxyType
from typing import Iterable, Mapping

from moughorai.java_knowledge.models import (
    ImpactReport,
    KnowledgeEdge,
    KnowledgeEdgeKind,
    KnowledgeNode,
    KnowledgeNodeKind,
)


class JavaKnowledgeGraph:
    def __init__(self, nodes: Iterable[KnowledgeNode] = (), edges: Iterable[KnowledgeEdge] = (), unresolved: Iterable[str] = ()) -> None:
        self._nodes = tuple(nodes)
        self._edges = tuple(edges)
        self._unresolved = tuple(unresolved)
        self._node_map: Mapping[str, KnowledgeNode] = MappingProxyType({node.key: node for node in self._nodes})
        outgoing: dict[str, list[KnowledgeEdge]] = defaultdict(list)
        incoming: dict[str, list[KnowledgeEdge]] = defaultdict(list)
        for edge in self._edges:
            outgoing[edge.source].append(edge)
            incoming[edge.target].append(edge)
        self._outgoing = MappingProxyType({key: tuple(value) for key, value in outgoing.items()})
        self._incoming = MappingProxyType({key: tuple(value) for key, value in incoming.items()})

    @property
    def nodes(self) -> tuple[KnowledgeNode, ...]:
        return self._nodes

    @property
    def edges(self) -> tuple[KnowledgeEdge, ...]:
        return self._edges

    @property
    def unresolved(self) -> tuple[str, ...]:
        return self._unresolved

    def node(self, key: str) -> KnowledgeNode | None:
        return self._node_map.get(key)

    def find(self, text: str, kind: KnowledgeNodeKind | None = None) -> tuple[KnowledgeNode, ...]:
        needle = text.casefold()
        return tuple(
            node for node in self._nodes
            if (kind is None or node.kind is kind)
            and (needle in node.display_name.casefold() or needle in node.key.casefold())
        )

    def outgoing(self, key: str, kind: KnowledgeEdgeKind | None = None) -> tuple[KnowledgeEdge, ...]:
        edges = self._outgoing.get(key, ())
        return edges if kind is None else tuple(edge for edge in edges if edge.kind is kind)

    def incoming(self, key: str, kind: KnowledgeEdgeKind | None = None) -> tuple[KnowledgeEdge, ...]:
        edges = self._incoming.get(key, ())
        return edges if kind is None else tuple(edge for edge in edges if edge.kind is kind)

    def dependencies(self, key: str) -> tuple[KnowledgeNode, ...]:
        names = dict.fromkeys(edge.target for edge in self.outgoing(key) if edge.kind is not KnowledgeEdgeKind.EXPOSES)
        return tuple(self._node_map[name] for name in names if name in self._node_map)

    def dependents(self, key: str) -> tuple[KnowledgeNode, ...]:
        names = dict.fromkeys(edge.source for edge in self.incoming(key) if edge.kind is not KnowledgeEdgeKind.EXPOSES)
        return tuple(self._node_map[name] for name in names if name in self._node_map)

    def transitive_dependents(self, key: str, max_depth: int | None = None) -> tuple[KnowledgeNode, ...]:
        seen = {key}
        queue = deque([(key, 0)])
        result: list[KnowledgeNode] = []
        while queue:
            current, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            for edge in self.incoming(current):
                if edge.kind is KnowledgeEdgeKind.EXPOSES or edge.source in seen:
                    continue
                seen.add(edge.source)
                node = self._node_map.get(edge.source)
                if node is not None:
                    result.append(node)
                    queue.append((edge.source, depth + 1))
        return tuple(result)

    def impact(self, key: str) -> ImpactReport:
        subject = self._node_map[key]
        endpoint_names = dict.fromkeys(edge.target for edge in self.outgoing(key, KnowledgeEdgeKind.EXPOSES))
        persistence_names = dict.fromkeys(edge.target for edge in self.outgoing(key, KnowledgeEdgeKind.JPA_RELATION))
        unresolved = tuple(item for item in self._unresolved if item.startswith(f"{key}:") or item.startswith(f"{key}#"))
        return ImpactReport(
            subject=subject,
            direct_dependencies=self.dependencies(key),
            direct_dependents=self.dependents(key),
            endpoints=tuple(self._node_map[name] for name in endpoint_names if name in self._node_map),
            persistence_targets=tuple(self._node_map[name] for name in persistence_names if name in self._node_map),
            unresolved_roles=unresolved,
        )
