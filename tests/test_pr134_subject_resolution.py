from __future__ import annotations

from copy import deepcopy
from urllib.parse import quote

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import KnowledgeKind
from moughorai.repository_report.safety import (
    contains_absolute_path,
    contains_absolute_path_text,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    ResolutionStatus,
    SubjectMatchBasis,
    SubjectQuery,
    SubjectResolution,
)


def _node(
    node_id: str,
    kind: str,
    qualified_name: str,
    *,
    project: str | None = None,
    language: str = "unknown",
    metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": node_id,
        "kind": kind,
        "qualified_name": qualified_name,
        "project_id": project,
        "language": language,
    }
    if metadata:
        value["metadata"] = metadata
    return value


def _context(
    nodes: list[dict[str, object]],
    *,
    edges: list[dict[str, object]] | None = None,
    symbols: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "semantic_graph": {
            "schema_version": 1,
            "nodes": nodes,
            "edges": edges or [],
        },
        "symbols": symbols or [],
    }


def _snapshot(context: dict[str, object]) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr134-subject-resolution",
        analyzer_version="test",
    )


def test_resolution_order_and_structured_constraints() -> None:
    context = _context(
        [
            _node(
                "type:service",
                "type",
                "demo.Service",
                project="api",
                language="java",
            ),
            _node(
                "type:other-service",
                "type",
                "other.Service",
                project="web",
                language="typescript",
            ),
        ],
        symbols=[
            {
                "id": "type:service",
                "name": "Service",
                "qualified_name": "demo.Service",
                "source": "./src/main/java/demo/Service.java",
            },
            {
                "id": "type:other-service",
                "name": "Service",
                "qualified_name": "other.Service",
                "source": "src/web/Service.ts",
            },
        ],
    )
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(context))

    by_id = resolver.resolve(SubjectQuery("type:service"))
    assert by_id.status is ResolutionStatus.RESOLVED
    assert by_id.match_basis is SubjectMatchBasis.CANONICAL_ID
    assert by_id.subject is not None
    assert by_id.subject.canonical_id == "type:service"
    assert by_id.subject.name == "Service"
    assert by_id.subject.path == "src/main/java/demo/Service.java"

    by_qualified = resolver.resolve(
        SubjectQuery(
            "demo.Service",
            kind=KnowledgeKind.TYPE,
            project="API",
            language="JAVA",
            path=r"src\main\java\demo\Service.java",
        )
    )
    assert by_qualified.status is ResolutionStatus.RESOLVED
    assert by_qualified.match_basis is SubjectMatchBasis.QUALIFIED_NAME

    by_normalized_name = resolver.resolve(
        SubjectQuery(" service ", project="web", language="typescript")
    )
    assert by_normalized_name.status is ResolutionStatus.RESOLVED
    assert by_normalized_name.match_basis is SubjectMatchBasis.NORMALIZED_NAME
    assert by_normalized_name.subject is not None
    assert by_normalized_name.subject.canonical_id == "type:other-service"

    mismatch = resolver.resolve(
        SubjectQuery("type:service", project="web")
    )
    assert mismatch.status is ResolutionStatus.NOT_FOUND
    assert "does not satisfy" in mismatch.limitations[0]
    assert SubjectResolution.from_dict(by_id.to_dict()).to_dict() == by_id.to_dict()


def test_overloads_are_bounded_deterministic_ambiguities() -> None:
    nodes = [
        _node("method:string", "method", "demo.Service#run(java.lang.String)", project="api", language="java"),
        _node("method:none", "method", "demo.Service#run()", project="api", language="java"),
    ]
    symbols = [
        {"id": "method:string", "name": "run", "qualified_name": "demo.Service#run(java.lang.String)"},
        {"id": "method:none", "name": "run", "qualified_name": "demo.Service#run()"},
    ]
    first = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(nodes, symbols=symbols)), maximum_candidates=1,
    ).resolve(SubjectQuery("RUN", kind=KnowledgeKind.METHOD, project="api"))
    second = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(list(reversed(nodes)), symbols=list(reversed(symbols)))),
        maximum_candidates=1,
    ).resolve(SubjectQuery("RUN", kind=KnowledgeKind.METHOD, project="api"))

    assert first.status is ResolutionStatus.AMBIGUOUS
    assert first.total_candidate_count == 2
    assert len(first.candidates) == 1
    assert first.omitted_candidate_count == 1
    assert first.to_json() == second.to_json()

    exact_signature = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(nodes, symbols=symbols))
    ).resolve(SubjectQuery("demo.Service#run()"))
    assert exact_signature.status is ResolutionStatus.RESOLVED
    assert exact_signature.subject is not None
    assert exact_signature.subject.canonical_id == "method:none"


