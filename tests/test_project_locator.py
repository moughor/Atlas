from pathlib import Path

import pytest

from moughorai.project_locator import (
    ProjectLocator,
    ProjectLocatorError,
)


def test_explicit_project_has_priority(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()

    other = tmp_path / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text(
        "[project]\nname = 'other'\n",
        encoding="utf-8",
    )

    locator = ProjectLocator()

    result = locator.locate(
        explicit,
        start=other,
    )

    assert result == explicit.resolve()


def test_explicit_project_does_not_require_marker(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    locator = ProjectLocator()

    assert locator.locate(project) == project.resolve()


def test_missing_explicit_project_is_rejected(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"

    locator = ProjectLocator()

    with pytest.raises(
        ProjectLocatorError,
        match="does not exist",
    ):
        locator.locate(missing)


def test_explicit_file_is_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "README.md"
    file_path.write_text("# Test\n", encoding="utf-8")

    locator = ProjectLocator()

    with pytest.raises(
        ProjectLocatorError,
        match="not a directory",
    ):
        locator.locate(file_path)


def test_current_directory_marker_is_detected(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'example'\n",
        encoding="utf-8",
    )

    locator = ProjectLocator()

    assert locator.locate(start=tmp_path) == tmp_path.resolve()


def test_parent_project_is_detected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "src" / "package"

    nested.mkdir(parents=True)
    (project / ".git").mkdir()

    locator = ProjectLocator()

    assert locator.locate(start=nested) == project.resolve()


@pytest.mark.parametrize(
    "marker",
    [
        ".git",
        ".moughorai",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
    ],
)
def test_supported_markers_are_detected(
    tmp_path: Path,
    marker: str,
) -> None:
    marker_path = tmp_path / marker

    if marker.startswith(".") and marker in {
        ".git",
        ".moughorai",
    }:
        marker_path.mkdir()
    else:
        marker_path.write_text("", encoding="utf-8")

    locator = ProjectLocator()

    assert locator.locate(start=tmp_path) == tmp_path.resolve()


def test_closest_parent_project_wins(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    nested = inner / "src"

    nested.mkdir(parents=True)

    (outer / ".git").mkdir()
    (inner / "pyproject.toml").write_text(
        "[project]\nname = 'inner'\n",
        encoding="utf-8",
    )

    locator = ProjectLocator()

    assert locator.locate(start=nested) == inner.resolve()


def test_file_start_uses_its_parent_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'example'\n",
        encoding="utf-8",
    )

    locator = ProjectLocator()

    assert locator.locate(start=source) == tmp_path.resolve()


def test_no_project_returns_none(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    locator = ProjectLocator(
        markers=("definitely-not-a-real-marker",),
    )

    assert locator.locate(start=empty) is None


def test_custom_markers_are_supported(
    tmp_path: Path,
) -> None:
    (tmp_path / "moughor.project").write_text(
        "",
        encoding="utf-8",
    )

    locator = ProjectLocator(
        markers=("moughor.project",),
    )

    assert locator.locate(start=tmp_path) == tmp_path.resolve()


def test_empty_marker_collection_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="at least one project marker",
    ):
        ProjectLocator(markers=())
