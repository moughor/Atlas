from pathlib import Path

import pytest

from moughorai.projects import (
    ProjectAnalyzer,
)


def test_analyze_loads_supported_project_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    source = project / "src"

    source.mkdir(parents=True)

    (project / "README.md").write_text(
        "# Example Project",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[project]\nname = \"example\"",
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        "def main() -> None:\n    pass",
        encoding="utf-8",
    )
    (project / "image.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
    )

    analyzer = ProjectAnalyzer(tmp_path)

    context = analyzer.analyze("example")

    assert context.name == "example"
    assert context.file_count == 3

    assert tuple(
        project_file.path
        for project_file in context.files
    ) == (
        Path("pyproject.toml"),
        Path("README.md"),
        Path("src/main.py"),
    )


def test_analysis_order_is_deterministic(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    project.mkdir()

    (project / "zeta.py").write_text(
        "ZETA = True",
        encoding="utf-8",
    )
    (project / "Alpha.py").write_text(
        "ALPHA = True",
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(tmp_path)

    context = analyzer.analyze(project)

    assert tuple(
        project_file.path
        for project_file in context.files
    ) == (
        Path("Alpha.py"),
        Path("zeta.py"),
    )


def test_dependency_and_cache_directories_are_excluded(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"

    (project / "node_modules" / "package").mkdir(
        parents=True
    )
    (project / ".venv").mkdir(parents=True)
    (project / "__pycache__").mkdir(parents=True)

    (project / "app.py").write_text(
        "print('loaded')",
        encoding="utf-8",
    )
    (
        project
        / "node_modules"
        / "package"
        / "index.js"
    ).write_text(
        "console.log('ignored')",
        encoding="utf-8",
    )
    (project / ".venv" / "ignored.py").write_text(
        "IGNORED = True",
        encoding="utf-8",
    )
    (
        project
        / "__pycache__"
        / "ignored.py"
    ).write_text(
        "IGNORED = True",
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(tmp_path)

    context = analyzer.analyze(project)

    assert context.file_count == 1
    assert context.files[0].path == Path("app.py")
    assert "node_modules" not in context.tree
    assert ".venv" not in context.tree
    assert "__pycache__" not in context.tree


def test_secret_files_are_excluded(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    project.mkdir()

    (project / ".env").write_text(
        "API_KEY=secret",
        encoding="utf-8",
    )
    (project / ".env.production").write_text(
        "TOKEN=secret",
        encoding="utf-8",
    )
    (project / "private.key").write_text(
        "secret",
        encoding="utf-8",
    )
    (project / "settings.py").write_text(
        "DEBUG = False",
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(tmp_path)

    context = analyzer.analyze(project)

    assert context.file_count == 1
    assert context.files[0].path == Path("settings.py")
    assert ".env" not in context.tree
    assert "private.key" not in context.tree


def test_large_file_is_truncated(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    project.mkdir()

    (project / "large.py").write_text(
        "x" * 100,
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(
        tmp_path,
        max_file_characters=20,
    )

    context = analyzer.analyze(project)

    assert context.file_count == 1
    assert context.files[0].character_count == 20
    assert context.files[0].truncated is True
    assert context.truncated_file_count == 1


def test_total_character_limit_is_respected(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    project.mkdir()

    (project / "a.py").write_text(
        "a" * 15,
        encoding="utf-8",
    )
    (project / "b.py").write_text(
        "b" * 15,
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(
        tmp_path,
        max_file_characters=20,
        max_total_characters=20,
    )

    context = analyzer.analyze(project)

    assert context.total_character_count == 20
    assert context.files[0].character_count == 15
    assert context.files[1].character_count == 5
    assert context.files[1].truncated is True


def test_missing_project_is_rejected(
    tmp_path: Path,
) -> None:
    analyzer = ProjectAnalyzer(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match="Project directory not found",
    ):
        analyzer.analyze("missing")


def test_file_path_is_rejected(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "project.py"

    file_path.write_text(
        "print('hello')",
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(tmp_path)

    with pytest.raises(
        NotADirectoryError,
        match="Project path is not a directory",
    ):
        analyzer.analyze(file_path)


def test_render_contains_structure_and_selected_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "example"
    project.mkdir()

    (project / "README.md").write_text(
        "# Example",
        encoding="utf-8",
    )
    (project / "app.py").write_text(
        "print('hello')",
        encoding="utf-8",
    )

    analyzer = ProjectAnalyzer(tmp_path)

    context = analyzer.analyze(project)
    rendered = context.render()

    assert "Project: example" in rendered
    assert "## Project Structure" in rendered
    assert "README.md" in rendered
    assert "app.py" in rendered
    assert "## Project File: README.md" in rendered
    assert "# Example" in rendered