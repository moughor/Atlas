from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from moughorai.workspace import WorkspaceDiscovery


def _write_pom(path: Path, *, artifact_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.example</groupId>"
            f"<artifactId>{artifact_id}</artifactId><version>1</version>"
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
