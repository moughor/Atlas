"""Immutable, source-free models for Atlas performance measurements.

This module intentionally contains no integration with semantic analysis.  Performance
measurements are operational artifacts and must never participate in Atlas semantic
identity, snapshots, evidence, reports, or ordering decisions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import math
import re
from typing import Any, Self


MEASUREMENT_SCHEMA_VERSION = 1
MEASUREMENT_PRODUCER = "atlas-performance-measurement/1.0"


class MeasurementPhase(StrEnum):
    """Stable identifiers for the major Atlas execution phases."""

    WORKSPACE_DISCOVERY = "workspace.discovery"
    PROJECT_OWNERSHIP = "project.ownership"
    PROJECT_ANALYSIS = "project.analysis"
    REPOSITORY_INVENTORY = "repository.inventory"
    FILESYSTEM_TRAVERSAL = "filesystem.traversal"
    PATH_NORMALIZATION = "path.normalization"
    BUILD_PARSING = "build.parsing"
    JAVA_PARSING = "language.java.parsing"
    KOTLIN_PARSING = "language.kotlin.parsing"
    PYTHON_PARSING = "language.python.parsing"
    SYMBOL_EXTRACTION = "symbol.extraction"
    DEPENDENCY_INTELLIGENCE = "dependency.intelligence"
    KNOWLEDGE_GRAPH = "knowledge_graph.build"
    ARCHITECTURE = "architecture.analysis"
    REACHABILITY = "reachability.analysis"
    RISK = "risk.analysis"
    REPOSITORY_SUMMARY = "repository.summary"
    REPOSITORY_REPORT = "repository.report"
    EXPLAIN_PROJECTION = "explain.projection"
    SNAPSHOT = "semantic_snapshot.build"
    SERIALIZATION = "serialization"
    PERSISTENCE = "persistence"
    RECOVERY = "recovery"
    PUBLICATION = "publication"


STABLE_PHASE_IDS = tuple(item.value for item in MeasurementPhase)


class MetricStatus(StrEnum):
    """Whether a metric is a measured fact or lacks a usable observation."""

    MEASURED = "measured"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class MetricReason(StrEnum):
    """Source-free reasons for a metric without a measured value."""

    COLLECTION_DISABLED = "collection-disabled"
    PLATFORM_UNSUPPORTED = "platform-unsupported"
    RUNTIME_UNSUPPORTED = "runtime-unsupported"
    PROVIDER_UNAVAILABLE = "provider-unavailable"
    NOT_RECORDED = "not-recorded"
    ZERO_WALL_TIME = "zero-wall-time"
    TRACEMALLOC_INACTIVE = "tracemalloc-inactive"
    CONCURRENT_ATTRIBUTION = "concurrent-scope-attribution"
    SAMPLED_OUT = "sampled-out"


class MetricUnit(StrEnum):
    NANOSECONDS = "nanoseconds"
    BYTES = "bytes"
    COUNT = "count"
    PERCENT = "percent"


class MetricAggregation(StrEnum):
    """How repeated samples may be summarized without inventing semantics."""

    SUM = "sum"
    SAMPLE_SUM = "sample-sum"
    DISTRIBUTION = "distribution"


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def stable_identifier(value: str, *, label: str) -> str:
    """Validate a portable identifier that cannot contain a filesystem path."""

    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(
            f"{label} must be a lowercase portable identifier containing only "
            "letters, digits, '.', '_' or '-'"
        )
    return normalized


def phase_identifier(value: MeasurementPhase | str) -> str:
    return stable_identifier(str(value), label="measurement phase")


def _non_negative_integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One measured value or an explicit explanation for its absence."""

    status: MetricStatus
    unit: MetricUnit
    value: int | float | None = None
    reason: MetricReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MetricStatus):
            raise TypeError("metric status must be a MetricStatus")
        if not isinstance(self.unit, MetricUnit):
            raise TypeError("metric unit must be a MetricUnit")
        if self.reason is not None and not isinstance(self.reason, MetricReason):
            raise TypeError("metric reason must be a MetricReason")
        if self.status is MetricStatus.MEASURED:
            if (
                not isinstance(self.value, (int, float))
                or isinstance(self.value, bool)
            ):
                raise ValueError("a measured metric requires a numeric value")
            if isinstance(self.value, float) and not math.isfinite(self.value):
                raise ValueError("a measured metric must be finite")
            if self.reason is not None:
                raise ValueError("a measured metric cannot have an absence reason")
        else:
            if self.value is not None:
                raise ValueError("an unmeasured metric cannot have a value")
            if self.reason is None:
                raise ValueError("an unmeasured metric requires an absence reason")
            unsupported_reasons = {
                MetricReason.PLATFORM_UNSUPPORTED,
                MetricReason.RUNTIME_UNSUPPORTED,
            }
            if (
                self.status is MetricStatus.UNSUPPORTED
                and self.reason not in unsupported_reasons
            ):
                raise ValueError("unsupported metrics require an unsupported reason")
            if (
                self.status is MetricStatus.UNAVAILABLE
                and self.reason in unsupported_reasons
            ):
                raise ValueError("unavailable metrics cannot use an unsupported reason")

    @classmethod
    def measured(cls, value: int | float, unit: MetricUnit) -> Self:
        return cls(MetricStatus.MEASURED, unit, value=value)

    @classmethod
    def unsupported(cls, unit: MetricUnit, reason: MetricReason) -> Self:
        return cls(MetricStatus.UNSUPPORTED, unit, reason=reason)

    @classmethod
    def unavailable(cls, unit: MetricUnit, reason: MetricReason) -> Self:
        return cls(MetricStatus.UNAVAILABLE, unit, reason=reason)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "unit": self.unit.value,
        }
        if self.status is MetricStatus.MEASURED:
            payload["value"] = self.value
        else:
            assert self.reason is not None
            payload["reason"] = self.reason.value
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        status = MetricStatus(_string(value.get("status"), label="metric status"))
        unit = MetricUnit(_string(value.get("unit"), label="metric unit"))
        if status is MetricStatus.MEASURED:
            if set(value) != {"status", "unit", "value"}:
                raise ValueError("invalid measured metric fields")
            raw = value.get("value")
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise ValueError("measured metric value must be numeric")
            return cls.measured(raw, unit)
        if set(value) != {"status", "unit", "reason"}:
            raise ValueError("invalid unmeasured metric fields")
        return cls(
            status,
            unit,
            reason=MetricReason(_string(value.get("reason"), label="metric reason")),
        )


