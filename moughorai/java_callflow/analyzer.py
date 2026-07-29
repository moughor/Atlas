"""Deterministic path analysis over a JavaWorkspaceGraph."""
from __future__ import annotations

from collections import deque

from moughorai.java_knowledge.models import KnowledgeEdgeKind, KnowledgeNodeKind
from moughorai.java_workspace.graph import JavaWorkspaceGraph
from moughorai.java_workspace.models import WorkspaceEdge, WorkspaceNode

from moughorai.java_callflow.models import (
    EndpointFlow,
    FlowAnalysis,
    FlowDirection,
    FlowPath,
    FlowStep,
)


class JavaCallFlowAnalyzer:
    """Traces architectural execution paths without source-code guessing."""

    def analyze(
        self,
        graph: JavaWorkspaceGraph,
        project_key: str,
        key: str,
        *,
        direction: FlowDirection = FlowDirection.DOWNSTREAM,
        max_depth: int = 8,
        max_paths: int = 100,
    ) -> FlowAnalysis:
        subject = graph.node(project_key, key)
        if subject is None:
            raise KeyError((project_key, key))
        paths, reachable, cycles, truncated = self._walk(
            graph, subject, direction=direction, max_depth=max_depth, max_paths=max_paths
        )
        return FlowAnalysis(subject, direction, paths, reachable, cycles, truncated)

    def endpoint_flow(
        self,
        graph: JavaWorkspaceGraph,
        project_key: str,
        endpoint_key: str,
        *,
        max_depth: int = 8,
        max_paths: int = 100,
    ) -> EndpointFlow:
        endpoint = graph.node(project_key, endpoint_key)
        if endpoint is None:
            raise KeyError((project_key, endpoint_key))
        if endpoint.node.kind is not KnowledgeNodeKind.ENDPOINT:
            raise ValueError(f"not an endpoint: {project_key}:{endpoint_key}")

        owner_edges = tuple(
            edge for edge in graph.incoming(project_key, endpoint_key)
            if edge.edge.kind is KnowledgeEdgeKind.EXPOSES
        )
        collected_paths: list[FlowPath] = []
        reachable: list[WorkspaceNode] = []
        for edge in owner_edges:
            owner = graph.node(edge.source_project, edge.edge.source)
            if owner is None:
                continue
            paths, nodes, _, _ = self._walk(
                graph, owner, direction=FlowDirection.DOWNSTREAM,
                max_depth=max_depth, max_paths=max_paths,
                prefix=(FlowStep(endpoint, "exposed_by", 0),),
            )
            collected_paths.extend(paths)
            reachable.extend(nodes)

        unique = self._unique_nodes(reachable)
        services = tuple(node for node in unique if any(f in node.node.facets for f in ("spring:service", "spring:component")))
        repositories = tuple(node for node in unique if "spring:repository" in node.node.facets)
        entities = tuple(node for node in unique if "jpa:entity" in node.node.facets)
        return EndpointFlow(endpoint, tuple(collected_paths), services, repositories, entities)

    def _walk(
        self,
        graph: JavaWorkspaceGraph,
        subject: WorkspaceNode,
        *,
        direction: FlowDirection,
        max_depth: int,
        max_paths: int,
        prefix: tuple[FlowStep, ...] = (),
    ) -> tuple[tuple[FlowPath, ...], tuple[WorkspaceNode, ...], tuple[FlowPath, ...], bool]:
        start_step = FlowStep(subject, "start", len(prefix))
        queue = deque([(subject, (*prefix, start_step), {(subject.project_key, subject.key)})])
        paths: list[FlowPath] = []
        cycles: list[FlowPath] = []
        reachable: list[WorkspaceNode] = []
        truncated = False

        while queue:
            current, steps, seen = queue.popleft()
            depth = len(steps) - len(prefix) - 1
            if depth >= max_depth:
                paths.append(FlowPath(steps))
                truncated = True
                continue
            edges = self._edges(graph, current, direction)
            if not edges:
                paths.append(FlowPath(steps))
                if len(paths) >= max_paths:
                    truncated = bool(queue)
                    break
                continue
            expanded = False
            for edge in edges:
                next_node, relation = self._next(graph, edge, direction)
                if next_node is None:
                    continue
                expanded = True
                identity = (next_node.project_key, next_node.key)
                next_steps = (*steps, FlowStep(next_node, relation, depth + 1))
                if identity in seen:
                    cycle = FlowPath(next_steps, cycle=True)
                    cycles.append(cycle)
                    paths.append(cycle)
                    continue
                reachable.append(next_node)
                queue.append((next_node, next_steps, {*seen, identity}))
            if not expanded:
                paths.append(FlowPath(steps))
            if len(paths) >= max_paths:
                truncated = True
                break

        return tuple(paths[:max_paths]), self._unique_nodes(reachable), tuple(cycles), truncated

    @staticmethod
    def _edges(graph: JavaWorkspaceGraph, node: WorkspaceNode, direction: FlowDirection) -> tuple[WorkspaceEdge, ...]:
        edges = graph.outgoing(node.project_key, node.key) if direction is FlowDirection.DOWNSTREAM else graph.incoming(node.project_key, node.key)
        return tuple(edge for edge in edges if edge.edge.kind is not KnowledgeEdgeKind.EXPOSES)

    @staticmethod
    def _next(graph: JavaWorkspaceGraph, edge: WorkspaceEdge, direction: FlowDirection) -> tuple[WorkspaceNode | None, str]:
        if direction is FlowDirection.DOWNSTREAM:
            return graph.node(edge.target_project, edge.edge.target), edge.edge.kind.value
        return graph.node(edge.source_project, edge.edge.source), f"reverse:{edge.edge.kind.value}"

    @staticmethod
    def _unique_nodes(nodes: list[WorkspaceNode]) -> tuple[WorkspaceNode, ...]:
        result: list[WorkspaceNode] = []
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            identity = (node.project_key, node.key)
            if identity not in seen:
                seen.add(identity)
                result.append(node)
        return tuple(result)
