"""Deterministic Java architecture baselines and regression detection."""
from .comparator import JavaArchitectureBaselineComparator
from .models import (
    ArchitectureBaseline,
    ArchitectureRegression,
    ArchitectureRegressionReport,
    BaselineEdge,
    BaselineNode,
    BaselineViolation,
    RegressionSeverity,
)
from .serialization import JavaArchitectureBaselineJson
from .service import JavaArchitectureBaselineService
from .snapshot import JavaArchitectureSnapshotter

__all__ = [
    "ArchitectureBaseline",
    "ArchitectureRegression",
    "ArchitectureRegressionReport",
    "BaselineEdge",
    "BaselineNode",
    "BaselineViolation",
    "JavaArchitectureBaselineComparator",
    "JavaArchitectureBaselineJson",
    "JavaArchitectureBaselineService",
    "JavaArchitectureSnapshotter",
    "RegressionSeverity",
]
