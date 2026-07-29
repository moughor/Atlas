from pathlib import Path

from moughorai.project_inventory.models import (
    FileKind,
    ProjectFile,
    ProjectInventory,
)


def test_inventory_filters_files_by_kind_and_language() -> None:
    java = ProjectFile(
        path=Path("/project/src/App.java"),
        relative_path=Path("src/App.java"),
        size=100,
        extension=".java",
        language="Java",
        kind=FileKind.SOURCE,
    )
    config = ProjectFile(
        path=Path("/project/app.yaml"),
        relative_path=Path("app.yaml"),
        size=20,
        extension=".yaml",
        language=None,
        kind=FileKind.CONFIG,
    )
    inventory = ProjectInventory(
        root=Path("/project"),
        total_files=2,
        total_directories=2,
        total_size=120,
        average_file_size=60.0,
        largest_file=java,
        files=(java, config),
        languages=(),
        extensions=(),
        kinds=(),
        largest_directories=(),
    )

    assert inventory.files_of_kind(FileKind.SOURCE) == (java,)
    assert inventory.files_for_language("java") == (java,)
