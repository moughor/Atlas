import pytest

from moughorai.java_callflow import FlowDirection, JavaCallFlowService
from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_workspace import JavaWorkspaceService, WorkspaceGraphInput


def node(name: str, *facets: str, kind=KnowledgeNodeKind.TYPE) -> KnowledgeNode:
    return KnowledgeNode(name, kind, name.rsplit(".", 1)[-1], name if kind is KnowledgeNodeKind.TYPE else None, facets=facets)


def workspace():
    api = JavaKnowledgeGraph(
        nodes=(node("Controller", "spring:rest_controller"), node("endpoint:get", kind=KnowledgeNodeKind.ENDPOINT)),
        edges=(
            KnowledgeEdge("Controller", "endpoint:get", KnowledgeEdgeKind.EXPOSES),
            KnowledgeEdge("Controller", "Service", KnowledgeEdgeKind.INJECTS),
        ),
    )
    core = JavaKnowledgeGraph(
        nodes=(node("Service", "spring:service"), node("Repository", "spring:repository"), node("Entity", "jpa:entity")),
        edges=(
            KnowledgeEdge("Service", "Repository", KnowledgeEdgeKind.INJECTS),
            KnowledgeEdge("Repository", "Entity", KnowledgeEdgeKind.DEPENDS_ON),
        ),
    )
    return JavaWorkspaceService().build((
        WorkspaceGraphInput("api", "API", api),
        WorkspaceGraphInput("core", "Core", core),
    ))


def test_traces_downstream_paths_across_projects():
    flow = JavaCallFlowService().downstream(workspace(), "api", "Controller")
    assert flow.direction is FlowDirection.DOWNSTREAM
    assert flow.paths[0].keys == ("Controller", "Service", "Repository", "Entity")


def test_traces_upstream_impact_paths():
    flow = JavaCallFlowService().upstream(workspace(), "core", "Entity")
    assert flow.paths[0].keys == ("Entity", "Repository", "Service", "Controller")


def test_builds_endpoint_to_entity_flow_summary():
    flow = JavaCallFlowService().endpoint(workspace(), "api", "endpoint:get")
    assert [item.key for item in flow.services] == ["Service"]
    assert [item.key for item in flow.repositories] == ["Repository"]
    assert [item.key for item in flow.entities] == ["Entity"]
    assert flow.paths[0].keys == ("endpoint:get", "Controller", "Service", "Repository", "Entity")


def test_detects_cycles_without_infinite_walk():
    graph = JavaKnowledgeGraph(
        nodes=(node("A"), node("B")),
        edges=(KnowledgeEdge("A", "B", KnowledgeEdgeKind.DEPENDS_ON), KnowledgeEdge("B", "A", KnowledgeEdgeKind.DEPENDS_ON)),
    )
    ws = JavaWorkspaceService().build((WorkspaceGraphInput("p", "P", graph),))
    flow = JavaCallFlowService().downstream(ws, "p", "A")
    assert flow.cycles
    assert flow.cycles[0].keys == ("A", "B", "A")


def test_respects_depth_limit_and_marks_truncation():
    flow = JavaCallFlowService().downstream(workspace(), "api", "Controller", max_depth=1)
    assert flow.truncated is True
    assert flow.paths[0].keys == ("Controller", "Service")


def test_rejects_non_endpoint_for_endpoint_analysis():
    with pytest.raises(ValueError, match="not an endpoint"):
        JavaCallFlowService().endpoint(workspace(), "api", "Controller")
