from pathlib import Path

from moughorai.project_inventory.models import FileKind
from moughorai.project_inventory.service import ProjectInventoryService


def test_service_builds_complete_inventory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.java").write_text(
        "public class App {}",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text(
        "<project />",
        encoding="utf-8",
    )
    (tmp_path / "application.yaml").write_text(
        "server: {}",
        encoding="utf-8",
    )

    inventory = ProjectInventoryService().build(tmp_path)

    assert inventory.total_files == 3
    assert inventory.total_directories == 2
    assert len(inventory.files_of_kind(FileKind.SOURCE)) == 1
    assert len(inventory.files_of_kind(FileKind.BUILD)) == 1
    assert len(inventory.files_of_kind(FileKind.CONFIG)) == 1
    assert inventory.files_for_language("Java")[0].relative_path == Path(
        "src/App.java"
    )


def test_service_detects_project_technologies(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.java").write_text(
        "public class App {}",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text(
        "<project />",
        encoding="utf-8",
    )

    detection = ProjectInventoryService().detect(tmp_path)

    assert detection.has("Maven")
    assert detection.has("Java")
