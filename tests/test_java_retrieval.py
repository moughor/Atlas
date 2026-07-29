from pathlib import Path

from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_retrieval import JavaKnowledgeRetriever, JavaLlmContextBuilder, JavaRetrievalService


def graph() -> JavaKnowledgeGraph:
    return JavaKnowledgeGraph(
        nodes=(
            KnowledgeNode("com.example.UserController", KnowledgeNodeKind.TYPE, "UserController", "com.example.UserController", Path("UserController.java"), ("java:class", "spring:rest_controller")),
            KnowledgeNode("com.example.UserService", KnowledgeNodeKind.TYPE, "UserService", "com.example.UserService", Path("UserService.java"), ("java:class", "spring:service")),
            KnowledgeNode("com.example.UserRepository", KnowledgeNodeKind.TYPE, "UserRepository", "com.example.UserRepository", Path("UserRepository.java"), ("java:interface", "spring:repository")),
            KnowledgeNode("endpoint:com.example.UserController#get:0", KnowledgeNodeKind.ENDPOINT, "GET /users/{id}", metadata=(("owner", "com.example.UserController"),)),
        ),
        edges=(
            KnowledgeEdge("com.example.UserController", "com.example.UserService", KnowledgeEdgeKind.INJECTS, "service"),
            KnowledgeEdge("com.example.UserService", "com.example.UserRepository", KnowledgeEdgeKind.INJECTS, "repository"),
            KnowledgeEdge("com.example.UserController", "endpoint:com.example.UserController#get:0", KnowledgeEdgeKind.EXPOSES, "get"),
        ),
        unresolved=("com.example.UserService#audit:AuditClient:unresolved-injection",),
    )


def test_exact_type_name_ranks_first() -> None:
    result = JavaKnowledgeRetriever().retrieve(graph(), "UserService")
    assert result.hits[0].node.key == "com.example.UserService"
    assert "exact-name" in result.hits[0].reasons


def test_facet_query_finds_repository() -> None:
    result = JavaKnowledgeRetriever().retrieve(graph(), "repository")
    assert result.hits[0].node.key == "com.example.UserRepository"


def test_retrieval_expands_related_evidence() -> None:
    result = JavaKnowledgeRetriever().retrieve(graph(), "UserController", limit=1)
    assert {node.key for node in result.related_nodes} == {
        "com.example.UserService",
        "endpoint:com.example.UserController#get:0",
    }
    assert len(result.evidence_edges) == 2


def test_retrieval_includes_owner_unresolved_references() -> None:
    result = JavaKnowledgeRetriever().retrieve(graph(), "UserService", limit=1)
    assert result.unresolved == ("com.example.UserService#audit:AuditClient:unresolved-injection",)


def test_context_contains_traceable_symbols_and_relationships() -> None:
    result = JavaKnowledgeRetriever().retrieve(graph(), "UserController", limit=1)
    context = JavaLlmContextBuilder().build(result)
    assert "[S1] type: com.example.UserController" in context.text
    assert "--injects--> com.example.UserService" in context.text
    assert "source=UserController.java" in context.text


def test_context_truncation_is_deterministic() -> None:
    context = JavaRetrievalService().context(graph(), "User", max_characters=120)
    assert len(context.text) <= 120
    assert context.text.endswith("...[context truncated deterministically]")
