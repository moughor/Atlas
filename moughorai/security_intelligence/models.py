"""Strict, deterministic, source-free contracts for PR138 security intelligence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import heapq
import hashlib
from itertools import islice
import json
import math
from pathlib import PurePosixPath
import re

from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)


SECURITY_INTELLIGENCE_SCHEMA_VERSION = 1
SECURITY_INTELLIGENCE_PRODUCER = "atlas-pr138/1"
SECURITY_INTELLIGENCE_SNAPSHOT_KEY = "security_intelligence"

_MAX_TEXT = 4_096
_MAX_ITEMS = 4_096
_MAX_PROJECTS = 10_000
_MAX_TRACE_LOCATIONS = 256
_MAX_REQUEST_LIMIT = 10_000
_MAX_PRODUCER_INPUT_FINDINGS = 100_000
_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_FINDING_ID = re.compile(r"^security-intelligence:[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^legacy-fingerprint:[0-9a-f]{64}$")
_DIGEST = re.compile(r"^(?:[0-9a-f]{64}|unavailable)$")
_SOURCE_FRAGMENTS = ("//", "/*", "*/", "```", " = ", "=>")
_SOURCE_CHARS = frozenset("{}`")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|credential|password|passwd|secret|token)\s*[:=]\s*\S+"
)
_PORTABLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,1023}$")
_PORTABLE_LANGUAGE = re.compile(r"^[a-z0-9][a-z0-9_+.-]{0,127}$")
_PRODUCER_LIMITATION_PATTERNS = tuple(re.compile(item) for item in (
    r"Java security evidence is file-local; inter-file and cross-project flows are not analyzed by this producer\.",
    r"Java security analysis skipped [1-9][0-9]{0,8} selected source file\(s\) that could not be read\.",
    r"Java security analysis skipped [1-9][0-9]{0,8} source file\(s\) whose project-relative path could not be established\.",
    r"Java security analysis failed for [1-9][0-9]{0,8} selected source file\(s\)\.",
    r"Java security producers exceeded the per-project finding bound; retained 4096 deterministic findings and omitted [1-9][0-9]{0,8}\.",
    r"Gradle source sets were analyzed independently; cross-source-set security flows are unavailable\.",
    r"Security producer result normalization failed; findings from this project were omitted\.",
    r"Security producer emitted [1-9][0-9]{0,8} findings; retained the deterministic first 4096 and omitted [1-9][0-9]{0,8}\.",
    r"[1-9][0-9]{0,2} unstructured producer limitation\(s\) were omitted at the source-free boundary\.",
))


class SecurityCategory(str, Enum):
    SECRETS = "secrets"
    SQL_INJECTION = "sql_injection"
    WEAK_CRYPTOGRAPHY = "weak_cryptography"
    PATH_TRAVERSAL = "path_traversal"
    SSRF = "ssrf"
    XSS = "xss"
    UNSAFE_DESERIALIZATION = "unsafe_deserialization"
    UNSAFE_REFLECTION = "unsafe_reflection"
    GENERAL_TAINT = "general_taint"


class SecurityCapabilityState(str, Enum):
    ANALYZED = "analyzed"
    PARTIAL = "partial"
    NOT_ANALYZED = "not_analyzed"
    INCOMPATIBLE = "incompatible"


class SecuritySeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LegacyConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SecurityScope(str, Enum):
    REPOSITORY = "repository"
    PROJECT = "project"
    SYMBOL = "symbol"


class SecurityPriorityTier(str, Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER = {
    SecuritySeverity.INFO: 0,
    SecuritySeverity.LOW: 1,
    SecuritySeverity.MEDIUM: 2,
    SecuritySeverity.HIGH: 3,
    SecuritySeverity.CRITICAL: 4,
}
_LEGACY_CONFIDENCE_ORDER = {
    LegacyConfidence.LOW: 0,
    LegacyConfidence.MEDIUM: 1,
    LegacyConfidence.HIGH: 2,
}
_LEGACY_RELIABILITY = {
    LegacyConfidence.LOW: 0.50,
    LegacyConfidence.MEDIUM: 0.70,
    LegacyConfidence.HIGH: 0.90,
}


def security_severity_rank(value: SecuritySeverity) -> int:
    return _SEVERITY_ORDER[value]


def legacy_confidence_rank(value: LegacyConfidence) -> int:
    return _LEGACY_CONFIDENCE_ORDER[value]


def security_evidence_reliability(value: LegacyConfidence) -> float:
    return _LEGACY_RELIABILITY[value]


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
        any(fragment in result for fragment in _SOURCE_FRAGMENTS)
        or any(character in result for character in _SOURCE_CHARS)
        or _SENSITIVE_ASSIGNMENT.search(result) is not None
    ):
        raise ValueError(f"{label} must contain source-free semantic text")
    return result


def _optional_text(value: object, label: str, *, maximum: int = _MAX_TEXT) -> str | None:
    return None if value is None else _text(value, label, maximum=maximum)


def _strings(
    value: object,
    label: str,
    *,
    maximum_count: int = _MAX_ITEMS,
    maximum_length: int = _MAX_TEXT,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    items = _sequence(value, label)
    if len(items) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    normalized = tuple(
        _text(item, f"{label} entry", maximum=maximum_length)
        for item in items
    )
    if preserve_order:
        return tuple(dict.fromkeys(normalized))
    return tuple(sorted(set(normalized)))


def _producer_limitations(value: object) -> tuple[str, ...]:
    """Retain only Atlas-owned limitation forms across the source-free boundary."""

    normalized = _strings(
        value,
        "producer limitations",
        maximum_count=64,
        maximum_length=512,
    )
    accepted = [
        item
        for item in normalized
        if any(pattern.fullmatch(item) for pattern in _PRODUCER_LIMITATION_PATTERNS)
    ]
    omitted = len(normalized) - len(accepted)
    if omitted:
        accepted.append(
            f"{omitted} unstructured producer limitation(s) were omitted at "
            "the source-free boundary."
        )
    return tuple(sorted(set(accepted)))


def _strict_int(value: object, label: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _strict_bool(value: object, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _unit(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{label} must be finite and between zero and one")
    return result


def _relative_path(value: object, label: str = "security location path") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_TEXT
        or any(character in normalized for character in "\r\n\x00")
    ):
        raise ValueError(f"{label} must be a bounded single line")
    normalized = normalized.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path == PurePosixPath(".")
        or path.is_absolute()
        or ".." in path.parts
        or re.match(r"^[A-Za-z]:", normalized) is not None
        or contains_absolute_path(normalized)
    ):
        raise ValueError(f"{label} must be workspace-relative")
    return path.as_posix()


def _enum_tuple(value: object, enum_type: type[Enum], label: str) -> tuple[Enum, ...]:
    items = _sequence(value, label)
    try:
        result = tuple(
            item if isinstance(item, enum_type) else enum_type(str(item))
            for item in items
        )
    except ValueError as exc:
        raise ValueError(f"{label} contains an unsupported value") from exc
    return tuple(sorted(set(result), key=lambda item: item.value))


def _validate_confidence_result(result: ConfidenceResult) -> None:
    for field in (
        "score", "support", "coverage", "agreement",
        "contradiction_penalty", "ambiguity_penalty",
    ):
        value = getattr(result, field)
        if type(value) is not float:
            raise TypeError(f"confidence {field} must use canonical floating point")
        _unit(value, f"confidence {field}")
    model_version = _strict_int(
        result.model_version, "confidence model version"
    )
    missing_roles = _strings(
        result.missing_roles,
        "confidence missing roles",
        maximum_count=64,
        maximum_length=128,
    )
    if missing_roles != result.missing_roles:
        raise ValueError("security confidence missing roles are inconsistent")
    if model_version != ConfidenceCalculator.MODEL_VERSION:
        raise ValueError("unsupported security confidence model")
    expected_score = round(max(
        0.0,
        min(
            1.0,
            result.support * result.coverage * result.agreement
            - result.contradiction_penalty
            - result.ambiguity_penalty,
        ),
    ), 4)
    if not math.isclose(
        result.score, expected_score, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("security confidence arithmetic is inconsistent")


def _confidence_from_dict(value: Mapping[str, object]) -> ConfidenceResult:
    _reject_unknown(value, {
        "score", "tier", "support", "coverage", "agreement",
        "contradiction_penalty", "ambiguity_penalty", "missing_roles",
        "model_version",
    }, "security confidence")
    result = ConfidenceResult(
        _unit(value.get("score", 0.0), "confidence score"),
        ConfidenceTier(_text(value.get("tier", "insufficient"), "confidence tier")),
        _unit(value.get("support", 0.0), "confidence support"),
        _unit(value.get("coverage", 0.0), "confidence coverage"),
        _unit(value.get("agreement", 1.0), "confidence agreement"),
        _unit(value.get("contradiction_penalty", 0.0), "confidence contradiction penalty"),
        _unit(value.get("ambiguity_penalty", 0.0), "confidence ambiguity penalty"),
        _strings(value.get("missing_roles"), "confidence missing roles"),
        _strict_int(value.get("model_version"), "confidence model version", default=1),
    )
    _validate_confidence_result(result)
    return result


_SECURITY_FINDING_REF = re.compile(r"^security-finding:[0-9a-f]{64}$")
_SECURITY_NODE_REF = re.compile(r"^semantic_graph\.node_ref:[0-9a-f]{64}$")
_SECURITY_CAPABILITY_REF = re.compile(
    r"^security-capability-input:[0-9a-f]{64}$"
)
_SECURITY_EVIDENCE_LIMITATIONS = frozenset({
    "No unique canonical subject matched the exact project, language, and relative path.",
    "The exact project, language, and relative path matched multiple canonical subjects.",
})


def _validate_security_evidence_record(record: EvidenceRecord) -> None:
    """Accept only the bounded evidence shapes emitted by the PR138 service."""

    _text(record.subject_id, "security evidence subject", maximum=1_024)
    producer = _text(record.producer, "security evidence producer", maximum=256)
    _text(record.snapshot_id, "security evidence lineage", maximum=1_024)
    language = _text(record.language, "security evidence language", maximum=128)
    if _PORTABLE_IDENTIFIER.fullmatch(producer) is None:
        raise ValueError("security evidence producer must be a portable identifier")
    if _PORTABLE_LANGUAGE.fullmatch(language) is None:
        raise ValueError("security evidence language must be a normalized identifier")
    if type(record.reliability) is not float or type(record.specificity) is not float:
        raise TypeError("security evidence quality must use canonical floating point")
    _unit(record.reliability, "security evidence reliability")
    _unit(record.specificity, "security evidence specificity")
    if any(character.isspace() for character in record.subject_id):
        raise ValueError("security evidence subject must be a portable identity")
    detail = dict(record.detail)
    if record.kind is EvidenceKind.ANALYSIS_RESULT:
        if (
            len(record.source_refs) == 1
            and _SECURITY_CAPABILITY_REF.fullmatch(record.source_refs[0])
            is not None
        ):
            if (
                record.producer != SECURITY_INTELLIGENCE_PRODUCER
                or record.scope not in {item.value for item in SecurityScope}
                or record.language != "unknown"
                or set(detail) != {
                    "evidence_role", "category", "state", "coverage",
                    "source_files", "finding_count", "project_ids_ref",
                    "languages_ref", "producer_versions_ref",
                    "limitations_ref", "report_limitations_ref", "request_ref",
                    "input_fingerprint", "graph_digest",
                }
                or detail.get("evidence_role") != "capability"
                or detail.get("category") not in {
                    item.value for item in SecurityCategory
                }
                or detail.get("state") not in {
                    item.value for item in SecurityCapabilityState
                }
                or not (
                    detail.get("coverage") == "unknown"
                    or re.fullmatch(
                        r"(?:0(?:\.[0-9]{4})?|1(?:\.0{4})?)",
                        detail.get("coverage", ""),
                    ) is not None
                )
                or any(
                    re.fullmatch(r"(?:0|[1-9][0-9]{0,11})", detail.get(key, ""))
                    is None
                    for key in ("source_files", "finding_count")
                )
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", detail.get(key, "")) is None
                    for key in (
                        "project_ids_ref", "languages_ref",
                        "producer_versions_ref", "limitations_ref",
                        "report_limitations_ref", "request_ref",
                        "input_fingerprint",
                    )
                )
                or _DIGEST.fullmatch(detail.get("graph_digest", "")) is None
                or record.limitations
                or record.reliability != 1.0
                or record.specificity != 1.0
            ):
                raise ValueError(
                    "security capability evidence shape is incompatible"
                )
        elif (
            record.scope != "project"
            or len(record.source_refs) != 1
            or _SECURITY_FINDING_REF.fullmatch(record.source_refs[0]) is None
            or set(detail) != {
                "category", "rule_id", "project_id_ref", "location_ref",
                "trace_location_count",
                "merged_trace_ref",
                "finding_limitations_ref",
                "severity", "legacy_confidence", "coverage_observed",
                "coverage_eligible", "legacy_fingerprint", "cwe", "owasp",
            }
            or detail.get("category") not in {
                item.value for item in SecurityCategory
            }
            or re.fullmatch(
                r"[A-Za-z0-9._:/-]{1,256}", detail.get("rule_id", "")
            ) is None
            or re.fullmatch(r"[0-9a-f]{64}", detail.get("location_ref", "")) is None
            or re.fullmatch(r"[0-9a-f]{64}", detail.get("project_id_ref", "")) is None
            or re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", detail.get("trace_location_count", "")) is None
            or int(detail.get("trace_location_count", "0")) > _MAX_TRACE_LOCATIONS
            or re.fullmatch(
                r"[0-9a-f]{64}", detail.get("merged_trace_ref", "")
            ) is None
            or re.fullmatch(
                r"[0-9a-f]{64}", detail.get("finding_limitations_ref", "")
            ) is None
            or detail.get("severity") not in {
                item.value for item in SecuritySeverity
            }
            or detail.get("legacy_confidence") not in {
                item.value for item in LegacyConfidence
            }
            or _FINGERPRINT.fullmatch(
                detail.get("legacy_fingerprint", "")
            ) is None
            or len(detail.get("cwe", "")) > 128
            or _PORTABLE_IDENTIFIER.fullmatch(detail.get("cwe", "")) is None
            or len(detail.get("owasp", "")) > 256
            or _PORTABLE_IDENTIFIER.fullmatch(detail.get("owasp", "")) is None
            or re.fullmatch(
                r"[1-9][0-9]{0,5}", detail.get("coverage_observed", "")
            ) is None
            or re.fullmatch(
                r"[1-9][0-9]{0,5}", detail.get("coverage_eligible", "")
            ) is None
            or int(detail.get("coverage_observed", "0"))
            > int(detail.get("coverage_eligible", "0"))
            or not set(record.limitations).issubset(_SECURITY_EVIDENCE_LIMITATIONS)
        ):
            raise ValueError("security analysis evidence shape is incompatible")
        else:
            confidence = LegacyConfidence(detail["legacy_confidence"])
            expected_specificity = 0.8 if record.limitations else 1.0
            if (
                record.reliability != security_evidence_reliability(confidence)
                or record.specificity != expected_specificity
            ):
                raise ValueError(
                    "security analysis evidence quality is incompatible"
                )
    elif record.kind is EvidenceKind.GRAPH_NODE:
        if (
            record.scope != "project"
            or record.producer != "atlas-pr129/1"
            or len(record.source_refs) != 1
            or _SECURITY_NODE_REF.fullmatch(record.source_refs[0]) is None
            or record.source_refs[0] != (
                "semantic_graph.node_ref:"
                + stable_security_digest(record.subject_id)
            )
            or set(detail) != {
                "match", "subject_kind", "subject_name_ref",
            }
            or detail.get("match") != "exact_project_language_relative_path"
            or _PORTABLE_IDENTIFIER.fullmatch(
                detail.get("subject_kind", "")
            ) is None
            or re.fullmatch(
                r"[0-9a-f]{64}", detail.get("subject_name_ref", "")
            ) is None
            or record.limitations
            or record.reliability != 1.0
            or record.specificity != 1.0
        ):
            raise ValueError("security graph evidence shape is incompatible")
    else:
        raise ValueError("security evidence kind is incompatible")

    expected = EvidenceRecord.create(
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
    if expected != record:
        raise ValueError("security evidence identity is inconsistent")


def _evidence_index_from_dict(value: Mapping[str, object]) -> EvidenceIndex:
    _reject_unknown(value, {"schema_version", "records"}, "security evidence index")
    if set(value) != {"schema_version", "records"}:
        raise ValueError("security evidence index is incomplete")
    if type(value.get("schema_version")) is not int:
        raise TypeError("security evidence schema version must be an integer")
    if not isinstance(value.get("records"), list):
        raise TypeError("security evidence records must be a list")
    schema = _strict_int(value.get("schema_version"), "evidence schema version", default=1)
    if schema != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported security evidence index schema")
    records = []
    allowed = {
        "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
        "source_refs", "scope", "language", "detail", "limitations",
        "reliability", "specificity",
    }
    for item in _mappings(value.get("records"), "security evidence records"):
        _reject_unknown(item, allowed, "security evidence record")
        if set(item) != allowed:
            raise ValueError("security evidence record is incomplete")
        if any(
            type(item.get(key)) is not str
            for key in (
                "evidence_id", "kind", "subject_id", "producer",
                "snapshot_id", "scope", "language",
            )
        ):
            raise TypeError("security evidence text fields must be strings")
        if any(
            not isinstance(item.get(key), list)
            or any(type(entry) is not str for entry in item[key])
            for key in ("source_refs", "limitations")
        ):
            raise TypeError("security evidence sequences must contain strings")
        raw_detail = item.get("detail")
        if (
            not isinstance(raw_detail, Mapping)
            or any(
                type(key) is not str or type(entry) is not str
                for key, entry in raw_detail.items()
            )
        ):
            raise TypeError("security evidence detail must contain strings")
        if any(
            type(item.get(key)) is not float
            for key in ("reliability", "specificity")
        ):
            raise TypeError("security evidence quality values must be floats")
        record = EvidenceRecord.from_dict(item)
        if contains_absolute_path(record.to_dict()):
            raise ValueError("security evidence must be source-free")
        _validate_security_evidence_record(record)
        records.append(record)
    return EvidenceIndex(records, frozen=True)


def security_category_for_rule(rule_id: str) -> SecurityCategory:
    """Map an existing Atlas security rule to its PR138 category."""

    normalized = _text(rule_id, "security rule ID", maximum=256).upper()
    mapping = {
        "ATLAS-SECRET-001": SecurityCategory.SECRETS,
        "ATLAS-SQL-001": SecurityCategory.SQL_INJECTION,
        "ATLAS-POLICY-SQL-001": SecurityCategory.SQL_INJECTION,
        "ATLAS-JPA-QUERY-001": SecurityCategory.SQL_INJECTION,
        "ATLAS-JPA-001": SecurityCategory.SQL_INJECTION,
        "ATLAS-CRYPTO-001": SecurityCategory.WEAK_CRYPTOGRAPHY,
        "ATLAS-PATH-001": SecurityCategory.PATH_TRAVERSAL,
        "ATLAS-POLICY-PATH-001": SecurityCategory.PATH_TRAVERSAL,
        "ATLAS-SSRF-001": SecurityCategory.SSRF,
        "ATLAS-DESER-001": SecurityCategory.UNSAFE_DESERIALIZATION,
        "ATLAS-JACKSON-TYPE-001": SecurityCategory.UNSAFE_DESERIALIZATION,
        "ATLAS-JACKSON-001": SecurityCategory.UNSAFE_DESERIALIZATION,
        "ATLAS-GSON-DESER-001": SecurityCategory.UNSAFE_DESERIALIZATION,
        "ATLAS-REFLECT-001": SecurityCategory.UNSAFE_REFLECTION,
    }
    return mapping.get(normalized, SecurityCategory.GENERAL_TAINT)


def _legacy_fingerprint_ref(value: object) -> str:
    """Retain correlation without persisting producer-controlled literals."""

    if not isinstance(value, str) or not value or any(
        character in value for character in "\r\n\x00"
    ):
        raise ValueError("legacy security fingerprint is malformed")
    return "legacy-fingerprint:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, order=True, slots=True)
class SecurityLocation:
    path: str
    line: int
    column: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path))
        line = _strict_int(self.line, "security location line")
        column = _strict_int(self.column, "security location column")
        if line < 1 or column < 1:
            raise ValueError("security location line and column must be positive")
        object.__setattr__(self, "line", line)
        object.__setattr__(self, "column", column)

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "column": self.column}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityLocation:
        _reject_unknown(value, {"path", "line", "column"}, "security location")
        return cls(
            _relative_path(value.get("path", "")),
            _strict_int(value.get("line"), "security location line"),
            _strict_int(value.get("column"), "security location column", default=1),
        )


@dataclass(frozen=True, slots=True)
class SecurityProducerFinding:
    category: SecurityCategory
    rule_id: str
    legacy_fingerprint: str
    severity: SecuritySeverity
    legacy_confidence: LegacyConfidence
    cwe: str
    owasp: str
    location: SecurityLocation
    trace_locations: tuple[SecurityLocation, ...] = ()

    def __post_init__(self) -> None:
        category = self.category if isinstance(self.category, SecurityCategory) else SecurityCategory(self.category)
        severity = self.severity if isinstance(self.severity, SecuritySeverity) else SecuritySeverity(self.severity)
        confidence = self.legacy_confidence if isinstance(self.legacy_confidence, LegacyConfidence) else LegacyConfidence(self.legacy_confidence)
        rule_id = _text(self.rule_id, "producer rule ID", maximum=256)
        if _PORTABLE_IDENTIFIER.fullmatch(rule_id) is None:
            raise ValueError("producer rule ID must be a portable identifier")
        fingerprint = _text(
            self.legacy_fingerprint,
            "legacy security fingerprint reference",
            maximum=83,
        )
        if _FINGERPRINT.fullmatch(fingerprint) is None:
            raise ValueError("legacy security fingerprint is malformed")
        cwe = _text(self.cwe, "security CWE", maximum=128)
        owasp = _text(self.owasp, "security OWASP category", maximum=256)
        if (
            _PORTABLE_IDENTIFIER.fullmatch(cwe) is None
            or _PORTABLE_IDENTIFIER.fullmatch(owasp) is None
        ):
            raise ValueError("security classifications must be portable identifiers")
        if not isinstance(self.location, SecurityLocation):
            raise TypeError("producer finding location must be a SecurityLocation")
        trace = tuple(self.trace_locations)
        if len(trace) > _MAX_TRACE_LOCATIONS or any(not isinstance(item, SecurityLocation) for item in trace):
            raise ValueError("producer finding trace locations are invalid or too numerous")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "legacy_confidence", confidence)
        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "legacy_fingerprint", fingerprint)
        object.__setattr__(self, "cwe", cwe)
        object.__setattr__(self, "owasp", owasp)
        object.__setattr__(self, "trace_locations", trace)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("producer findings must be source-free and portable")

    @property
    def fingerprint(self) -> str:
        return self.legacy_fingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "rule_id": self.rule_id,
            "legacy_fingerprint": self.legacy_fingerprint,
            "severity": self.severity.value,
            "legacy_confidence": self.legacy_confidence.value,
            "cwe": self.cwe,
            "owasp": self.owasp,
            "location": self.location.to_dict(),
            "trace_locations": [item.to_dict() for item in self.trace_locations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityProducerFinding:
        _reject_unknown(value, {
            "category", "rule_id", "legacy_fingerprint", "severity",
            "legacy_confidence", "cwe", "owasp", "location", "trace_locations",
        }, "security producer finding")
        raw_location = value.get("location")
        if not isinstance(raw_location, Mapping):
            raise TypeError("producer finding location must be an object")
        return cls(
            SecurityCategory(_text(value.get("category", ""), "producer category")),
            _text(value.get("rule_id", ""), "producer rule ID", maximum=256),
            _text(
                value.get("legacy_fingerprint", ""),
                "legacy fingerprint reference",
                maximum=83,
            ),
            SecuritySeverity(_text(value.get("severity", ""), "producer severity")),
            LegacyConfidence(_text(value.get("legacy_confidence", ""), "producer confidence")),
            _text(value.get("cwe", ""), "producer CWE", maximum=128),
            _text(value.get("owasp", ""), "producer OWASP", maximum=256),
            SecurityLocation.from_dict(raw_location),
            tuple(SecurityLocation.from_dict(item) for item in _mappings(value.get("trace_locations"), "producer trace locations")),
        )


def _producer_finding_sort_key(item: SecurityProducerFinding) -> tuple[object, ...]:
    return (
        -_SEVERITY_ORDER[item.severity], item.category.value,
        item.location.path, item.location.line,
        item.location.column, item.rule_id, item.legacy_fingerprint,
        -legacy_confidence_rank(item.legacy_confidence),
        item.cwe, item.owasp,
        tuple((location.path, location.line, location.column)
              for location in item.trace_locations),
    )


class _DescendingFindingKey:
    """Heap key whose root is the greatest retained deterministic finding."""

    __slots__ = ("value",)

    def __init__(self, value: tuple[object, ...]) -> None:
        self.value = value

    def __lt__(self, other: _DescendingFindingKey) -> bool:
        return self.value > other.value


def _project_legacy_finding(finding: object) -> SecurityProducerFinding:
    if isinstance(finding, SecurityProducerFinding):
        return finding
    try:
        location = getattr(finding, "location")
        severity = getattr(finding, "severity")
        confidence = getattr(finding, "confidence")
        trace = getattr(finding, "trace", ())
        rule_id = str(getattr(finding, "rule_id"))
        trace_items = tuple(islice(trace, _MAX_TRACE_LOCATIONS + 1))
        if len(trace_items) > _MAX_TRACE_LOCATIONS:
            raise ValueError("legacy security finding trace is too large")
        trace_locations = tuple(
            SecurityLocation(step.location.path, step.location.line, step.location.column)
            for step in trace_items
            if getattr(step, "location", None) is not None
        )
        return SecurityProducerFinding(
            security_category_for_rule(rule_id),
            rule_id,
            _legacy_fingerprint_ref(getattr(finding, "fingerprint")),
            SecuritySeverity(getattr(severity, "value", severity)),
            LegacyConfidence(getattr(confidence, "value", confidence)),
            str(getattr(finding, "cwe")),
            str(getattr(finding, "owasp")),
            SecurityLocation(location.path, location.line, location.column),
            trace_locations,
        )
    except AttributeError as exc:
        raise TypeError("legacy security finding has an incompatible shape") from exc


def _bounded_producer_findings(
    findings: Iterable[object],
) -> tuple[tuple[SecurityProducerFinding, ...], int]:
    heap: list[tuple[_DescendingFindingKey, int, SecurityProducerFinding]] = []
    count = 0
    for raw in findings:
        if count >= _MAX_PRODUCER_INPUT_FINDINGS:
            raise ValueError(
                "security producer input exceeds the deterministic work bound "
                f"of {_MAX_PRODUCER_INPUT_FINDINGS} findings"
            )
        finding = _project_legacy_finding(raw)
        key = _producer_finding_sort_key(finding)
        entry = (_DescendingFindingKey(key), count, finding)
        if len(heap) < _MAX_ITEMS:
            heapq.heappush(heap, entry)
        elif key < heap[0][0].value:
            heapq.heapreplace(heap, entry)
        count += 1
    selected = tuple(sorted(
        (entry[2] for entry in heap),
        key=_producer_finding_sort_key,
    ))
    return selected, max(0, count - len(selected))


@dataclass(frozen=True, slots=True)
class SecurityProducerReport:
    project_id: str
    language: str
    analyzed_categories: tuple[SecurityCategory, ...]
    findings: tuple[SecurityProducerFinding, ...]
    source_files: int
    warning_count: int
    producer_version: str
    limitations: tuple[str, ...] = ()
    schema_version: int = SECURITY_INTELLIGENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if _strict_int(self.schema_version, "producer schema version") != SECURITY_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("unsupported security producer schema")
        project_id = _text(self.project_id, "producer project ID", maximum=1_024)
        language = _text(self.language, "producer language", maximum=128).casefold()
        producer_version = _text(self.producer_version, "security producer version", maximum=256)
        if _PORTABLE_LANGUAGE.fullmatch(language) is None:
            raise ValueError("producer language must be a normalized identifier")
        if _PORTABLE_IDENTIFIER.fullmatch(producer_version) is None:
            raise ValueError("security producer version must be a portable identifier")
        categories = _enum_tuple(self.analyzed_categories, SecurityCategory, "analyzed security categories")
        findings = tuple(self.findings)
        if len(findings) > _MAX_ITEMS or any(not isinstance(item, SecurityProducerFinding) for item in findings):
            raise ValueError("security producer findings are invalid or too numerous")
        findings = tuple(sorted(findings, key=_producer_finding_sort_key))
        if any(item.category not in categories for item in findings):
            raise ValueError("producer findings must belong to an analyzed category")
        source_files = _strict_int(self.source_files, "producer source file count")
        warning_count = _strict_int(self.warning_count, "producer warning count")
        if source_files < 0 or warning_count < 0:
            raise ValueError("producer counts must be non-negative")
        limitations = _producer_limitations(self.limitations)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "producer_version", producer_version)
        object.__setattr__(self, "analyzed_categories", categories)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "source_files", source_files)
        object.__setattr__(self, "warning_count", warning_count)
        object.__setattr__(self, "limitations", limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("security producer reports must be source-free")

    @classmethod
    def from_legacy(
        cls,
        findings: Iterable[object],
        *,
        project_id: str,
        language: str = "java",
        analyzed_categories: Iterable[SecurityCategory] | None = None,
        source_files: int = 0,
        warning_count: int = 0,
        producer_version: str = "atlas-security-analysis/legacy",
        limitations: Iterable[str] = (),
    ) -> SecurityProducerReport:
        """Create the loss-minimized, source-free boundary from legacy findings.

        Legacy message, title, properties, expression values and trace prose are
        intentionally never copied. Absolute source paths are rejected instead of
        being silently rewritten because a workspace-relative identity cannot be
        proven at this boundary.
        """

        selected_categories = tuple(analyzed_categories) if analyzed_categories is not None else tuple(
            category for category in SecurityCategory if category is not SecurityCategory.XSS
        )
        ordered_projected, omitted = _bounded_producer_findings(findings)
        normalized_limitations = tuple(limitations)
        if omitted:
            normalized_limitations = (*normalized_limitations, (
                f"Security producer emitted {len(ordered_projected) + omitted} findings; "
                f"retained the deterministic first {_MAX_ITEMS} and omitted {omitted}."
            ))
            warning_count += 1
        return cls(
            project_id,
            language,
            selected_categories,
            ordered_projected,
            source_files,
            warning_count,
            producer_version,
            normalized_limitations,
        )

    @classmethod
    def from_findings(
        cls,
        findings: Iterable[object],
        *,
        project_id: str,
        language: str = "java",
        analyzed_categories: Iterable[SecurityCategory] | None = None,
        source_files: int = 0,
        warning_count: int = 0,
        producer_version: str = "atlas-java-security/1",
        limitations: Iterable[str] = (),
    ) -> SecurityProducerReport:
        """Compatibility spelling used by normal analyzer integration."""

        return cls.from_legacy(
            findings,
            project_id=project_id,
            language=language,
            analyzed_categories=analyzed_categories,
            source_files=source_files,
            warning_count=warning_count,
            producer_version=producer_version,
            limitations=limitations,
        )

    @staticmethod
    def normalize_findings(
        findings: Iterable[object],
    ) -> tuple[tuple[SecurityProducerFinding, ...], int]:
        """Project and retain the deterministic bounded producer subset."""

        return _bounded_producer_findings(findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "language": self.language,
            "analyzed_categories": [item.value for item in self.analyzed_categories],
            "findings": [item.to_dict() for item in self.findings],
            "source_files": self.source_files,
            "warning_count": self.warning_count,
            "producer_version": self.producer_version,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityProducerReport:
        _reject_unknown(value, {
            "schema_version", "project_id", "language", "analyzed_categories",
            "findings", "source_files", "warning_count", "producer_version",
            "limitations",
        }, "security producer report")
        raw_limitations = _strings(
            value.get("limitations"),
            "producer limitations",
            maximum_count=64,
            maximum_length=512,
        )
        if _producer_limitations(raw_limitations) != raw_limitations:
            raise ValueError("security producer limitations are incompatible")
        return cls(
            _text(value.get("project_id", ""), "producer project ID"),
            _text(value.get("language", ""), "producer language"),
            _enum_tuple(value.get("analyzed_categories"), SecurityCategory, "analyzed categories"),
            tuple(SecurityProducerFinding.from_dict(item) for item in _mappings(value.get("findings"), "producer findings")),
            _strict_int(value.get("source_files"), "producer source file count"),
            _strict_int(value.get("warning_count"), "producer warning count"),
            _text(value.get("producer_version", ""), "producer version"),
            raw_limitations,
            _strict_int(value.get("schema_version"), "producer schema version", default=1),
        )


@dataclass(frozen=True, slots=True)
class SecurityIntelligenceRequest:
    scope: SecurityScope = SecurityScope.REPOSITORY
    projects: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    categories: tuple[SecurityCategory, ...] = ()
    severities: tuple[SecuritySeverity, ...] = ()
    limit: int = 100
    canonical_subject_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        scope = self.scope if isinstance(self.scope, SecurityScope) else SecurityScope(self.scope)
        projects = _strings(self.projects, "security request projects", maximum_count=256)
        languages = tuple(sorted({
            item.casefold()
            for item in _strings(
                self.languages,
                "security request languages",
                maximum_count=64,
            )
        }))
        if any(_PORTABLE_LANGUAGE.fullmatch(item) is None for item in languages):
            raise ValueError("security request languages must be portable identifiers")
        categories = _enum_tuple(self.categories, SecurityCategory, "security request categories")
        severities = _enum_tuple(self.severities, SecuritySeverity, "security request severities")
        canonical_subject_ids = _strings(
            self.canonical_subject_ids,
            "security request canonical subject IDs",
            maximum_count=256,
        )
        limit = _strict_int(self.limit, "security request limit")
        if limit < 1 or limit > _MAX_REQUEST_LIMIT:
            raise ValueError(f"security request limit must be between 1 and {_MAX_REQUEST_LIMIT}")
        if scope is SecurityScope.PROJECT and len(projects) != 1:
            raise ValueError("project-scoped security requests require exactly one project")
        if scope is SecurityScope.SYMBOL and not canonical_subject_ids:
            raise ValueError("symbol-scoped security requests require canonical subject IDs")
        if scope is not SecurityScope.SYMBOL and canonical_subject_ids:
            raise ValueError("canonical subject IDs require symbol scope")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "projects", projects)
        object.__setattr__(self, "languages", languages)
        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "severities", severities)
        object.__setattr__(self, "limit", limit)
        object.__setattr__(self, "canonical_subject_ids", canonical_subject_ids)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("security requests must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "projects": list(self.projects),
            "languages": list(self.languages),
            "categories": [item.value for item in self.categories],
            "severities": [item.value for item in self.severities],
            "limit": self.limit,
            "canonical_subject_ids": list(self.canonical_subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityIntelligenceRequest:
        _reject_unknown(value, {"scope", "projects", "languages", "categories", "severities", "limit", "canonical_subject_ids"}, "security request")
        return cls(
            SecurityScope(_text(value.get("scope", "repository"), "security request scope")),
            _strings(value.get("projects"), "security request projects"),
            _strings(value.get("languages"), "security request languages"),
            _enum_tuple(value.get("categories"), SecurityCategory, "security request categories"),
            _enum_tuple(value.get("severities"), SecuritySeverity, "security request severities"),
            _strict_int(value.get("limit"), "security request limit", default=100),
            _strings(value.get("canonical_subject_ids"), "security request canonical subject IDs"),
        )


@dataclass(frozen=True, order=True, slots=True)
class SecurityPriorityComponent:
    name: str
    available: bool
    value: float | None
    weight: float
    contribution: float
    evidence_ids: tuple[str, ...] = ()
    limitation: str | None = None

    def __post_init__(self) -> None:
        name = _text(self.name, "security priority component", maximum=128)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("security priority component names must be portable identifiers")
        if not isinstance(self.available, bool):
            raise TypeError("security priority availability must be boolean")
        weight = _unit(self.weight, "security priority weight")
        contribution = _unit(self.contribution, "security priority contribution")
        value = None if self.value is None else _unit(self.value, "security priority value")
        evidence_ids = _strings(self.evidence_ids, "security priority evidence")
        if any(_EVIDENCE_ID.fullmatch(item) is None for item in evidence_ids):
            raise ValueError("security priority contains an invalid evidence ID")
        limitation = _optional_text(self.limitation, "security priority limitation")
        if self.available:
            if value is None or weight <= 0.0:
                raise ValueError("available security priority components require value and weight")
            if not math.isclose(contribution, round(value * weight, 4), rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("security priority contribution is inconsistent")
        elif value is not None or contribution != 0.0 or evidence_ids:
            raise ValueError("unavailable security priority components cannot contribute")
        elif limitation is None:
            raise ValueError("unavailable security priority components require a limitation")
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
    def from_dict(cls, value: Mapping[str, object]) -> SecurityPriorityComponent:
        _reject_unknown(value, {"name", "available", "value", "weight", "contribution", "evidence_ids", "limitation"}, "security priority component")
        return cls(
            _text(value.get("name", ""), "priority component name", maximum=128),
            _strict_bool(value.get("available"), "priority component availability"),
            None if value.get("value") is None else _unit(value.get("value"), "priority component value"),
            _unit(value.get("weight", 0.0), "priority component weight"),
            _unit(value.get("contribution", 0.0), "priority component contribution"),
            _strings(value.get("evidence_ids"), "priority component evidence"),
            _optional_text(value.get("limitation"), "priority component limitation"),
        )


@dataclass(frozen=True, slots=True)
class SecurityPriority:
    score: float
    tier: SecurityPriorityTier
    coverage: float
    components: tuple[SecurityPriorityComponent, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        score = _unit(self.score, "security priority score")
        coverage = _unit(self.coverage, "security priority coverage")
        tier = self.tier if isinstance(self.tier, SecurityPriorityTier) else SecurityPriorityTier(self.tier)
        components = tuple(self.components)
        if not components or any(not isinstance(item, SecurityPriorityComponent) for item in components):
            raise ValueError("security priority requires valid components")
        components = tuple(sorted(components))
        if len({item.name for item in components}) != len(components):
            raise ValueError("security priority component names must be unique")
        available = tuple(item for item in components if item.available)
        total_weight = sum(item.weight for item in available)
        all_weight = sum(item.weight for item in components)
        expected_score = round(sum(item.contribution for item in available) / total_weight, 4) if total_weight else 0.0
        expected_coverage = round(total_weight / all_weight, 4) if all_weight else 0.0
        if not math.isclose(score, expected_score, rel_tol=0.0, abs_tol=1e-12) or not math.isclose(coverage, expected_coverage, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("security priority score or coverage is inconsistent")
        expected_tier = priority_tier(score)
        if tier is not expected_tier:
            raise ValueError("security priority tier is inconsistent")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "tier", tier)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "limitations", _strings(self.limitations, "security priority limitations", maximum_count=64))

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score, "tier": self.tier.value, "coverage": self.coverage,
            "components": [item.to_dict() for item in self.components],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityPriority:
        _reject_unknown(value, {"score", "tier", "coverage", "components", "limitations"}, "security priority")
        return cls(
            _unit(value.get("score", 0.0), "security priority score"),
            SecurityPriorityTier(_text(value.get("tier", "informational"), "security priority tier")),
            _unit(value.get("coverage", 0.0), "security priority coverage"),
            tuple(SecurityPriorityComponent.from_dict(item) for item in _mappings(value.get("components"), "security priority components")),
            _strings(value.get("limitations"), "security priority limitations", maximum_count=64),
        )


def priority_tier(score: float) -> SecurityPriorityTier:
    if score >= 0.85:
        return SecurityPriorityTier.CRITICAL
    if score >= 0.65:
        return SecurityPriorityTier.HIGH
    if score >= 0.45:
        return SecurityPriorityTier.MEDIUM
    if score >= 0.2:
        return SecurityPriorityTier.LOW
    return SecurityPriorityTier.INFORMATIONAL


_PRIORITY_SEVERITY_VALUE = {
    SecuritySeverity.INFO: 0.10,
    SecuritySeverity.LOW: 0.30,
    SecuritySeverity.MEDIUM: 0.60,
    SecuritySeverity.HIGH: 0.80,
    SecuritySeverity.CRITICAL: 1.00,
}
_PRIORITY_TRACE_LIMITATION = (
    "No structured trace locations were supplied by the producer."
)
_PRIORITY_CANONICAL_LIMITATION = (
    "No unique canonical graph subject was resolved for this finding."
)
_PRIORITY_EXPOSURE_LIMITATION = (
    "Runtime exposure evidence is unavailable; priority does not infer exploitability."
)
_PRIORITY_IMPACT_LIMITATION = (
    "PR136 impact analysis was not supplied; priority does not include blast radius."
)


def security_priority_for_finding(
    severity: SecuritySeverity,
    producer_evidence_ids: Iterable[str],
    trace_locations: Sequence[object],
    canonical_evidence_id: str | None,
) -> SecurityPriority:
    """Build the fixed schema-v1 review-priority projection."""

    producer_ids = tuple(sorted(set(producer_evidence_ids)))
    severity_value = _PRIORITY_SEVERITY_VALUE[severity]
    components = [SecurityPriorityComponent(
        "severity", True, severity_value, 0.50,
        round(severity_value * 0.50, 4), producer_ids,
    )]
    if trace_locations:
        trace_value = 1.0 if len(trace_locations) >= 2 else 0.65
        components.append(SecurityPriorityComponent(
            "trace_completeness", True, trace_value, 0.15,
            round(trace_value * 0.15, 4), producer_ids,
        ))
    else:
        components.append(SecurityPriorityComponent(
            "trace_completeness", False, None, 0.15, 0.0,
            limitation=_PRIORITY_TRACE_LIMITATION,
        ))
    if canonical_evidence_id is not None:
        components.append(SecurityPriorityComponent(
            "canonical_scope", True, 1.0, 0.15, 0.15,
            (canonical_evidence_id,),
        ))
    else:
        components.append(SecurityPriorityComponent(
            "canonical_scope", False, None, 0.15, 0.0,
            limitation=_PRIORITY_CANONICAL_LIMITATION,
        ))
    components.extend((
        SecurityPriorityComponent(
            "runtime_exposure", False, None, 0.10, 0.0,
            limitation=_PRIORITY_EXPOSURE_LIMITATION,
        ),
        SecurityPriorityComponent(
            "impact_radius", False, None, 0.10, 0.0,
            limitation=_PRIORITY_IMPACT_LIMITATION,
        ),
    ))
    available = tuple(item for item in components if item.available)
    total_weight = sum(item.weight for item in available)
    all_weight = sum(item.weight for item in components)
    score = round(
        sum(item.contribution for item in available) / total_weight,
        4,
    )
    coverage = round(total_weight / all_weight, 4)
    limitations = tuple(
        item.limitation for item in components if item.limitation is not None
    )
    return SecurityPriority(
        score,
        priority_tier(score),
        coverage,
        tuple(components),
        limitations,
    )


@dataclass(frozen=True, order=True, slots=True)
class SecurityCapability:
    category: SecurityCategory
    state: SecurityCapabilityState
    languages: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()
    source_files: int = 0
    finding_count: int = 0
    coverage: float | None = None
    producer_versions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        category = self.category if isinstance(self.category, SecurityCategory) else SecurityCategory(self.category)
        state = self.state if isinstance(self.state, SecurityCapabilityState) else SecurityCapabilityState(self.state)
        source_files = _strict_int(self.source_files, "security capability source files")
        finding_count = _strict_int(self.finding_count, "security capability finding count")
        if source_files < 0 or finding_count < 0:
            raise ValueError("security capability counts must be non-negative")
        coverage = None if self.coverage is None else _unit(self.coverage, "security capability coverage")
        limitations = _strings(self.limitations, "security capability limitations", maximum_count=128)
        languages = tuple(sorted({
            item.casefold()
            for item in _strings(
                self.languages,
                "security capability languages",
                maximum_count=64,
            )
        }))
        projects = _strings(
            self.project_ids,
            "security capability projects",
            maximum_count=_MAX_PROJECTS,
        )
        producers = _strings(
            self.producer_versions,
            "security capability producers",
            maximum_count=64,
        )
        if state in {SecurityCapabilityState.NOT_ANALYZED, SecurityCapabilityState.INCOMPATIBLE} and coverage is not None:
            raise ValueError("unavailable security capabilities cannot claim coverage")
        if state in {SecurityCapabilityState.NOT_ANALYZED, SecurityCapabilityState.INCOMPATIBLE} and (
            source_files or finding_count or languages or projects or producers
        ):
            raise ValueError("unavailable security capabilities cannot claim analysis results")
        if state is SecurityCapabilityState.ANALYZED and (
            coverage != 1.0 or limitations
        ):
            raise ValueError("analyzed security capabilities require complete coverage")
        if state is not SecurityCapabilityState.ANALYZED and not limitations:
            raise ValueError("non-analyzed security capability states require a limitation")
        if any(_PORTABLE_LANGUAGE.fullmatch(item) is None for item in languages):
            raise ValueError("security capability languages must be portable identifiers")
        if any(_PORTABLE_IDENTIFIER.fullmatch(item) is None for item in producers):
            raise ValueError("security capability producers must be portable identifiers")
        evidence_ids = _strings(
            self.evidence_ids,
            "security capability evidence IDs",
            maximum_count=64,
        )
        if any(_EVIDENCE_ID.fullmatch(item) is None for item in evidence_ids):
            raise ValueError("security capability evidence IDs are malformed")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "languages", languages)
        object.__setattr__(self, "project_ids", projects)
        object.__setattr__(self, "source_files", source_files)
        object.__setattr__(self, "finding_count", finding_count)
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "producer_versions", producers)
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value, "state": self.state.value,
            "languages": list(self.languages), "project_ids": list(self.project_ids),
            "source_files": self.source_files, "finding_count": self.finding_count,
            "coverage": self.coverage, "producer_versions": list(self.producer_versions),
            "limitations": list(self.limitations),
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityCapability:
        _reject_unknown(value, {"category", "state", "languages", "project_ids", "source_files", "finding_count", "coverage", "producer_versions", "limitations", "evidence_ids"}, "security capability")
        return cls(
            SecurityCategory(_text(value.get("category", ""), "security capability category")),
            SecurityCapabilityState(_text(value.get("state", ""), "security capability state")),
            _strings(value.get("languages"), "security capability languages"),
            _strings(
                value.get("project_ids"),
                "security capability projects",
                maximum_count=_MAX_PROJECTS,
            ),
            _strict_int(value.get("source_files"), "security capability source files"),
            _strict_int(value.get("finding_count"), "security capability finding count"),
            None if value.get("coverage") is None else _unit(value.get("coverage"), "security capability coverage"),
            _strings(value.get("producer_versions"), "security capability producers"),
            _strings(value.get("limitations"), "security capability limitations", maximum_count=128),
            _strings(
                value.get("evidence_ids"),
                "security capability evidence IDs",
                maximum_count=64,
            ),
        )


def security_capability_evidence_identity(
    capability: SecurityCapability,
    request: SecurityIntelligenceRequest,
    report_limitations: tuple[str, ...] = (),
    input_fingerprint: str = "unavailable",
    graph_digest: str = "unavailable",
) -> tuple[str, dict[str, object]]:
    """Return the replayable aggregate identity for one capability conclusion."""

    coverage = (
        "unknown"
        if capability.coverage is None
        else f"{capability.coverage:.4f}"
    )
    detail: dict[str, object] = {
        "evidence_role": "capability",
        "category": capability.category.value,
        "state": capability.state.value,
        "coverage": coverage,
        "source_files": capability.source_files,
        "finding_count": capability.finding_count,
        "project_ids_ref": stable_security_digest(
            list(capability.project_ids)
        ),
        "languages_ref": stable_security_digest(list(capability.languages)),
        "producer_versions_ref": stable_security_digest(
            list(capability.producer_versions)
        ),
        "limitations_ref": stable_security_digest(
            list(capability.limitations)
        ),
        "report_limitations_ref": stable_security_digest(
            list(report_limitations)
        ),
        "request_ref": stable_security_digest(request.to_dict()),
        "input_fingerprint": input_fingerprint,
        "graph_digest": graph_digest,
    }
    subject_id = "security-capability:" + stable_security_digest({
        "category": capability.category.value,
        "request": request.to_dict(),
    })
    return subject_id, detail


@dataclass(frozen=True, slots=True)
class SecurityIntelligenceFinding:
    finding_id: str
    category: SecurityCategory
    rule_id: str
    legacy_fingerprints: tuple[str, ...]
    severity: SecuritySeverity
    legacy_confidence: LegacyConfidence
    cwe: tuple[str, ...]
    owasp: tuple[str, ...]
    project_id: str
    language: str
    location: SecurityLocation
    trace_locations: tuple[SecurityLocation, ...]
    canonical_subject_id: str | None
    canonical_subject_kind: str | None
    canonical_subject_name: str | None
    producer_versions: tuple[str, ...]
    confidence: ConfidenceResult
    priority: SecurityPriority
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        finding_id = _text(self.finding_id, "security intelligence finding ID", maximum=128)
        if _FINDING_ID.fullmatch(finding_id) is None:
            raise ValueError("security intelligence finding ID is malformed")
        category = self.category if isinstance(self.category, SecurityCategory) else SecurityCategory(self.category)
        severity = self.severity if isinstance(self.severity, SecuritySeverity) else SecuritySeverity(self.severity)
        legacy_confidence = self.legacy_confidence if isinstance(self.legacy_confidence, LegacyConfidence) else LegacyConfidence(self.legacy_confidence)
        if not isinstance(self.location, SecurityLocation):
            raise TypeError("security intelligence location must be a SecurityLocation")
        trace = tuple(self.trace_locations)
        if len(trace) > _MAX_TRACE_LOCATIONS or any(not isinstance(item, SecurityLocation) for item in trace):
            raise ValueError("security intelligence trace locations are invalid")
        evidence_ids = _strings(self.evidence_ids, "security intelligence evidence")
        if not evidence_ids or any(_EVIDENCE_ID.fullmatch(item) is None for item in evidence_ids):
            raise ValueError("security intelligence findings require valid evidence IDs")
        if not isinstance(self.confidence, ConfidenceResult):
            raise TypeError("security intelligence confidence must use ConfidenceResult")
        _validate_confidence_result(self.confidence)
        if not isinstance(self.priority, SecurityPriority):
            raise TypeError("security intelligence priority must use SecurityPriority")
        subject_values = (self.canonical_subject_id, self.canonical_subject_kind, self.canonical_subject_name)
        if any(value is None for value in subject_values) and any(value is not None for value in subject_values):
            raise ValueError("canonical security subject fields must be all present or all absent")
        object.__setattr__(self, "finding_id", finding_id)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "legacy_confidence", legacy_confidence)
        rule_id = _text(
            self.rule_id, "security intelligence rule", maximum=256
        )
        if _PORTABLE_IDENTIFIER.fullmatch(rule_id) is None:
            raise ValueError(
                "security intelligence rule must be a portable identifier"
            )
        legacy_fingerprints = _strings(
            self.legacy_fingerprints, "legacy security fingerprints"
        )
        if any(_FINGERPRINT.fullmatch(item) is None for item in legacy_fingerprints):
            raise ValueError("legacy security fingerprint references are malformed")
        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "legacy_fingerprints", legacy_fingerprints)
        cwe = _strings(self.cwe, "security intelligence CWE", maximum_count=64)
        owasp = _strings(self.owasp, "security intelligence OWASP", maximum_count=64)
        if any(
            _PORTABLE_IDENTIFIER.fullmatch(item) is None
            for item in (*cwe, *owasp)
        ):
            raise ValueError("security classifications must be portable identifiers")
        object.__setattr__(self, "cwe", cwe)
        object.__setattr__(self, "owasp", owasp)
        object.__setattr__(self, "project_id", _text(self.project_id, "security intelligence project", maximum=1_024))
        language = _text(
            self.language, "security intelligence language", maximum=128
        ).casefold()
        if _PORTABLE_LANGUAGE.fullmatch(language) is None:
            raise ValueError("security intelligence language must be portable")
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "trace_locations", trace)
        object.__setattr__(self, "canonical_subject_id", _optional_text(self.canonical_subject_id, "canonical security subject ID", maximum=1_024))
        object.__setattr__(self, "canonical_subject_kind", _optional_text(self.canonical_subject_kind, "canonical security subject kind", maximum=128))
        object.__setattr__(self, "canonical_subject_name", _optional_text(self.canonical_subject_name, "canonical security subject name", maximum=1_024))
        producers = _strings(
            self.producer_versions,
            "security intelligence producers",
            maximum_count=64,
        )
        if not producers or any(
            _PORTABLE_IDENTIFIER.fullmatch(item) is None for item in producers
        ):
            raise ValueError("security intelligence producers must be portable")
        object.__setattr__(self, "producer_versions", producers)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "limitations", _strings(self.limitations, "security intelligence limitations", maximum_count=128))
        if contains_absolute_path(self.to_dict()):
            raise ValueError("security intelligence findings must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id, "category": self.category.value,
            "rule_id": self.rule_id, "legacy_fingerprints": list(self.legacy_fingerprints),
            "severity": self.severity.value, "legacy_confidence": self.legacy_confidence.value,
            "cwe": list(self.cwe), "owasp": list(self.owasp),
            "project_id": self.project_id, "language": self.language,
            "location": self.location.to_dict(),
            "trace_locations": [item.to_dict() for item in self.trace_locations],
            "canonical_subject_id": self.canonical_subject_id,
            "canonical_subject_kind": self.canonical_subject_kind,
            "canonical_subject_name": self.canonical_subject_name,
            "producer_versions": list(self.producer_versions),
            "confidence": self.confidence.to_dict(), "priority": self.priority.to_dict(),
            "evidence_ids": list(self.evidence_ids), "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityIntelligenceFinding:
        _reject_unknown(value, {
            "finding_id", "category", "rule_id", "legacy_fingerprints", "severity",
            "legacy_confidence", "cwe", "owasp", "project_id", "language",
            "location", "trace_locations", "canonical_subject_id",
            "canonical_subject_kind", "canonical_subject_name", "producer_versions",
            "confidence", "priority", "evidence_ids", "limitations",
        }, "security intelligence finding")
        raw_location = value.get("location")
        raw_confidence = value.get("confidence")
        raw_priority = value.get("priority")
        if not isinstance(raw_location, Mapping) or not isinstance(raw_confidence, Mapping) or not isinstance(raw_priority, Mapping):
            raise TypeError("security intelligence finding nested values must be objects")
        return cls(
            _text(value.get("finding_id", ""), "security intelligence finding ID"),
            SecurityCategory(_text(value.get("category", ""), "security category")),
            _text(value.get("rule_id", ""), "security rule ID"),
            _strings(value.get("legacy_fingerprints"), "legacy fingerprints"),
            SecuritySeverity(_text(value.get("severity", ""), "security severity")),
            LegacyConfidence(_text(value.get("legacy_confidence", ""), "legacy confidence")),
            _strings(value.get("cwe"), "security CWE"),
            _strings(value.get("owasp"), "security OWASP"),
            _text(value.get("project_id", ""), "security project"),
            _text(value.get("language", ""), "security language"),
            SecurityLocation.from_dict(raw_location),
            tuple(SecurityLocation.from_dict(item) for item in _mappings(value.get("trace_locations"), "security trace locations")),
            _optional_text(value.get("canonical_subject_id"), "canonical subject ID"),
            _optional_text(value.get("canonical_subject_kind"), "canonical subject kind"),
            _optional_text(value.get("canonical_subject_name"), "canonical subject name"),
            _strings(value.get("producer_versions"), "security producers"),
            _confidence_from_dict(raw_confidence), SecurityPriority.from_dict(raw_priority),
            _strings(value.get("evidence_ids"), "security evidence"),
            _strings(value.get("limitations"), "security limitations"),
        )


def security_finding_sort_key(item: SecurityIntelligenceFinding) -> tuple[object, ...]:
    return (
        -_SEVERITY_ORDER[item.severity],
        -item.priority.score,
        item.category.value,
        item.project_id.casefold(), item.project_id,
        item.location.path.casefold(), item.location.path,
        item.location.line, item.location.column,
        item.rule_id, item.finding_id,
    )


def stable_security_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()


def security_intelligence_finding_id(
    *,
    project_id: str,
    language: str,
    category: SecurityCategory,
    rule_id: str,
    location: SecurityLocation,
    producer_versions: Iterable[str],
    snapshot_id: str,
    canonical_subject_id: str | None,
    evidence_ids: Iterable[str],
) -> str:
    """Return the canonical, lineage-bound identity for one merged finding."""

    return "security-intelligence:" + stable_security_digest({
        "project_id": project_id,
        "language": language,
        "category": category.value,
        "rule_id": rule_id,
        "path": location.path,
        "line": location.line,
        "column": location.column,
        "producer_versions": sorted(set(producer_versions)),
        "snapshot_id": snapshot_id,
        "canonical_subject_id": canonical_subject_id,
        "evidence_ids": sorted(set(evidence_ids)),
    })


@dataclass(frozen=True, slots=True)
class SecurityIntelligenceReport:
    request: SecurityIntelligenceRequest
    findings: tuple[SecurityIntelligenceFinding, ...]
    capabilities: tuple[SecurityCapability, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    snapshot_id: str
    total_finding_count: int
    omitted_count: int = 0
    truncated: bool = False
    limitations: tuple[str, ...] = ()
    producer: str = SECURITY_INTELLIGENCE_PRODUCER
    schema_version: int = SECURITY_INTELLIGENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, SecurityIntelligenceRequest):
            raise TypeError("security report request is invalid")
        limitations = _strings(
            self.limitations,
            "security report limitations",
            maximum_count=256,
        )
        findings = tuple(self.findings)
        if len(findings) > _MAX_REQUEST_LIMIT or any(not isinstance(item, SecurityIntelligenceFinding) for item in findings):
            raise ValueError("security report findings are invalid or too numerous")
        findings = tuple(sorted(findings, key=security_finding_sort_key))
        if len(findings) > self.request.limit:
            raise ValueError("security report exceeds its request limit")
        if any(
            (self.request.projects and item.project_id not in self.request.projects)
            or (self.request.languages and item.language not in self.request.languages)
            or (self.request.categories and item.category not in self.request.categories)
            or (self.request.severities and item.severity not in self.request.severities)
            or (
                self.request.scope is SecurityScope.SYMBOL
                and item.canonical_subject_id
                not in self.request.canonical_subject_ids
            )
            for item in findings
        ):
            raise ValueError("security report findings do not satisfy the request")
        if len({item.finding_id for item in findings}) != len(findings):
            raise ValueError("security report finding IDs must be unique")
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, SecurityCapability) for item in capabilities):
            raise TypeError("security report capabilities are invalid")
        capabilities = tuple(sorted(
            capabilities,
            key=lambda item: item.category.value,
        ))
        if len({item.category for item in capabilities}) != len(capabilities):
            raise ValueError("security report capability categories must be unique")
        expected_categories = set(self.request.categories or tuple(SecurityCategory))
        if {item.category for item in capabilities} != expected_categories:
            raise ValueError(
                "security report capabilities must cover every requested category"
            )
        included_by_category = {
            category: sum(1 for item in findings if item.category is category)
            for category in expected_categories
        }
        if any(
            item.finding_count < included_by_category[item.category]
            for item in capabilities
        ):
            raise ValueError("security capability finding counts are inconsistent")
        capabilities_by_category = {
            item.category: item for item in capabilities
        }
        if any(
            finding.project_id not in capabilities_by_category[
                finding.category
            ].project_ids
            or finding.language not in capabilities_by_category[
                finding.category
            ].languages
            or not set(finding.producer_versions).issubset(
                capabilities_by_category[finding.category].producer_versions
            )
            for finding in findings
        ):
            raise ValueError(
                "security capability scope or producer lineage is inconsistent"
            )
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("security report evidence index is invalid")
        evidence_index = self.evidence_index.freeze()
        for record in evidence_index.records:
            if contains_absolute_path(record.to_dict()):
                raise ValueError("security evidence must be source-free")
            _validate_security_evidence_record(record)
        referenced = {evidence_id for item in findings for evidence_id in item.evidence_ids}
        referenced.update(
            evidence_id
            for capability in capabilities
            for evidence_id in capability.evidence_ids
        )
        referenced.update(
            evidence_id
            for item in findings
            for component in item.priority.components
            for evidence_id in component.evidence_ids
        )
        if any(evidence_index.get(evidence_id) is None for evidence_id in referenced):
            raise ValueError("security report references missing evidence")
        evidence_ids = {record.evidence_id for record in evidence_index.records}
        if evidence_ids != referenced:
            raise ValueError("security report evidence index must be exactly closed")
        if any(
            evidence_id not in item.evidence_ids
            for item in findings
            for component in item.priority.components
            for evidence_id in component.evidence_ids
        ):
            raise ValueError("security priority evidence must belong to its finding")
        total = _strict_int(self.total_finding_count, "security report total count")
        omitted = _strict_int(self.omitted_count, "security report omitted count")
        if total < 0 or omitted < 0 or total != len(findings) + omitted:
            raise ValueError("security report counts are inconsistent")
        if sum(item.finding_count for item in capabilities) != total:
            raise ValueError("security capability totals are inconsistent")
        if not isinstance(self.truncated, bool) or self.truncated != (omitted > 0):
            raise ValueError("security report truncation is inconsistent")
        fingerprint = _text(self.input_fingerprint, "security report fingerprint", maximum=64)
        graph_digest = _text(self.graph_digest, "security graph digest", maximum=64)
        if _DIGEST.fullmatch(fingerprint) is None or _DIGEST.fullmatch(graph_digest) is None:
            raise ValueError("security report digest is malformed")
        snapshot_id = _text(self.snapshot_id, "security snapshot ID", maximum=1_024)
        if any(
            record.snapshot_id != snapshot_id
            for record in evidence_index.records
        ):
            raise ValueError("security evidence lineage is inconsistent")
        for capability in capabilities:
            if len(capability.evidence_ids) != 1:
                raise ValueError(
                    "security capabilities require one aggregate evidence record"
                )
            capability_record = evidence_index.get(capability.evidence_ids[0])
            if capability_record is None:
                raise ValueError("security capability evidence is unavailable")
            expected_subject, expected_detail = (
                security_capability_evidence_identity(
                    capability,
                    self.request,
                    limitations,
                    self.input_fingerprint,
                    self.graph_digest,
                )
            )
            normalized_detail = {
                str(key): str(value) for key, value in expected_detail.items()
            }
            if (
                capability_record.kind is not EvidenceKind.ANALYSIS_RESULT
                or capability_record.subject_id != expected_subject
                or capability_record.producer != SECURITY_INTELLIGENCE_PRODUCER
                or capability_record.snapshot_id != snapshot_id
                or capability_record.scope != self.request.scope.value
                or capability_record.language != "unknown"
                or dict(capability_record.detail) != normalized_detail
                or len(capability_record.source_refs) != 1
                or _SECURITY_CAPABILITY_REF.fullmatch(
                    capability_record.source_refs[0]
                ) is None
                or capability_record.limitations
                or capability_record.reliability != 1.0
                or capability_record.specificity != 1.0
            ):
                raise ValueError(
                    "security capability evidence is inconsistent"
                )
        for finding in findings:
            analysis_records = tuple(
                record
                for evidence_id in finding.evidence_ids
                if (
                    (record := evidence_index.get(evidence_id)) is not None
                    and record.kind is EvidenceKind.ANALYSIS_RESULT
                )
            )
            graph_records = tuple(
                record
                for evidence_id in finding.evidence_ids
                if (
                    (record := evidence_index.get(evidence_id)) is not None
                    and record.kind is EvidenceKind.GRAPH_NODE
                )
            )
            expected_subject = (
                finding.canonical_subject_id
                if finding.canonical_subject_id is not None
                else f"project:{stable_security_digest(finding.project_id)}"
            )
            expected_location = stable_security_digest(finding.location.to_dict())
            expected_trace = stable_security_digest(
                [location.to_dict() for location in finding.trace_locations]
            )
            expected_limitations = stable_security_digest(
                list(finding.limitations)
            )
            if not analysis_records or any(
                record.subject_id != expected_subject
                or record.language.casefold() != finding.language
                or record.producer not in finding.producer_versions
                or dict(record.detail).get("category") != finding.category.value
                or dict(record.detail).get("rule_id") != finding.rule_id
                or dict(record.detail).get("project_id_ref")
                != stable_security_digest(finding.project_id)
                or dict(record.detail).get("location_ref") != expected_location
                or int(dict(record.detail).get("trace_location_count", "-1"))
                != len(finding.trace_locations)
                or dict(record.detail).get("merged_trace_ref") != expected_trace
                or dict(record.detail).get("finding_limitations_ref")
                != expected_limitations
                for record in analysis_records
            ):
                raise ValueError("security finding evidence is inconsistent")
            if {
                record.producer for record in analysis_records
            } != set(finding.producer_versions):
                raise ValueError("security finding producer lineage is inconsistent")
            if finding.canonical_subject_id is None:
                if graph_records:
                    raise ValueError("unresolved security findings cannot claim graph evidence")
            elif (
                len(graph_records) != 1
                or graph_records[0].subject_id != finding.canonical_subject_id
                or graph_records[0].language.casefold() != finding.language
                or dict(graph_records[0].detail).get("subject_kind")
                != finding.canonical_subject_kind
                or dict(graph_records[0].detail).get("subject_name_ref")
                != stable_security_digest(finding.canonical_subject_name)
            ):
                raise ValueError("canonical security finding evidence is inconsistent")
            details = tuple(dict(record.detail) for record in analysis_records)
            severities = tuple(
                SecuritySeverity(detail["severity"]) for detail in details
            )
            legacy_confidences = tuple(
                LegacyConfidence(detail["legacy_confidence"])
                for detail in details
            )
            if finding.severity is not max(
                severities, key=security_severity_rank
            ) or finding.legacy_confidence is not max(
                legacy_confidences, key=legacy_confidence_rank
            ):
                raise ValueError("security finding producer values are inconsistent")
            expected_cwe = tuple(sorted({detail["cwe"] for detail in details}))
            expected_owasp = tuple(sorted({detail["owasp"] for detail in details}))
            expected_fingerprints = tuple(sorted({
                detail["legacy_fingerprint"] for detail in details
            }))
            if (
                finding.cwe != expected_cwe
                or finding.owasp != expected_owasp
                or finding.legacy_fingerprints != expected_fingerprints
            ):
                raise ValueError(
                    "security finding taxonomy evidence is inconsistent"
                )
            coverage_pairs = {
                (
                    int(detail["coverage_observed"]),
                    int(detail["coverage_eligible"]),
                )
                for detail in details
            }
            if len(coverage_pairs) != 1:
                raise ValueError("security finding coverage evidence is inconsistent")
            coverage_observed, coverage_eligible = next(iter(coverage_pairs))
            severity_agreement = max(
                severities.count(value) for value in set(severities)
            ) / len(severities)
            analysis_ids = tuple(
                record.evidence_id for record in analysis_records
            )
            canonical_id = (
                graph_records[0].evidence_id if graph_records else None
            )
            expected_confidence = ConfidenceCalculator().calculate(
                (
                    EvidenceRole("producer_finding", analysis_ids, True),
                    EvidenceRole(
                        "canonical_subject",
                        (canonical_id,) if canonical_id is not None else (),
                        False,
                    ),
                ),
                evidence_index,
                coverage=round(coverage_observed / coverage_eligible, 4),
                agreement=round(severity_agreement, 4),
            )
            if finding.confidence != expected_confidence:
                raise ValueError("security finding confidence evidence is inconsistent")
            expected_priority = security_priority_for_finding(
                finding.severity,
                analysis_ids,
                finding.trace_locations,
                canonical_id,
            )
            if finding.priority != expected_priority:
                raise ValueError("security finding priority evidence is inconsistent")
            expected_finding_id = security_intelligence_finding_id(
                project_id=finding.project_id,
                language=finding.language,
                category=finding.category,
                rule_id=finding.rule_id,
                location=finding.location,
                producer_versions=finding.producer_versions,
                snapshot_id=snapshot_id,
                canonical_subject_id=finding.canonical_subject_id,
                evidence_ids=finding.evidence_ids,
            )
            if finding.finding_id != expected_finding_id:
                raise ValueError("security intelligence finding identity is inconsistent")
        producer = _text(self.producer, "security report producer", maximum=256)
        if producer != SECURITY_INTELLIGENCE_PRODUCER:
            raise ValueError("unsupported security intelligence producer")
        if _strict_int(self.schema_version, "security report schema version") != SECURITY_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("unsupported security intelligence schema")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "evidence_index", evidence_index)
        object.__setattr__(self, "total_finding_count", total)
        object.__setattr__(self, "omitted_count", omitted)
        object.__setattr__(self, "input_fingerprint", fingerprint)
        object.__setattr__(self, "graph_digest", graph_digest)
        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "producer", producer)
        object.__setattr__(self, "limitations", limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("security intelligence reports must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "producer": self.producer,
            "request": self.request.to_dict(),
            "findings": [item.to_dict() for item in self.findings],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest, "snapshot_id": self.snapshot_id,
            "total_finding_count": self.total_finding_count,
            "included_finding_count": len(self.findings),
            "omitted_count": self.omitted_count, "truncated": self.truncated,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def to_ai_context(self, *, maximum_findings: int = 12) -> dict[str, object]:
        maximum = _strict_int(maximum_findings, "AI security finding limit")
        if maximum < 0 or maximum > 100:
            raise ValueError("AI security finding limit must be between zero and 100")
        selected = self.findings[:maximum]
        states = {item.state for item in self.capabilities}
        status = (
            "unavailable"
            if not states.intersection({SecurityCapabilityState.ANALYZED, SecurityCapabilityState.PARTIAL})
            else "partial"
            if states.intersection({SecurityCapabilityState.PARTIAL, SecurityCapabilityState.NOT_ANALYZED, SecurityCapabilityState.INCOMPATIBLE})
            else "available"
        )
        payload = {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "status": status,
            "finding_count": self.total_finding_count,
            "included_finding_count": len(selected),
            "omitted_finding_count": self.total_finding_count - len(selected),
            "capabilities": [
                {
                    "category": item.category.value,
                    "state": item.state.value,
                    "finding_count": item.finding_count,
                    "coverage": item.coverage,
                    "evidence_count": len(item.evidence_ids),
                    "limitations": list(item.limitations[:3]),
                }
                for item in self.capabilities
            ],
            "findings": [
                _ai_finding(item)
                for item in selected
            ],
            "limitations": list(self.limitations[:12]),
        }
        if contains_absolute_path(payload):
            raise ValueError("AI security context must be source-free")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SecurityIntelligenceReport:
        _reject_unknown(value, {
            "schema_version", "producer", "request", "findings", "capabilities",
            "evidence_index", "input_fingerprint", "graph_digest", "snapshot_id",
            "total_finding_count", "included_finding_count", "omitted_count",
            "truncated", "limitations",
        }, "security intelligence report")
        raw_request = value.get("request")
        raw_evidence = value.get("evidence_index")
        if not isinstance(raw_request, Mapping) or not isinstance(raw_evidence, Mapping):
            raise TypeError("security report request and evidence index must be objects")
        findings = tuple(SecurityIntelligenceFinding.from_dict(item) for item in _mappings(value.get("findings"), "security report findings"))
        included = _strict_int(value.get("included_finding_count"), "security report included count", default=len(findings))
        if included != len(findings):
            raise ValueError("security report included count is inconsistent")
        return cls(
            SecurityIntelligenceRequest.from_dict(raw_request), findings,
            tuple(SecurityCapability.from_dict(item) for item in _mappings(value.get("capabilities"), "security report capabilities")),
            _evidence_index_from_dict(raw_evidence),
            _text(value.get("input_fingerprint", ""), "security input fingerprint"),
            _text(value.get("graph_digest", "unavailable"), "security graph digest"),
            _text(value.get("snapshot_id", ""), "security snapshot ID"),
            _strict_int(value.get("total_finding_count"), "security total finding count"),
            _strict_int(value.get("omitted_count"), "security omitted count"),
            _strict_bool(value.get("truncated"), "security truncation"),
            _strings(value.get("limitations"), "security report limitations", maximum_count=256),
            _text(value.get("producer", SECURITY_INTELLIGENCE_PRODUCER), "security producer"),
            _strict_int(value.get("schema_version"), "security schema version", default=1),
        )


_KNOWLEDGE_RULE_ALIASES = {
    "ATLAS-POLICY-SQL-001": "ATLAS-SQL-001",
    "ATLAS-JPA-QUERY-001": "ATLAS-JPA-001",
    "ATLAS-POLICY-PATH-001": "ATLAS-PATH-001",
    "ATLAS-JACKSON-TYPE-001": "ATLAS-JACKSON-001",
    "ATLAS-GSON-DESER-001": "ATLAS-DESER-001",
}


def _ai_finding(item: SecurityIntelligenceFinding) -> dict[str, object]:
    """Build one bounded projection using approved knowledge, never examples."""

    from moughorai.security_knowledge import SecurityKnowledgeBase

    rule_id = _KNOWLEDGE_RULE_ALIASES.get(item.rule_id, item.rule_id)
    knowledge = SecurityKnowledgeBase().get(rule_id)
    payload: dict[str, object] = {
        "finding_id": item.finding_id,
        "category": item.category.value,
        "rule_id": item.rule_id,
        "severity": item.severity.value,
        "confidence": item.confidence.to_dict(),
        "priority": {
            "score": item.priority.score,
            "tier": item.priority.tier.value,
            "coverage": item.priority.coverage,
        },
        "cwe": list(item.cwe),
        "owasp": list(item.owasp),
        "project_id": item.project_id,
        "location": item.location.to_dict(),
        "canonical_subject_id": item.canonical_subject_id,
        "participating_location_count": 1 + len(item.trace_locations),
        "evidence_count": len(item.evidence_ids),
        "limitations": list(item.limitations[:4]),
    }
    if knowledge is not None:
        payload["remediation"] = {
            "summary": knowledge.remediation.summary,
            "steps": list(knowledge.remediation.steps[:5]),
            "knowledge_rule_id": knowledge.rule_id,
        }
    return payload


__all__ = [
    "LegacyConfidence", "SECURITY_INTELLIGENCE_PRODUCER",
    "SECURITY_INTELLIGENCE_SCHEMA_VERSION", "SECURITY_INTELLIGENCE_SNAPSHOT_KEY",
    "SecurityCapability", "SecurityCapabilityState", "SecurityCategory",
    "SecurityIntelligenceFinding", "SecurityIntelligenceReport",
    "SecurityIntelligenceRequest", "SecurityLocation", "SecurityPriority",
    "SecurityPriorityComponent", "SecurityPriorityTier", "SecurityProducerFinding",
    "SecurityProducerReport", "SecurityScope", "SecuritySeverity", "priority_tier",
    "security_category_for_rule", "security_finding_sort_key",
    "security_intelligence_finding_id", "stable_security_digest",
]
