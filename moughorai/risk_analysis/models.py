from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math

from moughorai.semantic_evidence import (
    ConfidenceResult,
    EvidenceIndex,
    EvidenceRecord,
)


class RiskMetricKind(str, Enum):
    COMPLEXITY = "complexity"
    FAN_IN = "fan_in"
    FAN_OUT = "fan_out"
    CHANGE_FREQUENCY = "change_frequency"
    OWNERSHIP_CONCENTRATION = "ownership_concentration"
    LOW_TEST_DENSITY = "low_test_density"
    SIZE = "size"


class RiskAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class RiskScope(str, Enum):
    PRODUCTION = "production"
    TEST = "test"
    GENERATED = "generated"
    UNKNOWN = "unknown"


class RiskTrend(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    UNAVAILABLE = "unavailable"


DEFAULT_RISK_WEIGHTS: tuple[tuple[RiskMetricKind, float], ...] = (
    (RiskMetricKind.COMPLEXITY, 0.25),
    (RiskMetricKind.FAN_IN, 0.20),
    (RiskMetricKind.FAN_OUT, 0.15),
    (RiskMetricKind.CHANGE_FREQUENCY, 0.15),
    (RiskMetricKind.OWNERSHIP_CONCENTRATION, 0.10),
    (RiskMetricKind.LOW_TEST_DENSITY, 0.10),
    (RiskMetricKind.SIZE, 0.05),
)

_SEMANTIC_IDENTIFIER_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@+-"
)


