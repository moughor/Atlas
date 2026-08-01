from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import TypeAlias

from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceResult,
    EvidenceIndex,
    EvidenceRecord,
)


JsonScalar: TypeAlias = str | int | float | bool | None


def _require_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _require_boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


class ExplanationAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"


class ExplanationFactKind(str, Enum):
    IDENTITY = "identity"
    RELATIONSHIP = "relationship"
    METADATA = "metadata"
    FINDING = "finding"
    LIMITATION = "limitation"


class ExplanationConfidenceBasis(str, Enum):
    DIRECT_EVIDENCE = "direct_evidence"
    UPSTREAM = "upstream"
    LEGACY_UPSTREAM = "legacy_upstream"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, order=True, slots=True)
class ExplanationAttribute:
    key: str
    value: JsonScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        key = self.key.strip()
        if not key:
            raise ValueError("explanation attribute key must not be empty")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("explanation attribute numbers must be finite")
        unit = self.unit.strip() if self.unit is not None else None
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "unit", unit or None)

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationAttribute:
        raw = value.get("value")
        if raw is not None and not isinstance(raw, (str, int, float, bool)):
            raise ValueError("explanation attribute value must be a JSON scalar")
        return cls(
            str(value.get("key", "")),
            raw,
            str(value["unit"]) if value.get("unit") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ExplanationRequest:
    subject: str
    kind: str | None = None
    project: str | None = None
    language: str | None = None
    path_constraint: str | None = None
    relationship_source: str | None = None
    relationship_target: str | None = None
    relationship_kind: str | None = None

    def __post_init__(self) -> None:
        subject = self.subject.strip()
        if not subject:
            raise ValueError("explanation request subject must not be empty")
        object.__setattr__(self, "subject", subject)
        for name in (
            "kind",
            "project",
            "language",
            "path_constraint",
            "relationship_source",
            "relationship_target",
            "relationship_kind",
        ):
            raw = getattr(self, name)
            object.__setattr__(self, name, raw.strip() if raw and raw.strip() else None)
        relationship_values = (
            self.relationship_source,
            self.relationship_target,
            self.relationship_kind,
        )
        if any(relationship_values) and not all(relationship_values):
            raise ValueError(
                "relationship explanations require source, target, and relationship kind"
            )

    @property
    def relationship(self) -> bool:
        return self.relationship_source is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "kind": self.kind,
            "project": self.project,
            "language": self.language,
            "path_constraint": self.path_constraint,
            "relationship_source": self.relationship_source,
            "relationship_target": self.relationship_target,
            "relationship_kind": self.relationship_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationRequest:
        def optional(name: str) -> str | None:
            raw = value.get(name)
            return str(raw) if raw is not None else None

        return cls(
            str(value.get("subject", "")),
            optional("kind"),
            optional("project"),
            optional("language"),
            optional("path_constraint"),
            optional("relationship_source"),
            optional("relationship_target"),
            optional("relationship_kind"),
        )


@dataclass(frozen=True, slots=True)
class ExplanationSubject:
    subject_id: str
    kind: str
    name: str
    qualified_name: str | None = None
    project: str | None = None
    language: str = "unknown"
    match_basis: str = "canonical_id"

    def __post_init__(self) -> None:
        for name in ("subject_id", "kind", "name", "language", "match_basis"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"explanation subject {name} must not be empty")
            object.__setattr__(self, name, normalized)
        for name in ("qualified_name", "project"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "kind": self.kind,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "project": self.project,
            "language": self.language,
            "match_basis": self.match_basis,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationSubject:
        return cls(
            str(value.get("subject_id", "")),
            str(value.get("kind", "")),
            str(value.get("name", "")),
            str(value["qualified_name"])
            if value.get("qualified_name") is not None
            else None,
            str(value["project"]) if value.get("project") is not None else None,
            str(value.get("language", "unknown")),
            str(value.get("match_basis", "canonical_id")),
        )


@dataclass(frozen=True, slots=True)
class ExplanationFact:
    fact_id: str
    kind: ExplanationFactKind
    subject_id: str
    title: str
    statement: str
    availability: ExplanationAvailability
    priority: int
    attributes: tuple[ExplanationAttribute, ...] = ()
    confidence: ConfidenceResult | None = None
    confidence_basis: ExplanationConfidenceBasis = ExplanationConfidenceBasis.UNAVAILABLE
    producer_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("fact_id", "subject_id", "title", "statement"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"explanation fact {name} must not be empty")
            object.__setattr__(self, name, normalized)
        _require_integer(self.priority, "explanation fact priority")
        if self.priority < 0:
            raise ValueError("explanation fact priority must not be negative")
        attributes = tuple(sorted(self.attributes, key=lambda item: item.key))
        if len({item.key for item in attributes}) != len(attributes):
            raise ValueError("explanation fact attribute keys must be unique")
        object.__setattr__(self, "attributes", attributes)
        for name in ("producer_ids", "evidence_ids", "limitations", "references"):
            object.__setattr__(
                self,
                name,
                tuple(sorted({item.strip() for item in getattr(self, name) if item.strip()})),
            )
        if self.availability in {
            ExplanationAvailability.AVAILABLE,
            ExplanationAvailability.PARTIAL,
        } and not self.evidence_ids:
            raise ValueError("available explanation facts require evidence")
        if self.confidence is None:
            if self.confidence_basis not in {
                ExplanationConfidenceBasis.LEGACY_UPSTREAM,
                ExplanationConfidenceBasis.NOT_APPLICABLE,
                ExplanationConfidenceBasis.UNAVAILABLE,
            }:
                raise ValueError("missing confidence requires an explicit null basis")
        elif self.confidence_basis not in {
            ExplanationConfidenceBasis.DIRECT_EVIDENCE,
            ExplanationConfidenceBasis.UPSTREAM,
        }:
            raise ValueError("confidence must identify its deterministic basis")

    def to_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "title": self.title,
            "statement": self.statement,
            "availability": self.availability.value,
            "priority": self.priority,
            "attributes": [item.to_dict() for item in self.attributes],
            "confidence": self.confidence.to_dict() if self.confidence else None,
            "confidence_basis": self.confidence_basis.value,
            "producer_ids": list(self.producer_ids),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "references": list(self.references),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationFact:
        raw_confidence = value.get("confidence")
        return cls(
            str(value.get("fact_id", "")),
            ExplanationFactKind(str(value.get("kind", ExplanationFactKind.METADATA.value))),
            str(value.get("subject_id", "")),
            str(value.get("title", "")),
            str(value.get("statement", "")),
            ExplanationAvailability(str(value.get(
                "availability", ExplanationAvailability.UNAVAILABLE.value
            ))),
            _require_integer(value.get("priority", 0), "explanation fact priority"),
            tuple(
                ExplanationAttribute.from_dict(item)
                for item in _mapping_items(value.get("attributes"))
            ),
            ConfidenceResult.from_dict(raw_confidence)
            if isinstance(raw_confidence, Mapping)
            else None,
            ExplanationConfidenceBasis(str(value.get(
                "confidence_basis", ExplanationConfidenceBasis.UNAVAILABLE.value
            ))),
            _strings(value.get("producer_ids")),
            _strings(value.get("evidence_ids")),
            _strings(value.get("limitations")),
            _strings(value.get("references")),
        )


@dataclass(frozen=True, slots=True)
class ExplanationCapability:
    name: str
    availability: ExplanationAvailability
    producer_ids: tuple[str, ...] = ()
    coverage: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("explanation capability name must not be empty")
        object.__setattr__(self, "name", name)
        if self.coverage is not None:
            if (
                isinstance(self.coverage, bool)
                or not isinstance(self.coverage, (int, float))
                or not math.isfinite(float(self.coverage))
                or not 0.0 <= float(self.coverage) <= 1.0
            ):
                raise ValueError(
                    "explanation capability coverage must be a finite number between 0 and 1"
                )
            object.__setattr__(self, "coverage", float(self.coverage))
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

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "availability": self.availability.value,
            "producer_ids": list(self.producer_ids),
            "coverage": self.coverage,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationCapability:
        raw_coverage = value.get("coverage")
        return cls(
            str(value.get("name", "")),
            ExplanationAvailability(str(value.get(
                "availability", ExplanationAvailability.UNAVAILABLE.value
            ))),
            _strings(value.get("producer_ids")),
            raw_coverage if raw_coverage is not None else None,
            _strings(value.get("limitations")),
        )


@dataclass(frozen=True, slots=True)
class ExplanationSelection:
    applied: bool = False
    token_budget: int | None = None
    estimated_tokens: int = 0
    total_fact_count: int = 0
    included_fact_count: int = 0
    omitted_fact_count: int = 0
    total_evidence_count: int = 0
    included_evidence_count: int = 0
    omitted_evidence_count: int = 0
    truncated: bool = False
    policy: str = "structured-explanation-context.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.applied, bool) or not isinstance(self.truncated, bool):
            raise TypeError("explanation selection flags must be booleans")
        if self.token_budget is not None:
            _require_integer(self.token_budget, "explanation token budget")
        if self.token_budget is not None and self.token_budget <= 0:
            raise ValueError("explanation token budget must be positive")
        for name in (
            "estimated_tokens",
            "total_fact_count",
            "included_fact_count",
            "omitted_fact_count",
            "total_evidence_count",
            "included_evidence_count",
            "omitted_evidence_count",
        ):
            _require_integer(
                getattr(self, name),
                f"explanation selection {name}",
            )
            if getattr(self, name) < 0:
                raise ValueError(f"explanation selection {name} must not be negative")
        if self.applied:
            if self.token_budget is None:
                raise ValueError("applied explanation selection requires a token budget")
            if self.estimated_tokens > self.token_budget:
                raise ValueError("explanation estimate exceeds its token budget")
            if self.total_fact_count != self.included_fact_count + self.omitted_fact_count:
                raise ValueError("explanation selection fact counts are inconsistent")
            if self.total_evidence_count != (
                self.included_evidence_count + self.omitted_evidence_count
            ):
                raise ValueError("explanation selection evidence counts are inconsistent")
            if self.truncated != bool(
                self.omitted_fact_count or self.omitted_evidence_count
            ):
                raise ValueError("explanation truncation flag is inconsistent")
        elif any((
            self.token_budget is not None,
            self.estimated_tokens,
            self.total_fact_count,
            self.included_fact_count,
            self.omitted_fact_count,
            self.total_evidence_count,
            self.included_evidence_count,
            self.omitted_evidence_count,
            self.truncated,
        )):
            raise ValueError("unapplied explanation selection must use empty metadata")
        if not self.policy.strip():
            raise ValueError("explanation selection policy must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "total_fact_count": self.total_fact_count,
            "included_fact_count": self.included_fact_count,
            "omitted_fact_count": self.omitted_fact_count,
            "total_evidence_count": self.total_evidence_count,
            "included_evidence_count": self.included_evidence_count,
            "omitted_evidence_count": self.omitted_evidence_count,
            "truncated": self.truncated,
            "policy": self.policy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ExplanationSelection:
        raw_budget = value.get("token_budget")
        result = cls(
            _require_boolean(value.get("applied", False), "selection applied"),
            _require_integer(raw_budget, "explanation token budget")
            if raw_budget is not None else None,
            _require_integer(value.get("estimated_tokens", 0), "estimated tokens"),
            _require_integer(value.get("total_fact_count", 0), "total fact count"),
            _require_integer(value.get("included_fact_count", 0), "included fact count"),
            _require_integer(value.get("omitted_fact_count", 0), "omitted fact count"),
            _require_integer(value.get("total_evidence_count", 0), "total evidence count"),
            _require_integer(value.get("included_evidence_count", 0), "included evidence count"),
            _require_integer(value.get("omitted_evidence_count", 0), "omitted evidence count"),
            _require_boolean(value.get("truncated", False), "selection truncated"),
            str(value.get("policy", "structured-explanation-context.v1")),
        )
        return result


@dataclass(frozen=True, slots=True)
class StructuredExplanation:
    request: ExplanationRequest
    availability: ExplanationAvailability
    snapshot_id: str
    graph_digest: str
    input_fingerprint: str
    lineage: str
    subject: ExplanationSubject | None
    candidates: tuple[ExplanationSubject, ...]
    facts: tuple[ExplanationFact, ...]
    capabilities: tuple[ExplanationCapability, ...]
    evidence_index: EvidenceIndex
    limitations: tuple[str, ...] = ()
    selection: ExplanationSelection = ExplanationSelection()
    context_digest: str = ""
    producer_version: str = "atlas-pr134/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_integer(self.schema_version, "structured explanation schema version")
        if self.schema_version != 1:
            raise ValueError("unsupported structured explanation schema")
        for name in (
            "snapshot_id",
            "graph_digest",
            "input_fingerprint",
            "lineage",
            "producer_version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"structured explanation {name} must not be empty")
        facts = tuple(sorted(self.facts, key=lambda item: (item.priority, item.fact_id)))
        if len({item.fact_id for item in facts}) != len(facts):
            raise ValueError("structured explanation fact IDs must be unique")
        object.__setattr__(self, "facts", facts)
        candidates = tuple(sorted(
            self.candidates,
            key=lambda item: (
                item.kind,
                item.project or "",
                item.qualified_name or item.name,
                item.subject_id,
            ),
        ))
        if len({item.subject_id for item in candidates}) != len(candidates):
            raise ValueError("structured explanation candidate IDs must be unique")
        object.__setattr__(self, "candidates", candidates)
        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.name))
        if len({item.name for item in capabilities}) != len(capabilities):
            raise ValueError("structured explanation capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        evidence = self.evidence_index.freeze()
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        cited = {evidence_id for fact in facts for evidence_id in fact.evidence_ids}
        retained = {record.evidence_id for record in evidence.records}
        if cited != retained:
            raise ValueError("structured explanation evidence index must contain exactly cited evidence")
        for fact in facts:
            if len(fact.evidence_ids) > 1:
                raise ValueError(
                    "structured explanation facts must cite one derived PR134 evidence record"
                )
            for evidence_id in fact.evidence_ids:
                record = evidence.get(evidence_id)
                if record is None:
                    raise ValueError(f"structured explanation references missing evidence: {evidence_id}")
                if (
                    record.subject_id != fact.fact_id
                    or record.producer != self.producer_version
                    or record.snapshot_id != self.lineage
                    or record.scope != fact.subject_id
                ):
                    raise ValueError(
                        f"structured explanation cites foreign or cross-subject evidence: {evidence_id}"
                    )
                logical_key = dict(record.detail).get("logical_key")
                if not logical_key:
                    raise ValueError(
                        f"structured explanation evidence lacks fact identity: {evidence_id}"
                    )
                expected_fact_id = "explanation-fact:" + hashlib.sha256(
                    _canonical_json({
                        "logical_key": logical_key,
                        "subject_id": fact.subject_id,
                        "source_refs": record.source_refs,
                        "statement": fact.statement,
                    }).encode("utf-8")
                ).hexdigest()
                if fact.fact_id != expected_fact_id:
                    raise ValueError(
                        f"structured explanation fact ID is inconsistent: {fact.fact_id}"
                    )
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
            if canonical != record:
                raise ValueError(f"non-canonical explanation evidence ID: {record.evidence_id}")
        if self.selection.applied:
            if self.selection.included_fact_count != len(facts):
                raise ValueError("explanation included fact count is inconsistent")
            if self.selection.included_evidence_count != len(evidence):
                raise ValueError("explanation included evidence count is inconsistent")
        expected_digest = self._calculate_context_digest()
        if self.context_digest and self.context_digest != expected_digest:
            raise ValueError("structured explanation context digest is inconsistent")
        object.__setattr__(self, "context_digest", expected_digest)
        if contains_absolute_path(self._payload(include_context_digest=True)):
            raise ValueError("structured explanations must not contain absolute paths")

    @property
    def citations(self) -> tuple[str, ...]:
        return tuple(sorted({item for fact in self.facts for item in fact.evidence_ids}))

    def _payload(self, *, include_context_digest: bool) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "request": self.request.to_dict(),
            "availability": self.availability.value,
            "snapshot_id": self.snapshot_id,
            "graph_digest": self.graph_digest,
            "input_fingerprint": self.input_fingerprint,
            "lineage": self.lineage,
            "subject": self.subject.to_dict() if self.subject else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "facts": [item.to_dict() for item in self.facts],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "citations": list(self.citations),
            "limitations": list(self.limitations),
            "selection": self.selection.to_dict(),
        }
        if include_context_digest:
            result["context_digest"] = self.context_digest
        return result

    def _calculate_context_digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(self._payload(include_context_digest=False)).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return self._payload(include_context_digest=True)

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> StructuredExplanation:
        raw_request = value.get("request")
        raw_subject = value.get("subject")
        raw_evidence = value.get("evidence_index")
        raw_selection = value.get("selection")
        if not isinstance(raw_request, Mapping) or not isinstance(raw_evidence, Mapping):
            raise TypeError("structured explanation request and evidence index must be objects")
        result = cls(
            ExplanationRequest.from_dict(raw_request),
            ExplanationAvailability(str(value.get(
                "availability", ExplanationAvailability.UNAVAILABLE.value
            ))),
            str(value.get("snapshot_id", "")),
            str(value.get("graph_digest", "")),
            str(value.get("input_fingerprint", "")),
            str(value.get("lineage", "")),
            ExplanationSubject.from_dict(raw_subject)
            if isinstance(raw_subject, Mapping)
            else None,
            tuple(
                ExplanationSubject.from_dict(item)
                for item in _mapping_items(value.get("candidates"))
            ),
            tuple(
                ExplanationFact.from_dict(item)
                for item in _mapping_items(value.get("facts"))
            ),
            tuple(
                ExplanationCapability.from_dict(item)
                for item in _mapping_items(value.get("capabilities"))
            ),
            EvidenceIndex.from_dict(raw_evidence),
            _strings(value.get("limitations")),
            ExplanationSelection.from_dict(raw_selection)
            if isinstance(raw_selection, Mapping)
            else ExplanationSelection(),
            str(value.get("context_digest", "")),
            str(value.get("producer_version", "atlas-pr134/1")),
            _require_integer(
                value.get("schema_version", 1),
                "structured explanation schema version",
            ),
        )
        raw_citations = value.get("citations")
        if raw_citations is not None and _strings(raw_citations) != result.citations:
            raise ValueError("structured explanation citations are inconsistent")
        return result


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(sorted({str(item) for item in value if str(item).strip()}))
