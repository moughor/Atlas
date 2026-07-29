from pathlib import Path

import pytest

from moughorai.project_inventory.classifier import ProjectClassifier
from moughorai.project_inventory.models import FileKind, ScannedFile


@pytest.mark.parametrize(
    ("relative_path", "language", "kind"),
    [
        ("src/App.java", "Java", FileKind.SOURCE),
        ("src/app.py", "Python", FileKind.SOURCE),
        ("pom.xml", None, FileKind.BUILD),
        ("config/app.yaml", None, FileKind.CONFIG),
        ("lib/app.jar", None, FileKind.ARCHIVE),
        ("classes/App.class", None, FileKind.BINARY),
        ("README.md", None, FileKind.DOCUMENTATION),
        ("assets/logo.png", None, FileKind.ASSET),
        ("target/generated/App.java", "Java", FileKind.GENERATED),
        ("unknown.data", None, FileKind.UNKNOWN),
    ],
)
def test_classifier_classifies_known_files(
    relative_path: str,
    language: str | None,
    kind: FileKind,
) -> None:
    path = Path(relative_path)
    scanned = ScannedFile(
        path=Path("/project") / path,
        relative_path=path,
        size=10,
        extension=path.suffix.casefold(),
    )

    result = ProjectClassifier().classify(scanned)

    assert result.language == language
    assert result.kind is kind
