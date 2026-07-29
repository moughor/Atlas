from pathlib import Path

import pytest

from moughorai.project_inventory.models import FileKind, ProjectFile
from moughorai.project_inventory.statistics import ProjectStatisticsCollector


def project_file(
    relative_path: str,
    *,
    size: int,
    language: str | None,
    kind: FileKind,
) -> ProjectFile:
    relative = Path(relative_path)
    return ProjectFile(
        path=Path("/project") / relative,
        relative_path=relative,
        size=size,
        extension=relative.suffix.casefold(),
        language=language,
        kind=kind,
    )


def test_statistics_collects_totals_and_rankings() -> None:
    files = (
        project_file(
            "src/App.java",
            size=100,
            language="Java",
            kind=FileKind.SOURCE,
        ),
        project_file(
            "src/Service.java",
            size=200,
            language="Java",
            kind=FileKind.SOURCE,
        ),
        project_file(
            "config/app.yaml",
            size=50,
            language=None,
            kind=FileKind.CONFIG,
        ),
    )

    inventory = ProjectStatisticsCollector().collect(
        root=Path("/project"),
        files=files,
        total_directories=3,
    )

    assert inventory.total_files == 3
    assert inventory.total_size == 350
    assert inventory.average_file_size == pytest.approx(350 / 3)
    assert inventory.largest_file == files[1]
    assert inventory.languages[0].name == "Java"
    assert inventory.languages[0].files == 2
    assert inventory.largest_directories[0].path == Path("src")
    assert inventory.largest_directories[0].size == 300


def test_statistics_handles_empty_project() -> None:
    inventory = ProjectStatisticsCollector().collect(
        root=Path("/project"),
        files=(),
        total_directories=1,
    )

    assert inventory.total_files == 0
    assert inventory.total_size == 0
    assert inventory.average_file_size == 0.0
    assert inventory.largest_file is None


def test_statistics_rejects_negative_directory_limit() -> None:
    with pytest.raises(ValueError):
        ProjectStatisticsCollector(largest_directories_limit=-1)
