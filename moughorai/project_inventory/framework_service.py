"""High-level Maven framework analysis service."""

from __future__ import annotations

from pathlib import Path

from moughorai.project_inventory.framework_detector import (
    MavenFrameworkDetector,
)
from moughorai.project_inventory.framework_models import FrameworkReport
from moughorai.project_inventory.maven_parser import MavenParser


class MavenFrameworkService:
    """Parse Maven metadata and detect technologies in one operation."""

    def __init__(
        self,
        parser: MavenParser | None = None,
        detector: MavenFrameworkDetector | None = None,
    ) -> None:
        self._parser = parser or MavenParser()
        self._detector = detector or MavenFrameworkDetector()

    def analyze(self, pom_path: Path) -> FrameworkReport:
        """Parse one POM and return its framework report."""

        project = self._parser.parse(pom_path)
        return self._detector.detect(project)

    def analyze_many(
        self,
        pom_paths: tuple[Path, ...] | list[Path],
    ) -> tuple[FrameworkReport, ...]:
        """Parse and analyze several POM files deterministically."""

        projects = self._parser.parse_many(pom_paths)
        return self._detector.detect_many(projects)