def test_resolution_payload_canonicalizes_candidates_and_rejects_loose_counts() -> None:
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(_context([
        _node("project:api", "project", "api"),
        _node("module:api", "module", "api", project="api"),
    ])))
    result = resolver.resolve(SubjectQuery("api"))
    payload = result.to_dict()
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidates.reverse()

    assert SubjectResolution.from_dict(payload).to_dict() == result.to_dict()

    for field in (
        "total_candidate_count",
        "included_candidate_count",
        "omitted_candidate_count",
    ):
        for invalid in (True, 2.0, "2"):
            malformed = deepcopy(payload)
            malformed[field] = invalid
            with pytest.raises(ValueError, match="integer"):
                SubjectResolution.from_dict(malformed)

    duplicate = deepcopy(payload)
    duplicate_candidates = duplicate["candidates"]
    assert isinstance(duplicate_candidates, list)
    duplicate_candidates.append(deepcopy(duplicate_candidates[0]))
    duplicate["included_candidate_count"] = 3
    duplicate["total_candidate_count"] = 3
    with pytest.raises(ValueError, match="unique"):
        SubjectResolution.from_dict(duplicate)


def test_project_and_module_names_require_kind_disambiguation() -> None:
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(_context([
        _node("project:api", "project", "api"),
        _node("module:api", "module", "api", project="api"),
    ])))

    unresolved = resolver.resolve(SubjectQuery("api"))
    assert unresolved.status is ResolutionStatus.AMBIGUOUS
    assert [item.kind for item in unresolved.candidates] == [
        KnowledgeKind.PROJECT,
        KnowledgeKind.MODULE,
    ]

    project = resolver.resolve(SubjectQuery("api", kind=KnowledgeKind.PROJECT))
    assert project.status is ResolutionStatus.RESOLVED
    assert project.subject is not None
    assert project.subject.canonical_id == "project:api"


def test_dependency_and_framework_project_scopes_come_from_canonical_edges() -> None:
    nodes = [
        _node("project:api", "project", "api"),
        _node("project:docs", "project", "docs"),
        _node("dependency:maven:lib:1:compile", "dependency", "org.demo:lib"),
        _node("dependency:maven:lib:2:test", "dependency", "org.demo:lib"),
        _node("framework:Spring%20Framework", "framework", "Spring Framework"),
    ]
    edges = [
        {
            "source": "project:api",
            "target": "dependency:maven:lib:1:compile",
            "kind": "depends_on",
            "evidence": ["declared_dependency.source:api/pom.xml"],
        },
        {
            "source": "project:docs",
            "target": "dependency:maven:lib:2:test",
            "kind": "depends_on",
            "evidence": ["declared_dependency.source:docs/pom.xml"],
        },
        {
            "source": "project:docs",
            "target": "framework:Spring%20Framework",
            "kind": "depends_on",
            "evidence": ["test-or-sample:org.springframework:spring-context"],
        },
    ]
    resolver = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(nodes, edges=edges))
    )

    dependency = resolver.resolve(
        SubjectQuery("org.demo:lib", kind=KnowledgeKind.DEPENDENCY, project="api")
    )
    assert dependency.status is ResolutionStatus.RESOLVED
    assert dependency.subject is not None
    assert dependency.subject.project == "api"
    assert dependency.subject.project_scopes == ("api",)
    assert dependency.subject.path == "api/pom.xml"

    framework = resolver.resolve(
        SubjectQuery("Spring Framework", project="docs")
    )
    assert framework.status is ResolutionStatus.RESOLVED
    assert framework.subject is not None
    assert framework.subject.project_scopes == ("docs",)

    wrong_scope = resolver.resolve(
        SubjectQuery("Spring Framework", project="api")
    )
    assert wrong_scope.status is ResolutionStatus.NOT_FOUND


def test_build_system_is_not_promoted_to_a_build_target() -> None:
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(_context([
        _node("build_system:api:Maven", "build_system", "Maven", project="api"),
    ])))

    system = resolver.resolve(
        SubjectQuery("Maven", kind=KnowledgeKind.BUILD_SYSTEM, project="api")
    )
    assert system.status is ResolutionStatus.RESOLVED

    target = resolver.resolve(
        SubjectQuery("Maven", kind=KnowledgeKind.BUILD_TARGET, project="api")
    )
    assert target.status is ResolutionStatus.NOT_FOUND
    assert any("build target" in item.casefold() for item in target.limitations)


def test_safe_relative_paths_are_constraints_and_absolute_paths_are_excluded() -> None:
    context = _context(
        [_node("type:safe", "type", "demo.Safe", project="api", language="java")],
        symbols=[{
            "id": "type:safe",
            "name": "Safe",
            "qualified_name": "demo.Safe",
            "source": "C:/Users/alice/private/Safe.java",
        }],
    )
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(context))
    result = resolver.resolve(SubjectQuery("demo.Safe"))

    assert result.status is ResolutionStatus.RESOLVED
    assert result.subject is not None
    assert result.subject.path is None
    assert not contains_absolute_path(result.to_dict())
    with pytest.raises(ValueError, match="workspace-relative"):
        SubjectQuery("demo.Safe", path="C:/Users/alice/private/Safe.java")


