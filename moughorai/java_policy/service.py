"""Public service facade for Java architecture policy checks."""
from __future__ import annotations

from moughorai.java_workspace.graph import JavaWorkspaceGraph

from .analyzer import JavaArchitecturePolicyAnalyzer
from .models import ArchitecturePolicy, ArchitecturePolicyReport


class JavaArchitecturePolicyService:
    def __init__(self, analyzer: JavaArchitecturePolicyAnalyzer | None = None) -> None:
        self._analyzer = analyzer or JavaArchitecturePolicyAnalyzer()

    def evaluate(
        self,
        graph: JavaWorkspaceGraph,
        policy: ArchitecturePolicy | None = None,
    ) -> ArchitecturePolicyReport:
        return self._analyzer.analyze(graph, policy)
