"""Immutable, source-free contracts for PR142 technical-debt observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re

from moughorai.impact_analysis import ImpactRiskContext
from moughorai.knowledge_graph import KnowledgeKind
from moughorai.platform.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
    EvidenceIndex,
    EvidenceRecord,
)
from moughorai.subject_resolution import SubjectCandidate, SubjectQuery


TECHNICAL_DEBT_SCHEMA_VERSION = 1
TECHNICAL_DEBT_PRODUCER = "atlas-pr142/1"
TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER = "atlas-pr142-impact-adapter/1"

_MAX_RESULT_LIMIT = 1_000
_MAX_CANDIDATE_LIMIT = 256
_MAX_IMPACT_DEPTH = 64
_MAX_TEXT = 4_096
_MAX_ITEMS = 512
_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_ADVICE_ID = re.compile(r"^refactoring-advice:[0-9a-f]{64}$")
_IMPACT_FINGERPRINT = re.compile(r"^impact-prediction:[0-9a-f]{64}$")
_ITEM_ID = re.compile(r"^technical-debt:[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^technical-debt-request:[0-9a-f]{64}$")

DEPENDENCY_CYCLE_OBSERVATION = (
    "A fully revalidated PR137 dependency-cycle seam was observed; this is a "
    "review candidate, not proof of a defect."
)
TECHNICAL_DEBT_ITEM_LIMITATIONS = (
    "A represented dependency cycle is not by itself proof of a defect or technical debt.",
    "Equivalent PR137 observations for the same directed seam are one debt item and do not increase priority.",
    "PR132 risk context is evidence about represented risk signals, not proof of technical debt.",
    "At most one exact participant risk context is retained, selected by score then canonical identity; it orders only represented-impact items.",
    "PR136 impact is bounded static repository impact, not runtime execution or external-consumer behavior.",
    "Effort, business priority, ownership, developer intent, and a safe remediation remain unknown.",
)


class TechnicalDebtCategory(str, Enum):
    DEPENDENCY_CYCLE = "dependency_cycle"


class TechnicalDebtState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class TechnicalDebtCapabilityKind(str, Enum):
    CYCLE_EVIDENCE = "cycle_evidence"
    ENGINEERING_IMPACT = "engineering_impact"
    RISK_CONTEXT = "risk_context"
    STRUCTURED_COMPLEXITY = "structured_complexity"


def _reject_unknown(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(sorted(unknown))}")


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be an array")
    return tuple(value)


def _mappings(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    values = _sequence(value, label)
    if any(not isinstance(item, Mapping) for item in values):
        raise TypeError(f"{label} entries must be objects")
    return tuple(item for item in values if isinstance(item, Mapping))


def _text(value: object, label: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    result = value.strip()
    if not result or len(result) > maximum or any(char in result for char in "\r\n\x00"):
        raise ValueError(f"{label} must be a bounded single line")
    if contains_absolute_path(result):
        raise ValueError(f"{label} must be source-free")
    return result


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label, maximum=1_024)


def _strings(
    value: object,
    label: str,
    *,
    maximum_count: int = _MAX_ITEMS,
    maximum_length: int = _MAX_TEXT,
) -> tuple[str, ...]:
    values = _sequence(value, label)
    if len(values) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    return tuple(sorted({_text(item, f"{label} entry", maximum=maximum_length) for item in values}))


def _integer(value: object, label: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{label} must be finite and between 0 and 1")
    return result


def _evidence_ids(value: object, label: str) -> tuple[str, ...]:
    result = _strings(value, label)
    if any(_EVIDENCE_ID.fullmatch(item) is None for item in result):
        raise ValueError(f"{label} contains an invalid evidence ID")
    return result


def _query_from_dict(value: Mapping[str, object]) -> SubjectQuery:
    _reject_unknown(value, {"identifier", "kind", "project", "language", "path"}, "technical debt subject query")
    raw_kind = value.get("kind")
    if raw_kind is not None and not isinstance(raw_kind, str):
        raise TypeError("technical debt subject kind must be a string or null")
    return SubjectQuery(
        _text(value.get("identifier"), "technical debt subject identifier"),
        KnowledgeKind(raw_kind) if raw_kind is not None else None,
        _optional_text(value.get("project"), "technical debt subject project"),
        _optional_text(value.get("language"), "technical debt subject language"),
        _optional_text(value.get("path"), "technical debt subject path"),
    )


def _candidate_from_dict(value: Mapping[str, object]) -> SubjectCandidate:
    _reject_unknown(value, {
        "canonical_id", "kind", "name", "qualified_name", "project", "language",
        "path", "project_scopes", "match_basis",
    }, "technical debt subject")
    return SubjectCandidate.from_dict(value)


def _confidence_from_dict(value: Mapping[str, object]) -> ConfidenceResult:
    _reject_unknown(value, {
        "score", "tier", "support", "coverage", "agreement",
        "contradiction_penalty", "ambiguity_penalty", "missing_roles",
        "model_version",
    }, "technical debt confidence")
    return _validate_confidence(ConfidenceResult.from_dict(value))


def _validate_confidence(value: ConfidenceResult) -> ConfidenceResult:
    if not isinstance(value, ConfidenceResult):
        raise TypeError("technical debt confidence must use ConfidenceResult")
    if value.model_version != ConfidenceCalculator.MODEL_VERSION:
        raise ValueError("unsupported technical debt confidence model")
    expected = round(max(0.0, min(
        1.0,
        value.support * value.coverage * value.agreement
        - value.contradiction_penalty - value.ambiguity_penalty,
    )), 4)
    if not math.isclose(value.score, expected, rel_tol=0.0, abs_tol=3e-4):
        raise ValueError("technical debt confidence score is inconsistent")
    return value


def _evidence_index_from_dict(value: Mapping[str, object]) -> EvidenceIndex:
    _reject_unknown(value, {"schema_version", "records"}, "technical debt evidence index")
    if _integer(value.get("schema_version"), "technical debt evidence schema", default=1) != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported technical debt evidence schema")
    records: list[EvidenceRecord] = []
    for raw in _mappings(value.get("records"), "technical debt evidence records"):
        _reject_unknown(raw, {
            "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
            "source_refs", "scope", "language", "detail", "limitations",
            "reliability", "specificity",
        }, "technical debt evidence record")
        record = EvidenceRecord.from_dict(raw)
        canonical = EvidenceRecord.create(
            record.kind, record.subject_id, record.producer, record.snapshot_id,
            source_refs=record.source_refs, scope=record.scope, language=record.language,
            detail=record.detail, limitations=record.limitations,
            reliability=record.reliability, specificity=record.specificity,
        )
        if canonical != record:
            raise ValueError("technical debt evidence identity is inconsistent")
        records.append(record)
    return EvidenceIndex(records, frozen=True)


@dataclass(frozen=True, slots=True)
class TechnicalDebtRequest:
    subject: SubjectQuery = field(
        default_factory=lambda: SubjectQuery("repository", KnowledgeKind.REPOSITORY)
    )
    limit: int = 20
    candidate_limit: int = 100
    impact_depth: int = 4

    def __post_init__(self) -> None:
        if not isinstance(self.subject, SubjectQuery):
            raise TypeError("technical debt subject must be a SubjectQuery")
        for name, maximum in (
            ("limit", _MAX_RESULT_LIMIT),
            ("candidate_limit", _MAX_CANDIDATE_LIMIT),
            ("impact_depth", _MAX_IMPACT_DEPTH),
        ):
            value = _integer(getattr(self, name), f"technical debt {name}")
            if not 1 <= value <= maximum:
                raise ValueError(f"technical debt {name} must be between 1 and {maximum}")
        if self.limit > self.candidate_limit:
            raise ValueError("technical debt limit cannot exceed candidate_limit")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("technical debt requests must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject.to_dict(),
            "limit": self.limit,
            "candidate_limit": self.candidate_limit,
            "impact_depth": self.impact_depth,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TechnicalDebtRequest:
        _reject_unknown(value, {"subject", "limit", "candidate_limit", "impact_depth"}, "technical debt request")
        subject = value.get("subject")
        if not isinstance(subject, Mapping):
            raise TypeError("technical debt request subject must be an object")
        return cls(
            _query_from_dict(subject),
            _integer(value.get("limit"), "technical debt limit", default=20),
            _integer(value.get("candidate_limit"), "technical debt candidate limit", default=100),
            _integer(value.get("impact_depth"), "technical debt impact depth", default=4),
        )


@dataclass(frozen=True, order=True, slots=True)
class TechnicalDebtCapability:
    capability: TechnicalDebtCapabilityKind
    state: TechnicalDebtState
    coverage: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.capability, str):
            object.__setattr__(self, "capability", TechnicalDebtCapabilityKind(self.capability))
        if isinstance(self.state, str):
            object.__setattr__(self, "state", TechnicalDebtState(self.state))
        if self.coverage is not None:
            object.__setattr__(self, "coverage", _number(self.coverage, "technical debt capability coverage"))
        limitations = _strings(self.limitations, "technical debt capability limitations")
        if self.state is not TechnicalDebtState.AVAILABLE and not limitations:
            raise ValueError("non-available technical debt capabilities require a limitation")
        object.__setattr__(self, "limitations", limitations)

    def to_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "state": self.state.value,
            "coverage": self.coverage,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TechnicalDebtCapability:
        _reject_unknown(value, {"capability", "state", "coverage", "limitations"}, "technical debt capability")
        raw_coverage = value.get("coverage")
        return cls(
            TechnicalDebtCapabilityKind(_text(value.get("capability"), "technical debt capability")),
            TechnicalDebtState(_text(value.get("state"), "technical debt capability state")),
            _number(raw_coverage, "technical debt capability coverage") if raw_coverage is not None else None,
            _strings(value.get("limitations"), "technical debt capability limitations"),
        )


@dataclass(frozen=True, slots=True)
class TechnicalDebtImpact:
    state: TechnicalDebtState
    affected_count: int = 0
    direct_count: int = 0
    transitive_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    categories: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.state, str):
            object.__setattr__(self, "state", TechnicalDebtState(self.state))
        for name in ("affected_count", "direct_count", "transitive_count", "omitted_count"):
            value = _integer(getattr(self, name), f"technical debt impact {name}")
            if value < 0:
                raise ValueError(f"technical debt impact {name} must be non-negative")
        if self.affected_count != self.direct_count + self.transitive_count:
            raise ValueError("technical debt impact counts are inconsistent")
        if not isinstance(self.truncated, bool):
            raise TypeError("technical debt impact truncation must be boolean")
        if self.omitted_count and not self.truncated:
            raise ValueError("technical debt impact omissions require truncation")
        categories = _strings(self.categories, "technical debt impact categories", maximum_count=64, maximum_length=128)
        evidence_ids = _evidence_ids(self.evidence_ids, "technical debt impact evidence")
        limitations = _strings(self.limitations, "technical debt impact limitations")
        if self.state not in {TechnicalDebtState.AVAILABLE, TechnicalDebtState.PARTIAL}:
            if self.affected_count or evidence_ids or categories:
                raise ValueError("unrepresented impact cannot retain findings or evidence")
            if not limitations:
                raise ValueError("unrepresented impact requires a limitation")
        elif not self.affected_count or not evidence_ids or not categories:
            raise ValueError("represented impact requires findings, categories, and evidence")
        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "limitations", limitations)

    @property
    def represented(self) -> bool:
        return self.state in {TechnicalDebtState.AVAILABLE, TechnicalDebtState.PARTIAL}

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "represented": self.represented,
            "affected_count": self.affected_count,
            "direct_count": self.direct_count,
            "transitive_count": self.transitive_count,
            "omitted_count": self.omitted_count,
            "truncated": self.truncated,
            "categories": list(self.categories),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TechnicalDebtImpact:
        _reject_unknown(value, {
            "state", "represented", "affected_count", "direct_count",
            "transitive_count", "omitted_count", "truncated", "categories",
            "evidence_ids", "limitations",
        }, "technical debt impact")
        result = cls(
            TechnicalDebtState(_text(value.get("state"), "technical debt impact state")),
            _integer(value.get("affected_count"), "technical debt affected count"),
            _integer(value.get("direct_count"), "technical debt direct count"),
            _integer(value.get("transitive_count"), "technical debt transitive count"),
            _integer(value.get("omitted_count"), "technical debt impact omitted count"),
            _boolean(value.get("truncated"), "technical debt impact truncation"),
            _strings(value.get("categories"), "technical debt impact categories", maximum_count=64, maximum_length=128),
            _evidence_ids(value.get("evidence_ids"), "technical debt impact evidence"),
            _strings(value.get("limitations"), "technical debt impact limitations"),
        )
        if _boolean(value.get("represented"), "technical debt represented impact") != result.represented:
            raise ValueError("technical debt represented impact is inconsistent")
        return result


def technical_debt_item_id(
    source_id: str,
    target_id: str,
) -> str:
    payload = {
        "producer": TECHNICAL_DEBT_PRODUCER,
        "category": TechnicalDebtCategory.DEPENDENCY_CYCLE.value,
        "source": _text(source_id, "technical debt source", maximum=1_024),
        "target": _text(target_id, "technical debt target", maximum=1_024),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    return f"technical-debt:{digest}"


def technical_debt_advice_set_digest(
    advice_ids: Sequence[str],
    evidence_backed_advice_ids: Sequence[str],
) -> str:
    all_ids = _strings(
        advice_ids,
        "technical debt advice IDs",
        maximum_count=_MAX_ITEMS,
        maximum_length=96,
    )
    backed_ids = _strings(
        evidence_backed_advice_ids,
        "technical debt evidence-backed advice IDs",
        maximum_count=_MAX_ITEMS,
        maximum_length=96,
    )
    if (
        not all_ids
        or not backed_ids
        or not set(backed_ids).issubset(all_ids)
        or any(_ADVICE_ID.fullmatch(item) is None for item in all_ids)
    ):
        raise ValueError("technical debt advice lineage is invalid")
    payload = {
        "producer": TECHNICAL_DEBT_PRODUCER,
        "advice_ids": list(all_ids),
        "evidence_backed_advice_ids": list(backed_ids),
    }
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return f"technical-debt-advice-set:{digest}"


@dataclass(frozen=True, slots=True)
class TechnicalDebtItem:
    item_id: str
    rank: int | None
    category: TechnicalDebtCategory
    subjects: tuple[SubjectCandidate, ...]
    source: SubjectCandidate
    target: SubjectCandidate
    refactoring_advice_ids: tuple[str, ...]
    evidence_backed_refactoring_advice_ids: tuple[str, ...]
    confidence_advice_id: str
    omitted_advice_evidence_count: int
    impact_fingerprint: str | None
    observation: str
    confidence: ConfidenceResult
    evidence_ids: tuple[str, ...]
    impact: TechnicalDebtImpact
    risk_context: ImpactRiskContext | None = None
    risk_subject_id: str | None = None
    complexity_subject_ids: tuple[str, ...] = ()
    complexity_evidence_ids: tuple[str, ...] = ()
    complexity_observed: bool = False
    limitations: tuple[str, ...] = TECHNICAL_DEBT_ITEM_LIMITATIONS

    def __post_init__(self) -> None:
        if isinstance(self.category, str):
            object.__setattr__(self, "category", TechnicalDebtCategory(self.category))
        subjects = tuple(sorted(self.subjects, key=lambda item: item.canonical_id))
        if len(subjects) != 2 or any(not isinstance(item, SubjectCandidate) for item in subjects):
            raise ValueError("dependency-cycle debt observations require exactly two canonical subjects")
        if self.source not in subjects or self.target not in subjects or self.source == self.target:
            raise ValueError("technical debt source and target must be distinct observed subjects")
        object.__setattr__(self, "subjects", subjects)
        advice_ids = _strings(
            self.refactoring_advice_ids,
            "technical debt advice IDs",
            maximum_count=_MAX_ITEMS,
            maximum_length=96,
        )
        if not advice_ids or any(
            _ADVICE_ID.fullmatch(advice_id) is None for advice_id in advice_ids
        ):
            raise ValueError("technical debt advice IDs are malformed")
        object.__setattr__(self, "refactoring_advice_ids", advice_ids)
        evidenced_advice_ids = _strings(
            self.evidence_backed_refactoring_advice_ids,
            "technical debt evidence-backed advice IDs",
            maximum_count=_MAX_ITEMS,
            maximum_length=96,
        )
        if (
            not evidenced_advice_ids
            or not set(evidenced_advice_ids).issubset(advice_ids)
        ):
            raise ValueError(
                "technical debt evidence-backed advice IDs are incomplete or foreign"
            )
        omitted_advice = _integer(
            self.omitted_advice_evidence_count,
            "technical debt omitted advice evidence count",
        )
        if omitted_advice != len(advice_ids) - len(evidenced_advice_ids):
            raise ValueError(
                "technical debt omitted advice evidence count is inconsistent"
            )
        object.__setattr__(
            self,
            "evidence_backed_refactoring_advice_ids",
            evidenced_advice_ids,
        )
        confidence_advice_id = _text(
            self.confidence_advice_id,
            "technical debt confidence advice ID",
            maximum=96,
        )
        if confidence_advice_id not in evidenced_advice_ids:
            raise ValueError(
                "technical debt confidence advice must retain its evidence"
            )
        object.__setattr__(
            self, "confidence_advice_id", confidence_advice_id
        )
        object.__setattr__(
            self, "omitted_advice_evidence_count", omitted_advice
        )
        if self.impact_fingerprint is not None and _IMPACT_FINGERPRINT.fullmatch(self.impact_fingerprint) is None:
            raise ValueError("technical debt impact fingerprint is malformed")
        expected_id = technical_debt_item_id(
            self.source.canonical_id, self.target.canonical_id,
        )
        if _ITEM_ID.fullmatch(self.item_id) is None or self.item_id != expected_id:
            raise ValueError("technical debt item ID is inconsistent")
        if self.observation != DEPENDENCY_CYCLE_OBSERVATION:
            raise ValueError("technical debt observation wording is not canonical")
        confidence = _validate_confidence(self.confidence)
        if not isinstance(self.impact, TechnicalDebtImpact):
            raise TypeError("technical debt item impact is invalid")
        evidence_ids = _evidence_ids(self.evidence_ids, "technical debt item evidence")
        if not evidence_ids or not set(self.impact.evidence_ids).issubset(evidence_ids):
            raise ValueError("technical debt item evidence closure is incomplete")
        if self.risk_context is not None:
            if not isinstance(self.risk_context, ImpactRiskContext):
                raise TypeError("technical debt risk context is invalid")
            if not set(self.risk_context.evidence_ids).issubset(evidence_ids):
                raise ValueError("technical debt risk evidence closure is incomplete")
        if (self.risk_context is None) != (self.risk_subject_id is None):
            raise ValueError(
                "technical debt risk context and exact subject must be present together"
            )
        if self.risk_subject_id is not None:
            risk_subject = _text(
                self.risk_subject_id,
                "technical debt risk subject",
                maximum=1_024,
            )
            if risk_subject not in {item.canonical_id for item in subjects}:
                raise ValueError(
                    "technical debt risk context must belong to a cycle participant"
                )
            object.__setattr__(self, "risk_subject_id", risk_subject)
        complexity_subjects = _strings(
            self.complexity_subject_ids,
            "technical debt complexity subjects",
        )
        if not set(complexity_subjects).issubset(
            item.canonical_id for item in subjects
        ):
            raise ValueError(
                "technical debt complexity context must belong to cycle participants"
            )
        complexity_evidence = _evidence_ids(
            self.complexity_evidence_ids,
            "technical debt complexity evidence",
        )
        if not set(complexity_evidence).issubset(evidence_ids):
            raise ValueError("technical debt complexity evidence closure is incomplete")
        expected_complexity = bool(complexity_subjects)
        if (
            self.complexity_observed != expected_complexity
            or bool(complexity_evidence) != expected_complexity
        ):
            raise ValueError("technical debt complexity flag is inconsistent")
        object.__setattr__(self, "complexity_subject_ids", complexity_subjects)
        object.__setattr__(self, "complexity_evidence_ids", complexity_evidence)
        if self.rank is not None and (
            isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1
        ):
            raise ValueError("technical debt rank must be a positive ordinal or null")
        if (self.rank is not None) != self.impact.represented:
            raise ValueError("only represented impact may receive an ordinal debt rank")
        limitations = _strings(self.limitations, "technical debt item limitations")
        if not set(TECHNICAL_DEBT_ITEM_LIMITATIONS).issubset(limitations):
            raise ValueError("technical debt item omits mandatory interpretation limits")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "limitations", limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("technical debt items must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "rank": self.rank,
            "category": self.category.value,
            "subjects": [item.to_dict() for item in self.subjects],
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "refactoring_advice_ids": list(self.refactoring_advice_ids),
            "evidence_backed_refactoring_advice_ids": list(
                self.evidence_backed_refactoring_advice_ids
            ),
            "confidence_advice_id": self.confidence_advice_id,
            "omitted_advice_evidence_count": self.omitted_advice_evidence_count,
            "impact_fingerprint": self.impact_fingerprint,
            "observation": self.observation,
            "confidence": self.confidence.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "impact": self.impact.to_dict(),
            "risk_context": self.risk_context.to_dict() if self.risk_context is not None else None,
            "risk_subject_id": self.risk_subject_id,
            "complexity_subject_ids": list(self.complexity_subject_ids),
            "complexity_evidence_ids": list(self.complexity_evidence_ids),
            "complexity_observed": self.complexity_observed,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TechnicalDebtItem:
        _reject_unknown(value, {
            "item_id", "rank", "category", "subjects", "source", "target",
            "refactoring_advice_ids", "evidence_backed_refactoring_advice_ids",
            "confidence_advice_id", "omitted_advice_evidence_count",
            "impact_fingerprint", "observation",
            "confidence", "evidence_ids", "impact", "risk_context",
            "risk_subject_id", "complexity_subject_ids",
            "complexity_evidence_ids", "complexity_observed", "limitations",
        }, "technical debt item")
        source = value.get("source")
        target = value.get("target")
        confidence = value.get("confidence")
        impact = value.get("impact")
        risk = value.get("risk_context")
        if not all(isinstance(item, Mapping) for item in (source, target, confidence, impact)):
            raise TypeError("technical debt item nested contracts must be objects")
        if risk is not None and not isinstance(risk, Mapping):
            raise TypeError("technical debt risk context must be an object or null")
        raw_rank = value.get("rank")
        return cls(
            _text(value.get("item_id"), "technical debt item ID", maximum=96),
            _integer(raw_rank, "technical debt rank") if raw_rank is not None else None,
            TechnicalDebtCategory(_text(value.get("category"), "technical debt category")),
            tuple(_candidate_from_dict(item) for item in _mappings(value.get("subjects"), "technical debt subjects")),
            _candidate_from_dict(source),  # type: ignore[arg-type]
            _candidate_from_dict(target),  # type: ignore[arg-type]
            _strings(
                value.get("refactoring_advice_ids"),
                "technical debt advice IDs",
                maximum_count=_MAX_ITEMS,
                maximum_length=96,
            ),
            _strings(
                value.get("evidence_backed_refactoring_advice_ids"),
                "technical debt evidence-backed advice IDs",
                maximum_count=_MAX_ITEMS,
                maximum_length=96,
            ),
            _text(
                value.get("confidence_advice_id"),
                "technical debt confidence advice ID",
                maximum=96,
            ),
            _integer(
                value.get("omitted_advice_evidence_count"),
                "technical debt omitted advice evidence count",
            ),
            _optional_text(value.get("impact_fingerprint"), "technical debt impact fingerprint"),
            _text(value.get("observation"), "technical debt observation"),
            _confidence_from_dict(confidence),  # type: ignore[arg-type]
            _evidence_ids(value.get("evidence_ids"), "technical debt item evidence"),
            TechnicalDebtImpact.from_dict(impact),  # type: ignore[arg-type]
            ImpactRiskContext.from_dict(risk) if isinstance(risk, Mapping) else None,
            _optional_text(value.get("risk_subject_id"), "technical debt risk subject"),
            _strings(
                value.get("complexity_subject_ids"),
                "technical debt complexity subjects",
            ),
            _evidence_ids(
                value.get("complexity_evidence_ids"),
                "technical debt complexity evidence",
            ),
            _boolean(value.get("complexity_observed"), "technical debt complexity flag"),
            _strings(value.get("limitations"), "technical debt item limitations"),
        )

    @property
    def refactoring_advice_id(self) -> str:
        """Return the canonical representative ID for legacy/internal callers."""

        return self.confidence_advice_id


def technical_debt_sort_key(item: TechnicalDebtItem) -> tuple[object, ...]:
    return (
        not item.impact.represented,
        -item.impact.affected_count if item.impact.represented else 0,
        -item.impact.direct_count if item.impact.represented else 0,
        (
            -item.risk_context.score
            if item.impact.represented and item.risk_context is not None
            else 1.0
        ),
        item.item_id,
    )


def technical_debt_fingerprint(lineage: str, graph_digest: str, request: TechnicalDebtRequest) -> str:
    if not isinstance(request, TechnicalDebtRequest):
        raise TypeError("technical debt fingerprint requires TechnicalDebtRequest")
    payload = {
        "producer": TECHNICAL_DEBT_PRODUCER,
        "schema_version": TECHNICAL_DEBT_SCHEMA_VERSION,
        "lineage": _text(lineage, "technical debt lineage", maximum=256),
        "graph_digest": _text(graph_digest, "technical debt graph digest", maximum=256),
        "request": request.to_dict(),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    return f"technical-debt-request:{digest}"


@dataclass(frozen=True, slots=True)
class TechnicalDebtResponse:
    request: TechnicalDebtRequest
    items: tuple[TechnicalDebtItem, ...]
    capabilities: tuple[TechnicalDebtCapability, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    lineage: str
    total_candidate_count: int = 0
    evaluated_count: int = 0
    unique_evaluated_count: int = 0
    equivalent_observation_count: int = 0
    unevaluated_count: int = 0
    output_omitted_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    limitations: tuple[str, ...] = ()
    producer_version: str = TECHNICAL_DEBT_PRODUCER
    schema_version: int = TECHNICAL_DEBT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, TechnicalDebtRequest):
            raise TypeError("technical debt response request is invalid")
        items = tuple(sorted(self.items, key=technical_debt_sort_key))
        if len({item.item_id for item in items}) != len(items):
            raise ValueError("technical debt item IDs must be unique")
        ranked = tuple(item for item in items if item.impact.represented)
        if tuple(item.rank for item in ranked) != tuple(range(1, len(ranked) + 1)):
            raise ValueError("technical debt ordinal ranks are inconsistent")
        if any(item.rank is not None for item in items[len(ranked):]):
            raise ValueError("unrepresented technical debt items must remain unranked")
        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.capability.value))
        if {item.capability for item in capabilities} != set(TechnicalDebtCapabilityKind):
            raise ValueError("technical debt response must report every capability")
        if len(capabilities) != len(TechnicalDebtCapabilityKind):
            raise ValueError("technical debt capabilities must be unique")
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("technical debt response requires an EvidenceIndex")
        evidence = self.evidence_index.freeze()
        available = {record.evidence_id for record in evidence.records}
        referenced = {evidence_id for item in items for evidence_id in item.evidence_ids}
        if available != referenced:
            raise ValueError("technical debt response evidence closure is not exact")
        for item in items:
            adapters = tuple(
                record for record in evidence.records
                if record.producer == TECHNICAL_DEBT_PRODUCER and record.subject_id == item.item_id
            )
            if len(adapters) != 1 or adapters[0].evidence_id not in item.evidence_ids:
                raise ValueError("technical debt items require exactly one PR142 adapter evidence record")
            adapter_detail = dict(adapters[0].detail)
            if (
                adapter_detail.get("advice_set_digest")
                != technical_debt_advice_set_digest(
                    item.refactoring_advice_ids,
                    item.evidence_backed_refactoring_advice_ids,
                )
                or adapter_detail.get("representative_refactoring_advice_id")
                != item.confidence_advice_id
                or adapter_detail.get("impact_fingerprint")
                != (item.impact_fingerprint or "unavailable")
            ):
                raise ValueError(
                    "technical debt item lineage does not match its adapter evidence"
                )
            impact_records = tuple(
                evidence.get(evidence_id)
                for evidence_id in item.impact.evidence_ids
            )
            if item.impact.represented and (
                len(impact_records) != 1
                or impact_records[0] is None
                or impact_records[0].producer
                != TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER
                or dict(impact_records[0].detail).get(
                    "impact_input_fingerprint"
                ) != item.impact_fingerprint
            ):
                raise ValueError(
                    "technical debt impact fingerprint does not match its adapter evidence"
                )
        for record in evidence.records:
            canonical = EvidenceRecord.create(
                record.kind, record.subject_id, record.producer, record.snapshot_id,
                source_refs=record.source_refs, scope=record.scope, language=record.language,
                detail=record.detail, limitations=record.limitations,
                reliability=record.reliability, specificity=record.specificity,
            )
            if canonical != record or record.snapshot_id != self.lineage:
                raise ValueError("technical debt evidence identity or lineage is inconsistent")
            missing_refs = {
                ref for ref in record.source_refs
                if ref.startswith("evidence:") and ref not in available
            }
            if missing_refs:
                raise ValueError("technical debt adapter references unavailable evidence")
            if contains_absolute_path(record.to_dict()):
                raise ValueError("technical debt evidence must be source-free")
        for item in items:
            if item.risk_context is not None:
                risk_records = tuple(
                    evidence.get(evidence_id)
                    for evidence_id in item.risk_context.evidence_ids
                )
                if any(
                    record is None or record.subject_id != item.risk_subject_id
                    for record in risk_records
                ):
                    raise ValueError(
                        "technical debt risk evidence does not match its exact subject"
                    )
            complexity_records = tuple(
                evidence.get(evidence_id)
                for evidence_id in item.complexity_evidence_ids
            )
            valid_complexity_records = tuple(
                record for record in complexity_records if record is not None
            )
            if (
                len(valid_complexity_records) != len(complexity_records)
                or {record.subject_id for record in valid_complexity_records}
                != set(item.complexity_subject_ids)
                or len(valid_complexity_records) != len(item.complexity_subject_ids)
                or any(
                    record.producer != "atlas-pr132/1"
                    or "complexity" not in {
                        signal.strip()
                        for signal in dict(record.detail)
                        .get("signals", "")
                        .split(",")
                        if signal.strip()
                    }
                    for record in valid_complexity_records
                )
            ):
                raise ValueError(
                    "technical debt complexity evidence does not match its exact subjects"
                )
        total = _integer(self.total_candidate_count, "technical debt total candidate count")
        evaluated = _integer(self.evaluated_count, "technical debt evaluated count")
        unique = _integer(
            self.unique_evaluated_count,
            "technical debt unique evaluated count",
        )
        equivalent = _integer(
            self.equivalent_observation_count,
            "technical debt equivalent observation count",
        )
        unevaluated = _integer(
            self.unevaluated_count,
            "technical debt unevaluated count",
        )
        output_omitted = _integer(
            self.output_omitted_count,
            "technical debt output omitted count",
        )
        omitted = _integer(self.omitted_count, "technical debt omitted count")
        if min(
            total, evaluated, unique, equivalent, unevaluated,
            output_omitted, omitted,
        ) < 0 or total < evaluated or evaluated < unique or unique < len(items):
            raise ValueError("technical debt response counts are inconsistent")
        if equivalent != evaluated - unique:
            raise ValueError("technical debt equivalent observation count is inconsistent")
        if unevaluated != total - evaluated:
            raise ValueError("technical debt unevaluated count is inconsistent")
        if output_omitted != unique - len(items):
            raise ValueError("technical debt output omitted count is inconsistent")
        if omitted != equivalent + unevaluated + output_omitted:
            raise ValueError("technical debt omitted count is inconsistent")
        if (
            not isinstance(self.truncated, bool)
            or self.truncated != bool(unevaluated or output_omitted)
        ):
            raise ValueError("technical debt truncation is inconsistent")
        fingerprint = _text(self.input_fingerprint, "technical debt fingerprint", maximum=96)
        if _FINGERPRINT.fullmatch(fingerprint) is None or fingerprint != technical_debt_fingerprint(self.lineage, self.graph_digest, self.request):
            raise ValueError("technical debt fingerprint is inconsistent")
        if self.producer_version != TECHNICAL_DEBT_PRODUCER or self.schema_version != TECHNICAL_DEBT_SCHEMA_VERSION:
            raise ValueError("unsupported technical debt producer or schema")
        limitations = _strings(self.limitations, "technical debt response limitations")
        if self.truncated and not limitations:
            raise ValueError("truncated technical debt responses require a limitation")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(self, "input_fingerprint", fingerprint)
        object.__setattr__(self, "total_candidate_count", total)
        object.__setattr__(self, "evaluated_count", evaluated)
        object.__setattr__(self, "unique_evaluated_count", unique)
        object.__setattr__(self, "equivalent_observation_count", equivalent)
        object.__setattr__(self, "unevaluated_count", unevaluated)
        object.__setattr__(self, "output_omitted_count", output_omitted)
        object.__setattr__(self, "omitted_count", omitted)
        object.__setattr__(self, "limitations", limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("technical debt responses must be source-free")

    @property
    def returned_count(self) -> int:
        return len(self.items)

    @property
    def ranked_count(self) -> int:
        return sum(item.rank is not None for item in self.items)

    @property
    def unranked_count(self) -> int:
        return self.returned_count - self.ranked_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "lineage": self.lineage,
            "request": self.request.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "total_candidate_count": self.total_candidate_count,
            "evaluated_count": self.evaluated_count,
            "unique_evaluated_count": self.unique_evaluated_count,
            "equivalent_observation_count": self.equivalent_observation_count,
            "unevaluated_count": self.unevaluated_count,
            "output_omitted_count": self.output_omitted_count,
            "returned_count": self.returned_count,
            "omitted_count": self.omitted_count,
            "ranked_count": self.ranked_count,
            "unranked_count": self.unranked_count,
            "truncated": self.truncated,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TechnicalDebtResponse:
        _reject_unknown(value, {
            "schema_version", "producer_version", "input_fingerprint", "graph_digest",
            "lineage", "request", "items", "capabilities", "evidence_index",
            "total_candidate_count", "evaluated_count", "returned_count",
            "unique_evaluated_count", "equivalent_observation_count",
            "unevaluated_count", "output_omitted_count", "omitted_count",
            "ranked_count", "unranked_count", "truncated",
            "limitations",
        }, "technical debt response")
        request = value.get("request")
        evidence = value.get("evidence_index")
        if not isinstance(request, Mapping) or not isinstance(evidence, Mapping):
            raise TypeError("technical debt response nested contracts must be objects")
        items = tuple(TechnicalDebtItem.from_dict(item) for item in _mappings(value.get("items"), "technical debt items"))
        result = cls(
            TechnicalDebtRequest.from_dict(request),
            items,
            tuple(TechnicalDebtCapability.from_dict(item) for item in _mappings(value.get("capabilities"), "technical debt capabilities")),
            _evidence_index_from_dict(evidence),
            _text(value.get("input_fingerprint"), "technical debt fingerprint", maximum=96),
            _text(value.get("graph_digest"), "technical debt graph digest", maximum=256),
            _text(value.get("lineage"), "technical debt lineage", maximum=256),
            _integer(value.get("total_candidate_count"), "technical debt total candidate count"),
            _integer(value.get("evaluated_count"), "technical debt evaluated count"),
            _integer(value.get("unique_evaluated_count"), "technical debt unique evaluated count"),
            _integer(value.get("equivalent_observation_count"), "technical debt equivalent observation count"),
            _integer(value.get("unevaluated_count"), "technical debt unevaluated count"),
            _integer(value.get("output_omitted_count"), "technical debt output omitted count"),
            _integer(value.get("omitted_count"), "technical debt omitted count"),
            _boolean(value.get("truncated"), "technical debt truncation"),
            _strings(value.get("limitations"), "technical debt response limitations"),
            _text(value.get("producer_version", TECHNICAL_DEBT_PRODUCER), "technical debt producer", maximum=128),
            _integer(value.get("schema_version"), "technical debt schema", default=1),
        )
        expected = result.to_dict()
        for name in ("returned_count", "ranked_count", "unranked_count"):
            if _integer(value.get(name), f"technical debt {name}") != expected[name]:
                raise ValueError(f"technical debt {name} is inconsistent")
        return result
