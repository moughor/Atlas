"""High-level API for deterministic Java change-impact reports."""
from __future__ import annotations

from moughorai.java_impact.analyzer import JavaChangeImpactAnalyzer
from moughorai.java_impact.models import ChangeImpactReport
from moughorai.java_workspace.graph import JavaWorkspaceGraph


class JavaChangeImpactService:
    def __init__(self, analyzer: JavaChangeImpactAnalyzer | None = None) -> None:
        self._analyzer = analyzer or JavaChangeImpactAnalyzer()

    def analyze(self, graph: JavaWorkspaceGraph, project_key: str, key: str, **options: int) -> ChangeImpactReport:
        return self._analyzer.analyze(graph, project_key, key, **options)
