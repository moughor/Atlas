"""Optional production measurement infrastructure for Atlas.

The package is deliberately opt-in and separate from semantic analysis.  Create a
``MeasurementSession`` per run; no process-global collector is installed.
"""

from .filesystem import FilesystemLedger, FilesystemOperation
from .models import (
    FILESYSTEM_COUNTERS,
    MEASUREMENT_PRODUCER,
    MEASUREMENT_SCHEMA_VERSION,
    STABLE_PHASE_IDS,
    FilesystemConsumerMetrics,
    FilesystemConsumerOverlap,
    FilesystemLedgerSnapshot,
    MeasurementPhase,
    MeasurementPhaseSampling,
    MeasurementReport,
    MeasurementSample,
    MeasurementSampling,
    MetricAggregate,
    MetricAggregation,
    MetricReason,
    MetricStatus,
    MetricUnit,
    MetricValue,
    PhaseAggregate,
    aggregate_samples,
    metric_aggregation,
)
from .probes import (
    CurrentProcessMemoryProbe,
    ProcessMemoryProbe,
    ProcessMemoryReading,
)
from .session import MeasurementConfig, MeasurementScope, MeasurementSession


__all__ = [
    "FILESYSTEM_COUNTERS",
    "MEASUREMENT_PRODUCER",
    "MEASUREMENT_SCHEMA_VERSION",
    "STABLE_PHASE_IDS",
    "CurrentProcessMemoryProbe",
    "FilesystemConsumerMetrics",
    "FilesystemConsumerOverlap",
    "FilesystemLedger",
    "FilesystemLedgerSnapshot",
    "FilesystemOperation",
    "MeasurementConfig",
    "MeasurementPhase",
    "MeasurementPhaseSampling",
    "MeasurementReport",
    "MeasurementSample",
    "MeasurementSampling",
    "MeasurementScope",
    "MeasurementSession",
    "MetricAggregate",
    "MetricAggregation",
    "MetricReason",
    "MetricStatus",
    "MetricUnit",
    "MetricValue",
    "PhaseAggregate",
    "ProcessMemoryProbe",
    "ProcessMemoryReading",
    "aggregate_samples",
    "metric_aggregation",
]
