from pathlib import Path

import pytest

from moughorai.project_inventory.maven_models import (
    MavenDependency,
    MavenModule,
    MavenParent,
    MavenProject,
)
from moughorai.project_inventory.module_graph_builder import (
    MavenModuleGraphBuilder,
)
from moughorai.project_inventory.module_graph_models import ModuleEdgeKind


def project(
    artifact_id: str,
    *,
    pom_path: str,
    group_id: str | None = "com.demo",
    version: str | None = "1.0",
    packaging: str = "jar",
    parent: MavenParent | None = None,
    dependencies: tuple[MavenDependency, ...] = (),
    modules: tuple[MavenModule, ...] = (),
) -> MavenProject:
    return MavenProject(
        pom_path=Path(pom_path),
        model_version="4.0.0",
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        packaging=packaging,
        name=None,
        parent=parent,
        properties=(),
        dependencies=dependencies,
        managed_dependencies=(),
        plugins=(),
        modules=modules,
    )


def dependency(
    artifact_id: str,
    *,
    scope: str | None = None,
    optional: bool = False,
) -> MavenDependency:
    return MavenDependency(
        group_id="com.demo",
        artifact_id=artifact_id,
        version="1.0",
        scope=scope,
        optional=optional,
    )


def parent() -> MavenParent:
    return MavenParent(
        group_id="com.demo",
        artifact_id="parent",
        version="1.0",
        relative_path="../pom.xml",
    )


def test_builder_creates_nodes_in_deterministic_order() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project("web", pom_path="web/pom.xml"),
            project("api", pom_path="api/pom.xml"),
        ]
    )

    assert graph.node_ids == (
        "com.demo:api",
        "com.demo:web",
    )


def test_builder_creates_declared_module_edges() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "parent",
                pom_path="pom.xml",
                packaging="pom",
                modules=(
                    MavenModule(path="api"),
                    MavenModule(path="core"),
                ),
            ),
            project("api", pom_path="api/pom.xml"),
            project("core", pom_path="core/pom.xml"),
        ]
    )

    targets = {
        edge.target
        for edge in graph.outgoing(
            "com.demo:parent",
            ModuleEdgeKind.DECLARES_MODULE,
        )
    }

    assert targets == {"com.demo:api", "com.demo:core"}


def test_builder_accepts_module_path_pointing_to_pom() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "parent",
                pom_path="pom.xml",
                modules=(MavenModule(path="api/pom.xml"),),
            ),
            project("api", pom_path="api/pom.xml"),
        ]
    )

    assert len(graph.edges) == 1


def test_builder_creates_parent_relationship() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project("parent", pom_path="pom.xml"),
            project(
                "api",
                pom_path="api/pom.xml",
                group_id=None,
                version=None,
                parent=parent(),
            ),
        ]
    )

    assert any(
        edge.kind is ModuleEdgeKind.PARENT
        and edge.source == "com.demo:parent"
        and edge.target == "com.demo:api"
        for edge in graph.edges
    )


def test_builder_creates_internal_dependency_edges() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "api",
                pom_path="api/pom.xml",
                dependencies=(
                    dependency(
                        "core",
                        scope="compile",
                        optional=True,
                    ),
                ),
            ),
            project("core", pom_path="core/pom.xml"),
        ]
    )

    edge = graph.outgoing(
        "com.demo:api",
        ModuleEdgeKind.DEPENDS_ON,
    )[0]

    assert edge.target == "com.demo:core"
    assert edge.scope == "compile"
    assert edge.optional is True


def test_external_dependencies_are_not_graph_edges() -> None:
    external = MavenDependency(
        group_id="org.springframework",
        artifact_id="spring-core",
        version="6.2",
    )
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "api",
                pom_path="api/pom.xml",
                dependencies=(external,),
            )
        ]
    )

    assert graph.edges == ()


def test_unresolved_declared_module_is_reported() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "parent",
                pom_path="pom.xml",
                modules=(MavenModule(path="missing"),),
            )
        ]
    )

    assert len(graph.unresolved) == 1
    assert graph.unresolved[0].reference == "missing"
    assert (
        graph.unresolved[0].kind
        is ModuleEdgeKind.DECLARES_MODULE
    )


def test_external_parent_is_reported_as_unresolved() -> None:
    external_parent = MavenParent(
        group_id="org.springframework.boot",
        artifact_id="spring-boot-starter-parent",
        version="3.5.0",
    )
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "api",
                pom_path="api/pom.xml",
                group_id=None,
                version=None,
                parent=external_parent,
            )
        ]
    )

    assert len(graph.unresolved) == 1
    assert graph.unresolved[0].reference == (
        "org.springframework.boot:spring-boot-starter-parent"
    )


def test_builder_detects_dependency_cycle() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "api",
                pom_path="api/pom.xml",
                dependencies=(dependency("core"),),
            ),
            project(
                "core",
                pom_path="core/pom.xml",
                dependencies=(dependency("data"),),
            ),
            project(
                "data",
                pom_path="data/pom.xml",
                dependencies=(dependency("api"),),
            ),
        ]
    )

    assert len(graph.dependency_cycles) == 1
    assert graph.dependency_cycles[0].modules == (
        "com.demo:api",
        "com.demo:core",
        "com.demo:data",
    )


def test_builder_does_not_report_acyclic_dependencies() -> None:
    graph = MavenModuleGraphBuilder().build(
        [
            project(
                "api",
                pom_path="api/pom.xml",
                dependencies=(dependency("core"),),
            ),
            project("core", pom_path="core/pom.xml"),
        ]
    )

    assert graph.dependency_cycles == ()


def test_duplicate_coordinates_are_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="duplicate Maven module coordinate",
    ):
        MavenModuleGraphBuilder().build(
            [
                project("api", pom_path="one/pom.xml"),
                project("api", pom_path="two/pom.xml"),
            ]
        )


def test_project_without_effective_coordinate_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="no effective coordinate",
    ):
        MavenModuleGraphBuilder().build(
            [
                project(
                    "api",
                    pom_path="api/pom.xml",
                    group_id=None,
                    version=None,
                    parent=None,
                )
            ]
        )
