from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_context import AnalyzerRegistry
from moughorai.ai_context.persistence import (
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.dependency_intelligence import DeclaredDependency
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_summary.models import ProjectSummary, RepositorySummary
from moughorai.workspace import Project, Workspace


def _context() -> dict[str, object]:
    return {
        "workspace": {
            "root": "C:/demo",
            "projects": [{"name": "api", "path": "api"}],
        },
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{
                "name": "api",
                "path": "api",
                "build_systems": ["Gradle"],
            }],
            "module_hierarchy": [{"project": "api", "parent": None}],
            "frameworks": ["Spring Framework"],
            "framework_evidence": [{
                "framework": "Spring Framework",
                "project": "api",
                "scope": "project-local",
                "reference": "org.springframework:spring-context",
            }],
        },
        "dependencies": [{
            "ecosystem": "maven",
            "name": "org.example:library",
            "version": "1.0",
            "scope": "compile",
            "source": "api/build.gradle",
        }],
        "semantic_graph": {
            "nodes": [
                {
                    "id": "package:demo",
                    "kind": "package",
                    "qualified_name": "demo",
                    "project_id": "api",
                    "language": "java",
                },
                {
                    "id": "type:service",
                    "kind": "type",
                    "qualified_name": "demo.Service",
                    "project_id": "api",
                    "language": "java",
                },
                {
                    "id": "type:base",
                    "kind": "type",
                    "qualified_name": "demo.Base",
                    "project_id": "api",
                    "language": "java",
                },
                {
                    "id": "method:run",
                    "kind": "method",
                    "qualified_name": "demo.Service#run()",
                    "project_id": "api",
                    "language": "java",
                },
                {
                    "id": "field:client",
                    "kind": "field",
                    "qualified_name": "demo.Service.client",
                    "project_id": "api",
                    "language": "java",
                },
            ],
            "edges": [
                {"source": "type:service", "target": "package:demo", "kind": "member_of"},
                {"source": "type:service", "target": "type:base", "kind": "extends"},
                {"source": "type:service", "target": "type:base", "kind": "imports"},
                {"source": "field:client", "target": "type:service", "kind": "composition"},
                {"source": "method:run", "target": "type:base", "kind": "calls"},
                {"source": "method:run", "target": "type:base", "kind": "overrides"},
            ],
        },
    }


def test_unified_graph_contains_all_pr129_node_kinds() -> None:
    graph = KnowledgeGraphBuilder().build_context(_context())

    assert {
        KnowledgeKind.REPOSITORY,
        KnowledgeKind.WORKSPACE,
        KnowledgeKind.PROJECT,
        KnowledgeKind.PACKAGE,
        KnowledgeKind.MODULE,
        KnowledgeKind.TYPE,
        KnowledgeKind.METHOD,
        KnowledgeKind.FIELD,
        KnowledgeKind.DEPENDENCY,
        KnowledgeKind.FRAMEWORK,
        KnowledgeKind.BUILD_SYSTEM,
    } <= {node.kind for node in graph.nodes}
    assert graph.find("Spring Framework")[0].kind is KnowledgeKind.FRAMEWORK
    assert graph.by_kind(KnowledgeKind.DEPENDENCY)[0].name == "org.example:library"


def test_unified_graph_contains_queryable_pr129_relations() -> None:
    graph = KnowledgeGraphBuilder().build_context(_context())
    relations = {edge.relation for edge in graph.edges}

    assert {
        KnowledgeRelation.IMPORTS,
        KnowledgeRelation.INHERITS,
        KnowledgeRelation.COMPOSES,
        KnowledgeRelation.CALLS,
        KnowledgeRelation.OVERRIDES,
        KnowledgeRelation.DEPENDS_ON,
        KnowledgeRelation.OWNS,
    } <= relations
    assert graph.outgoing("type:service", KnowledgeRelation.IMPORTS)
    assert graph.incoming("type:base", KnowledgeRelation.CALLS)
    assert {node.id for node in graph.neighborhood("type:service")} >= {
        "type:service",
        "type:base",
        "package:demo",
    }


def test_unified_graph_serialization_is_deterministic_and_pr125_compatible() -> None:
    first = KnowledgeGraphBuilder().build_context(_context()).to_dict()
    second = KnowledgeGraphBuilder().build_context(_context()).to_dict()

    assert first == second
    service = next(node for node in first["nodes"] if node["id"] == "type:service")
    assert service["qualified_name"] == "demo.Service"
    assert service["project_id"] == "api"
    assert service["language"] == "java"
    assert any(edge["kind"] == "imports" for edge in first["edges"])
    restored = KnowledgeGraph.from_dict(first)
    assert restored.outgoing("type:service", KnowledgeRelation.IMPORTS)
    assert restored.get("type:service").symbol_id is not None
    assert restored.to_dict() == first


