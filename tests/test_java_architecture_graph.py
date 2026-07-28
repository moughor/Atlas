from pathlib import Path

from moughorai.java_architecture import (
    ArchitectureEdgeKind,
    JavaArchitectureService,
)


def analyze(*sources: tuple[str, str]):
    return JavaArchitectureService().analyze_sources(
        {Path(name): source for name, source in sources}
    )


def test_builds_inheritance_and_implementation_edges() -> None:
    graph = analyze(
        ("Base.java", "package app; public class Base {}"),
        ("Api.java", "package app; public interface Api {}"),
        (
            "Service.java",
            "package app; public class Service extends Base implements Api {}",
        ),
    )

    assert graph.node("app.Service") is not None
    assert graph.outgoing("app.Service", ArchitectureEdgeKind.EXTENDS)[0].target == "app.Base"
    assert graph.outgoing("app.Service", ArchitectureEdgeKind.IMPLEMENTS)[0].target == "app.Api"


def test_builds_field_and_callable_dependency_edges() -> None:
    graph = analyze(
        ("Repo.java", "package app; public class Repo {}"),
        ("Dto.java", "package app; public class Dto {}"),
        (
            "Service.java",
            """
            package app;
            public class Service {
                private Repo repo;
                public Service(Repo repo) {}
                public Dto find(Repo input) { return null; }
            }
            """,
        ),
    )

    kinds = {edge.kind for edge in graph.outgoing("app.Service")}
    assert ArchitectureEdgeKind.FIELD_TYPE in kinds
    assert ArchitectureEdgeKind.CONSTRUCTOR_PARAMETER in kinds
    assert ArchitectureEdgeKind.METHOD_RETURN in kinds
    assert ArchitectureEdgeKind.METHOD_PARAMETER in kinds


def test_dependencies_and_dependents_are_queryable() -> None:
    graph = analyze(
        ("Repo.java", "package app; public class Repo {}"),
        (
            "Service.java",
            "package app; public class Service { private Repo repo; }",
        ),
    )

    assert tuple(node.qualified_name for node in graph.dependencies("app.Service")) == ("app.Repo",)
    assert tuple(node.qualified_name for node in graph.dependents("app.Repo")) == ("app.Service",)


def test_unresolved_and_primitive_references_are_handled_separately() -> None:
    graph = analyze(
        (
            "Service.java",
            "package app; public class Service { int count; Missing missing; }",
        ),
    )

    assert len(graph.edges) == 0
    assert len(graph.unresolved) == 1
    assert graph.unresolved[0].requested_name == "Missing"
    assert graph.unresolved[0].status == "unresolved"


def test_nested_types_are_independent_graph_nodes() -> None:
    graph = analyze(
        ("Dependency.java", "package app; public class Dependency {}"),
        (
            "Outer.java",
            """
            package app;
            public class Outer {
                class Inner { Dependency dependency; }
            }
            """,
        ),
    )

    assert graph.node("app.Outer.Inner") is not None
    assert graph.outgoing("app.Outer.Inner")[0].target == "app.Dependency"