@dataclass(frozen=True, slots=True)
class RiskConfiguration:
    top_k: int = 25
    git_commit_limit: int = 200
    percentile_cohort_minimum: int = 20
    include_test: bool = False
    include_generated: bool = False
    include_unknown: bool = False
    weights: tuple[tuple[RiskMetricKind, float], ...] = DEFAULT_RISK_WEIGHTS
    normalization_version: str = "atlas-pr132-normalization/1"

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("risk top_k must be positive")
        if self.git_commit_limit < 0:
            raise ValueError("Git commit limit must be non-negative")
        if self.percentile_cohort_minimum < 2:
            raise ValueError("percentile cohort minimum must be at least 2")
        normalized = tuple(sorted(
            ((RiskMetricKind(kind), float(weight)) for kind, weight in self.weights),
            key=lambda item: item[0].value,
        ))
        if (
            len(normalized) != len(RiskMetricKind)
            or {kind for kind, _ in normalized} != set(RiskMetricKind)
        ):
            raise ValueError("risk weights must define every PR132 metric exactly once")
        if any(not math.isfinite(weight) or weight < 0 for _, weight in normalized):
            raise ValueError("risk weights must be finite and non-negative")
        if sum(weight for _, weight in normalized) <= 0:
            raise ValueError("at least one risk weight must be positive")
        if not self.normalization_version.strip():
            raise ValueError("normalization version must not be empty")
        object.__setattr__(self, "weights", normalized)

    def weight(self, metric: RiskMetricKind) -> float:
        return next(weight for kind, weight in self.weights if kind is metric)

    def to_dict(self) -> dict[str, object]:
        return {
            "top_k": self.top_k,
            "git_commit_limit": self.git_commit_limit,
            "percentile_cohort_minimum": self.percentile_cohort_minimum,
            "include_test": self.include_test,
            "include_generated": self.include_generated,
            "include_unknown": self.include_unknown,
            "weights": {kind.value: weight for kind, weight in self.weights},
            "normalization_version": self.normalization_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskConfiguration:
        raw_weights = value.get("weights", {})
        weights = (
            tuple(
                (RiskMetricKind(str(kind)), float(weight))
                for kind, weight in raw_weights.items()
            )
            if isinstance(raw_weights, Mapping)
            else DEFAULT_RISK_WEIGHTS
        )
        return cls(
            int(value.get("top_k", 25)),
            int(value.get("git_commit_limit", 200)),
            int(value.get("percentile_cohort_minimum", 20)),
            bool(value.get("include_test", False)),
            bool(value.get("include_generated", False)),
            bool(value.get("include_unknown", False)),
            weights,
            str(value.get("normalization_version", "atlas-pr132-normalization/1")),
        )


@dataclass(frozen=True, slots=True)
class RiskMetricInput:
    """Structured producer input; higher values must mean higher risk."""

    subject_id: str
    metric: RiskMetricKind
    value: float
    unit: str
    producer: str
    evidence_records: tuple[EvidenceRecord, ...]
    window: str = "current-snapshot"
    coverage: float = 1.0
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.unit.strip() or not self.producer.strip():
            raise ValueError("risk metric inputs require subject, unit, and producer")
        for name, identifier in (("producer", self.producer), ("window", self.window)):
            if (
                len(identifier) > 256
                or not identifier
                or any(character not in _SEMANTIC_IDENTIFIER_CHARACTERS for character in identifier)
            ):
                raise ValueError(
                    f"risk metric {name} must be a bounded semantic identifier"
                )
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("risk metric values must be finite and non-negative")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("risk metric coverage must be between 0 and 1")
        if not self.evidence_records:
            raise ValueError("risk metric inputs require shared semantic evidence records")
        for record in self.evidence_records:
            if record.subject_id != self.subject_id:
                raise ValueError("risk metric evidence subject does not match the metric subject")
            if record.producer != self.producer:
                raise ValueError("risk metric evidence producer does not match the metric producer")
            canonical = EvidenceRecord.create(
                record.kind,
                record.subject_id,
                record.producer,
                record.snapshot_id,
                source_refs=record.source_refs,
                scope=record.scope,
                language=record.language,
                detail=record.detail,
                limitations=record.limitations,
                reliability=record.reliability,
                specificity=record.specificity,
            )
            if canonical != record:
                raise ValueError(
                    "risk metric evidence must have its canonical deterministic evidence ID"
                )
        object.__setattr__(
            self,
            "evidence_records",
            tuple(sorted(set(self.evidence_records))),
        )
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "metric": self.metric.value,
            "value": self.value,
            "unit": self.unit,
            "producer": self.producer,
            "evidence_records": [item.to_dict() for item in self.evidence_records],
            "window": self.window,
            "coverage": self.coverage,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskMetricInput:
        return cls(
            str(value["subject_id"]),
            RiskMetricKind(str(value["metric"])),
            float(value["value"]),
            str(value["unit"]),
            str(value["producer"]),
            tuple(
                EvidenceRecord.from_dict(item)
                for item in value.get("evidence_records", ())
                if isinstance(item, Mapping)
            ),
            str(value.get("window", "current-snapshot")),
            float(value.get("coverage", 1.0)),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, slots=True)
class RiskMetric:
    metric: RiskMetricKind
    status: RiskAvailability
    raw_value: float
    normalized_value: float
    unit: str
    window: str
    cohort: str
    producer: str
    coverage: float
    normalization: str
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("raw_value", "normalized_value", "coverage"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.raw_value < 0:
            raise ValueError("raw risk metric values must be non-negative")
        if not 0.0 <= self.normalized_value <= 1.0:
            raise ValueError("normalized risk metric must be between 0 and 1")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("risk metric coverage must be between 0 and 1")
        if self.status is RiskAvailability.UNAVAILABLE:
            raise ValueError("unavailable metrics are capabilities, not hotspot factors")
        if not self.evidence_ids:
            raise ValueError("scored risk metrics require evidence IDs")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric.value,
            "status": self.status.value,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "window": self.window,
            "cohort": self.cohort,
            "producer": self.producer,
            "coverage": self.coverage,
            "normalization": self.normalization,
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskMetric:
        return cls(
            RiskMetricKind(str(value["metric"])),
            RiskAvailability(str(value["status"])),
            float(value["raw_value"]),
            float(value["normalized_value"]),
            str(value["unit"]),
            str(value["window"]),
            str(value["cohort"]),
            str(value["producer"]),
            float(value["coverage"]),
            str(value["normalization"]),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, slots=True)
class RiskFactor:
    metric: RiskMetric
    configured_weight: float
    effective_weight: float
    contribution: float

    def __post_init__(self) -> None:
        for name in ("configured_weight", "effective_weight", "contribution"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.effective_weight > 1.0 or self.contribution > 1.0:
            raise ValueError("effective risk weight and contribution must not exceed 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric.to_dict(),
            "configured_weight": self.configured_weight,
            "effective_weight": self.effective_weight,
            "contribution": self.contribution,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskFactor:
        raw_metric = value.get("metric", {})
        if not isinstance(raw_metric, Mapping):
            raise TypeError("risk factor metric must be a mapping")
        return cls(
            RiskMetric.from_dict(raw_metric),
            float(value["configured_weight"]),
            float(value["effective_weight"]),
            float(value["contribution"]),
        )


@dataclass(frozen=True, slots=True)
class RiskHotspot:
    rank: int
    subject_id: str
    display_name: str
    project: str
    kind: str
    language: str
    scope: RiskScope
    cohort: str
    score: float
    confidence: ConfidenceResult
    factors: tuple[RiskFactor, ...]
    evidence_ids: tuple[str, ...]
    missing_signals: tuple[RiskMetricKind, ...]
    trend: RiskTrend
    explanation: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.rank <= 0:
            raise ValueError("risk hotspot rank must be positive")
        if not self.subject_id.strip() or not self.factors or not self.evidence_ids:
            raise ValueError("risk hotspots require a subject, factors, and evidence")
        if not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError("risk score must be finite and between 0 and 1")
        object.__setattr__(
            self,
            "factors",
            tuple(sorted(self.factors, key=lambda item: item.metric.metric.value)),
        )
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(
            self,
            "missing_signals",
            tuple(sorted(set(self.missing_signals), key=lambda item: item.value)),
        )
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "subject_id": self.subject_id,
            "display_name": self.display_name,
            "project": self.project,
            "kind": self.kind,
            "language": self.language,
            "scope": self.scope.value,
            "cohort": self.cohort,
            "score": self.score,
            "confidence": self.confidence.to_dict(),
            "factors": [item.to_dict() for item in self.factors],
            "evidence_ids": list(self.evidence_ids),
            "missing_signals": [item.value for item in self.missing_signals],
            "trend": self.trend.value,
            "explanation": self.explanation,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskHotspot:
        raw_confidence = value.get("confidence", {})
        if not isinstance(raw_confidence, Mapping):
            raise TypeError("risk hotspot confidence must be a mapping")
        return cls(
            int(value["rank"]),
            str(value["subject_id"]),
            str(value.get("display_name", value["subject_id"])),
            str(value.get("project", "repository")),
            str(value.get("kind", "unknown")),
            str(value.get("language", "unknown")),
            RiskScope(str(value.get("scope", RiskScope.UNKNOWN.value))),
            str(value.get("cohort", "unknown")),
            float(value["score"]),
            ConfidenceResult.from_dict(raw_confidence),
            tuple(
                RiskFactor.from_dict(item)
                for item in value.get("factors", ())
                if isinstance(item, Mapping)
            ),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(
                RiskMetricKind(str(item))
                for item in value.get("missing_signals", ())
            ),
            RiskTrend(str(value.get("trend", RiskTrend.UNAVAILABLE.value))),
            str(value.get("explanation", "Risk indicator based on available structured evidence.")),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, slots=True)
class RiskCapability:
    metric: RiskMetricKind
    status: RiskAvailability
    observation_count: int
    scored_subject_count: int
    scopes: tuple[str, ...]
    units: tuple[str, ...]
    producers: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    omitted_producer_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.observation_count < 0
            or self.scored_subject_count < 0
            or self.omitted_producer_count < 0
        ):
            raise ValueError("risk capability counts must be non-negative")
        for name in ("scopes", "units", "producers", "evidence_ids", "limitations"):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric.value,
            "status": self.status.value,
            "observation_count": self.observation_count,
            "scored_subject_count": self.scored_subject_count,
            "scopes": list(self.scopes),
            "units": list(self.units),
            "producers": list(self.producers),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "omitted_producer_count": self.omitted_producer_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskCapability:
        return cls(
            RiskMetricKind(str(value["metric"])),
            RiskAvailability(str(value["status"])),
            int(value.get("observation_count", 0)),
            int(value.get("scored_subject_count", 0)),
            tuple(map(str, value.get("scopes", ()))),
            tuple(map(str, value.get("units", ()))),
            tuple(map(str, value.get("producers", ()))),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
            int(value.get("omitted_producer_count", 0)),
        )


@dataclass(frozen=True, order=True, slots=True)
class RiskHeatmapBin:
    label: str
    count: int

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("risk heatmap bin label must not be empty")
        if self.count < 0:
            raise ValueError("risk heatmap bin count must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "count": self.count}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskHeatmapBin:
        return cls(str(value["label"]), int(value["count"]))


@dataclass(frozen=True, order=True, slots=True)
class RiskHeatmapCohort:
    cohort: str
    subject_count: int
    bins: tuple[RiskHeatmapBin, ...]

    def __post_init__(self) -> None:
        if not self.cohort.strip():
            raise ValueError("risk heatmap cohort must not be empty")
        if self.subject_count < 0:
            raise ValueError("risk heatmap subject count must be non-negative")
        ordered_bins = tuple(sorted(self.bins))
        if len({item.label for item in ordered_bins}) != len(ordered_bins):
            raise ValueError("risk heatmap bin labels must be unique")
        if sum(item.count for item in ordered_bins) != self.subject_count:
            raise ValueError("risk heatmap bin counts must equal the cohort subject count")
        object.__setattr__(self, "bins", ordered_bins)

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort": self.cohort,
            "subject_count": self.subject_count,
            "bins": [item.to_dict() for item in self.bins],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskHeatmapCohort:
        return cls(
            str(value["cohort"]),
            int(value["subject_count"]),
            tuple(
                RiskHeatmapBin.from_dict(item)
                for item in value.get("bins", ())
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True, order=True, slots=True)
class RiskHeatmap:
    metric: RiskMetricKind
    status: RiskAvailability
    cohorts: tuple[RiskHeatmapCohort, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    omitted_cohort_count: int = 0
    omitted_subject_count: int = 0

    def __post_init__(self) -> None:
        if self.omitted_cohort_count < 0 or self.omitted_subject_count < 0:
            raise ValueError("risk heatmap omitted counts must be non-negative")
        object.__setattr__(self, "cohorts", tuple(sorted(self.cohorts)))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric.value,
            "status": self.status.value,
            "cohorts": [item.to_dict() for item in self.cohorts],
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "omitted_cohort_count": self.omitted_cohort_count,
            "omitted_subject_count": self.omitted_subject_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskHeatmap:
        return cls(
            RiskMetricKind(str(value["metric"])),
            RiskAvailability(str(value["status"])),
            tuple(
                RiskHeatmapCohort.from_dict(item)
                for item in value.get("cohorts", ())
                if isinstance(item, Mapping)
            ),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
            int(value.get("omitted_cohort_count", 0)),
            int(value.get("omitted_subject_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class RiskAnalysisReport:
    hotspots: tuple[RiskHotspot, ...]
    capabilities: tuple[RiskCapability, ...]
    heatmaps: tuple[RiskHeatmap, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    configuration_fingerprint: str
    lineage: str
    configuration: RiskConfiguration
    analyzed_subject_count: int
    eligible_subject_count: int
    scope_counts: tuple[tuple[str, int], ...]
    excluded_scope_counts: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...] = ()
    producer_version: str = "atlas-pr132/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_index", self.evidence_index.freeze())
        for name in (
            "input_fingerprint", "graph_digest", "configuration_fingerprint", "lineage",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"risk report {name} must not be empty")
        if self.analyzed_subject_count < 0 or self.eligible_subject_count < 0:
            raise ValueError("risk report subject counts must be non-negative")
        object.__setattr__(self, "hotspots", tuple(sorted(self.hotspots, key=lambda item: item.rank)))
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(self.capabilities, key=lambda item: item.metric.value)),
        )
        object.__setattr__(self, "heatmaps", tuple(sorted(self.heatmaps)))
        object.__setattr__(self, "scope_counts", tuple(sorted(self.scope_counts)))
        object.__setattr__(self, "excluded_scope_counts", tuple(sorted(self.excluded_scope_counts)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        if tuple(item.rank for item in self.hotspots) != tuple(
            range(1, len(self.hotspots) + 1)
        ):
            raise ValueError("risk hotspot ranks must be consecutive and start at one")
        evidence_ids = {record.evidence_id for record in self.evidence_index.records}
        for record in self.evidence_index.records:
            canonical = EvidenceRecord.create(
                record.kind,
                record.subject_id,
                record.producer,
                record.snapshot_id,
                source_refs=record.source_refs,
                scope=record.scope,
                language=record.language,
                detail=record.detail,
                limitations=record.limitations,
                reliability=record.reliability,
                specificity=record.specificity,
            )
            if canonical != record:
                raise ValueError(
                    f"risk report contains non-canonical evidence: {record.evidence_id}"
                )
        for hotspot in self.hotspots:
            factor_ids = {
                evidence_id
                for factor in hotspot.factors
                for evidence_id in factor.metric.evidence_ids
            }
            if set(hotspot.evidence_ids) != factor_ids:
                raise ValueError(
                    f"hotspot evidence does not equal factor evidence: {hotspot.subject_id}"
                )
            missing = factor_ids.difference(evidence_ids)
            if missing:
                raise ValueError(f"hotspot references missing evidence: {sorted(missing)}")
        for capability in self.capabilities:
            missing = set(capability.evidence_ids).difference(evidence_ids)
            if missing:
                raise ValueError(f"capability references missing evidence: {sorted(missing)}")
        for heatmap in self.heatmaps:
            missing = set(heatmap.evidence_ids).difference(evidence_ids)
            if missing:
                raise ValueError(f"heatmap references missing evidence: {sorted(missing)}")

    def finding(self, subject_id: str) -> RiskHotspot | None:
        return next((item for item in self.hotspots if item.subject_id == subject_id), None)

    def top(self, limit: int) -> tuple[RiskHotspot, ...]:
        if limit < 0:
            raise ValueError("risk result limit must be non-negative")
        return self.hotspots[:limit]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "configuration_fingerprint": self.configuration_fingerprint,
            "lineage": self.lineage,
            "configuration": self.configuration.to_dict(),
            "coverage": {
                "analyzed_subject_count": self.analyzed_subject_count,
                "eligible_subject_count": self.eligible_subject_count,
                "scope_counts": dict(self.scope_counts),
                "excluded_scope_counts": dict(self.excluded_scope_counts),
            },
            "hotspots": [item.to_dict() for item in self.hotspots],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "heatmaps": [item.to_dict() for item in self.heatmaps],
            "evidence_index": self.evidence_index.to_dict(),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RiskAnalysisReport:
        if int(value.get("schema_version", 1)) != 1:
            raise ValueError("unsupported risk analysis report schema")
        raw_evidence = value.get("evidence_index", {})
        raw_configuration = value.get("configuration", {})
        raw_coverage = value.get("coverage", {})
        if not isinstance(raw_evidence, Mapping):
            raw_evidence = {}
        if not isinstance(raw_configuration, Mapping):
            raw_configuration = {}
        if not isinstance(raw_coverage, Mapping):
            raw_coverage = {}
        scope_counts = raw_coverage.get("scope_counts", {})
        excluded = raw_coverage.get("excluded_scope_counts", {})
        return cls(
            tuple(
                RiskHotspot.from_dict(item)
                for item in value.get("hotspots", ())
                if isinstance(item, Mapping)
            ),
            tuple(
                RiskCapability.from_dict(item)
                for item in value.get("capabilities", ())
                if isinstance(item, Mapping)
            ),
            tuple(
                RiskHeatmap.from_dict(item)
                for item in value.get("heatmaps", ())
                if isinstance(item, Mapping)
            ),
            EvidenceIndex.from_dict(raw_evidence),
            str(value["input_fingerprint"]),
            str(value["graph_digest"]),
            str(value["configuration_fingerprint"]),
            str(value["lineage"]),
            RiskConfiguration.from_dict(raw_configuration),
            int(raw_coverage.get("analyzed_subject_count", 0)),
            int(raw_coverage.get("eligible_subject_count", 0)),
            tuple(
                sorted((str(key), int(item)) for key, item in scope_counts.items())
            ) if isinstance(scope_counts, Mapping) else (),
            tuple(
                sorted((str(key), int(item)) for key, item in excluded.items())
            ) if isinstance(excluded, Mapping) else (),
            tuple(map(str, value.get("limitations", ()))),
            str(value.get("producer_version", "atlas-pr132/1")),
            int(value.get("schema_version", 1)),
        )