def test_serialized_graph_digest_preserves_canonical_evidence_order() -> None:
    graph = KnowledgeGraph(
        (
            KnowledgeNode("project:demo", KnowledgeKind.PROJECT, "demo"),
            KnowledgeNode("type:demo", KnowledgeKind.TYPE, "demo.Type"),
        ),
        (
            KnowledgeEdge(
                "project:demo",
                "type:demo",
                KnowledgeRelation.OWNS,
                ("semantic_graph.project_id:z", "semantic_graph.project_id:a"),
            ),
        ),
    )
    payload = graph.to_dict()

    assert KnowledgeGraph.stable_payload_digest(payload) == graph.stable_digest()

    evidence = payload["edges"][0]["evidence"]
    assert isinstance(evidence, list)
    evidence.reverse()
    assert KnowledgeGraph.stable_payload_digest(payload) != graph.stable_digest()

    payload["schema_version"] = True
    with pytest.raises(ValueError, match="schema"):
        KnowledgeGraph.stable_payload_digest(payload)

    payload = graph.to_dict()
    payload["nodes"] = tuple(payload["nodes"])
    with pytest.raises(TypeError, match="nodes and edges"):
        KnowledgeGraph.stable_payload_digest(payload)


def test_workspace_context_publishes_enriched_source_free_graph(tmp_path: Path) -> None:
    project = Project("api", tmp_path / "api")
    project.path.mkdir()
    workspace = Workspace(tmp_path, (project,))
    symbol = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Service",
        "demo.Service",
        project_id="api",
        source=project.path / "Service.java",
        metadata={"language": "java"},
    )
    project_summary = ProjectSummary(
        "api", "api", 1, 10, (("Java", 1),), ("Gradle",), (),
        ("Service.java",), 1, 0, 0, 1,
    )
    summary = RepositorySummary(
        tmp_path,
        (project_summary,),
        (("Java", 1),),
        ("Gradle",),
        (),
        ("api:Service.java",),
        (("api", None),),
        1,
        0,
        0,
        (("maven", 1),),
    )
    dependency = DeclaredDependency(
        "maven",
        "org.example:library",
        "1.0",
        "compile",
        project.path / "build.gradle",
    )

    context = WorkspaceContextBuilder().build(
        workspace,
        symbols=(symbol,),
        declared_dependencies=(dependency,),
        repository_summary=summary,
    ).to_dict()
    graph = context["semantic_graph"]

    assert graph["schema_version"] == 1
    assert {node["kind"] for node in graph["nodes"]} >= {
        "repository", "workspace", "project", "module", "type",
        "dependency", "build_system",
    }
    assert all("class Service" not in str(node) for node in graph["nodes"])


def test_java_frontend_populates_resolved_inheritance_and_explicit_override(
    tmp_path: Path,
) -> None:
    (tmp_path / "Base.java").write_text(
        "package demo; class Base { void run() {} }",
        encoding="utf-8",
    )
    (tmp_path / "Child.java").write_text(
        "package demo; class Child extends Base { @Override void run() {} }",
        encoding="utf-8",
    )
    project = Project("java-app", tmp_path)
    document = AnalyzerRegistry()(project, {})
    restored = decode_analysis_result(encode_analysis_result(document))
    context = WorkspaceContextBuilder().build(
        Workspace(tmp_path, (project,)),
        symbols=restored.get_artifact("global_symbols"),
    ).to_dict()
    graph = KnowledgeGraph.from_dict(context["semantic_graph"])
    by_name = {
        node.name: node.id
        for node in graph.nodes
        if node.kind in {KnowledgeKind.TYPE, KnowledgeKind.METHOD}
    }

    inheritance = graph.outgoing(
        by_name["demo.Child"],
        KnowledgeRelation.INHERITS,
    )
    overrides = graph.outgoing(
        by_name["demo.Child#run()"],
        KnowledgeRelation.OVERRIDES,
    )
    assert inheritance[0].target == by_name["demo.Base"]
    assert inheritance[0].evidence == (
        "global_symbol.metadata:inherits:demo.Base",
    )
    assert overrides[0].target == by_name["demo.Base#run()"]
    assert overrides[0].evidence == (
        "global_symbol.metadata:overrides:demo.Base#run()",
    )
    assert not graph.by_kind(KnowledgeKind.BUILD_TARGET)


def test_workspace_project_dependencies_are_canonical_edges(tmp_path: Path) -> None:
    core = Project("core", tmp_path / "core")
    api = Project("api", tmp_path / "api", dependencies=("core",))
    core.path.mkdir()
    api.path.mkdir()

    context = WorkspaceContextBuilder().build(
        Workspace(tmp_path, (api, core)),
    ).to_dict()
    graph = KnowledgeGraph.from_dict(context["semantic_graph"])

    edge = graph.outgoing(
        "project:api",
        KnowledgeRelation.DEPENDS_ON,
    )[0]
    assert edge.target == "project:core"
    assert edge.evidence == ("workspace.projects:api:dependencies:core",)


