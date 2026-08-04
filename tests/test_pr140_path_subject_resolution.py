from __future__ import annotations

from copy import deepcopy

import pytest

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    PathSubjectCandidates,
    SubjectMatchBasis,
)


def _node(
    node_id: str,
    kind: KnowledgeKind,
    qualified_name: str,
    *,
    project: str | None = None,
    language: str = "unknown",
    path: str | None = None,
) -> KnowledgeNode:
    metadata = (("path", path),) if path is not None else ()
    return KnowledgeNode(
        node_id,
        kind,
        qualified_name,
        metadata=metadata,
        qualified_name=qualified_name,
        project_id=project,
        language=language,
    )


def _resolver(
    nodes: list[KnowledgeNode],
    *,
    edges: list[KnowledgeEdge] | None = None,
    symbols: list[dict[str, object]] | None = None,
) -> CanonicalSubjectResolver:
    return CanonicalSubjectResolver.from_graph(
        KnowledgeGraph(nodes, edges or ()),
        symbols=symbols or (),
    )


def test_exact_path_candidates_are_normalized_bounded_and_deterministic() -> None:
    nodes = [
        _node("project:root", KnowledgeKind.PROJECT, "root", path="."),
        _node(
            "type:z", KnowledgeKind.TYPE, "demo.Z", project="root", language="java"
        ),
        _node(
            "method:b",
            KnowledgeKind.METHOD,
            "demo.A#run()",
            project="root",
            language="java",
        ),
        _node(
            "type:a", KnowledgeKind.TYPE, "demo.A", project="root", language="java"
        ),
    ]
    symbols = [
        {
            "id": node.id,
            "name": node.qualified_name.rsplit(".", 1)[-1],
            "source": "src/main/java/demo/A.java",
        }
        for node in nodes
        if node.kind is not KnowledgeKind.PROJECT
    ]

    first = _resolver(nodes, symbols=symbols).candidates_for_path(
        r".\src\main\java\demo\A.java",
        maximum_candidates=2,
    )
    second = _resolver(
        list(reversed(nodes)), symbols=list(reversed(symbols)),
    ).candidates_for_path("src/main/java/demo/A.java", maximum_candidates=2)

    assert first.path == "src/main/java/demo/A.java"
    assert [item.canonical_id for item in first.candidates] == [
        "method:b",
        "type:a",
    ]
    assert all(
        item.match_basis is SubjectMatchBasis.PATH for item in first.candidates
    )
    assert first.total_candidate_count == 3
    assert first.omitted_candidate_count == 1
    assert first.project_fallback is False
    assert {
        reference
        for item in first.candidate_evidence
        for reference in item.source_refs
    } == {"global_symbol.metadata:source"}
    assert "deterministically omitted" in " ".join(first.limitations)
    assert first.to_dict() == second.to_dict()
    assert not contains_absolute_path(first.to_dict())


def test_declared_dependency_source_is_an_exact_canonical_path() -> None:
    project = _node("project:api", KnowledgeKind.PROJECT, "api", path="api")
    dependency = _node(
        "dependency:maven:demo:lib:1:compile",
        KnowledgeKind.DEPENDENCY,
        "demo:lib",
    )
    edge = KnowledgeEdge(
        project.id,
        dependency.id,
        KnowledgeRelation.DEPENDS_ON,
        ("declared_dependency.source:api/pom.xml",),
    )

    result = _resolver([dependency, project], edges=[edge]).candidates_for_path(
        "api/pom.xml"
    )

    assert result.project_fallback is False
    assert result.total_candidate_count == 1
    assert result.candidates[0].canonical_id == dependency.id
    assert result.candidates[0].project == "api"
    assert result.candidate_evidence[0].source_refs == (
        "declared_dependency.source:api/pom.xml",
    )


def test_graph_node_path_has_explicit_resolver_provenance() -> None:
    symbol = _node(
        "type:metadata",
        KnowledgeKind.TYPE,
        "demo.Metadata",
        language="java",
        path="src/Metadata.java",
    )

    result = _resolver([symbol]).candidates_for_path("src/Metadata.java")

    assert result.candidate_evidence[0].source_refs == (
        "semantic_graph.node.metadata:path",
    )


