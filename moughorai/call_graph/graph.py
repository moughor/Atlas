from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Iterable

from .models import (
    CallEdge,
    CallGraphStatistics,
    CallPath,
    MethodId,
    MethodSymbol,
    Resolution,
    ResolutionStatus,
    StronglyConnectedComponent,
    TypeSymbol,
)


class CallGraph:
    """Immutable method-level call graph with deterministic traversal APIs."""

    def __init__(
        self,
        methods: Iterable[MethodSymbol] = (),
        edges: Iterable[CallEdge] = (),
        *,
        types: Iterable[TypeSymbol] = (),
        resolutions: Iterable[Resolution] = (),
    ) -> None:
        method_list = tuple(sorted(set(methods)))
        self._methods = {method.id: method for method in method_list}
        self._types = tuple(sorted(set(types)))
        self._edges = tuple(sorted(set(edges)))
        self._resolutions = tuple(resolutions)
        self._outgoing: dict[MethodId, list[CallEdge]] = defaultdict(list)
        self._incoming: dict[MethodId, list[CallEdge]] = defaultdict(list)
        for edge in self._edges:
            self._outgoing[edge.caller].append(edge)
            self._incoming[edge.callee].append(edge)
        for index in (self._outgoing, self._incoming):
            for values in index.values():
                values.sort()

    @property
    def methods(self) -> tuple[MethodSymbol, ...]:
        return tuple(sorted(self._methods.values()))

    @property
    def types(self) -> tuple[TypeSymbol, ...]:
        return self._types

    @property
    def edges(self) -> tuple[CallEdge, ...]:
        return self._edges

    @property
    def resolutions(self) -> tuple[Resolution, ...]:
        return self._resolutions

    def method(self, method_id: MethodId) -> MethodSymbol | None:
        return self._methods.get(method_id)

    def outgoing_edges(self, method_id: MethodId) -> tuple[CallEdge, ...]:
        return tuple(self._outgoing.get(method_id, ()))

    def incoming_edges(self, method_id: MethodId) -> tuple[CallEdge, ...]:
        return tuple(self._incoming.get(method_id, ()))

    def callees(self, method_id: MethodId, *, transitive: bool = False, max_depth: int | None = None) -> tuple[MethodId, ...]:
        return self._walk(method_id, self._outgoing, forward=True, transitive=transitive, max_depth=max_depth)

    def callers(self, method_id: MethodId, *, transitive: bool = False, max_depth: int | None = None) -> tuple[MethodId, ...]:
        return self._walk(method_id, self._incoming, forward=False, transitive=transitive, max_depth=max_depth)

    def _walk(self, start: MethodId, index: dict[MethodId, list[CallEdge]], *, forward: bool, transitive: bool, max_depth: int | None) -> tuple[MethodId, ...]:
        result: set[MethodId] = set()
        queue = deque([(start, 0)])
        seen_depth: dict[MethodId, int] = {start: 0}
        while queue:
            current, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            for edge in index.get(current, ()):
                target = edge.callee if forward else edge.caller
                if target != start:
                    result.add(target)
                next_depth = depth + 1
                if transitive and (target not in seen_depth or next_depth < seen_depth[target]):
                    seen_depth[target] = next_depth
                    queue.append((target, next_depth))
        return tuple(sorted(result))

    def shortest_path(self, source: MethodId, target: MethodId, *, max_depth: int = 64) -> CallPath | None:
        if source == target:
            return CallPath((source,))
        queue = deque([(source, (source,), tuple())])
        visited = {source}
        while queue:
            current, methods, edges = queue.popleft()
            if len(edges) >= max_depth:
                continue
            for edge in self._outgoing.get(current, ()):
                if edge.callee == target:
                    return CallPath((*methods, target), (*edges, edge))
                if edge.callee not in visited:
                    visited.add(edge.callee)
                    queue.append((edge.callee, (*methods, edge.callee), (*edges, edge)))
        return None

    def paths_from(self, root: MethodId, *, max_depth: int = 8, max_paths: int = 100) -> tuple[CallPath, ...]:
        if max_depth < 0 or max_paths < 1:
            raise ValueError("max_depth must be non-negative and max_paths positive")
        result: list[CallPath] = []
        stack = [(root, (root,), tuple(), {root})]
        while stack and len(result) < max_paths:
            current, methods, edges, seen = stack.pop()
            outgoing = self._outgoing.get(current, ())
            if not outgoing or len(edges) >= max_depth:
                result.append(CallPath(methods, edges))
                continue
            for edge in reversed(outgoing):
                if edge.callee in seen:
                    result.append(CallPath((*methods, edge.callee), (*edges, edge), cycle=True))
                else:
                    stack.append((edge.callee, (*methods, edge.callee), (*edges, edge), {*seen, edge.callee}))
        return tuple(result[:max_paths])

    def strongly_connected_components(self, *, recursive_only: bool = False) -> tuple[StronglyConnectedComponent, ...]:
        index = 0
        indices: dict[MethodId, int] = {}
        lowlinks: dict[MethodId, int] = {}
        stack: list[MethodId] = []
        on_stack: set[MethodId] = set()
        components: list[StronglyConnectedComponent] = []

        def connect(node: MethodId) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for edge in self._outgoing.get(node, ()):
                target = edge.callee
                if target not in indices:
                    connect(target)
                    lowlinks[node] = min(lowlinks[node], lowlinks[target])
                elif target in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[target])
            if lowlinks[node] == indices[node]:
                members: list[MethodId] = []
                while True:
                    member = stack.pop()
                    on_stack.remove(member)
                    members.append(member)
                    if member == node:
                        break
                ordered = tuple(sorted(members))
                recursive = len(ordered) > 1 or any(edge.callee == node for edge in self._outgoing.get(node, ()))
                if not recursive_only or recursive:
                    components.append(StronglyConnectedComponent(ordered, recursive))

        nodes = set(self._methods)
        nodes.update(edge.caller for edge in self._edges)
        nodes.update(edge.callee for edge in self._edges)
        for node in sorted(nodes):
            if node not in indices:
                connect(node)
        return tuple(sorted(components, key=lambda c: c.methods))

    def recursive_components(self) -> tuple[StronglyConnectedComponent, ...]:
        return self.strongly_connected_components(recursive_only=True)

    def roots(self) -> tuple[MethodId, ...]:
        nodes = set(self._methods)
        nodes.update(edge.caller for edge in self._edges)
        return tuple(sorted(node for node in nodes if not self._incoming.get(node)))

    def leaves(self) -> tuple[MethodId, ...]:
        nodes = set(self._methods)
        nodes.update(edge.callee for edge in self._edges)
        return tuple(sorted(node for node in nodes if not self._outgoing.get(node)))

    def statistics(self) -> CallGraphStatistics:
        unresolved = sum(r.status is ResolutionStatus.UNRESOLVED for r in self._resolutions)
        polymorphic = sum(r.status is ResolutionStatus.POLYMORPHIC for r in self._resolutions)
        external = sum(method.external for method in self._methods.values())
        return CallGraphStatistics(
            len(self._methods), len(self._edges), unresolved, external, polymorphic,
            len(self.recursive_components()),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "moughorai.call-graph.v1",
            "types": [self._type_dict(item) for item in self.types],
            "methods": [self._method_dict(item) for item in self.methods],
            "edges": [self._edge_dict(item) for item in self.edges],
            "statistics": asdict(self.statistics()),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @staticmethod
    def _type_dict(item: TypeSymbol) -> dict[str, object]:
        return {
            "qualified_name": item.qualified_name, "kind": item.kind.value,
            "super_type": item.super_type, "interfaces": list(item.interfaces),
            "abstract": item.abstract, "external": item.external,
        }

    @staticmethod
    def _method_dict(item: MethodSymbol) -> dict[str, object]:
        return {
            "id": item.id.qualified_name, "owner": item.id.owner, "name": item.id.name,
            "descriptor": item.id.descriptor, "static": item.static, "abstract": item.abstract,
            "final": item.final, "synthetic": item.synthetic, "external": item.external,
            "source_path": item.source_path, "line": item.line, "annotations": list(item.annotations),
        }

    @staticmethod
    def _edge_dict(item: CallEdge) -> dict[str, object]:
        return {
            "caller": item.caller.qualified_name, "callee": item.callee.qualified_name,
            "dispatch": item.dispatch.value, "kind": item.kind.value, "status": item.status.value,
            "source_path": item.source_path, "line": item.line, "column": item.column,
            "declared_target": item.declared_target.qualified_name if item.declared_target else None,
        }
