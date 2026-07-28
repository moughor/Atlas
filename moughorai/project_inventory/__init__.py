"""Deterministic project inventory and technology detection."""

from moughorai.project_inventory.classifier import ProjectClassifier
from moughorai.project_inventory.detector import ProjectTechnologyDetector
from moughorai.project_inventory.detection_models import (
    DetectedTechnology,
    ProjectDetection,
    TechnologyCategory,
)
from moughorai.project_inventory.models import (
    DirectoryStatistic,
    FileKind,
    FileStatistic,
    ProjectFile,
    ProjectInventory,
    ScannedFile,
)
from moughorai.project_inventory.scanner import ProjectScanner, ScanResult
from moughorai.project_inventory.service import ProjectInventoryService
from moughorai.project_inventory.statistics import ProjectStatisticsCollector

__all__ = [
    "DetectedTechnology",
    "DirectoryStatistic",
    "FileKind",
    "FileStatistic",
    "ProjectClassifier",
    "ProjectDetection",
    "ProjectFile",
    "ProjectInventory",
    "ProjectInventoryService",
    "ProjectScanner",
    "ProjectStatisticsCollector",
    "ProjectTechnologyDetector",
    "ScanResult",
    "ScannedFile",
    "TechnologyCategory",
]
