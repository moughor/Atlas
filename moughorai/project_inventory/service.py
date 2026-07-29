"""High-level project inventory orchestration."""

from __future__ import annotations

from pathlib import Path

from moughorai.project_inventory.classifier import ProjectClassifier
from moughorai.project_inventory.detector import ProjectTechnologyDetector
from moughorai.project_inventory.detection_models import ProjectDetection
from moughorai.project_inventory.models import ProjectInventory
from moughorai.project_inventory.scanner import ProjectScanner
from moughorai.project_inventory.statistics import ProjectStatisticsCollector


class ProjectInventoryService:
    """Scan, classify, summarize, and detect a project tree."""

    def __init__(
        self,
        scanner: ProjectScanner | None = None,
        classifier: ProjectClassifier | None = None,
        statistics: ProjectStatisticsCollector | None = None,
        detector: ProjectTechnologyDetector | None = None,
    ) -> None:
        self._scanner = scanner or ProjectScanner()
        self._classifier = classifier or ProjectClassifier()
        self._statistics = statistics or ProjectStatisticsCollector()
        self._detector = detector or ProjectTechnologyDetector()

    def build(self, root: Path) -> ProjectInventory:
        """Build a complete deterministic inventory for a project."""

        scan_result = self._scanner.scan(root)
        classified_files = self._classifier.classify_many(scan_result.files)

        return self._statistics.collect(
            root=scan_result.root,
            files=classified_files,
            total_directories=scan_result.total_directories,
        )

    def detect(self, root: Path) -> ProjectDetection:
        """Build an inventory and detect project technologies."""

        return self._detector.detect(self.build(root))
