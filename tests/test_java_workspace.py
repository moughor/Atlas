from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_workspace import JavaWorkspaceService, WorkspaceGraphInput


def type_node(name: str, *facets: str) -> KnowledgeNode:
    return KnowledgeNode(name, KnowledgeNodeKind.TYPE, name.rsplit(".", 1)[-1], name, facets=facets)


def endpoint_node(key: str, display: str) -> KnowledgeNode:
    return KnowledgeNode(key, KnowledgeNodeKind.ENDPOINT, display)


def workspace():
    api = JavaKnowledgeGraph(
        nodes=(
            type_node("com.acme.api.UserController", "spring:rest_controller"),
            endpoint_node("endpoint:users#get", "GET /users/{id}"),
        ),
        edges=(
            KnowledgeEdge("com.acme.api.UserController", "endpoint:users#get", KnowledgeEdgeKind.EXPOSES),
            KnowledgeEdge("com.acme.api.UserController", "com.acme.service.UserService", KnowledgeEdgeKind.INJECTS),
        ),
    )
    service = JavaKnowledgeGraph(
        nodes=(
            type_node("com.acme.service.UserService", "spring:service"),
            type_node("com.acme.service.DefaultUserService"),
        ),
        edges=(
            KnowledgeEdge("com.acme.service.DefaultUserService", "com.acme.service.UserService", KnowledgeEdgeKind.IMPLEMENTS),
            KnowledgeEdge("com.acme.service.UserService", "com.acme.persistence.UserRepository", KnowledgeEdgeKind.INJECTS),
        ),
    )
    persistence = JavaKnowledgeGraph(
        nodes=(type_node("com.acme.persistence.UserRepository", "spring:repository"), type_node("com.acme.persistence.User", "jpa:entity")),
        edges=(KnowledgeEdge("com.acme.persistence.UserRepository", "com.acme.persistence.User", KnowledgeEdgeKind.DEPENDS_ON),),
    )
    return JavaWorkspaceService().build((
        WorkspaceGraphInput("api", "API", api),
        WorkspaceGraphInput("service", "Service", service),
        WorkspaceGraphInput("persistence", "Persistence", persistence),
    ))


def test_builds_workspace_with_projects_and_cross_project_edges():
    graph = workspace()
    assert [project.key for project in graph.projects] == ["api", "service", "persistence"]
    assert len(graph.cross_project_edges()) == 2


def test_finds_symbols_across_projects():
    graph = workspace()
    matches = graph.find("repository")
    assert {(item.project_key, item.key) for item in matches} == {
        ("persistence", "com.acme.persistence.UserRepository"),
    }


def test_finds_implementations_across_modules():
    graph = workspace()
    implementations = graph.implementations("com.acme.service.UserService")
    assert [item.key for item in implementations] == ["com.acme.service.DefaultUserService"]


def test_reports_rename_impact_across_projects():
    graph = workspace()
    impact = graph.rename_impact("persistence", "com.acme.persistence.User")
    assert [item.key for item in impact.direct_references] == ["com.acme.persistence.UserRepository"]
    assert "service" in impact.affected_projects
    assert "api" in impact.affected_projects


def test_traces_endpoint_to_entity_across_projects():
    graph = workspace()
    trace = graph.trace_endpoint_to_entities("api", "endpoint:users#get")
    assert [item.key for item in trace.entities] == ["com.acme.persistence.User"]
    assert trace.paths[0][0] == "endpoint:users#get"
    assert trace.paths[0][-1] == "com.acme.persistence.User"


def test_records_ambiguous_cross_project_symbol_targets():
    caller = JavaKnowledgeGraph(
        nodes=(type_node("com.acme.Caller"),),
        edges=(KnowledgeEdge("com.acme.Caller", "com.acme.Shared", KnowledgeEdgeKind.DEPENDS_ON),),
    )
    left = JavaKnowledgeGraph(nodes=(type_node("com.acme.Shared"),))
    right = JavaKnowledgeGraph(nodes=(type_node("com.acme.Shared"),))
    graph = JavaWorkspaceService().build((
        WorkspaceGraphInput("caller", "Caller", caller),
        WorkspaceGraphInput("left", "Left", left),
        WorkspaceGraphInput("right", "Right", right),
    ))
    assert any("workspace-ambiguous" in value for value in graph.unresolved)
