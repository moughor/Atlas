from pathlib import Path

import pytest

from moughorai.project_inventory.scanner import ProjectScanner


def test_scanner_returns_sorted_relative_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "B.java").write_text("class B {}", encoding="utf-8")
    (tmp_path / "src" / "a.java").write_text("class A {}", encoding="utf-8")

    result = ProjectScanner().scan(tmp_path)

    assert tuple(file.relative_path for file in result.files) == (
        Path("src/a.java"),
        Path("src/B.java"),
    )
    assert result.total_directories == 2


def test_scanner_ignores_default_directories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")

    result = ProjectScanner().scan(tmp_path)

    assert tuple(file.relative_path for file in result.files) == (
        Path("main.py"),
    )


def test_scanner_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ProjectScanner().scan(tmp_path / "missing")


def test_scanner_rejects_file_root(tmp_path: Path) -> None:
    file = tmp_path / "project.txt"
    file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        ProjectScanner().scan(file)
