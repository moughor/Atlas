from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeRelation
from moughorai.workspace import WorkspaceDiscovery


def _write_pom(
    path: Path,
    *,
    artifact_id: str,
    modules: tuple[str, ...] = (),
    dependencies: tuple[tuple[str, str], ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    module_xml = "".join(f"<module>{module}</module>" for module in modules)
    dependency_xml = "".join(
        (
            f"<dependency><groupId>{group_id}</groupId>"
            f"<artifactId>{dependency_artifact}</artifactId>"
            "<version>1</version></dependency>"
        )
        for group_id, dependency_artifact in dependencies
    )
    path.write_text(
        (
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.example</groupId>"
            f"<artifactId>{artifact_id}</artifactId><version>1</version>"
            f"<modules>{module_xml}</modules>"
            f"<dependencies>{dependency_xml}</dependencies>"
            "</project>"
        ),
        encoding="utf-8",
    )


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _relative_project_paths(root: Path) -> set[str]:
    workspace = WorkspaceDiscovery().discover(root)
    return {
        project.path.relative_to(root).as_posix()
        for project in workspace.projects
    }


def test_tracked_maven_descriptor_beyond_traversal_depth_is_discovered(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    descriptor = root / "services/backend/runtime/bundles/release/pom.xml"
    _write_pom(descriptor, artifact_id="deep-component")
    _git(root, "init", "--quiet")
    _git(root, "add", "services/backend/runtime/bundles/release/pom.xml")

    paths = _relative_project_paths(root)

    assert "services/backend/runtime/bundles/release" in paths


@pytest.mark.parametrize(
    ("authoritative_path", "generated_path", "ignored_path"),
    (
        (
            "component/src/main/resources/bundle/pom.xml",
            "component/target/classes/bundle/pom.xml",
            "component/target/",
        ),
        (
            "domain/catalog/authoritative/pom.xml",
            "packaging/cache/copied/pom.xml",
            "packaging/cache/",
        ),
    ),
)
def test_tracked_maven_descriptor_wins_by_identity_without_path_assumptions(
    tmp_path: Path,
    authoritative_path: str,
    generated_path: str,
    ignored_path: str,
) -> None:
    root = tmp_path / "repository"
    _write_pom(root / authoritative_path, artifact_id="release-runner")
    _write_pom(root / generated_path, artifact_id="release-runner")
    (root / ".gitignore").write_text(f"/{ignored_path}\n", encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "add", ".gitignore", authoritative_path)

    paths = _relative_project_paths(root)

    assert authoritative_path.removesuffix("/pom.xml") in paths
    assert generated_path.removesuffix("/pom.xml") not in paths


def test_non_git_workspace_preserves_conservative_discovery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    _write_pom(root / "source/pom.xml", artifact_id="duplicate")
    _write_pom(root / "copy/pom.xml", artifact_id="duplicate")

    assert _relative_project_paths(root) == {"source", "copy"}


def test_duplicate_tracked_maven_coordinates_are_preserved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    _write_pom(root / "first/pom.xml", artifact_id="duplicate")
    _write_pom(root / "second/pom.xml", artifact_id="duplicate")
    _git(root, "init", "--quiet")
    _git(root, "add", "first/pom.xml", "second/pom.xml")

    paths = _relative_project_paths(root)

    assert {"first", "second"} <= paths


def test_maven_reactor_dependencies_become_workspace_and_graph_edges(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reactor"
    _write_pom(
        root / "pom.xml",
        artifact_id="root",
        modules=("module-a", "module-b"),
    )
    _write_pom(root / "module-a/pom.xml", artifact_id="module-a")
    _write_pom(
        root / "module-b/pom.xml",
        artifact_id="module-b",
        dependencies=(
            ("com.example", "module-a"),
            ("org.external", "library"),
        ),
    )

    workspace = WorkspaceDiscovery().discover(root)

    assert workspace.names() == ("module-a", "module-b", "reactor")
    assert workspace.get("module-b").dependencies == ("module-a",)
    graph = KnowledgeGraph.from_dict(
        WorkspaceContextBuilder().build(workspace).to_dict()["semantic_graph"]
    )
    edges = graph.outgoing("project:module-b", KnowledgeRelation.DEPENDS_ON)
    assert tuple(edge.target for edge in edges) == ("project:module-a",)


def test_maven_workspace_dependency_order_is_deterministic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reactor"
    _write_pom(
        root / "pom.xml",
        artifact_id="root",
        modules=("module-c", "module-b", "module-a"),
    )
    _write_pom(root / "module-a/pom.xml", artifact_id="module-a")
    _write_pom(root / "module-c/pom.xml", artifact_id="module-c")
    _write_pom(
        root / "module-b/pom.xml",
        artifact_id="module-b",
        dependencies=(
            ("com.example", "module-c"),
            ("com.example", "module-a"),
        ),
    )

    first = WorkspaceDiscovery().discover(root)
    second = WorkspaceDiscovery().discover(root)

    assert first.get("module-b").dependencies == ("module-a", "module-c")
    assert second.to_dict() == first.to_dict()


def test_ambiguous_maven_coordinates_are_not_projected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reactor"
    _write_pom(
        root / "pom.xml",
        artifact_id="root",
        modules=("first", "second", "consumer"),
    )
    _write_pom(root / "first/pom.xml", artifact_id="shared")
    _write_pom(root / "second/pom.xml", artifact_id="shared")
    _write_pom(
        root / "consumer/pom.xml",
        artifact_id="consumer",
        dependencies=(("com.example", "shared"),),
    )
    _git(root, "init", "--quiet")
    _git(
        root,
        "add",
        "pom.xml",
        "first/pom.xml",
        "second/pom.xml",
        "consumer/pom.xml",
    )

    workspace = WorkspaceDiscovery().discover(root)

    assert workspace.get("consumer").dependencies == ()
    graph = KnowledgeGraph.from_dict(
        WorkspaceContextBuilder().build(workspace).to_dict()["semantic_graph"]
    )
    assert graph.outgoing(
        "project:consumer",
        KnowledgeRelation.DEPENDS_ON,
    ) == ()
