import pytest

from moughorai.java_impact import JavaChangeImpactService, RiskLevel
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
    return JavaWorkspaceService().build((WorkspaceGraphInput("api", "API", api), WorkspaceGraphInput("core", "Core", core)))


def test_reports_direct_and_transitive_blast_radius():
    report = JavaChangeImpactService().analyze(workspace(), "core", "Entity")
    assert [node.key for node in report.direct_dependents] == ["Repository"]
    assert [node.key for node in report.transitive_dependents] == ["Service", "Controller"]
    assert report.blast_radius == 3


def test_reports_endpoint_exposure_and_projects():
    report = JavaChangeImpactService().analyze(workspace(), "core", "Entity")
    assert [node.key for node in report.exposed_endpoints] == ["endpoint:get"]
    assert report.affected_projects == ("core", "api")


def test_reports_downstream_persistence_reach():
    report = JavaChangeImpactService().analyze(workspace(), "api", "Controller")
    assert [node.key for node in report.reachable_entities] == ["Entity"]


def test_score_is_explainable_and_deterministic():
    service = JavaChangeImpactService()
    first = service.analyze(workspace(), "core", "Entity")
    second = service.analyze(workspace(), "core", "Entity")
    assert first.score == second.score
    assert first.level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert {factor.name for factor in first.factors} >= {"direct_dependents", "endpoint_exposure", "entity_subject"}


def test_detects_cycles_and_adds_cycle_factor():
    graph = JavaKnowledgeGraph(
        nodes=(node("A"), node("B")),
        edges=(KnowledgeEdge("A", "B", KnowledgeEdgeKind.DEPENDS_ON), KnowledgeEdge("B", "A", KnowledgeEdgeKind.DEPENDS_ON)),
    )
    ws = JavaWorkspaceService().build((WorkspaceGraphInput("p", "P", graph),))
    report = JavaChangeImpactService().analyze(ws, "p", "A")
    assert report.cycles
    assert "dependency_cycles" in {factor.name for factor in report.factors}


def test_rejects_unknown_subject():
    with pytest.raises(KeyError):
        JavaChangeImpactService().analyze(workspace(), "core", "Missing")
