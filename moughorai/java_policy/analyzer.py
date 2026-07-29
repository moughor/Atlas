"""Deterministic architecture-policy evaluation."""
from __future__ import annotations

from collections import defaultdict

from moughorai.java_knowledge.models import KnowledgeEdgeKind, KnowledgeNodeKind
from moughorai.java_workspace.graph import JavaWorkspaceGraph
from moughorai.java_workspace.models import WorkspaceNode

from .models import (
    ArchitectureLayer,
    ArchitecturePolicy,
    ArchitecturePolicyReport,
    PolicySeverity,
    PolicyViolation,
)


class JavaArchitecturePolicyAnalyzer:
    def analyze(
        self,
        graph: JavaWorkspaceGraph,
        policy: ArchitecturePolicy | None = None,
    ) -> ArchitecturePolicyReport:
        active = policy or ArchitecturePolicy()
        violations: list[PolicyViolation] = []
        allowed = set(active.allowed_layer_dependencies)
        forbidden_projects = set(active.forbidden_project_dependencies)

        for item in graph.edges:
            source = graph.node(item.source_project, item.edge.source)
            target = graph.node(item.target_project, item.edge.target)
            if source is None or target is None:
                continue
            source_layer = self.layer_of(source)
            target_layer = self.layer_of(target)

            if (item.source_project, item.target_project) in forbidden_projects:
                violations.append(PolicyViolation(
                    rule="forbidden_project_dependency",
                    severity=PolicySeverity.ERROR,
                    message=f"Project {item.source_project} must not depend on {item.target_project}",
                    source_project=item.source_project,
                    source=source.key,
                    target_project=item.target_project,
                    target=target.key,
                    evidence=(item.edge.kind.value,),
                ))

            if item.edge.kind is KnowledgeEdgeKind.EXPOSES:
                continue

            if (
                active.detect_controller_repository_shortcuts
                and source_layer is ArchitectureLayer.CONTROLLER
                and target_layer is ArchitectureLayer.REPOSITORY
            ):
                violations.append(PolicyViolation(
                    rule="controller_repository_shortcut",
                    severity=PolicySeverity.CRITICAL,
                    message=f"Controller {source.key} bypasses the service layer and depends on repository {target.key}",
                    source_project=item.source_project,
                    source=source.key,
                    target_project=item.target_project,
                    target=target.key,
                    evidence=(item.edge.kind.value, source_layer.value, target_layer.value),
                ))
                continue

            if source_layer is ArchitectureLayer.ENDPOINT or target_layer is ArchitectureLayer.ENDPOINT:
                continue
            if (source_layer, target_layer) not in allowed:
                violations.append(PolicyViolation(
                    rule="forbidden_layer_dependency",
                    severity=PolicySeverity.ERROR,
                    message=f"{source_layer.value} must not depend on {target_layer.value}",
                    source_project=item.source_project,
                    source=source.key,
                    target_project=item.target_project,
                    target=target.key,
                    evidence=(item.edge.kind.value, source_layer.value, target_layer.value),
                ))

        if active.detect_project_cycles:
            violations.extend(self._project_cycle_violations(graph))

        ordered = tuple(sorted(
            violations,
            key=lambda value: (
                value.rule,
                value.source_project,
                value.source,
                value.target_project,
                value.target,
            ),
        ))
        return ArchitecturePolicyReport(ordered, len(graph.edges), len(graph.projects))

    @staticmethod
    def layer_of(node: WorkspaceNode) -> ArchitectureLayer:
        if node.node.kind is KnowledgeNodeKind.ENDPOINT:
            return ArchitectureLayer.ENDPOINT
        facets = set(node.node.facets)
        if "spring:rest_controller" in facets or "spring:controller" in facets:
            return ArchitectureLayer.CONTROLLER
        if "spring:service" in facets:
            return ArchitectureLayer.SERVICE
        if "spring:repository" in facets:
            return ArchitectureLayer.REPOSITORY
        if "jpa:entity" in facets or "jpa:embeddable" in facets or "jpa:mapped_superclass" in facets:
            return ArchitectureLayer.ENTITY
        return ArchitectureLayer.OTHER

    def _project_cycle_violations(self, graph: JavaWorkspaceGraph) -> list[PolicyViolation]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in graph.cross_project_edges():
            adjacency[edge.source_project].add(edge.target_project)

        found: set[tuple[str, ...]] = set()
        violations: list[PolicyViolation] = []

        def canonical(cycle: tuple[str, ...]) -> tuple[str, ...]:
            body = cycle[:-1]
            rotations = [body[index:] + body[:index] for index in range(len(body))]
            smallest = min(rotations)
            return (*smallest, smallest[0])

        def walk(start: str, current: str, path: tuple[str, ...], visiting: set[str]) -> None:
            for target in sorted(adjacency.get(current, ())):
                if target == start and len(path) > 1:
                    cycle = canonical((*path, start))
                    if cycle not in found:
                        found.add(cycle)
                        violations.append(PolicyViolation(
                            rule="project_dependency_cycle",
                            severity=PolicySeverity.ERROR,
                            message="Project dependency cycle: " + " -> ".join(cycle),
                            source_project=cycle[0],
                            source=cycle[0],
                            target_project=cycle[-2],
                            target=cycle[-2],
                            evidence=cycle,
                        ))
                elif target not in visiting:
                    walk(start, target, (*path, target), {*visiting, target})

        for project in sorted(item.key for item in graph.projects):
            walk(project, project, (project,), {project})
        return violations
