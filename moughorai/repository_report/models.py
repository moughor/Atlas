from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import TypeAlias

from moughorai.semantic_evidence import (
    ConfidenceResult,
    EvidenceIndex,
    EvidenceRecord,
)

from .safety import contains_absolute_path


JsonScalar: TypeAlias = str | int | float | bool | None


class ReportCapabilityState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ReportObservationState(str, Enum):
    OBSERVED = "observed"
    UNKNOWN = "unknown"
    NOT_ANALYZED = "not_analyzed"


class ReportItemKind(str, Enum):
    MEASUREMENT = "measurement"
    FINDING = "finding"
    CONCLUSION = "conclusion"
    RECOMMENDATION = "recommendation"
    LIMITATION = "limitation"


class ReportConfidenceBasis(str, Enum):
    UPSTREAM = "upstream"
    SHARED_CALCULATOR = "shared_calculator"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class ReportSectionKind(str, Enum):
    EXECUTIVE_SUMMARY = "executive_summary"
    ARCHITECTURE = "architecture"
    REPOSITORY_HEALTH = "repository_health"
    STRENGTHS = "strengths"
    WEAKNESSES = "weaknesses"
    RISKS = "risks"
    TECHNICAL_DEBT = "technical_debt"
    QUALITY = "quality"
    RECOMMENDATIONS = "recommendations"


SECTION_ORDER = tuple(ReportSectionKind)


