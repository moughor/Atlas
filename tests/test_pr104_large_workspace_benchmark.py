from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.benchmark_large_workspace import benchmark, create_workspace
from moughorai.project_index import ProjectFileIndexer


def test_generated_workspace_is_balanced_and_indexable(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path, files=11, projects=3)

    assert workspace.names() == ("project-000", "project-001", "project-002")
    assert [len(ProjectFileIndexer().build(project.path).files) for project in workspace.projects] == [4, 4, 3]


def test_benchmark_exercises_all_files_and_has_stable_content(tmp_path: Path) -> None:
    first = benchmark(tmp_path / "first", files=12, projects=3)
    second = benchmark(tmp_path / "second", files=12, projects=3)

    assert first["schema_version"] == 1
    assert first["indexed_files"] == first["files"] == 12
    assert first["projects"] == 3
    assert first["content_checksum"] == second["content_checksum"]
    assert first["measured_seconds"] >= 0
    assert first["files_per_second"] > 0
    assert first["peak_memory_mib"] >= 0


@pytest.mark.parametrize(
    ("files", "projects", "message"),
    [(0, 1, "files and projects must be positive"), (1, 0, "files and projects must be positive"), (2, 3, "projects must not exceed files")],
)
def test_invalid_corpus_sizes_are_rejected(tmp_path: Path, files: int, projects: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        create_workspace(tmp_path, files=files, projects=projects)


def test_command_emits_one_machine_readable_report() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "benchmarks.benchmark_large_workspace", "--files", "9", "--projects", "3"],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert completed.stderr == ""
    assert report["files"] == report["indexed_files"] == 9
    assert list(report) == sorted(report)
