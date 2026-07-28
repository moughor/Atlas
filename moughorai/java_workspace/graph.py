"""Queryable multi-project Java workspace graph."""
from __future__ import annotations

from collections import defaultdict, deque
from types import MappingProxyType
from typing import Iterable, Mapping

from moughorai.java_knowledge.models import KnowledgeEdgeKind, KnowledgeNodeKind
from moughorai.java_workspace.models import (
    EndpointEntityTrace,
    RenameImpact,
    WorkspaceEdge,
    WorkspaceNode,
    WorkspaceProject,
)


class JavaWorkspaceGraph:
    def __init__(
        self,
        projects: Iterable[WorkspaceProject] = (),
        nodes: Iterable[WorkspaceNode] = (),
        edges: Iterable[WorkspaceEdge] = (),
        unresolved: Iterable[str] = (),
    ) -> None:
        self._projects = tuple(projects)
        self._nodes = tuple(nodes)
        self._edges = tuple(edges)
        self._unresolved = tuple(unresolved)
        self._project_map = MappingProxyType({project.key: project for project in self._projects})
        self._node_map: Mapping[tuple[str, str], WorkspaceNode] = MappingProxyType(
            {(node.project_key, node.key): node for node in self._nodes}
        )
        by_symbol: dict[str, list[WorkspaceNode]] = defaultdict(list)
        outgoing: dict[tuple[str, str], list[WorkspaceEdge]] = defaultdict(list)
        incoming: dict[tuple[str, str], list[WorkspaceEdge]] = defaultdict(list)
        for node in self._nodes:
            by_symbol[node.key].append(node)
        for edge in self._edges:
            outgoing[(edge.source_project, edge.edge.source)].append(edge)
            incoming[(edge.target_project, edge.edge.target)].append(edge)
        self._by_symbol = MappingProxyType({key: tuple(value) for key, value in by_symbol.items()})
        self._outgoing = MappingProxyType({key: tuple(value) for key, value in outgoing.items()})
        self._incoming = MappingProxyType({key: tuple(value) for key, value in incoming.items()})

    @property
    def projects(self) -> tuple[WorkspaceProject, ...]:
        return self._projects

    @property
    def nodes(self) -> tuple[WorkspaceNode, ...]:
        return self._nodes

    @property
    def edges(self) -> tuple[WorkspaceEdge, ...]:
        return self._edges

    @property
    def unresolved(self) -> tuple[str, ...]:
        return self._unresolved

    def project(self, key: str) -> WorkspaceProject | None:
        return self._project_map.get(key)

    def node(self, project_key: str, key: str) -> WorkspaceNode | None:
        return self._node_map.get((project_key, key))

    def symbols(self, key: str) -> tuple[WorkspaceNode, ...]:
        return self._by_symbol.get(key, ())

    def find(self, text: str, project_key: str | None = None) -> tuple[WorkspaceNode, ...]:
        needle = text.casefold()
        return tuple(
            item for item in self._nodes
            if (project_key is None or item.project_key == project_key)
            and (
                needle in item.node.display_name.casefold()
                or needle in item.node.key.casefold()
                or any(needle in facet.casefold() for facet in item.node.facets)
            )
        )

    def outgoing(self, project_key: str, key: str) -> tuple[WorkspaceEdge, ...]:
        return self._outgoing.get((project_key, key), ())

    def incoming(self, project_key: str, key: str) -> tuple[WorkspaceEdge, ...]:
        return self._incoming.get((project_key, key), ())

    def implementations(self, qualified_name: str) -> tuple[WorkspaceNode, ...]:
        result: list[WorkspaceNode] = []
        for target in self.symbols(qualified_name):
            for edge in self.incoming(target.project_key, target.key):
                if edge.edge.kind is KnowledgeEdgeKind.IMPLEMENTS:
                    source = self.node(edge.source_project, edge.edge.source)
                    if source is not None and source not in result:
                        result.append(source)
        return tuple(result)

    def cross_project_edges(self) -> tuple[WorkspaceEdge, ...]:
        return tuple(edge for edge in self._edges if edge.is_cross_project)

    def rename_impact(self, project_key: str, key: str) -> RenameImpact:
        subject = self._node_map[(project_key, key)]
        direct: list[WorkspaceNode] = []
        endpoints: list[WorkspaceNode] = []
        seen = {(project_key, key)}
        queue = deque([(project_key, key)])
        transitive: list[WorkspaceNode] = []
        while queue:
            current_project, current_key = queue.popleft()
            for edge in self.incoming(current_project, current_key):
                source_id = (edge.source_project, edge.edge.source)
                source = self._node_map.get(source_id)
                if source is None or source_id in seen:
                    continue
                seen.add(source_id)
                if (current_project, current_key) == (project_key, key):
                    direct.append(source)
                else:
                    transitive.append(source)
                queue.append(source_id)
            for edge in self.outgoing(current_project, current_key):
                if edge.edge.kind is KnowledgeEdgeKind.EXPOSES:
                    endpoint = self.node(edge.target_project, edge.edge.target)
                    if endpoint is not None and endpoint not in endpoints:
                        endpoints.append(endpoint)
        affected = tuple(dict.fromkeys(item.project_key for item in (*direct, *transitive, *endpoints)))
        return RenameImpact(subject, tuple(direct), tuple(transitive), tuple(endpoints), affected)

    def trace_endpoint_to_entities(self, project_key: str, endpoint_key: str, max_depth: int = 8) -> EndpointEntityTrace:
        endpoint = self._node_map[(project_key, endpoint_key)]
        owners = [
            self.node(edge.source_project, edge.edge.source)
            for edge in self.incoming(project_key, endpoint_key)
            if edge.edge.kind is KnowledgeEdgeKind.EXPOSES
        ]
        entities: list[WorkspaceNode] = []
        paths: list[tuple[str, ...]] = []
        queue = deque((owner.project_key, owner.key, (endpoint.key, owner.key), 0) for owner in owners if owner is not None)
        visited: set[tuple[str, str]] = set()
        while queue:
            current_project, current_key, path, depth = queue.popleft()
            identity = (current_project, current_key)
            if identity in visited or depth > max_depth:
                continue
            visited.add(identity)
            current = self.node(current_project, current_key)
            if current is None:
                continue
            if current.node.kind is KnowledgeNodeKind.TYPE and "jpa:entity" in current.node.facets:
                entities.append(current)
                paths.append(path)
                continue
            for edge in self.outgoing(current_project, current_key):
                if edge.edge.kind is KnowledgeEdgeKind.EXPOSES:
                    continue
                queue.append((edge.target_project, edge.edge.target, (*path, edge.edge.target), depth + 1))
        return EndpointEntityTrace(endpoint, tuple(entities), tuple(paths))
