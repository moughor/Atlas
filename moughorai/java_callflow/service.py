"""High-level service for deterministic Java workspace call-flow analysis."""
from __future__ import annotations

from moughorai.java_callflow.analyzer import JavaCallFlowAnalyzer
from moughorai.java_callflow.models import EndpointFlow, FlowAnalysis, FlowDirection
from moughorai.java_workspace.graph import JavaWorkspaceGraph


class JavaCallFlowService:
    def __init__(self, analyzer: JavaCallFlowAnalyzer | None = None) -> None:
        self._analyzer = analyzer or JavaCallFlowAnalyzer()

    def downstream(self, graph: JavaWorkspaceGraph, project_key: str, key: str, **options: int) -> FlowAnalysis:
        return self._analyzer.analyze(graph, project_key, key, direction=FlowDirection.DOWNSTREAM, **options)

    def upstream(self, graph: JavaWorkspaceGraph, project_key: str, key: str, **options: int) -> FlowAnalysis:
        return self._analyzer.analyze(graph, project_key, key, direction=FlowDirection.UPSTREAM, **options)

    def endpoint(self, graph: JavaWorkspaceGraph, project_key: str, endpoint_key: str, **options: int) -> EndpointFlow:
        return self._analyzer.endpoint_flow(graph, project_key, endpoint_key, **options)
