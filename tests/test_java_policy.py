from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_policy import ArchitectureLayer, ArchitecturePolicy, JavaArchitecturePolicyService, PolicySeverity
from moughorai.java_workspace import JavaWorkspaceService, WorkspaceGraphInput


def node(name: str, *facets: str) -> KnowledgeNode:
    return KnowledgeNode(name, KnowledgeNodeKind.TYPE, name.rsplit(".", 1)[-1], name, facets=facets)


def workspace(*inputs: WorkspaceGraphInput):
    return JavaWorkspaceService().build(inputs)


def test_accepts_standard_controller_service_repository_entity_flow():
    graph = JavaKnowledgeGraph(
        nodes=(
            node("Controller", "spring:rest_controller"),
            node("Service", "spring:service"),
            node("Repository", "spring:repository"),
            node("Entity", "jpa:entity"),
        ),
        edges=(
            KnowledgeEdge("Controller", "Service", KnowledgeEdgeKind.INJECTS),
            KnowledgeEdge("Service", "Repository", KnowledgeEdgeKind.INJECTS),
            KnowledgeEdge("Repository", "Entity", KnowledgeEdgeKind.DEPENDS_ON),
        ),
    )
    report = JavaArchitecturePolicyService().evaluate(workspace(WorkspaceGraphInput("app", "App", graph)))
    assert report.compliant
    assert report.checked_edges == 3


def test_flags_controller_repository_shortcut_as_critical():
    graph = JavaKnowledgeGraph(
        nodes=(node("Controller", "spring:rest_controller"), node("Repository", "spring:repository")),
        edges=(KnowledgeEdge("Controller", "Repository", KnowledgeEdgeKind.INJECTS),),
    )
    report = JavaArchitecturePolicyService().evaluate(workspace(WorkspaceGraphInput("app", "App", graph)))
    violation = report.by_rule("controller_repository_shortcut")[0]
    assert violation.severity is PolicySeverity.CRITICAL
    assert violation.evidence == ("injects", "controller", "repository")


def test_flags_repository_to_service_layer_violation():
    graph = JavaKnowledgeGraph(
        nodes=(node("Repository", "spring:repository"), node("Service", "spring:service")),
        edges=(KnowledgeEdge("Repository", "Service", KnowledgeEdgeKind.DEPENDS_ON),),
    )
    report = JavaArchitecturePolicyService().evaluate(workspace(WorkspaceGraphInput("app", "App", graph)))
    assert report.by_rule("forbidden_layer_dependency")[0].message == "repository must not depend on service"


def test_enforces_forbidden_cross_project_dependency():
    left = JavaKnowledgeGraph(
        nodes=(node("Api", "spring:service"),),
        edges=(KnowledgeEdge("Api", "Storage", KnowledgeEdgeKind.DEPENDS_ON),),
    )
    right = JavaKnowledgeGraph(nodes=(node("Storage", "spring:repository"),))
    graph = workspace(WorkspaceGraphInput("api", "API", left), WorkspaceGraphInput("data", "Data", right))
    policy = ArchitecturePolicy(forbidden_project_dependencies=(("api", "data"),))
    report = JavaArchitecturePolicyService().evaluate(graph, policy)
    assert report.by_rule("forbidden_project_dependency")[0].target_project == "data"


def test_detects_cross_project_dependency_cycle_once():
    left = JavaKnowledgeGraph(nodes=(node("A"),), edges=(KnowledgeEdge("A", "B", KnowledgeEdgeKind.DEPENDS_ON),))
    right = JavaKnowledgeGraph(nodes=(node("B"),), edges=(KnowledgeEdge("B", "A", KnowledgeEdgeKind.DEPENDS_ON),))
    graph = workspace(WorkspaceGraphInput("left", "Left", left), WorkspaceGraphInput("right", "Right", right))
    report = JavaArchitecturePolicyService().evaluate(graph)
    cycles = report.by_rule("project_dependency_cycle")
    assert len(cycles) == 1
    assert cycles[0].evidence == ("left", "right", "left")


def test_can_disable_shortcut_and_cycle_rules():
    graph = JavaKnowledgeGraph(
        nodes=(node("Controller", "spring:rest_controller"), node("Repository", "spring:repository")),
        edges=(KnowledgeEdge("Controller", "Repository", KnowledgeEdgeKind.INJECTS),),
    )
    policy = ArchitecturePolicy(
        allowed_layer_dependencies=((ArchitectureLayer.CONTROLLER, ArchitectureLayer.REPOSITORY),),
        detect_controller_repository_shortcuts=False,
        detect_project_cycles=False,
    )
    report = JavaArchitecturePolicyService().evaluate(workspace(WorkspaceGraphInput("app", "App", graph)), policy)
    assert report.compliant
