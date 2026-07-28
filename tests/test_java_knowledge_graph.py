from pathlib import Path

from moughorai.java_architecture.graph import JavaArchitectureGraph
from moughorai.java_architecture.models import ArchitectureEdge, ArchitectureEdgeKind, ArchitectureNode, UnresolvedArchitectureReference
from moughorai.java_jpa.models import JpaAnalysisReport, JpaEntity, JpaRelation, JpaRelationKind
from moughorai.java_knowledge import JavaKnowledgeGraphBuilder, KnowledgeEdgeKind, KnowledgeNodeKind
from moughorai.java_spring.models import InjectionKind, InjectionPoint, SpringAnalysisReport, SpringBean, SpringBeanKind, SpringEndpoint


def reports():
    nodes = (
        ArchitectureNode("com.app.UserController", "UserController", "class", "com.app", Path("UserController.java")),
        ArchitectureNode("com.app.UserService", "UserService", "class", "com.app", Path("UserService.java")),
        ArchitectureNode("com.app.UserRepository", "UserRepository", "interface", "com.app", Path("UserRepository.java")),
        ArchitectureNode("com.app.User", "User", "class", "com.app", Path("User.java")),
    )
    edges = (
        ArchitectureEdge("com.app.UserService", "com.app.UserRepository", ArchitectureEdgeKind.FIELD_TYPE, "repository", "UserRepository"),
        ArchitectureEdge("com.app.UserRepository", "com.app.User", ArchitectureEdgeKind.METHOD_RETURN, "find", "User"),
    )
    architecture = JavaArchitectureGraph(nodes, edges, (
        UnresolvedArchitectureReference("com.app.UserService", "field:clock", "Clock", "unresolved"),
    ))
    spring = SpringAnalysisReport(
        beans=(
            SpringBean("com.app.UserController", SpringBeanKind.REST_CONTROLLER, ("RestController",)),
            SpringBean("com.app.UserService", SpringBeanKind.SERVICE, ("Service",)),
            SpringBean("com.app.UserRepository", SpringBeanKind.REPOSITORY, ("Repository",)),
        ),
        injections=(
            InjectionPoint("com.app.UserController", "UserService", "com.app.UserService", InjectionKind.CONSTRUCTOR, "UserController"),
            InjectionPoint("com.app.UserService", "MissingClient", None, InjectionKind.FIELD, "client"),
        ),
        endpoints=(
            SpringEndpoint("com.app.UserController", "get", ("GET",), ("GetMapping",), ("/users/{id}",)),
        ),
    )
    jpa = JpaAnalysisReport(
        entities=(JpaEntity("com.app.User", "users", ("Entity",)),),
        relations=(JpaRelation("com.app.User", "manager", JpaRelationKind.MANY_TO_ONE, "User", "com.app.User", ("ManyToOne",)),),
    )
    return architecture, spring, jpa


def test_builder_merges_type_facets_and_metadata():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    service = graph.node("com.app.UserService")
    entity = graph.node("com.app.User")
    assert service is not None and "spring:service" in service.facets
    assert entity is not None and "jpa:entity" in entity.facets
    assert entity.metadata_value("table") == "users"


def test_builder_adds_injection_and_endpoint_edges():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    injections = graph.outgoing("com.app.UserController", KnowledgeEdgeKind.INJECTS)
    exposes = graph.outgoing("com.app.UserController", KnowledgeEdgeKind.EXPOSES)
    assert injections[0].target == "com.app.UserService"
    assert graph.node(exposes[0].target).kind is KnowledgeNodeKind.ENDPOINT


def test_graph_supports_dependency_and_reverse_queries():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    assert {node.qualified_name for node in graph.dependencies("com.app.UserController")} == {"com.app.UserService"}
    assert {node.qualified_name for node in graph.dependents("com.app.UserService")} == {"com.app.UserController"}
    assert {node.qualified_name for node in graph.transitive_dependents("com.app.User")} == {"com.app.UserRepository", "com.app.UserService", "com.app.UserController"}


def test_impact_report_combines_semantic_information():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    report = graph.impact("com.app.UserController")
    assert report.subject.display_name == "UserController"
    assert report.direct_dependencies[0].qualified_name == "com.app.UserService"
    assert report.endpoints[0].metadata_value("method") == "get"


def test_builder_keeps_unresolved_semantic_references():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    assert any("field:clock" in item for item in graph.unresolved)
    assert any("MissingClient" in item for item in graph.unresolved)


def test_find_searches_names_and_keys():
    graph = JavaKnowledgeGraphBuilder().build(*reports())
    assert graph.find("repository")[0].qualified_name == "com.app.UserRepository"
    assert graph.find("GET", KnowledgeNodeKind.ENDPOINT)[0].display_name.startswith("GET")