def test_deepest_containing_project_is_an_explicit_structural_fallback() -> None:
    root = _node("project:root", KnowledgeKind.PROJECT, "root", path=".")
    api = _node("project:api", KnowledgeKind.PROJECT, "api", path="modules/api")
    api_variant = _node(
        "project:api-variant",
        KnowledgeKind.PROJECT,
        "api-variant",
        path="modules/api",
    )
    similarly_named = _node(
        "project:api-tools",
        KnowledgeKind.PROJECT,
        "api-tools",
        path="modules/api-tools",
    )
    resolver = _resolver([similarly_named, api_variant, root, api])

    nested = resolver.candidates_for_path(
        "modules/api/src/demo/Service.java", maximum_candidates=1
    )
    boundary = resolver.candidates_for_path("modules/api-tools-extra/README.md")

    assert nested.project_fallback is True
    assert [item.canonical_id for item in nested.candidates] == ["project:api"]
    assert nested.total_candidate_count == 2
    assert nested.omitted_candidate_count == 1
    assert nested.candidates[0].match_basis is SubjectMatchBasis.PATH
    assert nested.candidate_evidence[0].source_refs == (
        "canonical_subject_resolver:project_path_containment",
        "semantic_graph.node.metadata:path",
    )
    assert "does not identify a changed declaration" in " ".join(
        nested.limitations
    )
    assert boundary.project_fallback is True
    assert [item.canonical_id for item in boundary.candidates] == ["project:root"]


def test_path_lookup_never_uses_basename_suffix_or_fuzzy_inference() -> None:
    symbol = _node("type:foo", KnowledgeKind.TYPE, "demo.Foo", language="java")
    resolver = _resolver(
        [symbol],
        symbols=[
            {
                "id": symbol.id,
                "name": "Foo",
                "source": "module/src/main/java/demo/Foo.java",
            }
        ],
    )

    result = resolver.candidates_for_path("other/Foo.java")

    assert result.candidates == ()
    assert result.total_candidate_count == 0
    assert result.project_fallback is False
    assert "No exact canonical subject source" in " ".join(result.limitations)


def test_unavailable_graph_and_invalid_inputs_are_explicit() -> None:
    unavailable = CanonicalSubjectResolver(
        None,
        limitations=("Canonical PR129 graph is unavailable in this snapshot.",),
    ).candidates_for_path("src/Foo.java")

    assert unavailable.candidates == ()
    assert unavailable.graph_digest == "unavailable"
    assert "was not performed" in " ".join(unavailable.limitations)

    resolver = _resolver([
        _node("project:root", KnowledgeKind.PROJECT, "root", path=".")
    ])
    for invalid_path in ("", "../src/Foo.java", "C:/private/Foo.java"):
        with pytest.raises(ValueError, match="workspace-relative"):
            resolver.candidates_for_path(invalid_path)
    for invalid_limit in (True, 0, -1, 1.5, "2"):
        with pytest.raises(ValueError, match="positive integer"):
            resolver.candidates_for_path(
                "src/Foo.java",
                maximum_candidates=invalid_limit,  # type: ignore[arg-type]
            )


def test_path_candidate_serialization_is_exact_and_strict() -> None:
    symbol = _node("type:a", KnowledgeKind.TYPE, "demo.A", language="java")
    result = _resolver(
        [symbol],
        symbols=[{"id": symbol.id, "name": "A", "source": "src/A.java"}],
    ).candidates_for_path("src/A.java")
    payload = result.to_dict()

    assert PathSubjectCandidates.from_dict(payload).to_dict() == payload

    unexpected = deepcopy(payload)
    unexpected["unknown"] = "value"
    with pytest.raises(ValueError, match="unexpected unknown"):
        PathSubjectCandidates.from_dict(unexpected)

    missing = deepcopy(payload)
    del missing["graph_digest"]
    with pytest.raises(ValueError, match="missing graph_digest"):
        PathSubjectCandidates.from_dict(missing)

    malformed_candidates = deepcopy(payload)
    malformed_candidates["candidates"] = [
        payload["candidates"][0],  # type: ignore[index]
        "not-an-object",
    ]
    with pytest.raises(TypeError, match="sequence of objects"):
        PathSubjectCandidates.from_dict(malformed_candidates)

    inconsistent = deepcopy(payload)
    inconsistent["included_candidate_count"] = 2
    with pytest.raises(ValueError, match="included candidate count"):
        PathSubjectCandidates.from_dict(inconsistent)