@dataclass(frozen=True, slots=True)
class MeasurementSample:
    """Immutable observation produced by one completed measurement scope."""

    phase_id: str
    scope_path: tuple[str, ...]
    consumer: str
    worker_id: str
    thread_id: int
    succeeded: bool
    metrics: tuple[tuple[str, MetricValue], ...]

    def __post_init__(self) -> None:
        phase = phase_identifier(self.phase_id)
        path = tuple(phase_identifier(item) for item in self.scope_path)
        if not path or path[-1] != phase:
            raise ValueError("scope path must end with the sample phase")
        if (
            not isinstance(self.thread_id, int)
            or isinstance(self.thread_id, bool)
            or self.thread_id < 0
        ):
            raise ValueError("thread identifier must be a non-negative integer")
        if not isinstance(self.succeeded, bool):
            raise TypeError("sample outcome must be a boolean")
        consumer = stable_identifier(self.consumer, label="measurement consumer")
        worker = stable_identifier(self.worker_id, label="worker identifier")
        normalized_metrics: list[tuple[str, MetricValue]] = []
        seen: set[str] = set()
        for name, metric in self.metrics:
            normalized_name = stable_identifier(name, label="metric name")
            if normalized_name in seen:
                raise ValueError(f"duplicate sample metric: {normalized_name}")
            if not isinstance(metric, MetricValue):
                raise TypeError("sample metrics must contain MetricValue instances")
            seen.add(normalized_name)
            normalized_metrics.append((normalized_name, metric))
        object.__setattr__(self, "phase_id", phase)
        object.__setattr__(self, "scope_path", path)
        object.__setattr__(self, "consumer", consumer)
        object.__setattr__(self, "worker_id", worker)
        object.__setattr__(self, "metrics", tuple(sorted(normalized_metrics)))

    def metric(self, name: str) -> MetricValue:
        normalized = stable_identifier(name, label="metric name")
        for metric_name, value in self.metrics:
            if metric_name == normalized:
                return value
        raise KeyError(normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "phase_id": self.phase_id,
            "scope_path": list(self.scope_path),
            "consumer": self.consumer,
            "worker_id": self.worker_id,
            "thread_id": self.thread_id,
            "succeeded": self.succeeded,
            "metrics": {
                name: metric.to_dict()
                for name, metric in self.metrics
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        expected = {
            "phase_id",
            "scope_path",
            "consumer",
            "worker_id",
            "thread_id",
            "succeeded",
            "metrics",
        }
        if set(value) != expected:
            raise ValueError("invalid measurement sample fields")
        raw_path = value.get("scope_path")
        raw_metrics = value.get("metrics")
        if not isinstance(raw_path, list) or not isinstance(raw_metrics, Mapping):
            raise ValueError("invalid measurement sample")
        if not all(isinstance(item, str) for item in raw_path):
            raise ValueError("measurement scope path must contain strings")
        raw_thread_id = value.get("thread_id")
        raw_succeeded = value.get("succeeded")
        if (
            not isinstance(raw_thread_id, int)
            or isinstance(raw_thread_id, bool)
        ):
            raise ValueError("measurement thread identifier must be an integer")
        if not isinstance(raw_succeeded, bool):
            raise ValueError("measurement outcome must be a boolean")
        if not all(
            isinstance(name, str) and isinstance(metric, Mapping)
            for name, metric in raw_metrics.items()
        ):
            raise ValueError("measurement metrics must be an object of metric values")
        return cls(
            phase_id=_string(value.get("phase_id"), label="sample phase"),
            scope_path=tuple(raw_path),
            consumer=_string(value.get("consumer"), label="sample consumer"),
            worker_id=_string(value.get("worker_id"), label="sample worker"),
            thread_id=raw_thread_id,
            succeeded=raw_succeeded,
            metrics=tuple(
                (name, MetricValue.from_dict(metric))
                for name, metric in raw_metrics.items()
            ),
        )


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    """Status-aware deterministic aggregation for a single metric."""

    name: str
    unit: MetricUnit
    aggregation: MetricAggregation
    measured_count: int
    unsupported_count: int
    unavailable_count: int
    total: int | float | None
    minimum: int | float | None
    maximum: int | float | None
    average: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", stable_identifier(self.name, label="metric name"))
        if not isinstance(self.unit, MetricUnit):
            raise TypeError("aggregate unit must be a MetricUnit")
        if not isinstance(self.aggregation, MetricAggregation):
            raise TypeError("aggregate strategy must be a MetricAggregation")
        for name in ("measured_count", "unsupported_count", "unavailable_count"):
            _non_negative_integer(getattr(self, name), label=f"aggregate {name}")
        for name in ("total", "minimum", "maximum", "average"):
            raw = getattr(self, name)
            if raw is not None and (
                not isinstance(raw, (int, float))
                or isinstance(raw, bool)
                or (isinstance(raw, float) and not math.isfinite(raw))
            ):
                raise ValueError(f"aggregate {name} must be finite numeric or null")
        if self.aggregation is MetricAggregation.DISTRIBUTION and self.total is not None:
            raise ValueError("distribution aggregates cannot claim an additive total")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "unit": self.unit.value,
            "aggregation": self.aggregation.value,
            "measured_count": self.measured_count,
            "unsupported_count": self.unsupported_count,
            "unavailable_count": self.unavailable_count,
            "total": self.total,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "average": self.average,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        expected = {
            "name",
            "unit",
            "aggregation",
            "measured_count",
            "unsupported_count",
            "unavailable_count",
            "total",
            "minimum",
            "maximum",
            "average",
        }
        if set(value) != expected:
            raise ValueError("invalid metric aggregate fields")

        def optional_number(name: str) -> int | float | None:
            raw = value.get(name)
            if raw is None:
                return None
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise ValueError(f"aggregate {name} must be numeric or null")
            return raw

        raw_average = optional_number("average")
        return cls(
            name=stable_identifier(
                _string(value.get("name"), label="metric name"),
                label="metric name",
            ),
            unit=MetricUnit(_string(value.get("unit"), label="aggregate unit")),
            aggregation=MetricAggregation(
                _string(value.get("aggregation"), label="aggregate strategy")
            ),
            measured_count=_non_negative_integer(
                value.get("measured_count"), label="aggregate measured_count"
            ),
            unsupported_count=_non_negative_integer(
                value.get("unsupported_count"), label="aggregate unsupported_count"
            ),
            unavailable_count=_non_negative_integer(
                value.get("unavailable_count"), label="aggregate unavailable_count"
            ),
            total=optional_number("total"),
            minimum=optional_number("minimum"),
            maximum=optional_number("maximum"),
            average=None if raw_average is None else float(raw_average),
        )


@dataclass(frozen=True, slots=True)
class PhaseAggregate:
    phase_id: str
    sample_count: int
    succeeded_count: int
    failed_count: int
    metrics: tuple[MetricAggregate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase_id", phase_identifier(self.phase_id))
        for name in ("sample_count", "succeeded_count", "failed_count"):
            _non_negative_integer(getattr(self, name), label=f"phase {name}")
        if self.succeeded_count + self.failed_count != self.sample_count:
            raise ValueError("phase outcome counts must equal the sample count")
        if not all(isinstance(item, MetricAggregate) for item in self.metrics):
            raise TypeError("phase metrics must contain MetricAggregate instances")

    def to_dict(self) -> dict[str, object]:
        return {
            "phase_id": self.phase_id,
            "sample_count": self.sample_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "metrics": [item.to_dict() for item in self.metrics],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        expected = {
            "phase_id",
            "sample_count",
            "succeeded_count",
            "failed_count",
            "metrics",
        }
        if set(value) != expected:
            raise ValueError("invalid phase aggregate fields")
        raw_metrics = value.get("metrics")
        if not isinstance(raw_metrics, list) or not all(
            isinstance(item, Mapping) for item in raw_metrics
        ):
            raise ValueError("aggregate metrics must be a list")
        return cls(
            phase_id=phase_identifier(
                _string(value.get("phase_id"), label="aggregate phase")
            ),
            sample_count=_non_negative_integer(
                value.get("sample_count"), label="phase sample_count"
            ),
            succeeded_count=_non_negative_integer(
                value.get("succeeded_count"), label="phase succeeded_count"
            ),
            failed_count=_non_negative_integer(
                value.get("failed_count"), label="phase failed_count"
            ),
            metrics=tuple(
                MetricAggregate.from_dict(item)
                for item in raw_metrics
            ),
        )


FILESYSTEM_COUNTERS = (
    "directory_enumerations",
    "metadata_lookups",
    "measurement_metadata_lookups",
    "path_normalizations",
    "content_reads",
    "bytes_read",
    "content_read_bytes_unavailable",
    "consumer_unique_content_resources",
    "consumer_repeated_content_reads",
    "hashes",
    "descriptor_parses",
    "language_parses",
)


_SUM_METRICS = frozenset({
    "units_processed",
    "bytes_processed",
    "objects_produced",
})
_SAMPLE_SUM_METRICS = frozenset({
    "wall_time_ns",
    "process_cpu_time_ns",
    "thread_cpu_time_ns",
    "queue_wait_ns",
    "service_time_ns",
    "idle_time_ns",
})


def metric_aggregation(name: str) -> MetricAggregation:
    """Return the conservative aggregation contract for one metric.

    Unknown extension metrics default to a distribution.  This avoids silently
    treating a gauge, ratio, or process-wide observation as additive.
    """

    normalized = stable_identifier(name, label="metric name")
    if normalized in _SUM_METRICS:
        return MetricAggregation.SUM
    if normalized in _SAMPLE_SUM_METRICS:
        return MetricAggregation.SAMPLE_SUM
    return MetricAggregation.DISTRIBUTION


@dataclass(frozen=True, slots=True)
class FilesystemConsumerMetrics:
    consumer: str
    directory_enumerations: int = 0
    metadata_lookups: int = 0
    measurement_metadata_lookups: int = 0
    path_normalizations: int = 0
    content_reads: int = 0
    bytes_read: int = 0
    content_read_bytes_unavailable: int = 0
    consumer_unique_content_resources: int = 0
    consumer_repeated_content_reads: int = 0
    hashes: int = 0
    descriptor_parses: int = 0
    language_parses: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "consumer",
            stable_identifier(self.consumer, label="filesystem consumer"),
        )
        for name in FILESYSTEM_COUNTERS:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"filesystem counter {name} must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer": self.consumer,
            **{name: getattr(self, name) for name in FILESYSTEM_COUNTERS},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        expected = {"consumer", *FILESYSTEM_COUNTERS}
        if set(value) != expected:
            raise ValueError("invalid filesystem consumer fields")
        return cls(
            consumer=_string(value.get("consumer"), label="filesystem consumer"),
            **{
                name: _non_negative_integer(
                    value.get(name), label=f"filesystem counter {name}"
                )
                for name in FILESYSTEM_COUNTERS
            },
        )


@dataclass(frozen=True, slots=True)
class FilesystemConsumerOverlap:
    """Source-free count of resources read by the same consumer pair."""

    consumers: tuple[str, str]
    observed_resources: int

    def __post_init__(self) -> None:
        consumers = tuple(
            sorted(
                stable_identifier(item, label="filesystem consumer")
                for item in self.consumers
            )
        )
        if len(consumers) != 2 or consumers[0] == consumers[1]:
            raise ValueError("filesystem overlap requires two distinct consumers")
        object.__setattr__(self, "consumers", consumers)
        _non_negative_integer(
            self.observed_resources,
            label="filesystem overlap resource count",
        )
        if self.observed_resources == 0:
            raise ValueError("filesystem overlap resource count must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "consumers": list(self.consumers),
            "observed_resources": self.observed_resources,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        if set(value) != {"consumers", "observed_resources"}:
            raise ValueError("invalid filesystem overlap fields")
        raw = value.get("consumers")
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(item, str) for item in raw)
        ):
            raise ValueError("filesystem overlap consumers must be two strings")
        return cls(
            (raw[0], raw[1]),
            _non_negative_integer(
                value.get("observed_resources"),
                label="filesystem overlap resource count",
            ),
        )


@dataclass(frozen=True, slots=True)
class FilesystemLedgerSnapshot:
    """Immutable aggregate of a run-local filesystem ledger."""

    consumers: tuple[FilesystemConsumerMetrics, ...] = ()
    observed_unique_content_resources: int = 0
    observed_content_reads: int = 0
    overlaps: tuple[FilesystemConsumerOverlap, ...] = ()
    coverage_status: str = "unavailable"
    coverage_reason: str = "collection-disabled"
    resource_tracking_limit: int = 100_000
    resource_limit_reached: bool = False
    untracked_content_reads: int = 0

    def __post_init__(self) -> None:
        consumers = tuple(sorted(self.consumers, key=lambda item: item.consumer))
        if len({item.consumer for item in consumers}) != len(consumers):
            raise ValueError("filesystem ledger contains duplicate consumers")
        object.__setattr__(self, "consumers", consumers)
        _non_negative_integer(
            self.observed_unique_content_resources,
            label="observed unique content resources",
        )
        _non_negative_integer(
            self.observed_content_reads,
            label="observed content reads",
        )
        if self.observed_unique_content_resources > self.observed_content_reads:
            raise ValueError("unique content resources cannot exceed content reads")
        overlaps = tuple(sorted(self.overlaps, key=lambda item: item.consumers))
        if (
            not all(isinstance(item, FilesystemConsumerOverlap) for item in overlaps)
            or len({item.consumers for item in overlaps}) != len(overlaps)
        ):
            raise ValueError("filesystem overlaps must be unique overlap metrics")
        object.__setattr__(self, "overlaps", overlaps)
        allowed_coverage = {
            ("partial", "explicit-instrumentation-boundaries"),
            ("unavailable", "collection-disabled"),
        }
        if (self.coverage_status, self.coverage_reason) not in allowed_coverage:
            raise ValueError("invalid filesystem ledger coverage")
        if (
            not isinstance(self.resource_tracking_limit, int)
            or isinstance(self.resource_tracking_limit, bool)
            or self.resource_tracking_limit < 1
        ):
            raise ValueError("filesystem resource tracking limit must be positive")
        if not isinstance(self.resource_limit_reached, bool):
            raise TypeError("filesystem resource limit state must be a boolean")
        _non_negative_integer(
            self.untracked_content_reads,
            label="untracked content read count",
        )
        total_content_reads = sum(item.content_reads for item in consumers)
        if (
            self.observed_content_reads + self.untracked_content_reads
            != total_content_reads
        ):
            raise ValueError(
                "observed and untracked content reads must equal filesystem totals"
            )
        tracked_consumer_reads = sum(
            item.consumer_unique_content_resources
            + item.consumer_repeated_content_reads
            for item in consumers
        )
        if tracked_consumer_reads != self.observed_content_reads:
            raise ValueError(
                "consumer tracked content reads must equal observed content reads"
            )
        consumers_by_name = {item.consumer: item for item in consumers}
        for consumer in consumers:
            tracked = (
                consumer.consumer_unique_content_resources
                + consumer.consumer_repeated_content_reads
            )
            if tracked > consumer.content_reads:
                raise ValueError(
                    "consumer tracked reads cannot exceed consumer content reads"
                )
            if (
                consumer.consumer_unique_content_resources
                > self.observed_unique_content_resources
            ):
                raise ValueError(
                    "consumer unique resources cannot exceed global resources"
                )
        for overlap in overlaps:
            left = consumers_by_name.get(overlap.consumers[0])
            right = consumers_by_name.get(overlap.consumers[1])
            if left is None or right is None:
                raise ValueError("filesystem overlap references an unknown consumer")
            if overlap.observed_resources > min(
                left.consumer_unique_content_resources,
                right.consumer_unique_content_resources,
            ):
                raise ValueError("filesystem overlap exceeds consumer resources")
        if self.observed_unique_content_resources > self.resource_tracking_limit:
            raise ValueError("tracked filesystem resources exceed the configured limit")
        if (
            self.resource_limit_reached
            and self.observed_unique_content_resources < self.resource_tracking_limit
        ):
            raise ValueError("filesystem resource limit state is inconsistent")
        if self.coverage_status == "unavailable" and (
            consumers
            or self.observed_unique_content_resources
            or self.observed_content_reads
            or overlaps
            or self.resource_limit_reached
            or self.untracked_content_reads
        ):
            raise ValueError(
                "unavailable filesystem coverage cannot contain observations"
            )

    @property
    def totals(self) -> dict[str, int]:
        return {
            name: sum(getattr(item, name) for item in self.consumers)
            for name in FILESYSTEM_COUNTERS
        }

    def to_dict(self) -> dict[str, object]:
        if self.coverage_status == "unavailable":
            tracking_status = "unavailable"
            tracking_reason: str | None = "collection-disabled"
        elif self.untracked_content_reads:
            tracking_status = "partial"
            tracking_reason = (
                "resource-limit-reached"
                if self.resource_limit_reached
                else "identity-unavailable"
            )
        else:
            tracking_status = "measured"
            tracking_reason = None
        return {
            "coverage": {
                "status": self.coverage_status,
                "reason": self.coverage_reason,
            },
            "content_resources": {
                "observed_reads": self.observed_content_reads,
                "observed_repeated_reads": (
                    self.observed_content_reads
                    - self.observed_unique_content_resources
                ),
                "observed_unique": self.observed_unique_content_resources,
                "consumer_overlaps": [item.to_dict() for item in self.overlaps],
                "resource_limit_reached": self.resource_limit_reached,
                "resource_tracking_limit": self.resource_tracking_limit,
                "tracking_status": tracking_status,
                "tracking_reason": tracking_reason,
                "untracked_reads": self.untracked_content_reads,
            },
            "totals": self.totals,
            "consumers": [item.to_dict() for item in self.consumers],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        if set(value) != {
            "coverage",
            "content_resources",
            "totals",
            "consumers",
        }:
            raise ValueError("invalid filesystem ledger fields")
        raw_coverage = value.get("coverage")
        if (
            not isinstance(raw_coverage, Mapping)
            or set(raw_coverage) != {"status", "reason"}
            or not isinstance(raw_coverage.get("status"), str)
            or not isinstance(raw_coverage.get("reason"), str)
        ):
            raise ValueError("invalid filesystem ledger coverage")
        raw = value.get("consumers")
        raw_totals = value.get("totals")
        raw_resources = value.get("content_resources")
        if (
            not isinstance(raw, list)
            or not all(isinstance(item, Mapping) for item in raw)
            or not isinstance(raw_totals, Mapping)
            or set(raw_totals) != set(FILESYSTEM_COUNTERS)
            or not isinstance(raw_resources, Mapping)
            or set(raw_resources) != {
                "observed_reads",
                "observed_repeated_reads",
                "observed_unique",
                "consumer_overlaps",
                "resource_limit_reached",
                "resource_tracking_limit",
                "tracking_reason",
                "tracking_status",
                "untracked_reads",
            }
        ):
            raise ValueError("filesystem consumers must be a list")
        raw_overlaps = raw_resources.get("consumer_overlaps")
        if not isinstance(raw_overlaps, list) or not all(
            isinstance(item, Mapping) for item in raw_overlaps
        ):
            raise ValueError("filesystem consumer overlaps must be a list")
        for name in FILESYSTEM_COUNTERS:
            _non_negative_integer(
                raw_totals.get(name), label=f"filesystem total {name}"
            )
        observed_reads = _non_negative_integer(
            raw_resources.get("observed_reads"),
            label="observed content reads",
        )
        observed_repeated = _non_negative_integer(
            raw_resources.get("observed_repeated_reads"),
            label="observed repeated content reads",
        )
        observed_unique = _non_negative_integer(
            raw_resources.get("observed_unique"),
            label="observed unique content resources",
        )
        if observed_repeated != observed_reads - observed_unique:
            raise ValueError("filesystem repeated content read count is inconsistent")
        resource_tracking_limit = _non_negative_integer(
            raw_resources.get("resource_tracking_limit"),
            label="filesystem resource tracking limit",
        )
        untracked_reads = _non_negative_integer(
            raw_resources.get("untracked_reads"),
            label="untracked content read count",
        )
        resource_limit_reached = raw_resources.get("resource_limit_reached")
        if not isinstance(resource_limit_reached, bool):
            raise ValueError("filesystem resource limit state must be a boolean")
        coverage_status = raw_coverage["status"]
        if coverage_status == "unavailable":
            expected_tracking_status = "unavailable"
            expected_tracking_reason: str | None = "collection-disabled"
        elif untracked_reads:
            expected_tracking_status = "partial"
            expected_tracking_reason = (
                "resource-limit-reached"
                if resource_limit_reached
                else "identity-unavailable"
            )
        else:
            expected_tracking_status = "measured"
            expected_tracking_reason = None
        if raw_resources.get("tracking_status") != expected_tracking_status:
            raise ValueError("filesystem resource tracking status is inconsistent")
        if raw_resources.get("tracking_reason") != expected_tracking_reason:
            raise ValueError("filesystem resource tracking reason is inconsistent")
        result = cls(
            consumers=tuple(
                FilesystemConsumerMetrics.from_dict(item) for item in raw
            ),
            observed_unique_content_resources=observed_unique,
            observed_content_reads=observed_reads,
            overlaps=tuple(
                FilesystemConsumerOverlap.from_dict(item)
                for item in raw_overlaps
            ),
            coverage_status=coverage_status,
            coverage_reason=raw_coverage["reason"],
            resource_tracking_limit=resource_tracking_limit,
            resource_limit_reached=resource_limit_reached,
            untracked_content_reads=untracked_reads,
        )
        if dict(raw_totals) != result.totals:
            raise ValueError("filesystem totals do not match consumer counters")
        return result


def aggregate_samples(samples: Iterable[MeasurementSample]) -> tuple[PhaseAggregate, ...]:
    """Aggregate samples by stable phase identifier without inferring missing data."""

    grouped: dict[str, list[MeasurementSample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.phase_id].append(sample)
    result: list[PhaseAggregate] = []
    for phase_id in sorted(grouped):
        phase_samples = grouped[phase_id]
        metrics: dict[str, list[MetricValue]] = defaultdict(list)
        for sample in phase_samples:
            for name, metric in sample.metrics:
                metrics[name].append(metric)
        metric_aggregates: list[MetricAggregate] = []
        for name in sorted(metrics):
            observations = metrics[name]
            units = {item.unit for item in observations}
            if len(units) != 1:
                raise ValueError(f"inconsistent units for metric {name}")
            measured = [
                item.value
                for item in observations
                if item.status is MetricStatus.MEASURED
            ]
            numeric = [item for item in measured if item is not None]
            aggregation = metric_aggregation(name)
            sample_sum = sum(numeric) if numeric else None
            total = (
                sample_sum
                if aggregation is not MetricAggregation.DISTRIBUTION
                else None
            )
            metric_aggregates.append(MetricAggregate(
                name=name,
                unit=next(iter(units)),
                aggregation=aggregation,
                measured_count=len(numeric),
                unsupported_count=sum(
                    item.status is MetricStatus.UNSUPPORTED for item in observations
                ),
                unavailable_count=sum(
                    item.status is MetricStatus.UNAVAILABLE for item in observations
                ),
                total=total,
                minimum=min(numeric) if numeric else None,
                maximum=max(numeric) if numeric else None,
                average=(
                    float(sample_sum) / len(numeric)
                    if numeric and sample_sum is not None
                    else None
                ),
            ))
        result.append(PhaseAggregate(
            phase_id=phase_id,
            sample_count=len(phase_samples),
            succeeded_count=sum(item.succeeded for item in phase_samples),
            failed_count=sum(not item.succeeded for item in phase_samples),
            metrics=tuple(metric_aggregates),
        ))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class MeasurementSampling:
    """Source-free coverage for deterministic scope down-sampling."""

    status: MetricStatus = MetricStatus.UNAVAILABLE
    sample_every: int = 1
    eligible_scopes: int = 0
    sampled_scopes: int = 0
    phases: tuple["MeasurementPhaseSampling", ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, MetricStatus):
            raise TypeError("sampling status must be a MetricStatus")
        if self.status not in {MetricStatus.MEASURED, MetricStatus.UNAVAILABLE}:
            raise ValueError("sampling status must be measured or unavailable")
        if (
            not isinstance(self.sample_every, int)
            or isinstance(self.sample_every, bool)
            or self.sample_every < 1
        ):
            raise ValueError("sampling interval must be a positive integer")
        _non_negative_integer(self.eligible_scopes, label="eligible scope count")
        _non_negative_integer(self.sampled_scopes, label="sampled scope count")
        if self.sampled_scopes > self.eligible_scopes:
            raise ValueError("sampled scopes cannot exceed eligible scopes")
        if self.status is MetricStatus.UNAVAILABLE and (
            self.eligible_scopes or self.sampled_scopes or self.phases
        ):
            raise ValueError("unavailable sampling cannot contain observations")
        if self.sample_every == 1 and self.sampled_scopes != self.eligible_scopes:
            raise ValueError("unsampled scopes are invalid when sample_every is one")
        phases = tuple(sorted(self.phases, key=lambda item: item.phase_id))
        if (
            not all(isinstance(item, MeasurementPhaseSampling) for item in phases)
            or len({item.phase_id for item in phases}) != len(phases)
        ):
            raise ValueError("sampling phase coverage must be unique")
        object.__setattr__(self, "phases", phases)
        if sum(item.eligible_scopes for item in phases) != self.eligible_scopes:
            raise ValueError("sampling phase eligible counts must match the total")
        if sum(item.sampled_scopes for item in phases) != self.sampled_scopes:
            raise ValueError("sampling phase sampled counts must match the total")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "status": self.status.value,
            "strategy": "deterministic-hash",
            "sample_every": self.sample_every,
            "eligible_scopes": self.eligible_scopes,
            "sampled_scopes": self.sampled_scopes,
            "phases": [item.to_dict() for item in self.phases],
        }
        if self.status is MetricStatus.UNAVAILABLE:
            value["reason"] = MetricReason.COLLECTION_DISABLED.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        raw_status = MetricStatus(
            _string(value.get("status"), label="sampling status")
        )
        expected = {
            "status",
            "strategy",
            "sample_every",
            "eligible_scopes",
            "sampled_scopes",
            "phases",
        }
        if raw_status is MetricStatus.UNAVAILABLE:
            expected.add("reason")
            if value.get("reason") != MetricReason.COLLECTION_DISABLED.value:
                raise ValueError("invalid unavailable sampling reason")
        if set(value) != expected or value.get("strategy") != "deterministic-hash":
            raise ValueError("invalid sampling fields")
        raw_phases = value.get("phases")
        if not isinstance(raw_phases, list) or not all(
            isinstance(item, Mapping) for item in raw_phases
        ):
            raise ValueError("sampling phases must be a list")
        return cls(
            raw_status,
            _non_negative_integer(
                value.get("sample_every"), label="sampling interval"
            ),
            _non_negative_integer(
                value.get("eligible_scopes"), label="eligible scope count"
            ),
            _non_negative_integer(
                value.get("sampled_scopes"), label="sampled scope count"
            ),
            tuple(MeasurementPhaseSampling.from_dict(item) for item in raw_phases),
        )


@dataclass(frozen=True, slots=True)
class MeasurementPhaseSampling:
    phase_id: str
    eligible_scopes: int
    sampled_scopes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase_id", phase_identifier(self.phase_id))
        _non_negative_integer(
            self.eligible_scopes,
            label="phase eligible scope count",
        )
        _non_negative_integer(
            self.sampled_scopes,
            label="phase sampled scope count",
        )
        if self.sampled_scopes > self.eligible_scopes:
            raise ValueError("phase sampled scopes cannot exceed eligible scopes")

    def to_dict(self) -> dict[str, object]:
        return {
            "phase_id": self.phase_id,
            "eligible_scopes": self.eligible_scopes,
            "sampled_scopes": self.sampled_scopes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        if set(value) != {"phase_id", "eligible_scopes", "sampled_scopes"}:
            raise ValueError("invalid phase sampling fields")
        return cls(
            _string(value.get("phase_id"), label="sampling phase"),
            _non_negative_integer(
                value.get("eligible_scopes"),
                label="phase eligible scope count",
            ),
            _non_negative_integer(
                value.get("sampled_scopes"),
                label="phase sampled scope count",
            ),
        )


@dataclass(frozen=True, slots=True)
class MeasurementReport:
    """Versioned, portable measurement artifact for a single Atlas run."""

    samples: tuple[MeasurementSample, ...]
    filesystem: FilesystemLedgerSnapshot = FilesystemLedgerSnapshot()
    sampling: MeasurementSampling = MeasurementSampling()
    schema_version: int = MEASUREMENT_SCHEMA_VERSION
    producer: str = MEASUREMENT_PRODUCER

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != MEASUREMENT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported performance measurement schema")
        if not isinstance(self.producer, str) or self.producer != MEASUREMENT_PRODUCER:
            raise ValueError("unsupported performance measurement producer")
        if not isinstance(self.filesystem, FilesystemLedgerSnapshot):
            raise TypeError("measurement filesystem must be a ledger snapshot")
        if not isinstance(self.sampling, MeasurementSampling):
            raise TypeError("measurement sampling must be MeasurementSampling")
        if not all(isinstance(item, MeasurementSample) for item in self.samples):
            raise TypeError("measurement samples must contain MeasurementSample instances")
        if self.sampling.status is MetricStatus.UNAVAILABLE and self.samples:
            raise ValueError("unavailable sampling cannot contain measurement samples")
        if len(self.samples) > self.sampling.sampled_scopes:
            raise ValueError("measurement samples exceed sampled scope coverage")
        sampled_by_phase = {
            item.phase_id: item.sampled_scopes
            for item in self.sampling.phases
        }
        observed_by_phase: dict[str, int] = defaultdict(int)
        for sample in self.samples:
            observed_by_phase[sample.phase_id] += 1
        if any(
            phase_id not in sampled_by_phase
            or count > sampled_by_phase[phase_id]
            for phase_id, count in observed_by_phase.items()
        ):
            raise ValueError("measurement samples contradict phase sampling coverage")
        object.__setattr__(self, "samples", tuple(sorted(
            self.samples,
            key=lambda item: (
                item.scope_path,
                item.phase_id,
                item.consumer,
                item.worker_id,
                item.thread_id,
                item.succeeded,
                json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":")),
            ),
        )))

    @property
    def aggregates(self) -> tuple[PhaseAggregate, ...]:
        return aggregate_samples(self.samples)

    @property
    def phase_statuses(self) -> tuple[dict[str, str], ...]:
        """Report phase coverage without interpreting a missing observation."""

        observed = {item.phase_id for item in self.samples}
        sampling = {item.phase_id: item for item in self.sampling.phases}
        phase_ids = sorted(set(STABLE_PHASE_IDS) | observed | set(sampling))
        statuses: list[dict[str, str]] = []
        for phase_id in phase_ids:
            if phase_id in observed:
                statuses.append({
                    "phase_id": phase_id,
                    "status": MetricStatus.MEASURED.value,
                })
            elif self.sampling.status is MetricStatus.UNAVAILABLE:
                statuses.append({
                    "phase_id": phase_id,
                    "status": MetricStatus.UNAVAILABLE.value,
                    "reason": MetricReason.COLLECTION_DISABLED.value,
                })
            elif (
                (coverage := sampling.get(phase_id)) is not None
                and coverage.eligible_scopes > 0
                and coverage.sampled_scopes == 0
            ):
                statuses.append({
                    "phase_id": phase_id,
                    "status": MetricStatus.UNAVAILABLE.value,
                    "reason": MetricReason.SAMPLED_OUT.value,
                })
            else:
                statuses.append({
                    "phase_id": phase_id,
                    "status": MetricStatus.UNAVAILABLE.value,
                    "reason": MetricReason.NOT_RECORDED.value,
                })
        return tuple(statuses)

    def to_dict(self) -> dict[str, object]:
        observed = {item.phase_id for item in self.samples}
        eligible = {item.phase_id for item in self.sampling.phases}
        return {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "phase_ids": sorted(set(STABLE_PHASE_IDS) | observed | eligible),
            "phase_status": list(self.phase_statuses),
            "samples": [item.to_dict() for item in self.samples],
            "sampling": self.sampling.to_dict(),
            "aggregates": [item.to_dict() for item in self.aggregates],
            "filesystem": self.filesystem.to_dict(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            sort_keys=True,
        ) + "\n"

    def to_text(self) -> str:
        """Render a deterministic summary that never hides missing observations."""

        lines = [
            "Atlas performance measurements",
            f"schema: {self.schema_version}",
            f"producer: {self.producer}",
            f"samples: {len(self.samples)}",
            "sampling: "
            f"status={self.sampling.status.value}, "
            f"sample_every={self.sampling.sample_every}, "
            f"eligible={self.sampling.eligible_scopes}, "
            f"sampled={self.sampling.sampled_scopes}",
            "phases:",
        ]
        if not self.aggregates:
            lines.append("- none measured")
        for aggregate in self.aggregates:
            lines.append(
                f"- {aggregate.phase_id}: samples={aggregate.sample_count}, "
                f"succeeded={aggregate.succeeded_count}, failed={aggregate.failed_count}"
            )
            for metric in aggregate.metrics:
                measured = (
                    "none"
                    if metric.measured_count == 0
                    else ", ".join(
                        (
                            f"count={metric.measured_count}",
                            *(
                                (f"total={metric.total}",)
                                if metric.total is not None
                                else ()
                            ),
                            f"minimum={metric.minimum}",
                            f"maximum={metric.maximum}",
                            f"average={metric.average} {metric.unit.value}",
                            f"aggregation={metric.aggregation.value}",
                        )
                    )
                )
                lines.append(
                    f"  {metric.name}: measured={measured}; "
                    f"unsupported={metric.unsupported_count}; "
                    f"unavailable={metric.unavailable_count}"
                )
        missing = [
            item
            for item in self.phase_statuses
            if item["status"] != MetricStatus.MEASURED.value
        ]
        lines.append("unobserved phases:")
        if not missing:
            lines.append("- none")
        for item in missing:
            lines.append(
                f"- {item['phase_id']}: {item['status']} "
                f"({item['reason']})"
            )
        totals = self.filesystem.totals
        lines.append(
            "filesystem: "
            f"{self.filesystem.coverage_status} "
            f"({self.filesystem.coverage_reason})"
        )
        lines.append(
            "- observed_content_resources: "
            f"reads={self.filesystem.observed_content_reads}, "
            f"unique={self.filesystem.observed_unique_content_resources}, "
            "repeated="
            f"{self.filesystem.observed_content_reads - self.filesystem.observed_unique_content_resources}"
        )
        resources = self.filesystem.to_dict()["content_resources"]
        lines.append(
            "- content_resource_tracking: "
            f"{resources['tracking_status']} "
            f"(reason={resources['tracking_reason']}, "
            f"limit={resources['resource_tracking_limit']}, "
            f"limit_reached={resources['resource_limit_reached']}, "
            f"untracked_reads={resources['untracked_reads']})"
        )
        for name in FILESYSTEM_COUNTERS:
            lines.append(f"- {name}: {totals[name]}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        expected_fields = {
            "schema_version",
            "producer",
            "phase_ids",
            "phase_status",
            "samples",
            "sampling",
            "aggregates",
            "filesystem",
        }
        if set(value) != expected_fields:
            raise ValueError("invalid performance measurement report fields")
        raw_schema = value.get("schema_version")
        if (
            not isinstance(raw_schema, int)
            or isinstance(raw_schema, bool)
            or raw_schema != MEASUREMENT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported performance measurement schema")
        if str(value.get("producer", "")) != MEASUREMENT_PRODUCER:
            raise ValueError("unsupported performance measurement producer")
        raw_samples = value.get("samples")
        raw_filesystem = value.get("filesystem")
        raw_sampling = value.get("sampling")
        if (
            not isinstance(raw_samples, list)
            or not isinstance(raw_filesystem, Mapping)
            or not isinstance(raw_sampling, Mapping)
        ):
            raise ValueError("invalid performance measurement report")
        report = cls(
            samples=tuple(
                MeasurementSample.from_dict(item)
                for item in raw_samples
                if isinstance(item, Mapping)
            ),
            filesystem=FilesystemLedgerSnapshot.from_dict(raw_filesystem),
            sampling=MeasurementSampling.from_dict(raw_sampling),
        )
        canonical = report.to_dict()
        for field in (
            "phase_ids",
            "phase_status",
            "samples",
            "sampling",
            "aggregates",
            "filesystem",
        ):
            if value.get(field) != canonical[field]:
                raise ValueError(
                    f"performance measurement {field} is not canonical"
                )
        return report
