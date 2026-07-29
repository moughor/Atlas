"""Deterministic change-impact and risk scoring over a Java workspace."""
from __future__ import annotations

from moughorai.java_callflow import JavaCallFlowService
from moughorai.java_impact.models import ChangeImpactReport, RiskFactor, RiskLevel
from moughorai.java_workspace.graph import JavaWorkspaceGraph
from moughorai.java_workspace.models import WorkspaceNode


class JavaChangeImpactAnalyzer:
    """Computes explainable blast radius without probabilistic inference."""

    def __init__(self, callflow: JavaCallFlowService | None = None) -> None:
        self._callflow = callflow or JavaCallFlowService()

    def analyze(
        self,
        graph: JavaWorkspaceGraph,
        project_key: str,
        key: str,
        *,
        max_depth: int = 12,
        max_paths: int = 250,
    ) -> ChangeImpactReport:
        subject = graph.node(project_key, key)
        if subject is None:
            raise KeyError((project_key, key))

        rename = graph.rename_impact(project_key, key)
        upstream = self._callflow.upstream(
            graph, project_key, key, max_depth=max_depth, max_paths=max_paths
        )
        downstream = self._callflow.downstream(
            graph, project_key, key, max_depth=max_depth, max_paths=max_paths
        )

        direct = self._unique(rename.direct_references)
        direct_ids = {(node.project_key, node.key) for node in direct}
        transitive = self._unique(
            node for node in upstream.reachable
            if (node.project_key, node.key) not in direct_ids
        )
        endpoints = self._unique(rename.exposed_endpoints)
        entities = self._unique(
            node for node in downstream.reachable if "jpa:entity" in node.node.facets
        )
        projects = tuple(dict.fromkeys(
            node.project_key
            for node in (subject, *direct, *transitive, *endpoints, *entities)
        ))

        factors = self._factors(subject, direct, transitive, endpoints, entities, projects, upstream.cycles, upstream.truncated or downstream.truncated)
        score = min(100, sum(factor.points for factor in factors))
        return ChangeImpactReport(
            subject=subject,
            score=score,
            level=self._level(score),
            direct_dependents=direct,
            transitive_dependents=transitive,
            exposed_endpoints=endpoints,
            reachable_entities=entities,
            affected_projects=projects,
            cycles=upstream.cycles,
            factors=factors,
            truncated=upstream.truncated or downstream.truncated,
        )

    @staticmethod
    def _factors(subject, direct, transitive, endpoints, entities, projects, cycles, truncated):
        factors: list[RiskFactor] = []
        if direct:
            points = min(25, len(direct) * 5)
            factors.append(RiskFactor("direct_dependents", points, f"{len(direct)} direct dependent(s)"))
        if transitive:
            points = min(25, len(transitive) * 3)
            factors.append(RiskFactor("transitive_dependents", points, f"{len(transitive)} transitive dependent(s)"))
        if endpoints:
            points = min(20, len(endpoints) * 10)
            factors.append(RiskFactor("endpoint_exposure", points, f"{len(endpoints)} exposed endpoint(s)"))
        if entities:
            points = min(15, len(entities) * 5)
            factors.append(RiskFactor("persistence_reach", points, f"{len(entities)} reachable JPA entity/entities"))
        cross_project = max(0, len(projects) - 1)
        if cross_project:
            points = min(10, cross_project * 5)
            factors.append(RiskFactor("cross_project", points, f"change reaches {cross_project} additional project(s)"))
        if cycles:
            factors.append(RiskFactor("dependency_cycles", 10, f"{len(cycles)} upstream cycle(s) detected"))
        if "jpa:entity" in subject.node.facets:
            factors.append(RiskFactor("entity_subject", 10, "subject is a persisted JPA entity"))
        if truncated:
            factors.append(RiskFactor("analysis_truncated", 5, "configured analysis limit was reached"))
        return tuple(factors)

    @staticmethod
    def _level(score: int) -> RiskLevel:
        if score >= 75:
            return RiskLevel.CRITICAL
        if score >= 50:
            return RiskLevel.HIGH
        if score >= 25:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _unique(nodes) -> tuple[WorkspaceNode, ...]:
        result: list[WorkspaceNode] = []
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            identity = (node.project_key, node.key)
            if identity not in seen:
                seen.add(identity)
                result.append(node)
        return tuple(result)
