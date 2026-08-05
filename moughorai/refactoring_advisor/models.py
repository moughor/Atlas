"""Immutable, source-free contracts for PR137 refactoring advice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re

from moughorai.knowledge_graph import KnowledgeKind
from moughorai.platform.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
)
from moughorai.subject_resolution import (
    ResolutionStatus,
    SubjectCandidate,
    SubjectMatchBasis,
    SubjectQuery,
    SubjectResolution,
)


REFACTORING_SCHEMA_VERSION = 1
REFACTORING_PRODUCER = "atlas-pr137/1"

_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_ADVICE_ID = re.compile(r"^refactoring-advice:[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^refactoring-advisor:[0-9a-f]{64}$")
_GRAPH_DIGEST = re.compile(r"^(?:[0-9a-f]{64}|unavailable)$")
_PORTABLE_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SAFE_REFERENCE = re.compile(
    r"^(?:semantic_graph\.edge_ref|evidence|report-item|repository-report):[0-9a-f]{64}$"
)
_SOURCE_FRAGMENTS = ("//", "/*", "*/", "```", " = ", "=>")
_SOURCE_CHARS = frozenset("{}`")
_MAX_TEXT = 4_096
_MAX_ITEMS = 256


class RefactoringFamily(str, Enum):
    DUPLICATE_CONSOLIDATION = "duplicate_consolidation"
    EXTRACTION = "extraction"
    PACKAGE_RESTRUCTURING = "package_restructuring"
    DEPENDENCY_CLEANUP = "dependency_cleanup"
    CYCLE_BREAKING = "cycle_breaking"
    LAYER_VIOLATION = "layer_violation"


class RefactoringOperation(str, Enum):
    REVIEW_DEPENDENCY_CYCLE_SEAM = "review_dependency_cycle_seam"


class RefactoringCapabilityState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED = "unsupported"


class EstimateLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be an array")
    return tuple(value)


def _mappings(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    items = _sequence(value, label)
    if any(not isinstance(item, Mapping) for item in items):
        raise TypeError(f"{label} entries must be objects")
    return tuple(item for item in items if isinstance(item, Mapping))


def _reject_unknown(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(sorted(unknown))}")


def _text(
    value: object,
    label: str,
    *,
    maximum: int = _MAX_TEXT,
    source_free: bool = True,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} must not be empty")
    if len(result) > maximum or any(character in result for character in "\r\n\x00"):
        raise ValueError(f"{label} must be a bounded single line")
    if contains_absolute_path(result):
        raise ValueError(f"{label} must not contain an absolute path")
    if source_free and (
        any(item in result for item in _SOURCE_FRAGMENTS)
        or any(item in result for item in _SOURCE_CHARS)
    ):
        raise ValueError(f"{label} must contain source-free semantic text")
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
    items = _sequence(value, label)
    if len(items) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    return tuple(sorted({
        _text(item, f"{label} entry", maximum=maximum_length) for item in items
    }))


def _strict_bool(value: object, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _strict_int(value: object, label: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _unit(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{label} must be finite and between 0 and 1")
    return result


def _optional_unit(value: object, label: str) -> float | None:
    return None if value is None else _unit(value, label)


def _evidence_ids(value: object, label: str) -> tuple[str, ...]:
    result = _strings(value, label)
    if any(_EVIDENCE_ID.fullmatch(item) is None for item in result):
        raise ValueError(f"{label} contains an invalid evidence ID")
    return result


def _attributes(
    value: object,
    label: str,
) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        raw_items = tuple(value.items())
    else:
        raw_items = _sequence(value, label)
        if any(
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes, bytearray))
            or len(item) != 2
            for item in raw_items
        ):
            raise TypeError(f"{label} must contain key/value pairs")
    if len(raw_items) > _MAX_ITEMS:
        raise ValueError(f"{label} contains too many entries")
    result = tuple(sorted(
        (
            _text(item[0], f"{label} key", maximum=128),
            _text(item[1], f"{label} value", maximum=1_024),
        )
        for item in raw_items
    ))
    if any(_PORTABLE_NAME.fullmatch(key) is None for key, _ in result):
        raise ValueError(f"{label} keys must be portable identifiers")
    if len({key for key, _ in result}) != len(result):
        raise ValueError(f"{label} keys must be unique")
    return result


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or null")
    return value


def _validate_subject_query(
    query: SubjectQuery,
    label: str = "refactoring subject query",
) -> SubjectQuery:
    if not isinstance(query, SubjectQuery):
        raise TypeError(f"{label} must be a SubjectQuery")
    _text(query.identifier, f"{label} identifier")
    if query.kind is not None and not isinstance(query.kind, KnowledgeKind):
        raise TypeError(f"{label} kind must be a KnowledgeKind")
    for name in ("project", "language", "path"):
        value = getattr(query, name)
        if value is not None:
            _text(value, f"{label} {name}", maximum=1_024)
    return query


def _subject_query_from_dict(
    value: Mapping[str, object],
    label: str = "refactoring subject query",
) -> SubjectQuery:
    _reject_unknown(
        value,
        {"identifier", "kind", "project", "language", "path"},
        label,
    )
    identifier = value.get("identifier")
    if not isinstance(identifier, str):
        raise TypeError(f"{label} identifier must be a string")
    raw_kind = value.get("kind")
    if raw_kind is not None and not isinstance(raw_kind, str):
        raise TypeError(f"{label} kind must be a string or null")
    return _validate_subject_query(SubjectQuery(
        identifier,
        KnowledgeKind(raw_kind) if raw_kind is not None else None,
        _optional_string(value.get("project"), f"{label} project"),
        _optional_string(value.get("language"), f"{label} language"),
        _optional_string(value.get("path"), f"{label} path"),
    ), label)


def _validate_subject_candidate(
    candidate: SubjectCandidate,
    label: str = "refactoring subject candidate",
) -> SubjectCandidate:
    if not isinstance(candidate, SubjectCandidate):
        raise TypeError(f"{label} must be a SubjectCandidate")
    if not isinstance(candidate.kind, KnowledgeKind):
        raise TypeError(f"{label} kind must be a KnowledgeKind")
    if not isinstance(candidate.match_basis, SubjectMatchBasis):
        raise TypeError(f"{label} match basis must be a SubjectMatchBasis")
    for name in ("canonical_id", "name", "qualified_name", "language"):
        _text(getattr(candidate, name), f"{label} {name}", maximum=1_024)
    for name in ("project", "path"):
        value = getattr(candidate, name)
        if value is not None:
            _text(value, f"{label} {name}", maximum=1_024)
    for scope in candidate.project_scopes:
        _text(scope, f"{label} project scope", maximum=256)
    return candidate


def _validate_subject_resolution(
    resolution: SubjectResolution,
) -> SubjectResolution:
    if not isinstance(resolution, SubjectResolution):
        raise TypeError("refactoring resolution must be a SubjectResolution")
    _validate_subject_query(resolution.query, "refactoring resolution query")
    if resolution.subject is not None:
        _validate_subject_candidate(
            resolution.subject, "refactoring resolved subject"
        )
    for candidate in resolution.candidates:
        _validate_subject_candidate(
            candidate, "refactoring resolution candidate"
        )
    _text(resolution.graph_digest, "refactoring resolution graph digest")
    for limitation in resolution.limitations:
        _text(limitation, "refactoring resolution limitation")
    return resolution


def _confidence_from_dict(value: Mapping[str, object]) -> ConfidenceResult:
    _reject_unknown(value, {
        "score", "tier", "support", "coverage", "agreement",
        "contradiction_penalty", "ambiguity_penalty", "missing_roles",
        "model_version",
    }, "refactoring confidence")
    result = ConfidenceResult(
        _unit(value.get("score", 0.0), "confidence score"),
        ConfidenceTier(_text(value.get("tier", "insufficient"), "confidence tier")),
        _unit(value.get("support", 0.0), "confidence support"),
        _unit(value.get("coverage", 0.0), "confidence coverage"),
        _unit(value.get("agreement", 1.0), "confidence agreement"),
        _unit(value.get("contradiction_penalty", 0.0), "confidence contradiction"),
        _unit(value.get("ambiguity_penalty", 0.0), "confidence ambiguity"),
        _strings(value.get("missing_roles"), "confidence missing roles"),
        _strict_int(value.get("model_version"), "confidence model version", default=1),
    )
    return _validate_confidence(result)


def _validate_confidence(value: ConfidenceResult) -> ConfidenceResult:
    if not isinstance(value, ConfidenceResult):
        raise TypeError("refactoring confidence must use the shared ConfidenceResult")
    if value.model_version != ConfidenceCalculator.MODEL_VERSION:
        raise ValueError("unsupported refactoring confidence model")
    expected = round(max(0.0, min(
        1.0,
        value.support * value.coverage * value.agreement
        - value.contradiction_penalty - value.ambiguity_penalty,
    )), 4)
    if not math.isclose(value.score, expected, rel_tol=0.0, abs_tol=3e-4):
        raise ValueError("refactoring confidence score is inconsistent")
    return value


@dataclass(frozen=True, order=True, slots=True)
class RefactoringEstimateComponent:
    name: str
    available: bool
    value: float | None
    weight: float
    contribution: float
    evidence_ids: tuple[str, ...] = ()
    limitation: str | None = None

    def __post_init__(self) -> None:
        name = _text(self.name, "estimate component name", maximum=128)
        if _PORTABLE_NAME.fullmatch(name) is None:
            raise ValueError("estimate component name must be a portable identifier")
        if not isinstance(self.available, bool):
            raise TypeError("estimate component availability must be boolean")
        value = _optional_unit(self.value, "estimate component value")
        weight = _unit(self.weight, "estimate component weight")
        contribution = _unit(self.contribution, "estimate component contribution")
        evidence_ids = _evidence_ids(self.evidence_ids, "estimate component evidence")
        limitation = _optional_text(self.limitation, "estimate component limitation")
        if self.available:
            if value is None or weight <= 0.0:
                raise ValueError("available estimate components require a value and weight")
            if not math.isclose(contribution, value * weight, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("estimate component contribution is inconsistent")
        elif value is not None or weight != 0.0 or contribution != 0.0 or evidence_ids:
            raise ValueError("unavailable estimate components cannot contribute")
        elif limitation is None:
            raise ValueError("unavailable estimate components require a limitation")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "weight", weight)
        object.__setattr__(self, "contribution", contribution)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "limitation", limitation)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "available": self.available, "value": self.value,
            "weight": self.weight, "contribution": self.contribution,
            "evidence_ids": list(self.evidence_ids), "limitation": self.limitation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringEstimateComponent:
        _reject_unknown(value, {
            "name", "available", "value", "weight", "contribution",
            "evidence_ids", "limitation",
        }, "estimate component")
        return cls(
            _text(value.get("name", ""), "estimate component name", maximum=128),
            _strict_bool(value.get("available"), "estimate component availability", default=False),
            _optional_unit(value.get("value"), "estimate component value"),
            _unit(value.get("weight", 0.0), "estimate component weight"),
            _unit(value.get("contribution", 0.0), "estimate component contribution"),
            _evidence_ids(value.get("evidence_ids"), "estimate component evidence"),
            _optional_text(value.get("limitation"), "estimate component limitation"),
        )


@dataclass(frozen=True, slots=True)
class RefactoringEstimate:
    level: EstimateLevel
    score: float | None
    components: tuple[RefactoringEstimateComponent, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        level = self.level if isinstance(self.level, EstimateLevel) else EstimateLevel(self.level)
        score = _optional_unit(self.score, "refactoring estimate score")
        components = tuple(sorted(self.components))
        if any(not isinstance(item, RefactoringEstimateComponent) for item in components):
            raise TypeError("estimate components must use RefactoringEstimateComponent")
        if len({item.name for item in components}) != len(components):
            raise ValueError("estimate component names must be unique")
        limitations = _strings(self.limitations, "estimate limitations")
        if level is EstimateLevel.UNKNOWN:
            if score is not None:
                raise ValueError("unknown estimates cannot contain a numeric score")
            if not limitations:
                raise ValueError("unknown estimates require an explicit limitation")
        elif score is None:
            raise ValueError("known estimates require a numeric score")
        else:
            available = tuple(item for item in components if item.available)
            total_weight = sum(item.weight for item in available)
            if not available or total_weight <= 0.0:
                raise ValueError("known estimates require an available component")
            expected_score = round(
                sum(item.contribution for item in available) / total_weight,
                4,
            )
            if not math.isclose(
                score, expected_score, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError("refactoring estimate score is inconsistent")
            expected_level = (
                EstimateLevel.HIGH
                if score >= 0.67
                else EstimateLevel.MEDIUM
                if score >= 0.34
                else EstimateLevel.LOW
            )
            if level is not expected_level:
                raise ValueError("refactoring estimate level is inconsistent")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "limitations", limitations)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({value for item in self.components for value in item.evidence_ids}))

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level.value, "score": self.score,
            "components": [item.to_dict() for item in self.components],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringEstimate:
        _reject_unknown(value, {"level", "score", "components", "limitations"}, "estimate")
        return cls(
            EstimateLevel(_text(value.get("level", "unknown"), "estimate level")),
            _optional_unit(value.get("score"), "estimate score"),
            tuple(RefactoringEstimateComponent.from_dict(item) for item in _mappings(value.get("components"), "estimate components")),
            _strings(value.get("limitations"), "estimate limitations"),
        )


@dataclass(frozen=True, slots=True)
class RefactoringImpact:
    state: RefactoringCapabilityState
    affected_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    breaking_state: str = "not_evaluated"
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    direct_count: int = 0
    transitive_count: int = 0
    possible_breaking_count: int = 0

    def __post_init__(self) -> None:
        state = self.state if isinstance(self.state, RefactoringCapabilityState) else RefactoringCapabilityState(self.state)
        for name in (
            "affected_count", "omitted_count", "direct_count", "transitive_count",
            "possible_breaking_count",
        ):
            value = _strict_int(getattr(self, name), f"impact {name}")
            if value < 0:
                raise ValueError(f"impact {name} must be non-negative")
            object.__setattr__(self, name, value)
        if not isinstance(self.truncated, bool):
            raise TypeError("impact truncation must be boolean")
        breaking = _text(self.breaking_state, "impact breaking state", maximum=64)
        if breaking not in {
            "proven_breaking", "potentially_breaking", "not_evaluated",
            "unsupported", "not_applicable",
        }:
            raise ValueError("impact breaking state is unsupported")
        evidence_ids = _evidence_ids(self.evidence_ids, "impact evidence")
        limitations = _strings(self.limitations, "impact limitations")
        if state is not RefactoringCapabilityState.AVAILABLE and not limitations:
            raise ValueError("non-available impact requires an explicit limitation")
        if self.direct_count + self.transitive_count != self.affected_count:
            raise ValueError("impact direct and transitive counts are inconsistent")
        if self.possible_breaking_count > self.affected_count:
            raise ValueError("impact breaking count exceeds affected subjects")
        if state in {
            RefactoringCapabilityState.UNAVAILABLE,
            RefactoringCapabilityState.INCOMPATIBLE,
            RefactoringCapabilityState.UNSUPPORTED,
        } and (
            self.affected_count
            or self.omitted_count
            or self.truncated
            or self.possible_breaking_count
            or evidence_ids
            or breaking != "not_evaluated"
        ):
            raise ValueError("unavailable impact cannot report evaluated results")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "breaking_state", breaking)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "limitations", limitations)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value, "affected_count": self.affected_count,
            "direct_count": self.direct_count, "transitive_count": self.transitive_count,
            "possible_breaking_count": self.possible_breaking_count,
            "omitted_count": self.omitted_count, "truncated": self.truncated,
            "breaking_state": self.breaking_state,
            "evidence_ids": list(self.evidence_ids), "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringImpact:
        _reject_unknown(value, {
            "state", "affected_count", "direct_count", "transitive_count",
            "possible_breaking_count", "omitted_count", "truncated",
            "breaking_state", "evidence_ids", "limitations",
        }, "refactoring impact")
        return cls(
            RefactoringCapabilityState(_text(value.get("state", "unavailable"), "impact state")),
            _strict_int(value.get("affected_count"), "impact affected count"),
            _strict_int(value.get("omitted_count"), "impact omitted count"),
            _strict_bool(value.get("truncated"), "impact truncation", default=False),
            _text(value.get("breaking_state", "not_evaluated"), "impact breaking state", maximum=64),
            _evidence_ids(value.get("evidence_ids"), "impact evidence"),
            _strings(value.get("limitations"), "impact limitations"),
            _strict_int(value.get("direct_count"), "impact direct count"),
            _strict_int(value.get("transitive_count"), "impact transitive count"),
            _strict_int(value.get("possible_breaking_count"), "impact possible breaking count"),
        )


@dataclass(frozen=True, order=True, slots=True)
class RefactoringCapability:
    family: RefactoringFamily
    state: RefactoringCapabilityState
    candidate_count: int = 0
    coverage: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        family = self.family if isinstance(self.family, RefactoringFamily) else RefactoringFamily(self.family)
        state = self.state if isinstance(self.state, RefactoringCapabilityState) else RefactoringCapabilityState(self.state)
        count = _strict_int(self.candidate_count, "capability candidate count")
        if count < 0:
            raise ValueError("capability candidate count must be non-negative")
        coverage = _optional_unit(self.coverage, "capability coverage")
        limitations = _strings(self.limitations, "capability limitations")
        if state is not RefactoringCapabilityState.AVAILABLE and not limitations:
            raise ValueError("non-available capabilities require an explicit limitation")
        if state in {
            RefactoringCapabilityState.UNAVAILABLE,
            RefactoringCapabilityState.INCOMPATIBLE,
            RefactoringCapabilityState.UNSUPPORTED,
        } and (count or coverage is not None):
            raise ValueError(
                "unavailable capabilities cannot contain candidates or coverage"
            )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "candidate_count", count)
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "limitations", limitations)

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family.value, "state": self.state.value,
            "candidate_count": self.candidate_count, "coverage": self.coverage,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringCapability:
        _reject_unknown(value, {"family", "state", "candidate_count", "coverage", "limitations"}, "refactoring capability")
        return cls(
            RefactoringFamily(_text(value.get("family", ""), "capability family")),
            RefactoringCapabilityState(_text(value.get("state", "unavailable"), "capability state")),
            _strict_int(value.get("candidate_count"), "capability candidate count"),
            _optional_unit(value.get("coverage"), "capability coverage"),
            _strings(value.get("limitations"), "capability limitations"),
        )


def _candidate_from_dict(value: Mapping[str, object]) -> SubjectCandidate:
    _reject_unknown(value, {
        "canonical_id", "kind", "name", "qualified_name", "project", "language",
        "path", "project_scopes", "match_basis",
    }, "refactoring subject")
    required = ("canonical_id", "kind", "name", "qualified_name")
    if any(not isinstance(value.get(name), str) for name in required):
        raise TypeError("refactoring subject required fields must be strings")
    raw_project_scopes = value.get("project_scopes")
    scopes = _strings(raw_project_scopes, "refactoring subject project scopes")
    raw_match_basis = value.get("match_basis", SubjectMatchBasis.NONE.value)
    if not isinstance(raw_match_basis, str):
        raise TypeError("refactoring subject match basis must be a string")
    raw_language = value.get("language", "unknown")
    if not isinstance(raw_language, str):
        raise TypeError("refactoring subject language must be a string")
    result = SubjectCandidate(
        str(value["canonical_id"]),
        KnowledgeKind(str(value["kind"])),
        str(value["name"]),
        str(value["qualified_name"]),
        _optional_string(value.get("project"), "refactoring subject project"),
        raw_language,
        _optional_string(value.get("path"), "refactoring subject path"),
        scopes,
        SubjectMatchBasis(raw_match_basis),
        str(value["canonical_id"]),
    )
    return _validate_subject_candidate(result)


def refactoring_advice_id(
    family: RefactoringFamily,
    operation: RefactoringOperation,
    subjects: Sequence[SubjectCandidate | str],
    evidence_ids: Sequence[str],
    attributes: Mapping[str, str] | Sequence[tuple[str, str]] = (),
) -> str:
    family = family if isinstance(family, RefactoringFamily) else RefactoringFamily(family)
    operation = operation if isinstance(operation, RefactoringOperation) else RefactoringOperation(operation)
    subject_ids = tuple(sorted({
        item.canonical_id if isinstance(item, SubjectCandidate) else _text(item, "advice subject ID", maximum=1_024)
        for item in subjects
    }))
    evidence = _evidence_ids(tuple(evidence_ids), "advice evidence")
    canonical_attributes = _attributes(attributes, "advice attributes")
    payload = {
        "family": family.value,
        "operation": operation.value,
        "subjects": list(subject_ids),
        "evidence_ids": list(evidence),
        "attributes": dict(canonical_attributes),
        "producer": REFACTORING_PRODUCER,
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return f"refactoring-advice:{digest}"


@dataclass(frozen=True, slots=True)
class RefactoringAdvice:
    advice_id: str
    family: RefactoringFamily
    operation: RefactoringOperation
    subjects: tuple[SubjectCandidate, ...]
    confidence: ConfidenceResult
    evidence_ids: tuple[str, ...]
    rationale: str
    preconditions: tuple[str, ...]
    expected_gain: RefactoringEstimate
    effort: RefactoringEstimate
    impact: RefactoringImpact
    limitations: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        family = self.family if isinstance(self.family, RefactoringFamily) else RefactoringFamily(self.family)
        operation = self.operation if isinstance(self.operation, RefactoringOperation) else RefactoringOperation(self.operation)
        subjects = tuple(sorted(
            (
                _validate_subject_candidate(item, "refactoring advice subject")
                for item in self.subjects
            ),
            key=lambda item: item.canonical_id,
        ))
        if not subjects:
            raise TypeError("refactoring advice requires canonical subjects")
        if len({item.canonical_id for item in subjects}) != len(subjects):
            raise ValueError("refactoring advice subject IDs must be unique")
        if operation is RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM and (
            family is not RefactoringFamily.CYCLE_BREAKING or len(subjects) != 2
        ):
            raise ValueError("cycle-seam advice requires two cycle-breaking subjects")
        evidence_ids = _evidence_ids(self.evidence_ids, "advice evidence")
        if not evidence_ids:
            raise ValueError("refactoring advice requires evidence")
        attributes = _attributes(self.attributes, "advice attributes")
        if operation is RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM:
            roles = dict(attributes)
            if roles.get("source") not in {
                item.canonical_id for item in subjects
            } or roles.get("target") not in {
                item.canonical_id for item in subjects
            } or roles.get("source") == roles.get("target"):
                raise ValueError(
                    "cycle-seam advice requires distinct source and target roles"
                )
        expected = refactoring_advice_id(
            family, operation, subjects, evidence_ids, attributes
        )
        advice_id = _text(self.advice_id, "refactoring advice ID", maximum=96)
        if _ADVICE_ID.fullmatch(advice_id) is None or advice_id != expected:
            raise ValueError("refactoring advice ID is inconsistent")
        confidence = _validate_confidence(self.confidence)
        if not isinstance(self.expected_gain, RefactoringEstimate) or not isinstance(self.effort, RefactoringEstimate):
            raise TypeError("refactoring estimates use RefactoringEstimate")
        if not isinstance(self.impact, RefactoringImpact):
            raise TypeError("refactoring impact uses RefactoringImpact")
        nested = set(self.expected_gain.evidence_ids) | set(self.effort.evidence_ids) | set(self.impact.evidence_ids)
        if not nested.issubset(evidence_ids):
            raise ValueError("nested estimate evidence must belong to the advice evidence closure")
        rationale = _text(self.rationale, "advice rationale", maximum=2_048)
        preconditions = _strings(self.preconditions, "advice preconditions")
        verification = _strings(self.verification, "advice verification")
        if not preconditions or not verification:
            raise ValueError("refactoring advice requires preconditions and verification")
        limitations = _strings(self.limitations, "advice limitations")
        object.__setattr__(self, "advice_id", advice_id)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "subjects", subjects)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "preconditions", preconditions)
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "verification", verification)
        object.__setattr__(self, "attributes", attributes)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("refactoring advice must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "advice_id": self.advice_id, "family": self.family.value,
            "operation": self.operation.value,
            "subjects": [item.to_dict() for item in self.subjects],
            "confidence": self.confidence.to_dict(),
            "evidence_ids": list(self.evidence_ids), "rationale": self.rationale,
            "preconditions": list(self.preconditions),
            "expected_gain": self.expected_gain.to_dict(), "effort": self.effort.to_dict(),
            "impact": self.impact.to_dict(), "limitations": list(self.limitations),
            "verification": list(self.verification),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringAdvice:
        _reject_unknown(value, {
            "advice_id", "family", "operation", "subjects", "confidence",
            "evidence_ids", "rationale", "preconditions", "expected_gain",
            "effort", "impact", "limitations", "verification",
            "attributes",
        }, "refactoring advice")
        confidence = value.get("confidence")
        gain = value.get("expected_gain")
        effort = value.get("effort")
        impact = value.get("impact")
        if not all(isinstance(item, Mapping) for item in (confidence, gain, effort, impact)):
            raise TypeError("refactoring advice nested values must be objects")
        return cls(
            _text(value.get("advice_id", ""), "advice ID", maximum=96),
            RefactoringFamily(_text(value.get("family", ""), "advice family")),
            RefactoringOperation(_text(value.get("operation", ""), "advice operation")),
            tuple(_candidate_from_dict(item) for item in _mappings(value.get("subjects"), "advice subjects")),
            _confidence_from_dict(confidence),  # type: ignore[arg-type]
            _evidence_ids(value.get("evidence_ids"), "advice evidence"),
            _text(value.get("rationale", ""), "advice rationale", maximum=2_048),
            _strings(value.get("preconditions"), "advice preconditions"),
            RefactoringEstimate.from_dict(gain),  # type: ignore[arg-type]
            RefactoringEstimate.from_dict(effort),  # type: ignore[arg-type]
            RefactoringImpact.from_dict(impact),  # type: ignore[arg-type]
            _strings(value.get("limitations"), "advice limitations"),
            _strings(value.get("verification"), "advice verification"),
            _attributes(value.get("attributes"), "advice attributes"),
        )


def _default_subject() -> SubjectQuery:
    return SubjectQuery("repository", KnowledgeKind.REPOSITORY)


@dataclass(frozen=True, slots=True)
class RefactoringRequest:
    subject: SubjectQuery = field(default_factory=_default_subject)
    families: tuple[RefactoringFamily, ...] = ()
    limit: int = 20
    include_impact: bool = True
    impact_depth: int = 4

    def __post_init__(self) -> None:
        _validate_subject_query(self.subject)
        families = tuple(sorted({
            item if isinstance(item, RefactoringFamily) else RefactoringFamily(item)
            for item in _sequence(self.families, "refactoring families")
        }, key=lambda item: item.value))
        limit = _strict_int(self.limit, "refactoring result limit")
        depth = _strict_int(self.impact_depth, "refactoring impact depth")
        if not 1 <= limit <= 1_000:
            raise ValueError("refactoring result limit must be between 1 and 1000")
        if not 1 <= depth <= 64:
            raise ValueError("refactoring impact depth must be between 1 and 64")
        if not isinstance(self.include_impact, bool):
            raise TypeError("refactoring impact option must be boolean")
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "limit", limit)
        object.__setattr__(self, "impact_depth", depth)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("refactoring requests must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject.to_dict(),
            "families": [item.value for item in self.families],
            "limit": self.limit, "include_impact": self.include_impact,
            "impact_depth": self.impact_depth,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringRequest:
        _reject_unknown(value, {"subject", "families", "limit", "include_impact", "impact_depth"}, "refactoring request")
        subject = value.get("subject")
        if not isinstance(subject, Mapping):
            raise TypeError("refactoring request subject must be an object")
        return cls(
            _subject_query_from_dict(subject),
            tuple(RefactoringFamily(_text(item, "refactoring family")) for item in _sequence(value.get("families"), "refactoring families")),
            _strict_int(value.get("limit"), "refactoring result limit", default=20),
            _strict_bool(value.get("include_impact"), "refactoring impact option", default=True),
            _strict_int(value.get("impact_depth"), "refactoring impact depth", default=4),
        )


def refactoring_fingerprint(
    lineage: str,
    graph_digest: str,
    request: RefactoringRequest,
) -> str:
    if not isinstance(request, RefactoringRequest):
        raise TypeError("refactoring fingerprint requires RefactoringRequest")
    lineage = _text(lineage, "refactoring lineage", maximum=256)
    graph_digest = _text(graph_digest, "refactoring graph digest", maximum=256)
    payload = {
        "producer": REFACTORING_PRODUCER, "schema_version": REFACTORING_SCHEMA_VERSION,
        "lineage": lineage, "graph_digest": graph_digest, "request": request.to_dict(),
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return f"refactoring-advisor:{digest}"


def _resolution_from_dict(value: Mapping[str, object]) -> SubjectResolution:
    _reject_unknown(value, {
        "query", "status", "subject", "candidates", "total_candidate_count",
        "included_candidate_count", "omitted_candidate_count", "match_basis",
        "graph_digest", "limitations",
    }, "refactoring resolution")
    query = value.get("query")
    raw_subject = value.get("subject")
    if not isinstance(query, Mapping):
        raise TypeError("refactoring resolution query must be an object")
    if raw_subject is not None and not isinstance(raw_subject, Mapping):
        raise TypeError("refactoring resolved subject must be an object or null")
    raw_status = value.get("status")
    raw_match_basis = value.get("match_basis")
    if not isinstance(raw_status, str) or not isinstance(raw_match_basis, str):
        raise TypeError("refactoring resolution enums must be strings")
    candidates = tuple(
        _candidate_from_dict(item)
        for item in _mappings(value.get("candidates"), "resolution candidates")
    )
    included = _strict_int(
        value.get("included_candidate_count"),
        "refactoring included candidate count",
        default=len(candidates),
    )
    if included != len(candidates):
        raise ValueError("refactoring included candidate count is inconsistent")
    return _validate_subject_resolution(SubjectResolution(
        _subject_query_from_dict(query, "refactoring resolution query"),
        ResolutionStatus(raw_status),
        _candidate_from_dict(raw_subject) if raw_subject is not None else None,
        candidates,
        _strict_int(
            value.get("total_candidate_count"),
            "refactoring resolution candidate count",
        ),
        _strict_int(
            value.get("omitted_candidate_count"),
            "refactoring resolution omitted count",
        ),
        SubjectMatchBasis(raw_match_basis),
        _text(
            value.get("graph_digest", ""),
            "refactoring resolution graph digest",
        ),
        _strings(value.get("limitations"), "refactoring resolution limitations"),
    ))


def _evidence_index_from_dict(value: Mapping[str, object]) -> EvidenceIndex:
    _reject_unknown(value, {"schema_version", "records"}, "refactoring evidence index")
    schema = _strict_int(value.get("schema_version"), "evidence schema", default=1)
    if schema != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported refactoring evidence schema")
    records = []
    seen = set()
    for item in _mappings(value.get("records"), "refactoring evidence records"):
        _reject_unknown(item, {
            "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
            "source_refs", "scope", "language", "detail", "limitations",
            "reliability", "specificity",
        }, "refactoring evidence record")
        raw_detail = item.get("detail", {})
        if not isinstance(raw_detail, Mapping):
            raise TypeError("refactoring evidence detail must be an object")
        source_refs = _strings(item.get("source_refs"), "evidence source references", maximum_length=256)
        if any(_SAFE_REFERENCE.fullmatch(reference) is None for reference in source_refs):
            raise ValueError("refactoring evidence contains unsafe source references")
        detail = {
            _text(key, "evidence detail key", maximum=128): _text(data, "evidence detail value", maximum=512)
            for key, data in raw_detail.items()
        }
        record = EvidenceRecord.create(
            EvidenceKind(_text(item.get("kind", ""), "evidence kind", maximum=64)),
            _text(item.get("subject_id", ""), "evidence subject", maximum=1_024),
            _text(item.get("producer", ""), "evidence producer", maximum=128),
            _text(item.get("snapshot_id", ""), "evidence snapshot", maximum=256),
            source_refs=source_refs,
            scope=_text(item.get("scope", "repository"), "evidence scope", maximum=256),
            language=_text(item.get("language", "unknown"), "evidence language", maximum=128),
            detail=detail,
            limitations=_strings(item.get("limitations"), "evidence limitations"),
            reliability=_unit(item.get("reliability", 1.0), "evidence reliability"),
            specificity=_unit(item.get("specificity", 1.0), "evidence specificity"),
        )
        serialized_id = _text(item.get("evidence_id", ""), "evidence ID", maximum=96)
        if serialized_id in seen or record.evidence_id != serialized_id:
            raise ValueError("refactoring evidence identity is inconsistent")
        seen.add(serialized_id)
        records.append(record)
    return EvidenceIndex(records, frozen=True)


@dataclass(frozen=True, slots=True)
class RefactoringResponse:
    request: RefactoringRequest
    resolution: SubjectResolution
    advice: tuple[RefactoringAdvice, ...]
    capabilities: tuple[RefactoringCapability, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    lineage: str
    total_candidate_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    limitations: tuple[str, ...] = ()
    visited_node_count: int = 0
    visited_edge_count: int = 0
    producer_version: str = REFACTORING_PRODUCER
    schema_version: int = REFACTORING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, RefactoringRequest):
            raise TypeError("refactoring response request and resolution are invalid")
        _validate_subject_resolution(self.resolution)
        if self.resolution.query != self.request.subject:
            raise ValueError("refactoring resolution does not match its request")
        advice = tuple(sorted(self.advice, key=lambda item: (
            -(item.expected_gain.score if item.expected_gain.score is not None else -1.0),
            item.effort.score if item.effort.score is not None else 2.0,
            -item.confidence.score,
            item.advice_id,
        )))
        if any(not isinstance(item, RefactoringAdvice) for item in advice):
            raise TypeError("refactoring response advice is invalid")
        if len({item.advice_id for item in advice}) != len(advice):
            raise ValueError("refactoring advice IDs must be unique")
        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.family.value))
        if any(not isinstance(item, RefactoringCapability) for item in capabilities):
            raise TypeError("refactoring response capabilities are invalid")
        if len({item.family for item in capabilities}) != len(capabilities):
            raise ValueError("refactoring capability families must be unique")
        if {item.family for item in capabilities} != set(RefactoringFamily):
            raise ValueError("refactoring response must report every capability family")
        if self.resolution.status is not ResolutionStatus.RESOLVED and advice:
            raise ValueError("unresolved refactoring scopes cannot contain advice")
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("refactoring response requires an EvidenceIndex")
        evidence = self.evidence_index.freeze()
        lineage = _text(self.lineage, "refactoring lineage", maximum=256)
        for record in evidence.records:
            canonical = EvidenceRecord.create(
                record.kind, record.subject_id, record.producer, record.snapshot_id,
                source_refs=record.source_refs, scope=record.scope, language=record.language,
                detail=record.detail, limitations=record.limitations,
                reliability=record.reliability, specificity=record.specificity,
            )
            if canonical != record or record.snapshot_id != lineage:
                raise ValueError("refactoring response evidence identity or lineage is inconsistent")
            if any(_SAFE_REFERENCE.fullmatch(item) is None for item in record.source_refs):
                raise ValueError("refactoring response evidence contains unsafe references")
            _text(record.subject_id, "refactoring evidence subject", maximum=1_024)
            _text(record.producer, "refactoring evidence producer", maximum=128)
            _text(record.scope, "refactoring evidence scope", maximum=256)
            _text(record.language, "refactoring evidence language", maximum=128)
            for key, item in record.detail:
                _text(key, "refactoring evidence detail key", maximum=128)
                _text(item, "refactoring evidence detail value", maximum=512)
            for item in record.limitations:
                _text(item, "refactoring evidence limitation")
        available = {item.evidence_id for item in evidence.records}
        referenced = {value for item in advice for value in item.evidence_ids}
        if referenced != available:
            raise ValueError("refactoring response evidence closure is not exact")
        total = _strict_int(self.total_candidate_count, "refactoring candidate count")
        omitted = _strict_int(self.omitted_count, "refactoring omitted count")
        visited_nodes = _strict_int(self.visited_node_count, "refactoring visited node count")
        visited_edges = _strict_int(self.visited_edge_count, "refactoring visited edge count")
        if min(total, omitted, visited_nodes, visited_edges) < 0 or total < len(advice):
            raise ValueError("refactoring response counts are inconsistent")
        if omitted != total - len(advice):
            raise ValueError("refactoring omitted count is inconsistent")
        if not isinstance(self.truncated, bool):
            raise TypeError("refactoring truncation must be boolean")
        if omitted and not self.truncated:
            raise ValueError("omitted advice requires an explicit truncation state")
        limitations = _strings(self.limitations, "refactoring response limitations")
        if self.truncated and not limitations:
            raise ValueError("truncated refactoring responses require a limitation")
        graph_digest = _text(self.graph_digest, "refactoring graph digest", maximum=256)
        if _GRAPH_DIGEST.fullmatch(graph_digest) is None:
            raise ValueError("refactoring graph digest is malformed")
        fingerprint = _text(self.input_fingerprint, "refactoring input fingerprint", maximum=96)
        if _FINGERPRINT.fullmatch(fingerprint) is None or fingerprint != refactoring_fingerprint(lineage, graph_digest, self.request):
            raise ValueError("refactoring response fingerprint is inconsistent")
        if self.resolution.graph_digest != graph_digest:
            raise ValueError("refactoring resolution graph digest is inconsistent")
        if self.producer_version != REFACTORING_PRODUCER or self.schema_version != REFACTORING_SCHEMA_VERSION:
            raise ValueError("unsupported refactoring response producer or schema")
        object.__setattr__(self, "advice", advice)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(self, "input_fingerprint", fingerprint)
        object.__setattr__(self, "graph_digest", graph_digest)
        object.__setattr__(self, "lineage", lineage)
        object.__setattr__(self, "total_candidate_count", total)
        object.__setattr__(self, "omitted_count", omitted)
        object.__setattr__(self, "visited_node_count", visited_nodes)
        object.__setattr__(self, "visited_edge_count", visited_edges)
        object.__setattr__(self, "limitations", limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("refactoring responses must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest, "lineage": self.lineage,
            "request": self.request.to_dict(), "resolution": self.resolution.to_dict(),
            "advice": [item.to_dict() for item in self.advice],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "total_candidate_count": self.total_candidate_count,
            "returned_count": len(self.advice), "omitted_count": self.omitted_count,
            "visited_node_count": self.visited_node_count,
            "visited_edge_count": self.visited_edge_count,
            "truncated": self.truncated, "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RefactoringResponse:
        _reject_unknown(value, {
            "schema_version", "producer_version", "input_fingerprint", "graph_digest",
            "lineage", "request", "resolution", "advice", "capabilities",
            "evidence_index", "total_candidate_count", "returned_count",
            "omitted_count", "visited_node_count", "visited_edge_count", "truncated",
            "limitations",
        }, "refactoring response")
        request = value.get("request")
        resolution = value.get("resolution")
        evidence = value.get("evidence_index")
        if not all(isinstance(item, Mapping) for item in (request, resolution, evidence)):
            raise TypeError("refactoring response nested contracts must be objects")
        advice = tuple(RefactoringAdvice.from_dict(item) for item in _mappings(value.get("advice"), "refactoring advice"))
        returned = _strict_int(value.get("returned_count"), "refactoring returned count", default=len(advice))
        if returned != len(advice):
            raise ValueError("refactoring returned count is inconsistent")
        return cls(
            RefactoringRequest.from_dict(request),  # type: ignore[arg-type]
            _resolution_from_dict(resolution),  # type: ignore[arg-type]
            advice,
            tuple(RefactoringCapability.from_dict(item) for item in _mappings(value.get("capabilities"), "refactoring capabilities")),
            _evidence_index_from_dict(evidence),  # type: ignore[arg-type]
            _text(value.get("input_fingerprint", ""), "refactoring fingerprint", maximum=96),
            _text(value.get("graph_digest", ""), "refactoring graph digest", maximum=256),
            _text(value.get("lineage", ""), "refactoring lineage", maximum=256),
            _strict_int(value.get("total_candidate_count"), "refactoring candidate count"),
            _strict_int(value.get("omitted_count"), "refactoring omitted count"),
            _strict_bool(value.get("truncated"), "refactoring truncation", default=False),
            _strings(value.get("limitations"), "refactoring response limitations"),
            _strict_int(value.get("visited_node_count"), "refactoring visited node count"),
            _strict_int(value.get("visited_edge_count"), "refactoring visited edge count"),
            _text(value.get("producer_version", REFACTORING_PRODUCER), "refactoring producer", maximum=128),
            _strict_int(value.get("schema_version"), "refactoring schema", default=1),
        )


# Concise aliases are internal conveniences; the explicit names remain canonical.
Family = RefactoringFamily
Operation = RefactoringOperation
CapabilityState = RefactoringCapabilityState
