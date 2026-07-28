"""Discover and parse Java sources under a project root."""

from pathlib import Path

from moughorai.java_analysis.models import JavaSourceFile
from moughorai.java_analysis.parser import JavaSourceParser


class JavaSourceAnalysisService:
    def __init__(self, parser: JavaSourceParser | None = None) -> None:
        self._parser = parser or JavaSourceParser()

    def discover(self, root: Path) -> tuple[Path, ...]:
        project_root = Path(root)
        if not project_root.exists():
            raise FileNotFoundError(
                f"project root does not exist: {project_root}"
            )
        if not project_root.is_dir():
            raise NotADirectoryError(
                f"project root is not a directory: {project_root}"
            )
        return tuple(
            sorted(
                (
                    path
                    for path in project_root.rglob("*.java")
                    if path.is_file()
                ),
                key=lambda path: path.as_posix().casefold(),
            )
        )

    def analyze(self, root: Path) -> tuple[JavaSourceFile, ...]:
        return self._parser.parse_many(self.discover(root))