@dataclass(frozen=True, order=True, slots=True)
class ReportAttribute:
    key: str
    value: JsonScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        key = self.key.strip()
        if not key:
            raise ValueError("report attribute key must not be empty")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("report attribute numbers must be finite")
        unit = self.unit.strip() if self.unit is not None else None
        if unit == "":
            unit = None
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "unit", unit)

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReportAttribute:
        raw_value = value.get("value")
        if raw_value is not None and not isinstance(raw_value, (str, int, float, bool)):
            raise ValueError("report attribute value must be a JSON scalar")
        return cls(
            str(value.get("key", "")),
            raw_value,
            str(value["unit"]) if value.get("unit") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class RepositoryReportItem:
    item_id: str
    kind: ReportItemKind
    subject_id: str
    title: str
    statement: str
    observation_state: ReportObservationState
    capability_state: ReportCapabilityState
    scope: str
    priority: int
    attributes: tuple[ReportAttribute, ...] = ()
    confidence: ConfidenceResult | None = None
    confidence_basis: ReportConfidenceBasis = ReportConfidenceBasis.UNAVAILABLE
    producer_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    related_item_ids: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("item_id", "subject_id", "title", "statement", "scope"):
            normalized = getattr(self, field_name).strip()
            if not normalized:
                raise ValueError(f"report item {field_name} must not be empty")
            object.__setattr__(self, field_name, normalized)
        if self.priority < 0:
            raise ValueError("report item priority must not be negative")
        attributes = tuple(sorted(self.attributes))
        if len({item.key for item in attributes}) != len(attributes):
            raise ValueError("report item attribute keys must be unique")
        object.__setattr__(self, "attributes", attributes)
        for field_name in (
            "producer_ids",
            "evidence_ids",
            "limitations",
            "related_item_ids",
            "prerequisites",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(sorted({item.strip() for item in getattr(self, field_name) if item.strip()})),
            )
        if self.observation_state is ReportObservationState.OBSERVED and not self.evidence_ids:
            raise ValueError("observed report items require evidence")
        if self.confidence is None:
            if self.confidence_basis not in {
                ReportConfidenceBasis.NOT_APPLICABLE,
                ReportConfidenceBasis.UNAVAILABLE,
            }:
                raise ValueError("missing confidence requires an explicit unavailable basis")
        elif self.confidence_basis not in {
            ReportConfidenceBasis.UPSTREAM,
            ReportConfidenceBasis.SHARED_CALCULATOR,
        }:
            raise ValueError("report confidence must identify its deterministic basis")
        if self.kind in {
            ReportItemKind.FINDING,
            ReportItemKind.CONCLUSION,
            ReportItemKind.RECOMMENDATION,
        } and self.observation_state is ReportObservationState.OBSERVED and self.confidence is None:
            raise ValueError("observed findings and interpretations require confidence")
        if self.kind is ReportItemKind.RECOMMENDATION:
            if not self.related_item_ids or not self.prerequisites:
                raise ValueError("recommendations require related findings and prerequisites")

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "title": self.title,
            "statement": self.statement,
            "observation_state": self.observation_state.value,
            "capability_state": self.capability_state.value,
            "scope": self.scope,
            "priority": self.priority,
            "attributes": [item.to_dict() for item in self.attributes],
            "confidence": self.confidence.to_dict() if self.confidence is not None else None,
            "confidence_basis": self.confidence_basis.value,
            "producer_ids": list(self.producer_ids),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "related_item_ids": list(self.related_item_ids),
            "prerequisites": list(self.prerequisites),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepositoryReportItem:
        raw_confidence = value.get("confidence")
        confidence = (
            ConfidenceResult.from_dict(raw_confidence)
            if isinstance(raw_confidence, Mapping)
            else None
        )
        return cls(
            str(value.get("item_id", "")),
            ReportItemKind(str(value.get("kind", ReportItemKind.MEASUREMENT.value))),
            str(value.get("subject_id", "")),
            str(value.get("title", "")),
            str(value.get("statement", "")),
            ReportObservationState(str(value.get(
                "observation_state", ReportObservationState.UNKNOWN.value
            ))),
            ReportCapabilityState(str(value.get(
                "capability_state", ReportCapabilityState.UNAVAILABLE.value
            ))),
            str(value.get("scope", "repository")),
            int(value.get("priority", 0)),
            tuple(
                ReportAttribute.from_dict(item)
                for item in _mapping_items(value.get("attributes"))
            ),
            confidence,
            ReportConfidenceBasis(str(value.get(
                "confidence_basis", ReportConfidenceBasis.UNAVAILABLE.value
            ))),
            _strings(value.get("producer_ids")),
            _strings(value.get("evidence_ids")),
            _strings(value.get("limitations")),
            _strings(value.get("related_item_ids")),
            _strings(value.get("prerequisites")),
        )


@dataclass(frozen=True, slots=True)
class RepositoryReportSection:
    kind: ReportSectionKind
    capability_state: ReportCapabilityState
    observation_state: ReportObservationState
    item_ids: tuple[str, ...]
    total_item_count: int
    omitted_item_count: int
    producer_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        item_ids = tuple(item.strip() for item in self.item_ids)
        if any(not item for item in item_ids) or len(set(item_ids)) != len(item_ids):
            raise ValueError("report section item IDs must be unique and non-empty")
        object.__setattr__(self, "item_ids", item_ids)
        object.__setattr__(
            self,
            "producer_ids",
            tuple(sorted({item.strip() for item in self.producer_ids if item.strip()})),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        if self.total_item_count < 0 or self.omitted_item_count < 0:
            raise ValueError("report section counts must not be negative")
        if self.total_item_count != len(item_ids) + self.omitted_item_count:
            raise ValueError("report section included and omitted counts must be exact")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "capability_state": self.capability_state.value,
            "observation_state": self.observation_state.value,
            "item_ids": list(self.item_ids),
            "total_item_count": self.total_item_count,
            "included_item_count": len(self.item_ids),
            "omitted_item_count": self.omitted_item_count,
            "producer_ids": list(self.producer_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepositoryReportSection:
        item_ids = _strings(value.get("item_ids"))
        raw_included = value.get("included_item_count")
        if raw_included is not None and int(raw_included) != len(item_ids):
            raise ValueError("report section included item count is inconsistent")
        return cls(
            ReportSectionKind(str(value.get("kind", ""))),
            ReportCapabilityState(str(value.get(
                "capability_state", ReportCapabilityState.UNAVAILABLE.value
            ))),
            ReportObservationState(str(value.get(
                "observation_state", ReportObservationState.NOT_ANALYZED.value
            ))),
            item_ids,
            int(value.get("total_item_count", 0)),
            int(value.get("omitted_item_count", 0)),
            _strings(value.get("producer_ids")),
            _strings(value.get("limitations")),
        )


@dataclass(frozen=True, slots=True)
class ReportSelection:
    applied: bool = False
    token_budget: int | None = None
    estimated_tokens: int = 0
    included_item_count: int = 0
    omitted_item_count: int = 0
    policy: str = "repository-report-context.v1"

    def __post_init__(self) -> None:
        if self.token_budget is not None and self.token_budget <= 0:
            raise ValueError("report token budget must be positive")
        for name in ("estimated_tokens", "included_item_count", "omitted_item_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"report selection {name} must not be negative")
        if self.applied and self.token_budget is None:
            raise ValueError("applied report selection requires a token budget")
        if not self.applied and (
            self.token_budget is not None
            or self.estimated_tokens
            or self.included_item_count
            or self.omitted_item_count
        ):
            raise ValueError("unapplied report selection must use empty selection metadata")
        if not self.policy.strip():
            raise ValueError("report selection policy must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "included_item_count": self.included_item_count,
            "omitted_item_count": self.omitted_item_count,
            "policy": self.policy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReportSelection:
        raw_budget = value.get("token_budget")
        result = cls(
            bool(value.get("applied", False)),
            int(raw_budget) if raw_budget is not None else None,
            int(value.get("estimated_tokens", 0)),
            int(value.get("included_item_count", 0)),
            int(value.get("omitted_item_count", 0)),
            str(value.get("policy", "repository-report-context.v1")),
        )
        if (
            result.applied
            and result.token_budget is not None
            and result.estimated_tokens > result.token_budget
        ):
            raise ValueError("report selection estimate exceeds its token budget")
        return result


@dataclass(frozen=True, slots=True)
class RepositoryReport:
    input_fingerprint: str
    graph_digest: str
    lineage: str
    items: tuple[RepositoryReportItem, ...]
    sections: tuple[RepositoryReportSection, ...]
    evidence_index: EvidenceIndex
    limitations: tuple[str, ...] = ()
    selection: ReportSelection = ReportSelection()
    producer_version: str = "atlas-pr133/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported repository report schema")
        for name in ("input_fingerprint", "graph_digest", "lineage", "producer_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"repository report {name} must not be empty")
        items = tuple(sorted(self.items, key=lambda item: item.item_id))
        if len({item.item_id for item in items}) != len(items):
            raise ValueError("repository report item IDs must be unique")
        object.__setattr__(self, "items", items)
        by_section = {section.kind: section for section in self.sections}
        if set(by_section) != set(SECTION_ORDER) or len(by_section) != len(self.sections):
            raise ValueError("repository report must contain every canonical section exactly once")
        items_by_id = {item.item_id: item for item in items}
        normalized_sections = []
        for kind in SECTION_ORDER:
            section = by_section[kind]
            missing = set(section.item_ids) - set(items_by_id)
            if missing:
                raise ValueError(
                    f"report section references missing items: {sorted(missing)!r}"
                )
            ordered_ids = tuple(sorted(
                section.item_ids,
                key=lambda item_id: (items_by_id[item_id].priority, item_id),
            ))
            normalized_sections.append(RepositoryReportSection(
                section.kind,
                section.capability_state,
                section.observation_state,
                ordered_ids,
                section.total_item_count,
                section.omitted_item_count,
                section.producer_ids,
                section.limitations,
            ))
        sections = tuple(normalized_sections)
        object.__setattr__(self, "sections", sections)
        evidence = self.evidence_index.freeze()
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        item_ids = set(items_by_id)
        section_item_ids = {
            item_id for section in sections for item_id in section.item_ids
        }
        unreferenced_items = item_ids - section_item_ids
        if unreferenced_items:
            raise ValueError(
                f"report contains items outside canonical sections: {sorted(unreferenced_items)!r}"
            )
        referenced_evidence_ids: set[str] = set()
        for item in items:
            missing_related = set(item.related_item_ids) - item_ids
            if missing_related:
                raise ValueError(
                    f"report item references missing related items: {sorted(missing_related)!r}"
                )
            missing_evidence = {
                evidence_id for evidence_id in item.evidence_ids
                if evidence.get(evidence_id) is None
            }
            if missing_evidence:
                raise ValueError(
                    f"report item references missing evidence: {sorted(missing_evidence)!r}"
                )
            referenced_evidence_ids.update(item.evidence_ids)
            for evidence_id in item.evidence_ids:
                record = evidence.get(evidence_id)
                if record is None:
                    continue
                if (
                    record.subject_id != item.item_id
                    or record.producer != self.producer_version
                    or record.snapshot_id != self.lineage
                ):
                    raise ValueError(
                        f"report item cites foreign or cross-subject evidence: {evidence_id}"
                    )
        retained_evidence_ids = {
            record.evidence_id for record in evidence.records
        }
        if retained_evidence_ids != referenced_evidence_ids:
            raise ValueError("report evidence index must contain exactly cited evidence")
        if self.selection.applied and self.selection.included_item_count != len(items):
            raise ValueError("report selection included item count is inconsistent")
        for record in evidence.records:
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
            if canonical.evidence_id != record.evidence_id:
                raise ValueError(f"non-canonical report evidence ID: {record.evidence_id}")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("repository reports must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "lineage": self.lineage,
            "items": [item.to_dict() for item in self.items],
            "sections": [section.to_dict() for section in self.sections],
            "evidence_index": self.evidence_index.to_dict(),
            "limitations": list(self.limitations),
            "selection": self.selection.to_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    def stable_digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepositoryReport:
        raw_evidence = value.get("evidence_index")
        if not isinstance(raw_evidence, Mapping):
            raise ValueError("repository report evidence index must be an object")
        raw_selection = value.get("selection")
        return cls(
            str(value.get("input_fingerprint", "")),
            str(value.get("graph_digest", "")),
            str(value.get("lineage", "")),
            tuple(
                RepositoryReportItem.from_dict(item)
                for item in _mapping_items(value.get("items"))
            ),
            tuple(
                RepositoryReportSection.from_dict(item)
                for item in _mapping_items(value.get("sections"))
            ),
            EvidenceIndex.from_dict(raw_evidence),
            _strings(value.get("limitations")),
            ReportSelection.from_dict(raw_selection)
            if isinstance(raw_selection, Mapping)
            else ReportSelection(),
            str(value.get("producer_version", "atlas-pr133/1")),
            int(value.get("schema_version", 1)),
        )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(str(item) for item in value)
