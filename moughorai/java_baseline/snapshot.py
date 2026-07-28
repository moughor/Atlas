"""Capture deterministic workspace architecture baselines."""
from __future__ import annotations

from moughorai.java_policy import ArchitecturePolicy, JavaArchitecturePolicyService
from moughorai.java_workspace.graph import JavaWorkspaceGraph

from .models import ArchitectureBaseline, BaselineEdge, BaselineNode, BaselineViolation


class JavaArchitectureSnapshotter:
    def capture(
        self,
        graph: JavaWorkspaceGraph,
        policy: ArchitecturePolicy | None = None,
    ) -> ArchitectureBaseline:
        policy_report = JavaArchitecturePolicyService().evaluate(graph, policy)
        nodes = tuple(sorted(
            BaselineNode(
                project=item.project_key,
                key=item.key,
                kind=item.node.kind.value,
                facets=tuple(sorted(item.node.facets)),
            )
            for item in graph.nodes
        ))
        edges = tuple(sorted(
            BaselineEdge(
                source_project=item.source_project,
                source=item.edge.source,
                target_project=item.target_project,
                target=item.edge.target,
                kind=item.edge.kind.value,
            )
            for item in graph.edges
        ))
        violations = tuple(sorted(
            BaselineViolation(
                rule=item.rule,
                severity=item.severity.value,
                source_project=item.source_project,
                source=item.source,
                target_project=item.target_project,
                target=item.target,
            )
            for item in policy_report.violations
        ))
        return ArchitectureBaseline(
            nodes=nodes,
            edges=edges,
            unresolved=tuple(sorted(set(graph.unresolved))),
            violations=violations,
        )
