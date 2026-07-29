from pathlib import Path

from moughorai.project_inventory.module_graph_models import ModuleEdgeKind
from moughorai.project_inventory.module_graph_service import (
    MavenModuleGraphService,
)


def write_pom(
    path: Path,
    *,
    artifact_id: str,
    dependencies: str = "",
    modules: str = "",
    packaging: str = "jar",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>com.demo</groupId>
          <artifactId>{artifact_id}</artifactId>
          <version>1.0</version>
          <packaging>{packaging}</packaging>
          {modules}
          {dependencies}
        </project>
        """,
        encoding="utf-8",
    )


def test_service_parses_poms_and_builds_graph(
    tmp_path: Path,
) -> None:
    root_pom = tmp_path / "pom.xml"
    api_pom = tmp_path / "api" / "pom.xml"
    core_pom = tmp_path / "core" / "pom.xml"

    write_pom(
        root_pom,
        artifact_id="parent",
        packaging="pom",
        modules="""
        <modules>
          <module>api</module>
          <module>core</module>
        </modules>
        """,
    )
    write_pom(
        api_pom,
        artifact_id="api",
        dependencies="""
        <dependencies>
          <dependency>
            <groupId>com.demo</groupId>
            <artifactId>core</artifactId>
            <version>1.0</version>
          </dependency>
        </dependencies>
        """,
    )
    write_pom(core_pom, artifact_id="core")

    graph = MavenModuleGraphService().build(
        [root_pom, api_pom, core_pom]
    )

    assert len(graph.nodes) == 3
    assert len(
        graph.outgoing(
            "com.demo:parent",
            ModuleEdgeKind.DECLARES_MODULE,
        )
    ) == 2
    assert len(
        graph.outgoing(
            "com.demo:api",
            ModuleEdgeKind.DEPENDS_ON,
        )
    ) == 1
