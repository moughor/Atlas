from moughorai.java_baseline import JavaArchitectureBaselineJson, JavaArchitectureBaselineService, RegressionSeverity
from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_workspace import JavaWorkspaceService, WorkspaceGraphInput


def node(name: str, *facets: str, kind=KnowledgeNodeKind.TYPE) -> KnowledgeNode:
    return KnowledgeNode(name, kind, name.rsplit(".", 1)[-1], name, facets=facets)


def workspace(graph: JavaKnowledgeGraph):
    return JavaWorkspaceService().build((WorkspaceGraphInput("app", "App", graph),))


def test_identical_snapshot_has_no_regressions():
    graph = workspace(JavaKnowledgeGraph(nodes=(node("Service", "spring:service"),)))
    service = JavaArchitectureBaselineService()
    baseline = service.capture(graph)
    assert service.compare(baseline, graph).clean


def test_reports_new_dependency():
    original = workspace(JavaKnowledgeGraph(nodes=(node("A"), node("B"))))
    changed = workspace(JavaKnowledgeGraph(
        nodes=(node("A"), node("B")),
        edges=(KnowledgeEdge("A", "B", KnowledgeEdgeKind.DEPENDS_ON),),
    ))
    service = JavaArchitectureBaselineService()
    report = service.compare(service.capture(original), changed)
    item = report.by_category("dependency_added")[0]
    assert item.severity is RegressionSeverity.WARNING
    assert item.evidence[0] == "depends_on"


def test_reports_new_unresolved_reference_as_error():
    original = workspace(JavaKnowledgeGraph())
    changed = JavaWorkspaceService().build((WorkspaceGraphInput("app", "App", JavaKnowledgeGraph()),))
    changed = type(changed)(changed.projects, changed.nodes, changed.edges, ("MissingType",))
    service = JavaArchitectureBaselineService()
    report = service.compare(service.capture(original), changed)
    assert report.by_category("unresolved_added")[0].severity is RegressionSeverity.ERROR


def test_reports_new_policy_violation_with_original_severity():
    original = workspace(JavaKnowledgeGraph(nodes=(node("Controller", "spring:rest_controller"), node("Repository", "spring:repository"))))
    changed = workspace(JavaKnowledgeGraph(
        nodes=(node("Controller", "spring:rest_controller"), node("Repository", "spring:repository")),
        edges=(KnowledgeEdge("Controller", "Repository", KnowledgeEdgeKind.INJECTS),),
    ))
    service = JavaArchitectureBaselineService()
    report = service.compare(service.capture(original), changed)
    violation = report.by_category("violation_added")[0]
    assert violation.severity is RegressionSeverity.CRITICAL
    assert violation.evidence[0] == "controller_repository_shortcut"


def test_reports_resolved_dependency_separately():
    original = workspace(JavaKnowledgeGraph(
        nodes=(node("A"), node("B")),
        edges=(KnowledgeEdge("A", "B", KnowledgeEdgeKind.DEPENDS_ON),),
    ))
    changed = workspace(JavaKnowledgeGraph(nodes=(node("A"), node("B"))))
    service = JavaArchitectureBaselineService()
    report = service.compare(service.capture(original), changed)
    assert report.clean
    assert report.resolved[0].category == "dependency_removed"


def test_json_round_trip_is_stable():
    graph = workspace(JavaKnowledgeGraph(
        nodes=(node("Service", "spring:service"), node("Entity", "jpa:entity")),
        edges=(KnowledgeEdge("Service", "Entity", KnowledgeEdgeKind.DEPENDS_ON),),
    ))
    baseline = JavaArchitectureBaselineService().capture(graph)
    codec = JavaArchitectureBaselineJson()
    encoded = codec.dumps(baseline)
    assert codec.loads(encoded) == baseline
    assert codec.dumps(codec.loads(encoded)) == encoded