def test_python_frontend_populates_only_resolved_internal_inheritance(
    tmp_path: Path,
) -> None:
    (tmp_path / "base.py").write_text(
        "class Base:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "child.py").write_text(
        "from base import Base\n\nclass Child(Base):\n    pass\n",
        encoding="utf-8",
    )
    project = Project("python-app", tmp_path)
    document = AnalyzerRegistry()(project, {})
    context = WorkspaceContextBuilder().build(
        Workspace(tmp_path, (project,)),
        symbols=document.get_artifact("global_symbols"),
    ).to_dict()
    graph = KnowledgeGraph.from_dict(context["semantic_graph"])
    by_name = {node.name: node.id for node in graph.by_kind(KnowledgeKind.TYPE)}

    edge = graph.outgoing(
        by_name["child.Child"],
        KnowledgeRelation.INHERITS,
    )[0]
    assert edge.target == by_name["base.Base"]
    assert edge.evidence == ("global_symbol.metadata:bases:Base",)


def test_dependency_identity_preserves_version_and_scope() -> None:
    context = _context()
    context["dependencies"] = [
        {
            "ecosystem": "maven",
            "name": "org.example:library",
            "version": "1.0",
            "scope": "compile",
            "source": "api/build.gradle",
        },
        {
            "ecosystem": "maven",
            "name": "org.example:library",
            "version": "2.0",
            "scope": "runtime",
            "source": "api/build.gradle",
        },
    ]

    graph = KnowledgeGraphBuilder().build_context(context)
    dependencies = graph.by_kind(KnowledgeKind.DEPENDENCY)

    assert len(dependencies) == 2
    assert len({node.id for node in dependencies}) == 2
    assert {
        (dict(node.metadata)["version"], dict(node.metadata)["scope"])
        for node in dependencies
    } == {("1.0", "compile"), ("2.0", "runtime")}


def test_bounded_graph_queries_are_deterministic_and_report_exact_counts() -> None:
    center = KnowledgeNode("type:center", KnowledgeKind.TYPE, "demo.Center")
    outgoing_nodes = tuple(
        KnowledgeNode(f"type:out:{index:04d}", KnowledgeKind.TYPE, f"demo.Out{index}")
        for index in range(200)
    )
    incoming_nodes = tuple(
        KnowledgeNode(f"type:in:{index:04d}", KnowledgeKind.TYPE, f"demo.In{index}")
        for index in range(75)
    )
    edges = tuple(
        KnowledgeEdge(
            center.id,
            node.id,
            KnowledgeRelation.IMPORTS,
            (f"import:{index:04d}",),
        )
        for index, node in enumerate(outgoing_nodes)
    ) + tuple(
        KnowledgeEdge(
            node.id,
            center.id,
            KnowledgeRelation.CALLS,
            (f"call:{index:04d}",),
        )
        for index, node in enumerate(incoming_nodes)
    )
    nodes = (center, *outgoing_nodes, *incoming_nodes)
    forward = KnowledgeGraph(nodes, edges)
    reversed_graph = KnowledgeGraph(reversed(nodes), reversed(edges))

    expected_outgoing = forward.outgoing(center.id)[:11]
    selected_outgoing, outgoing_count = forward.bounded_outgoing(
        center.id,
        limit=11,
    )
    reversed_outgoing, reversed_outgoing_count = reversed_graph.bounded_outgoing(
        center.id,
        limit=11,
    )
    assert selected_outgoing == expected_outgoing == reversed_outgoing
    assert outgoing_count == reversed_outgoing_count == 200

    calls, call_count = forward.bounded_incoming(
        center.id,
        limit=9,
        relation=KnowledgeRelation.CALLS,
    )
    assert calls == forward.incoming(center.id, KnowledgeRelation.CALLS)[:9]
    assert call_count == 75

    incident, incident_count = forward.bounded_incident(center.id, limit=17)
    reversed_incident, reversed_incident_count = reversed_graph.bounded_incident(
        center.id,
        limit=17,
    )
    assert incident == reversed_incident
    assert incident_count == reversed_incident_count == 275
    assert all(direction == "incoming" for direction, _ in incident)


def test_bounded_graph_query_can_filter_one_explicit_endpoint() -> None:
    graph = KnowledgeGraph(
        (
            KnowledgeNode("method:source", KnowledgeKind.METHOD, "demo.Source#run()"),
            KnowledgeNode("method:target", KnowledgeKind.METHOD, "demo.Target#run()"),
        ),
        tuple(
            KnowledgeEdge(
                "method:source",
                "method:target",
                KnowledgeRelation.CALLS,
                (f"call:{index:03d}",),
            )
            for index in reversed(range(100))
        ),
    )

    selected, total = graph.bounded_outgoing(
        "method:source",
        limit=8,
        relation=KnowledgeRelation.CALLS,
        target_id="method:target",
    )

    assert total == 100
    assert selected == graph.outgoing(
        "method:source",
        KnowledgeRelation.CALLS,
    )[:8]
