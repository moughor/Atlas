"""High-level architecture baseline service."""
from __future__ import annotations

from moughorai.java_policy import ArchitecturePolicy
from moughorai.java_workspace.graph import JavaWorkspaceGraph

from .comparator import JavaArchitectureBaselineComparator
from .models import ArchitectureBaseline, ArchitectureRegressionReport
from .snapshot import JavaArchitectureSnapshotter


class JavaArchitectureBaselineService:
    def __init__(self) -> None:
        self._snapshotter = JavaArchitectureSnapshotter()
        self._comparator = JavaArchitectureBaselineComparator()

    def capture(self, graph: JavaWorkspaceGraph, policy: ArchitecturePolicy | None = None) -> ArchitectureBaseline:
        return self._snapshotter.capture(graph, policy)

    def compare(
        self,
        baseline: ArchitectureBaseline,
        graph: JavaWorkspaceGraph,
        policy: ArchitecturePolicy | None = None,
    ) -> ArchitectureRegressionReport:
        return self._comparator.compare(baseline, self.capture(graph, policy))