def test_conflicting_symbol_metadata_is_ignored_deterministically() -> None:
    nodes = [_node("type:service", "type", "demo.Service", project="api")]
    symbols = [
        {
            "id": "type:service",
            "name": "First",
            "source": "src/first/Service.java",
        },
        {
            "id": "type:service",
            "name": "Second",
            "source": "src/second/Service.java",
        },
    ]
    first = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(nodes, symbols=symbols))
    ).resolve(SubjectQuery("demo.Service"))
    second = CanonicalSubjectResolver.from_snapshot(
        _snapshot(_context(nodes, symbols=list(reversed(symbols))))
    ).resolve(SubjectQuery("demo.Service"))

    assert first.to_json() == second.to_json()
    assert first.subject is not None
    assert first.subject.name == "Service"
    assert first.subject.path is None
    assert any("conflicting GlobalSymbol metadata" in item for item in first.limitations)


def test_four_layer_url_encoded_absolute_path_is_rejected() -> None:
    encoded = "C:/Users/alice/private/Service.java"
    for _ in range(4):
        encoded = quote(encoded, safe="")

    assert contains_absolute_path_text(encoded)
    with pytest.raises(ValueError, match="absolute paths"):
        SubjectQuery(encoded)


def test_deeply_url_encoded_absolute_path_is_rejected() -> None:
    encoded = "C:/Users/alice/private/Service.java"
    for _ in range(12):
        encoded = quote(encoded, safe="")

    assert contains_absolute_path_text(encoded)

    with pytest.raises(ValueError, match="absolute path"):
        SubjectQuery(encoded)


@pytest.mark.parametrize(
    "value",
    (
        "workspace:/home/alice/private/repo",
        "workspace:%2Fhome%2Falice%2Fprivate%2Frepo",
    ),
)
def test_embedded_posix_absolute_path_is_rejected(value: str) -> None:
    assert contains_absolute_path_text(value)

    with pytest.raises(ValueError, match="absolute path"):
        SubjectQuery(value)


def test_repository_root_identity_is_safe_in_serialized_resolution() -> None:
    encoded = "repository:C%3A%2FUsers%2Falice%2Fprivate%2Frepo"
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot(_context([
        _node(encoded, "repository", "C:/Users/alice/private/repo"),
    ])))

    result = resolver.resolve(
        SubjectQuery("repository", kind=KnowledgeKind.REPOSITORY)
    )
    serialized = result.to_json()
    assert result.status is ResolutionStatus.RESOLVED
    assert result.subject is not None
    assert result.subject.canonical_id == "repository"
    assert result.subject.name == "repository"
    assert result.subject.qualified_name == "repository"
    assert "C:/Users" not in serialized
    assert "C%3A%2FUsers" not in serialized
    assert not contains_absolute_path(result.to_dict())
    with pytest.raises(ValueError, match="absolute paths"):
        SubjectQuery(encoded)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda value: value.pop("schema_version"), "schema is unavailable"),
        (lambda value: value["nodes"].append(value["nodes"][0]), "duplicate"),
        (lambda value: value["nodes"].append("invalid"), "malformed"),
    ],
)
def test_malformed_canonical_graphs_degrade_to_unavailable(mutator, expected: str) -> None:
    context = _context([_node("type:service", "type", "demo.Service")])
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    mutator(graph)

    result = CanonicalSubjectResolver.from_snapshot(_snapshot(context)).resolve(
        SubjectQuery("demo.Service")
    )
    assert result.status is ResolutionStatus.UNAVAILABLE
    assert expected in " ".join(result.limitations).casefold()


def test_old_snapshot_and_dangling_relationships_degrade_explicitly() -> None:
    old = CanonicalSubjectResolver.from_snapshot(_snapshot({
        "schema_version": 1,
        "symbols": [{"id": "type:service", "qualified_name": "demo.Service"}],
    })).resolve(SubjectQuery("demo.Service"))
    assert old.status is ResolutionStatus.UNAVAILABLE
    assert "unavailable" in " ".join(old.limitations).casefold()

    context = _context(
        [_node("type:service", "type", "demo.Service")],
        edges=[{
            "source": "type:service",
            "target": "type:missing",
            "kind": "depends_on",
            "evidence": ["canonical:test"],
        }],
    )
    partial = CanonicalSubjectResolver.from_snapshot(_snapshot(context)).resolve(
        SubjectQuery("demo.Service")
    )
    assert partial.status is ResolutionStatus.RESOLVED
    assert any("dangling" in item for item in partial.limitations)
