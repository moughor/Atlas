from pathlib import Path

from moughorai.project_inventory.maven_models import (
    MavenDependency,
    MavenParent,
    MavenProject,
)


def test_dependency_identifier() -> None:
    dependency = MavenDependency(
        group_id="org.example",
        artifact_id="example-core",
    )

    assert dependency.identifier == "org.example:example-core"


def test_project_uses_parent_effective_coordinate() -> None:
    project = MavenProject(
        pom_path=Path("pom.xml"),
        model_version="4.0.0",
        group_id=None,
        artifact_id="child",
        version=None,
        packaging="jar",
        name=None,
        parent=MavenParent(
            group_id="org.example",
            artifact_id="parent",
            version="1.2.3",
        ),
        properties=(("java.version", "21"),),
        dependencies=(),
        managed_dependencies=(),
        plugins=(),
        modules=(),
    )

    assert project.effective_group_id == "org.example"
    assert project.effective_version == "1.2.3"
    assert project.coordinate is not None
    assert project.coordinate.identifier == "org.example:child"
    assert project.property_value("java.version") == "21"
