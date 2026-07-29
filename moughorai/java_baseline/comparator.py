"""Deterministic comparison of Java architecture baselines."""
from __future__ import annotations

from .models import (
    ArchitectureBaseline,
    ArchitectureRegression,
    ArchitectureRegressionReport,
    BaselineEdge,
    BaselineNode,
    BaselineViolation,
    RegressionSeverity,
)


class JavaArchitectureBaselineComparator:
    def compare(
        self,
        baseline: ArchitectureBaseline,
        current: ArchitectureBaseline,
    ) -> ArchitectureRegressionReport:
        added_nodes = set(current.nodes) - set(baseline.nodes)
        removed_nodes = set(baseline.nodes) - set(current.nodes)
        added_edges = set(current.edges) - set(baseline.edges)
        removed_edges = set(baseline.edges) - set(current.edges)
        added_unresolved = set(current.unresolved) - set(baseline.unresolved)
        removed_unresolved = set(baseline.unresolved) - set(current.unresolved)
        added_violations = set(current.violations) - set(baseline.violations)
        removed_violations = set(baseline.violations) - set(current.violations)

        regressions = [
            *(self._node(item, False) for item in added_nodes),
            *(self._edge(item, False) for item in added_edges),
            *(self._unresolved(item, False) for item in added_unresolved),
            *(self._violation(item, False) for item in added_violations),
        ]
        resolved = [
            *(self._node(item, True) for item in removed_nodes),
            *(self._edge(item, True) for item in removed_edges),
            *(self._unresolved(item, True) for item in removed_unresolved),
            *(self._violation(item, True) for item in removed_violations),
        ]
        key = lambda item: (item.category, item.severity.value, item.message, item.evidence)
        return ArchitectureRegressionReport(
            tuple(sorted(regressions, key=key)),
            tuple(sorted(resolved, key=key)),
        )

    @staticmethod
    def _node(item: BaselineNode, resolved: bool) -> ArchitectureRegression:
        action = "Removed" if resolved else "Added"
        return ArchitectureRegression(
            "node_removed" if resolved else "node_added",
            RegressionSeverity.INFO,
            f"{action} {item.kind} {item.project}:{item.key}",
            (item.project, item.key, item.kind, *item.facets),
        )

    @staticmethod
    def _edge(item: BaselineEdge, resolved: bool) -> ArchitectureRegression:
        action = "Removed" if resolved else "Added"
        severity = RegressionSeverity.INFO if resolved else RegressionSeverity.WARNING
        return ArchitectureRegression(
            "dependency_removed" if resolved else "dependency_added",
            severity,
            f"{action} {item.kind} dependency {item.source_project}:{item.source} -> {item.target_project}:{item.target}",
            (item.kind, item.source_project, item.source, item.target_project, item.target),
        )

    @staticmethod
    def _unresolved(item: str, resolved: bool) -> ArchitectureRegression:
        return ArchitectureRegression(
            "unresolved_resolved" if resolved else "unresolved_added",
            RegressionSeverity.INFO if resolved else RegressionSeverity.ERROR,
            ("Resolved" if resolved else "New unresolved reference") + f": {item}",
            (item,),
        )

    @staticmethod
    def _violation(item: BaselineViolation, resolved: bool) -> ArchitectureRegression:
        severity_map = {
            "info": RegressionSeverity.INFO,
            "warning": RegressionSeverity.WARNING,
            "error": RegressionSeverity.ERROR,
            "critical": RegressionSeverity.CRITICAL,
        }
        return ArchitectureRegression(
            "violation_resolved" if resolved else "violation_added",
            RegressionSeverity.INFO if resolved else severity_map.get(item.severity, RegressionSeverity.ERROR),
            ("Resolved" if resolved else "New") + f" policy violation {item.rule}: {item.source_project}:{item.source}",
            (item.rule, item.severity, item.source_project, item.source, item.target_project, item.target),
        )
