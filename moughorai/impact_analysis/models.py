from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re

from moughorai.dependency_graph import DependencyKind
from moughorai.global_symbols import GlobalSymbol, SymbolId
from moughorai.knowledge_graph import KnowledgeKind, KnowledgeRelation
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
    SubjectMatchBasis,
    SubjectCandidate,
    SubjectQuery,
    SubjectResolution,
)


# PR26 compatibility contracts. Field order and defaults are intentionally unchanged.
@dataclass(frozen=True)
class ImpactPath:
    symbols: tuple[SymbolId, ...]
    kinds: tuple[DependencyKind, ...]


@dataclass(frozen=True)
class ImpactedSymbol:
    symbol: GlobalSymbol
    distance: int
    path: ImpactPath


@dataclass(frozen=True)
class ImpactAnalysisReport:
    roots: tuple[GlobalSymbol, ...]
    impacted: tuple[ImpactedSymbol, ...]
    files: tuple[Path, ...]
    unresolved_ids: tuple[SymbolId, ...] = ()


IMPACT_PREDICTION_SCHEMA_VERSION = 1
IMPACT_PREDICTION_PRODUCER = "atlas-pr136/1"

_MAX_QUERY_ITEMS = 128
_MAX_RELATIONS = len(KnowledgeRelation)
_MAX_PATH_DEPTH = 64
_MAX_RESULT_LIMIT = 1_000
_MAX_TEXT = 4_096
_MAX_EXPLANATION = 1_024
_MAX_LIMITATIONS = 128
_MAX_ATTRIBUTES = 64
_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_PORTABLE_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMANTIC_IDENTIFIER = re.compile(
    r"^[A-Za-z0-9_$.:#<>?,()\[\]\-+*=&|!~^%@]+$"
)
_SEMANTIC_ATTRIBUTE_VALUE = re.compile(
    r"^[A-Za-z0-9_$.:#<>?,()\[\]/\-+*=&|!~^%@]+$"
)
_SAFE_EVIDENCE_REFERENCE = re.compile(
    r"^(?:semantic_graph\.edge_ref:[0-9a-f]{64}|"
    r"(?:evidence|report-item|repository-report):[0-9a-f]{64}|"
    r"global_symbol\.metadata:visibility)$"
)
_FINGERPRINT = re.compile(r"^impact-prediction:[0-9a-f]{64}$")
_PROHIBITED_SEMANTIC_FRAGMENTS = ("//", "/*", "*/", "://")
_PROHIBITED_SEMANTIC_CHARACTERS = frozenset("{};\"'`")
_PROHIBITED_SOURCE_FRAGMENTS = ("//", "/*", "*/", "```", " = ", "==", "=>")
_PROHIBITED_SOURCE_CHARACTERS = frozenset("{}`")
_QUOTED_LITERAL = re.compile(r"\"[^\"]*\"|'[^']{2,}'")
_SOURCE_DECLARATION = re.compile(
    r"\b(?:public|private|protected)\s+"
    r"(?:(?:static|final|abstract)\s+)*"
    r"(?:class|interface|enum|record|void|boolean|byte|short|int|long|"
    r"float|double|char|String|[A-Z][A-Za-z0-9_$<>?,.\[\]]*)\s+"
    r"[A-Za-z_$][A-Za-z0-9_$]*"
)
_SOURCE_FUNCTION = re.compile(
    r"\b(?:def|function)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*\("
)

EXTERNAL_CONSUMER_LIMITATION = (
    "No affected in-repository consumer was proven. "
    "External consumers may still exist."
)
EXTERNAL_SCOPE_LIMITATION = (
    "Only repository-local consumers were evaluated; "
    "external consumers may still exist."
)


class ImpactChangeKind(str, Enum):
    IMPLEMENTATION = "implementation"
    SIGNATURE = "signature"
    VISIBILITY = "visibility"
    REMOVAL = "removal"
    RENAME = "rename"
    MOVE = "move"
    DEPENDENCY = "dependency"
    INHERITANCE = "inheritance"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ImpactCategory(str, Enum):
    CALLER = "caller"
    CALLEE = "callee"
    IMPORTER = "importer"
    IMPORTED_DEPENDENCY = "imported_dependency"
    SUBTYPE = "subtype"
    SUPERTYPE = "supertype"
    OVERRIDING_MEMBER = "overriding_member"
    OVERRIDDEN_MEMBER = "overridden_member"
    IMPLEMENTING_TYPE = "implementing_type"
    IMPLEMENTED_INTERFACE = "implemented_interface"
    PROJECT_DEPENDENT = "project_dependent"
    MODULE_DEPENDENT = "module_dependent"
    PACKAGE_DEPENDENT = "package_dependent"
    OWNING_PROJECT = "owning_project"
    OWNING_MODULE = "owning_module"
    OWNING_PACKAGE = "owning_package"
    PUBLIC_API = "public_api"
    TEST = "test"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"
    GENERATED_ARTIFACT = "generated_artifact"
    UNKNOWN = "unknown"


class ImpactCapabilityState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED = "unsupported"


class BreakingChangeState(str, Enum):
    PROVEN_BREAKING = "proven_breaking"
    POTENTIALLY_BREAKING = "potentially_breaking"
    # Readable aliases retained within the new PR136 API. Serialization always
    # uses the explicit canonical values above.
    PROVEN = "proven_breaking"
    POTENTIAL = "potentially_breaking"
    NOT_EVALUATED = "not_evaluated"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


class ImpactStrength(str, Enum):
    PROVEN_DIRECT = "proven_direct"
    EVIDENCE_BACKED_TRANSITIVE = "evidence_backed_transitive"
    PROBABLE_INCOMPLETE = "probable_incomplete"
    STRUCTURAL_CONTEXT = "structural_context"
    INSUFFICIENT = "insufficient"


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise TypeError(f"{label} must be an array")
    return tuple(value)


def _mapping_items(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    values = _sequence(value, label)
    if any(not isinstance(item, Mapping) for item in values):
        raise TypeError(f"{label} entries must be objects")
    return tuple(item for item in values if isinstance(item, Mapping))


def _safe_text(
    value: object,
    label: str,
    *,
    maximum: int = _MAX_TEXT,
    empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    text = value.strip()
    if not text and not empty:
        raise ValueError(f"{label} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{label} is too long")
    if "\x00" in text or "\r" in text or "\n" in text:
        raise ValueError(f"{label} must be one line")
    if contains_absolute_path(text):
        raise ValueError(f"{label} must not contain an absolute path")
    return text


def _semantic_text(
    value: object,
    label: str,
    *,
    maximum: int = 512,
) -> str:
    """Validate bounded, source-free semantic identity text.

    Semantic identifiers may contain ordinary spaces and language-signature
    punctuation, but never source blocks, string literals, comments, URLs, or
    control characters.  This deliberately rejects source-shaped queries at the
    PR136 response boundary rather than echoing them into source-free output.
    """

    text = _safe_text(value, label, maximum=maximum)
    if any(character.isspace() and character != " " for character in text):
        raise ValueError(f"{label} must use ordinary spaces only")
    if any(character in _PROHIBITED_SEMANTIC_CHARACTERS for character in text):
        raise ValueError(f"{label} must contain semantic identity text, not source")
    if any(fragment in text for fragment in _PROHIBITED_SEMANTIC_FRAGMENTS):
        raise ValueError(f"{label} must contain semantic identity text, not source")
    return text


def _contains_source_shaped_text(value: object) -> bool:
    """Detect source-shaped payloads without rejecting ordinary engineering prose."""

    if isinstance(value, str):
        return bool(
            any(character in _PROHIBITED_SOURCE_CHARACTERS for character in value)
            or any(fragment in value for fragment in _PROHIBITED_SOURCE_FRAGMENTS)
            or _QUOTED_LITERAL.search(value)
            or _SOURCE_DECLARATION.search(value)
            or _SOURCE_FUNCTION.search(value)
        )
    if isinstance(value, Mapping):
        return any(_contains_source_shaped_text(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_source_shaped_text(item) for item in value)
    return False


def _coerce_enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{label} contains an unsupported value") from exc


def _strings(
    value: object,
    label: str,
    *,
    maximum_count: int = _MAX_QUERY_ITEMS,
    maximum_length: int = _MAX_TEXT,
) -> tuple[str, ...]:
    values = _sequence(value, label)
    if len(values) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    normalized = tuple(
        sorted({
            _safe_text(item, f"{label} entry", maximum=maximum_length)
            for item in values
        })
    )
    return normalized


def _optional_semantic_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _semantic_text(value, label)


def _strict_boolean(value: object, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _strict_integer(value: object, label: str, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _strict_number(value: object, label: str, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _unit_interval(value: object, label: str) -> float:
    result = _strict_number(value, label, default=0.0)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def _evidence_ids(value: object, label: str) -> tuple[str, ...]:
    result = _strings(value, label, maximum_count=256)
    if any(_EVIDENCE_ID.fullmatch(item) is None for item in result):
        raise ValueError(f"{label} contains an invalid evidence ID")
    return result


def _evidence_source_refs(value: object, label: str) -> tuple[str, ...]:
    references = _strings(value, label, maximum_count=256, maximum_length=256)
    if any(_SAFE_EVIDENCE_REFERENCE.fullmatch(item) is None for item in references):
        raise ValueError(f"{label} contains non-portable or source-shaped evidence")
    return references


def _semantic_identifiers(value: object, label: str) -> tuple[str, ...]:
    identifiers = _strings(
        value,
        label,
        maximum_count=_MAX_QUERY_ITEMS,
        maximum_length=512,
    )
    if any(
        _SEMANTIC_IDENTIFIER.fullmatch(item) is None or "=" in item
        for item in identifiers
    ):
        raise ValueError(
            f"{label} entries must be bounded semantic identifiers or signatures"
        )
    return identifiers


def _attributes(value: object, label: str) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        raw_items: tuple[object, ...] = tuple(value.items())
    else:
        raw_items = _sequence(value, label)
    if len(raw_items) > _MAX_ATTRIBUTES:
        raise ValueError(f"{label} contains too many entries")
    normalized: list[tuple[str, str]] = []
    for item in raw_items:
        if not isinstance(item, Sequence) or isinstance(
            item, (str, bytes, bytearray)
        ) or len(item) != 2:
            raise TypeError(f"{label} entries must be key/value pairs")
        key = _safe_text(item[0], f"{label} key", maximum=128)
        if _PORTABLE_NAME.fullmatch(key) is None:
            raise ValueError(f"{label} keys must be portable identifiers")
        attribute_value = _safe_text(
            item[1],
            f"{label} value",
            maximum=512,
        )
        if (
            "://" in attribute_value
            or _SEMANTIC_ATTRIBUTE_VALUE.fullmatch(attribute_value) is None
        ):
            raise ValueError(f"{label} values must be source-free semantic metadata")
        normalized.append((key, attribute_value))
    if len({key for key, _ in normalized}) != len(normalized):
        raise ValueError(f"{label} keys must be unique")
    return tuple(sorted(normalized))


def _enum_values(value: object, enum_type: type[Enum], label: str) -> tuple[Enum, ...]:
    values = _sequence(value, label)
    if len(values) > _MAX_RELATIONS:
        raise ValueError(f"{label} contains too many entries")
    normalized = {
        _coerce_enum(item, enum_type, f"{label} entry")
        for item in values
    }
    return tuple(sorted(normalized, key=lambda item: str(item.value)))


def _reject_unknown(
    value: Mapping[str, object], allowed: frozenset[str], label: str
) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(sorted(unknown))}")


def _strict_optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or null")
    return value


def _validate_subject_query(
    query: SubjectQuery, label: str = "impact subject query"
) -> SubjectQuery:
    if not isinstance(query, SubjectQuery):
        raise TypeError(f"{label} must be a SubjectQuery")
    _semantic_text(query.identifier, f"{label} identifier")
    if query.kind is not None and not isinstance(query.kind, KnowledgeKind):
        raise TypeError(f"{label} kind must be a KnowledgeKind")
    for name in ("project", "language"):
        value = getattr(query, name)
        if value is not None:
            _semantic_text(value, f"{label} {name}", maximum=256)
    if query.path is not None:
        _safe_text(query.path, f"{label} path", maximum=1_024)
    return query


def _subject_query_from_dict(
    value: Mapping[str, object], label: str = "impact subject query"
) -> SubjectQuery:
    _reject_unknown(
        value,
        frozenset({"identifier", "kind", "project", "language", "path"}),
        label,
    )
    identifier = value.get("identifier")
    if not isinstance(identifier, str):
        raise TypeError(f"{label} identifier must be a string")
    raw_kind = value.get("kind")
    kind = (
        _coerce_enum(raw_kind, KnowledgeKind, f"{label} kind")
        if raw_kind is not None
        else None
    )
    return _validate_subject_query(SubjectQuery(
        identifier,
        kind,  # type: ignore[arg-type]
        _strict_optional_string(value.get("project"), f"{label} project"),
        _strict_optional_string(value.get("language"), f"{label} language"),
        _strict_optional_string(value.get("path"), f"{label} path"),
    ), label)


def _subject_query_sort_key(query: SubjectQuery) -> str:
    return json.dumps(
        query.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _validate_subject_candidate(
    candidate: SubjectCandidate,
    label: str = "impact subject candidate",
) -> SubjectCandidate:
    if not isinstance(candidate, SubjectCandidate):
        raise TypeError(f"{label} must be a SubjectCandidate")
    if not isinstance(candidate.kind, KnowledgeKind):
        raise TypeError(f"{label} kind must be a KnowledgeKind")
    if not isinstance(candidate.match_basis, SubjectMatchBasis):
        raise TypeError(f"{label} match basis must be a SubjectMatchBasis")
    for name in ("canonical_id", "name", "qualified_name", "language"):
        _semantic_text(getattr(candidate, name), f"{label} {name}")
    if candidate.project is not None:
        _semantic_text(candidate.project, f"{label} project", maximum=256)
    if candidate.path is not None:
        _safe_text(candidate.path, f"{label} path", maximum=1_024)
    for scope in candidate.project_scopes:
        _semantic_text(scope, f"{label} project scope", maximum=256)
    return candidate


def _subject_candidate_from_dict(
    value: Mapping[str, object], label: str = "impact subject candidate"
) -> SubjectCandidate:
    _reject_unknown(
        value,
        frozenset({
            "canonical_id", "kind", "name", "qualified_name", "project",
            "language", "path", "project_scopes", "match_basis",
        }),
        label,
    )
    required = ("canonical_id", "kind", "name", "qualified_name")
    for name in required:
        if not isinstance(value.get(name), str):
            raise TypeError(f"{label} {name} must be a string")
    scopes = _strings(value.get("project_scopes"), f"{label} project scopes")
    return _validate_subject_candidate(SubjectCandidate(
        str(value["canonical_id"]),
        _coerce_enum(value["kind"], KnowledgeKind, f"{label} kind"),  # type: ignore[arg-type]
        str(value["name"]),
        str(value["qualified_name"]),
        _strict_optional_string(value.get("project"), f"{label} project"),
        _safe_text(value.get("language", "unknown"), f"{label} language"),
        _strict_optional_string(value.get("path"), f"{label} path"),
        scopes,
        _coerce_enum(
            value.get("match_basis", SubjectMatchBasis.NONE.value),
            SubjectMatchBasis,
            f"{label} match basis",
        ),  # type: ignore[arg-type]
        str(value["canonical_id"]),
    ), label)


def _validate_subject_resolution(
    resolution: SubjectResolution,
    label: str = "impact subject resolution",
) -> SubjectResolution:
    if not isinstance(resolution, SubjectResolution):
        raise TypeError(f"{label} must be a SubjectResolution")
    _validate_subject_query(resolution.query, f"{label} query")
    if not isinstance(resolution.status, ResolutionStatus):
        raise TypeError(f"{label} status must be a ResolutionStatus")
    if not isinstance(resolution.match_basis, SubjectMatchBasis):
        raise TypeError(f"{label} match basis must be a SubjectMatchBasis")
    if resolution.subject is not None:
        _validate_subject_candidate(resolution.subject, f"{label} subject")
    for candidate in resolution.candidates:
        _validate_subject_candidate(candidate, f"{label} candidate")
    _semantic_text(resolution.graph_digest, f"{label} graph digest", maximum=256)
    for limitation in resolution.limitations:
        _safe_text(limitation, f"{label} limitation", maximum=_MAX_EXPLANATION)
    return resolution


def _subject_resolution_from_dict(
    value: Mapping[str, object], label: str = "impact subject resolution"
) -> SubjectResolution:
    _reject_unknown(
        value,
        frozenset({
            "query", "status", "subject", "candidates",
            "total_candidate_count", "included_candidate_count",
            "omitted_candidate_count", "match_basis", "graph_digest",
            "limitations",
        }),
        label,
    )
    raw_query = value.get("query")
    raw_subject = value.get("subject")
    if not isinstance(raw_query, Mapping):
        raise TypeError(f"{label} query must be an object")
    if raw_subject is not None and not isinstance(raw_subject, Mapping):
        raise TypeError(f"{label} subject must be an object or null")
    candidates = tuple(
        _subject_candidate_from_dict(item, f"{label} candidate")
        for item in _mapping_items(value.get("candidates"), f"{label} candidates")
    )
    included = _strict_integer(
        value.get("included_candidate_count"),
        f"{label} included candidate count",
        default=len(candidates),
    )
    if included != len(candidates):
        raise ValueError(f"{label} included candidate count is inconsistent")
    resolution = SubjectResolution(
        _subject_query_from_dict(raw_query, f"{label} query"),
        _coerce_enum(
            value.get("status", ResolutionStatus.UNAVAILABLE.value),
            ResolutionStatus,
            f"{label} status",
        ),  # type: ignore[arg-type]
        _subject_candidate_from_dict(raw_subject, f"{label} subject")
        if isinstance(raw_subject, Mapping)
        else None,
        candidates,
        _strict_integer(
            value.get("total_candidate_count"),
            f"{label} total candidate count",
            default=0,
        ),
        _strict_integer(
            value.get("omitted_candidate_count"),
            f"{label} omitted candidate count",
            default=0,
        ),
        _coerce_enum(
            value.get("match_basis", SubjectMatchBasis.NONE.value),
            SubjectMatchBasis,
            f"{label} match basis",
        ),  # type: ignore[arg-type]
        _semantic_text(
            value.get("graph_digest", "unavailable"),
            f"{label} graph digest",
            maximum=256,
        ),
        _strings(
            value.get("limitations"),
            f"{label} limitations",
            maximum_count=_MAX_LIMITATIONS,
            maximum_length=_MAX_EXPLANATION,
        ),
    )
    return _validate_subject_resolution(resolution, label)


def _validate_confidence_result(
    result: ConfidenceResult, label: str = "impact confidence"
) -> ConfidenceResult:
    if not isinstance(result, ConfidenceResult):
        raise TypeError(f"{label} must be a ConfidenceResult")
    if result.model_version != ConfidenceCalculator.MODEL_VERSION:
        raise ValueError(f"{label} uses an unsupported confidence model")
    expected_score = round(max(
        0.0,
        min(
            1.0,
            result.support * result.coverage * result.agreement
            - result.contradiction_penalty
            - result.ambiguity_penalty,
        ),
    ), 4)
    # The shared calculator computes the score from full-precision components,
    # then serializes every component to four decimals.  Recomputing from those
    # serialized components can legitimately differ by a few quantization units.
    if not math.isclose(result.score, expected_score, rel_tol=0.0, abs_tol=3e-4):
        raise ValueError(f"{label} score is inconsistent with its components")
    return result


def _validated_confidence(value: Mapping[str, object]) -> ConfidenceResult:
    _reject_unknown(
        value,
        frozenset({
            "score", "tier", "support", "coverage", "agreement",
            "contradiction_penalty", "ambiguity_penalty", "missing_roles",
            "model_version",
        }),
        "impact confidence",
    )
    tier = value.get("tier", ConfidenceTier.INSUFFICIENT.value)
    if not isinstance(tier, str):
        raise TypeError("impact confidence tier must be a string")
    return _validate_confidence_result(ConfidenceResult(
        _unit_interval(value.get("score", 0.0), "impact confidence score"),
        ConfidenceTier(tier),
        _unit_interval(value.get("support", 0.0), "impact confidence support"),
        _unit_interval(value.get("coverage", 0.0), "impact confidence coverage"),
        _unit_interval(value.get("agreement", 1.0), "impact confidence agreement"),
        _unit_interval(
            value.get("contradiction_penalty", 0.0),
            "impact confidence contradiction penalty",
        ),
        _unit_interval(
            value.get("ambiguity_penalty", 0.0),
            "impact confidence ambiguity penalty",
        ),
        _strings(value.get("missing_roles"), "impact confidence missing roles"),
        _strict_integer(
            value.get("model_version"), "impact confidence model version", default=1
        ),
    ))


def _validated_evidence_index(value: Mapping[str, object]) -> EvidenceIndex:
    _reject_unknown(
        value,
        frozenset({"schema_version", "records"}),
        "impact evidence index",
    )
    schema = _strict_integer(
        value.get("schema_version"),
        "impact evidence schema version",
        default=EvidenceIndex.SCHEMA_VERSION,
    )
    if schema != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported impact evidence index schema")
    restored: list[EvidenceRecord] = []
    serialized_ids: set[str] = set()
    for item in _mapping_items(value.get("records"), "impact evidence records"):
        _reject_unknown(
            item,
            frozenset({
                "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
                "source_refs", "scope", "language", "detail", "limitations",
                "reliability", "specificity",
            }),
            "impact evidence record",
        )
        raw_detail = item.get("detail", {})
        if not isinstance(raw_detail, Mapping):
            raise TypeError("impact evidence detail must be an object")
        required = ("evidence_id", "kind", "subject_id", "producer", "snapshot_id")
        for name in required:
            if not isinstance(item.get(name), str):
                raise TypeError(f"impact evidence {name} must be a string")
        serialized_id = str(item["evidence_id"])
        if serialized_id in serialized_ids:
            raise ValueError("impact evidence index contains duplicate records")
        serialized_ids.add(serialized_id)
        record = EvidenceRecord.create(
            _coerce_enum(
                item["kind"], EvidenceKind, "impact evidence kind"
            ),  # type: ignore[arg-type]
            _semantic_text(item["subject_id"], "impact evidence subject"),
            _semantic_text(item["producer"], "impact evidence producer"),
            _semantic_text(item["snapshot_id"], "impact evidence snapshot"),
            source_refs=_evidence_source_refs(
                item.get("source_refs"),
                "impact evidence source references",
            ),
            scope=_semantic_text(
                item.get("scope", "repository"), "impact evidence scope"
            ),
            language=_semantic_text(
                item.get("language", "unknown"), "impact evidence language"
            ),
            detail=dict(_attributes(raw_detail, "impact evidence detail")),
            limitations=_strings(
                item.get("limitations"),
                "impact evidence limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
            reliability=_unit_interval(
                item.get("reliability", 1.0), "impact evidence reliability"
            ),
            specificity=_unit_interval(
                item.get("specificity", 1.0), "impact evidence specificity"
            ),
        )
        if record.evidence_id != item["evidence_id"]:
            raise ValueError("impact evidence ID is inconsistent")
        restored.append(record)
    return EvidenceIndex(restored, frozen=True)


@dataclass(frozen=True, slots=True)
class ImpactPredictionRequest:
    subject: SubjectQuery
    change_kind: ImpactChangeKind = ImpactChangeKind.UNKNOWN
    changed_members: tuple[str, ...] = ()
    changed_api_surface: tuple[str, ...] = ()
    relations: tuple[KnowledgeRelation, ...] = ()
    module: str | None = None
    package: str | None = None
    max_depth: int = 4
    limit: int = 50
    include_tests: bool = False
    include_dependencies: bool = True
    include_risk: bool = True
    include_git_context: bool = False
    include_search_enrichment: bool = False
    additional_subjects: tuple[SubjectQuery, ...] = ()

    def __post_init__(self) -> None:
        _validate_subject_query(self.subject)
        object.__setattr__(
            self,
            "change_kind",
            _coerce_enum(
                self.change_kind, ImpactChangeKind, "impact request change kind"
            ),
        )
        object.__setattr__(
            self,
            "changed_members",
            _semantic_identifiers(self.changed_members, "impact changed members"),
        )
        object.__setattr__(
            self,
            "changed_api_surface",
            _semantic_identifiers(
                self.changed_api_surface, "impact changed API surface"
            ),
        )
        object.__setattr__(
            self,
            "relations",
            _enum_values(
                self.relations, KnowledgeRelation, "impact relation filters"
            ),
        )
        object.__setattr__(
            self, "module", _optional_semantic_text(self.module, "impact module")
        )
        object.__setattr__(
            self, "package", _optional_semantic_text(self.package, "impact package")
        )
        if (
            isinstance(self.max_depth, bool)
            or not isinstance(self.max_depth, int)
            or not 1 <= self.max_depth <= _MAX_PATH_DEPTH
        ):
            raise ValueError(
                f"impact maximum depth must be between 1 and {_MAX_PATH_DEPTH}"
            )
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= _MAX_RESULT_LIMIT
        ):
            raise ValueError(
                f"impact result limit must be between 1 and {_MAX_RESULT_LIMIT}"
            )
        for name in (
            "include_tests", "include_dependencies", "include_risk",
            "include_git_context", "include_search_enrichment",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"impact request {name} must be a boolean")
        raw_additional = _sequence(
            self.additional_subjects, "impact additional subjects"
        )
        if len(raw_additional) > _MAX_QUERY_ITEMS - 1:
            raise ValueError("impact request contains too many additional subjects")
        additional = tuple(sorted(
            (
                _validate_subject_query(item, "impact additional subject")
                for item in raw_additional
            ),
            key=_subject_query_sort_key,
        ))
        keys = tuple(_subject_query_sort_key(item) for item in additional)
        if len(set(keys)) != len(keys):
            raise ValueError("impact additional subjects must be unique")
        if _subject_query_sort_key(self.subject) in set(keys):
            raise ValueError("impact primary subject must not be repeated")
        object.__setattr__(self, "additional_subjects", additional)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("impact requests must not contain absolute paths")
        if _contains_source_shaped_text(self.to_dict()):
            raise ValueError("impact requests must not contain source-shaped text")

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject.to_dict(),
            "change_kind": self.change_kind.value,
            "changed_members": list(self.changed_members),
            "changed_api_surface": list(self.changed_api_surface),
            "relations": [item.value for item in self.relations],
            "module": self.module,
            "package": self.package,
            "max_depth": self.max_depth,
            "limit": self.limit,
            "include_tests": self.include_tests,
            "include_dependencies": self.include_dependencies,
            "include_risk": self.include_risk,
            "include_git_context": self.include_git_context,
            "include_search_enrichment": self.include_search_enrichment,
            "additional_subjects": [
                item.to_dict() for item in self.additional_subjects
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactPredictionRequest:
        _reject_unknown(
            value,
            frozenset({
                "subject", "change_kind", "changed_members",
                "changed_api_surface", "relations", "module", "package",
                "max_depth", "limit", "include_tests", "include_dependencies",
                "include_risk", "include_git_context",
                "include_search_enrichment",
                "additional_subjects",
            }),
            "impact request",
        )
        raw_subject = value.get("subject")
        if not isinstance(raw_subject, Mapping):
            raise TypeError("impact request subject must be an object")
        return cls(
            _subject_query_from_dict(raw_subject),
            _coerce_enum(
                value.get("change_kind", "unknown"),
                ImpactChangeKind,
                "impact request change kind",
            ),  # type: ignore[arg-type]
            _semantic_identifiers(
                value.get("changed_members"), "impact changed members"
            ),
            _semantic_identifiers(
                value.get("changed_api_surface"), "impact changed API surface"
            ),
            tuple(
                _coerce_enum(
                    item, KnowledgeRelation, "impact relation filter"
                )  # type: ignore[misc]
                for item in _sequence(value.get("relations"), "impact relations")
            ),
            _optional_semantic_text(value.get("module"), "impact module"),
            _optional_semantic_text(value.get("package"), "impact package"),
            _strict_integer(value.get("max_depth"), "impact maximum depth", default=4),
            _strict_integer(value.get("limit"), "impact result limit", default=50),
            _strict_boolean(value.get("include_tests"), "impact include tests", default=False),
            _strict_boolean(
                value.get("include_dependencies"),
                "impact include dependencies",
                default=True,
            ),
            _strict_boolean(value.get("include_risk"), "impact include risk", default=True),
            _strict_boolean(
                value.get("include_git_context"),
                "impact include Git context",
                default=False,
            ),
            _strict_boolean(
                value.get("include_search_enrichment"),
                "impact include search enrichment",
                default=False,
            ),
            tuple(
                _subject_query_from_dict(item, "impact additional subject")
                for item in _mapping_items(
                    value.get("additional_subjects"),
                    "impact additional subjects",
                )
            ),
        )


def impact_prediction_fingerprint(
    snapshot_id: str,
    graph_digest: str,
    request: ImpactPredictionRequest,
) -> str:
    """Return the canonical PR136 request/graph/snapshot identity."""

    if not isinstance(request, ImpactPredictionRequest):
        raise TypeError("impact fingerprint request must be an ImpactPredictionRequest")
    snapshot = _semantic_text(
        snapshot_id, "impact fingerprint snapshot", maximum=256
    )
    graph = _semantic_text(
        graph_digest, "impact fingerprint graph digest", maximum=256
    )
    payload = {
        "graph_digest": graph,
        "producer": IMPACT_PREDICTION_PRODUCER,
        "request": request.to_dict(),
        "snapshot_id": snapshot,
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")).hexdigest()
    return f"impact-prediction:{digest}"


@dataclass(frozen=True, order=True, slots=True)
class ImpactScoreComponent:
    name: str
    value: float
    weight: float
    contribution: float
    evidence_ids: tuple[str, ...] = ()
    explanation: str = ""

    def __post_init__(self) -> None:
        name = _safe_text(self.name, "impact score component name", maximum=128)
        if _PORTABLE_NAME.fullmatch(name) is None:
            raise ValueError("impact score component name must be a portable identifier")
        object.__setattr__(self, "name", name)
        for field_name in ("value", "weight", "contribution"):
            object.__setattr__(
                self,
                field_name,
                _unit_interval(
                    getattr(self, field_name),
                    f"impact score component {field_name}",
                ),
            )
        if not math.isclose(
            self.contribution,
            self.value * self.weight,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("impact score component contribution is inconsistent")
        object.__setattr__(
            self,
            "evidence_ids",
            _evidence_ids(self.evidence_ids, "impact score component evidence IDs"),
        )
        object.__setattr__(
            self,
            "explanation",
            _safe_text(
                self.explanation,
                "impact score component explanation",
                maximum=_MAX_EXPLANATION,
                empty=True,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "evidence_ids": list(self.evidence_ids),
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactScoreComponent:
        _reject_unknown(
            value,
            frozenset({
                "name", "value", "weight", "contribution", "evidence_ids",
                "explanation",
            }),
            "impact score component",
        )
        return cls(
            _safe_text(value.get("name", ""), "impact score component name"),
            _strict_number(value.get("value"), "impact score component value", default=0.0),
            _strict_number(value.get("weight"), "impact score component weight", default=0.0),
            _strict_number(
                value.get("contribution"),
                "impact score component contribution",
                default=0.0,
            ),
            _evidence_ids(
                value.get("evidence_ids"), "impact score component evidence IDs"
            ),
            _safe_text(
                value.get("explanation", ""),
                "impact score component explanation",
                maximum=_MAX_EXPLANATION,
                empty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ImpactScore:
    value: float
    components: tuple[ImpactScoreComponent, ...]
    explanation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _unit_interval(self.value, "impact score"))
        raw = _sequence(self.components, "impact score components")
        if not raw or any(not isinstance(item, ImpactScoreComponent) for item in raw):
            raise TypeError("impact score requires ImpactScoreComponent values")
        components = tuple(sorted(raw))
        if len({item.name for item in components}) != len(components):
            raise ValueError("impact score component names must be unique")
        if not math.isclose(
            self.value,
            sum(item.contribution for item in components),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("impact score is inconsistent with its components")
        object.__setattr__(self, "components", components)
        object.__setattr__(
            self,
            "explanation",
            _safe_text(
                self.explanation,
                "impact score explanation",
                maximum=_MAX_EXPLANATION,
            ),
        )

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            evidence_id
            for component in self.components
            for evidence_id in component.evidence_ids
        }))

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "components": [item.to_dict() for item in self.components],
            "evidence_ids": list(self.evidence_ids),
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactScore:
        _reject_unknown(
            value,
            frozenset({"value", "components", "evidence_ids", "explanation"}),
            "impact score",
        )
        components = tuple(
            ImpactScoreComponent.from_dict(item)
            for item in _mapping_items(
                value.get("components"), "impact score components"
            )
        )
        expected = tuple(sorted({
            evidence_id
            for component in components
            for evidence_id in component.evidence_ids
        }))
        serialized = _evidence_ids(
            value.get("evidence_ids"), "impact score evidence IDs"
        )
        if serialized != expected:
            raise ValueError("impact score evidence IDs are inconsistent")
        return cls(
            _strict_number(value.get("value"), "impact score", default=0.0),
            components,
            _safe_text(
                value.get("explanation", ""),
                "impact score explanation",
                maximum=_MAX_EXPLANATION,
            ),
        )


@dataclass(frozen=True, order=True, slots=True)
class ImpactPathStep:
    source_subject_id: str
    target_subject_id: str
    relation: KnowledgeRelation
    reverse: bool
    strength: ImpactStrength
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_subject_id",
            _semantic_text(self.source_subject_id, "impact path source subject"),
        )
        object.__setattr__(
            self,
            "target_subject_id",
            _semantic_text(self.target_subject_id, "impact path target subject"),
        )
        if self.source_subject_id == self.target_subject_id:
            raise ValueError("impact path steps must connect distinct subjects")
        object.__setattr__(
            self,
            "relation",
            _coerce_enum(self.relation, KnowledgeRelation, "impact path relation"),
        )
        if not isinstance(self.reverse, bool):
            raise TypeError("impact path reverse flag must be a boolean")
        object.__setattr__(
            self,
            "strength",
            _coerce_enum(self.strength, ImpactStrength, "impact path strength"),
        )
        evidence = _evidence_ids(self.evidence_ids, "impact path step evidence IDs")
        if not evidence:
            raise ValueError("impact path steps require evidence")
        object.__setattr__(self, "evidence_ids", evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_subject_id": self.source_subject_id,
            "target_subject_id": self.target_subject_id,
            "relation": self.relation.value,
            "reverse": self.reverse,
            "strength": self.strength.value,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactPathStep:
        _reject_unknown(
            value,
            frozenset({
                "source_subject_id", "target_subject_id", "relation", "reverse",
                "strength", "evidence_ids",
            }),
            "impact path step",
        )
        return cls(
            _semantic_text(
                value.get("source_subject_id", ""), "impact path source subject"
            ),
            _semantic_text(
                value.get("target_subject_id", ""), "impact path target subject"
            ),
            _coerce_enum(
                value.get("relation", "related_to"),
                KnowledgeRelation,
                "impact path relation",
            ),  # type: ignore[arg-type]
            _strict_boolean(value.get("reverse"), "impact path reverse flag", default=False),
            _coerce_enum(
                value.get("strength", "insufficient"),
                ImpactStrength,
                "impact path strength",
            ),  # type: ignore[arg-type]
            _evidence_ids(value.get("evidence_ids"), "impact path step evidence IDs"),
        )


@dataclass(frozen=True, slots=True)
class ImpactPredictionPath:
    source_subject_id: str
    target_subject_id: str
    steps: tuple[ImpactPathStep, ...]
    truncated: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_subject_id",
            _semantic_text(self.source_subject_id, "impact path source subject"),
        )
        object.__setattr__(
            self,
            "target_subject_id",
            _semantic_text(self.target_subject_id, "impact path target subject"),
        )
        raw = _sequence(self.steps, "impact path steps")
        if (
            not raw
            or len(raw) > _MAX_PATH_DEPTH
            or any(not isinstance(item, ImpactPathStep) for item in raw)
        ):
            raise ValueError(
                f"impact paths require between 1 and {_MAX_PATH_DEPTH} steps"
            )
        steps = tuple(raw)
        if steps[0].source_subject_id != self.source_subject_id:
            raise ValueError("impact path first step does not start at its source")
        if steps[-1].target_subject_id != self.target_subject_id:
            raise ValueError("impact path final step does not end at its target")
        if any(
            left.target_subject_id != right.source_subject_id
            for left, right in zip(steps, steps[1:])
        ):
            raise ValueError("impact path steps are not contiguous")
        visited_subjects = (
            self.source_subject_id,
            *(step.target_subject_id for step in steps),
        )
        if len(set(visited_subjects)) != len(visited_subjects):
            raise ValueError("impact paths must be cycle-free and cannot self-impact")
        object.__setattr__(self, "steps", steps)
        if not isinstance(self.truncated, bool):
            raise TypeError("impact path truncation must be a boolean")
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "impact path limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )

    @property
    def length(self) -> int:
        return len(self.steps)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            evidence_id
            for step in self.steps
            for evidence_id in step.evidence_ids
        }))

    @property
    def relationships(self) -> tuple[KnowledgeRelation, ...]:
        return tuple(step.relation for step in self.steps)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_subject_id": self.source_subject_id,
            "target_subject_id": self.target_subject_id,
            "steps": [item.to_dict() for item in self.steps],
            "length": self.length,
            "relationships": [item.value for item in self.relationships],
            "evidence_ids": list(self.evidence_ids),
            "truncated": self.truncated,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactPredictionPath:
        _reject_unknown(
            value,
            frozenset({
                "source_subject_id", "target_subject_id", "steps", "length",
                "relationships", "evidence_ids", "truncated", "limitations",
            }),
            "impact path",
        )
        steps = tuple(
            ImpactPathStep.from_dict(item)
            for item in _mapping_items(value.get("steps"), "impact path steps")
        )
        length = _strict_integer(
            value.get("length"), "impact path length", default=len(steps)
        )
        if length != len(steps):
            raise ValueError("impact path length is inconsistent")
        relationships = tuple(
                _coerce_enum(
                    item, KnowledgeRelation, "impact path relationship"
                )  # type: ignore[misc]
            for item in _sequence(
                value.get("relationships"), "impact path relationships"
            )
        )
        if relationships != tuple(step.relation for step in steps):
            raise ValueError("impact path relationships are inconsistent")
        evidence = _evidence_ids(value.get("evidence_ids"), "impact path evidence IDs")
        expected_evidence = tuple(sorted({
            evidence_id for step in steps for evidence_id in step.evidence_ids
        }))
        if evidence != expected_evidence:
            raise ValueError("impact path evidence IDs are inconsistent")
        return cls(
            _semantic_text(
                value.get("source_subject_id", ""), "impact path source subject"
            ),
            _semantic_text(
                value.get("target_subject_id", ""), "impact path target subject"
            ),
            steps,
            _strict_boolean(value.get("truncated"), "impact path truncation", default=False),
            _strings(
                value.get("limitations"),
                "impact path limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )


@dataclass(frozen=True, slots=True)
class ImpactRiskContext:
    state: ImpactCapabilityState
    score: float
    rank: int
    signals: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    producer_version: str = "atlas-pr132/1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state",
            _coerce_enum(self.state, ImpactCapabilityState, "impact risk state"),
        )
        if self.state not in {
            ImpactCapabilityState.AVAILABLE,
            ImpactCapabilityState.PARTIAL,
        }:
            raise ValueError("attached impact risk context must be available or partial")
        object.__setattr__(self, "score", _unit_interval(self.score, "impact risk score"))
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("impact risk rank must be positive")
        object.__setattr__(
            self, "signals", _strings(self.signals, "impact risk signals")
        )
        evidence = _evidence_ids(self.evidence_ids, "impact risk evidence IDs")
        if not evidence:
            raise ValueError("impact risk context requires evidence")
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "impact risk limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )
        object.__setattr__(
            self,
            "producer_version",
            _safe_text(self.producer_version, "impact risk producer", maximum=128),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "score": self.score,
            "rank": self.rank,
            "signals": list(self.signals),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "producer_version": self.producer_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactRiskContext:
        _reject_unknown(
            value,
            frozenset({
                "state", "score", "rank", "signals", "evidence_ids",
                "limitations", "producer_version",
            }),
            "impact risk context",
        )
        return cls(
            _coerce_enum(
                value.get("state", "unavailable"),
                ImpactCapabilityState,
                "impact risk state",
            ),  # type: ignore[arg-type]
            _strict_number(value.get("score"), "impact risk score", default=0.0),
            _strict_integer(value.get("rank"), "impact risk rank", default=0),
            _strings(value.get("signals"), "impact risk signals"),
            _evidence_ids(value.get("evidence_ids"), "impact risk evidence IDs"),
            _strings(
                value.get("limitations"),
                "impact risk limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
            _safe_text(
                value.get("producer_version", "atlas-pr132/1"),
                "impact risk producer",
                maximum=128,
            ),
        )


@dataclass(frozen=True, slots=True)
class BreakingChangeAssessment:
    state: BreakingChangeState
    change_kind: ImpactChangeKind
    explanation: str
    evidence_ids: tuple[str, ...] = ()
    external_consumers_possible: bool = True
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state",
            _coerce_enum(self.state, BreakingChangeState, "breaking-change state"),
        )
        object.__setattr__(
            self,
            "change_kind",
            _coerce_enum(
                self.change_kind, ImpactChangeKind, "breaking-change kind"
            ),
        )
        object.__setattr__(
            self,
            "explanation",
            _safe_text(
                self.explanation,
                "breaking-change explanation",
                maximum=_MAX_EXPLANATION,
            ),
        )
        evidence = _evidence_ids(
            self.evidence_ids, "breaking-change evidence IDs"
        )
        if self.state in {
            BreakingChangeState.PROVEN_BREAKING,
            BreakingChangeState.POTENTIALLY_BREAKING,
        } and not evidence:
            raise ValueError("breaking-change conclusions require evidence")
        object.__setattr__(self, "evidence_ids", evidence)
        if not isinstance(self.external_consumers_possible, bool):
            raise TypeError("external consumer possibility must be a boolean")
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "breaking-change limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )
        if self.external_consumers_possible and not any(
            "external consumer" in limitation.casefold()
            for limitation in self.limitations
        ):
            raise ValueError(
                "breaking-change assessments with possible external consumers "
                "must preserve an external-consumer limitation"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "change_kind": self.change_kind.value,
            "explanation": self.explanation,
            "evidence_ids": list(self.evidence_ids),
            "external_consumers_possible": self.external_consumers_possible,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BreakingChangeAssessment:
        _reject_unknown(
            value,
            frozenset({
                "state", "change_kind", "explanation", "evidence_ids",
                "external_consumers_possible", "limitations",
            }),
            "breaking-change assessment",
        )
        return cls(
            _coerce_enum(
                value.get("state", "not_evaluated"),
                BreakingChangeState,
                "breaking-change state",
            ),  # type: ignore[arg-type]
            _coerce_enum(
                value.get("change_kind", "unknown"),
                ImpactChangeKind,
                "breaking-change kind",
            ),  # type: ignore[arg-type]
            _safe_text(
                value.get("explanation", ""),
                "breaking-change explanation",
                maximum=_MAX_EXPLANATION,
            ),
            _evidence_ids(
                value.get("evidence_ids"), "breaking-change evidence IDs"
            ),
            _strict_boolean(
                value.get("external_consumers_possible"),
                "external consumer possibility",
                default=True,
            ),
            _strings(
                value.get("limitations"),
                "breaking-change limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )


def _contains_explicit_before_after_evidence(
    evidence_ids: tuple[str, ...], evidence_index: EvidenceIndex
) -> bool:
    """Return whether a breaking claim has a compatible structured diff fact."""

    for evidence_id in evidence_ids:
        record = evidence_index.get(evidence_id)
        if record is None or record.kind is not EvidenceKind.ANALYSIS_RESULT:
            continue
        detail = dict(record.detail)
        before = detail.get("before_fingerprint")
        after = detail.get("after_fingerprint")
        rule = detail.get("compatibility_rule")
        if (
            before
            and after
            and before != after
            and rule
            and record.producer != IMPACT_PREDICTION_PRODUCER
        ):
            return True
    return False


@dataclass(frozen=True, order=True, slots=True)
class ImpactCapability:
    name: str
    state: ImpactCapabilityState
    coverage: float | None = None
    scopes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = _safe_text(self.name, "impact capability name", maximum=128)
        if _PORTABLE_NAME.fullmatch(name) is None:
            raise ValueError("impact capability name must be a portable identifier")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "state",
            _coerce_enum(
                self.state, ImpactCapabilityState, "impact capability state"
            ),
        )
        if self.coverage is not None:
            object.__setattr__(
                self, "coverage", _unit_interval(self.coverage, "impact capability coverage")
            )
        if self.state in {
            ImpactCapabilityState.UNAVAILABLE,
            ImpactCapabilityState.INCOMPATIBLE,
            ImpactCapabilityState.UNSUPPORTED,
        } and self.coverage not in {None, 0.0}:
            raise ValueError("unavailable impact capabilities cannot report positive coverage")
        object.__setattr__(
            self, "scopes", _strings(self.scopes, "impact capability scopes")
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _evidence_ids(self.evidence_ids, "impact capability evidence IDs"),
        )
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "impact capability limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "coverage": self.coverage,
            "scopes": list(self.scopes),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactCapability:
        _reject_unknown(
            value,
            frozenset({
                "name", "state", "coverage", "scopes", "evidence_ids",
                "limitations",
            }),
            "impact capability",
        )
        raw_coverage = value.get("coverage")
        return cls(
            _safe_text(value.get("name", ""), "impact capability name"),
            _coerce_enum(
                value.get("state", "unavailable"),
                ImpactCapabilityState,
                "impact capability state",
            ),  # type: ignore[arg-type]
            _strict_number(raw_coverage, "impact capability coverage", default=0.0)
            if raw_coverage is not None
            else None,
            _strings(value.get("scopes"), "impact capability scopes"),
            _evidence_ids(
                value.get("evidence_ids"), "impact capability evidence IDs"
            ),
            _strings(
                value.get("limitations"),
                "impact capability limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )


@dataclass(frozen=True, slots=True)
class ImpactFinding:
    subject: SubjectCandidate
    category: ImpactCategory
    strength: ImpactStrength
    direct: bool
    path: ImpactPredictionPath
    score: ImpactScore
    confidence: ConfidenceResult
    evidence_ids: tuple[str, ...]
    explanation: str
    module: str | None = None
    package: str | None = None
    risk_context: ImpactRiskContext | None = None
    breaking_change: BreakingChangeAssessment | None = None
    capability_state: ImpactCapabilityState = ImpactCapabilityState.AVAILABLE
    limitations: tuple[str, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_subject_candidate(self.subject, "impact finding subject")
        object.__setattr__(
            self,
            "category",
            _coerce_enum(self.category, ImpactCategory, "impact finding category"),
        )
        object.__setattr__(
            self,
            "strength",
            _coerce_enum(self.strength, ImpactStrength, "impact finding strength"),
        )
        if not isinstance(self.direct, bool):
            raise TypeError("impact finding direct flag must be a boolean")
        if not isinstance(self.path, ImpactPredictionPath):
            raise TypeError("impact finding path must be an ImpactPredictionPath")
        if self.path.target_subject_id != self.subject.canonical_id:
            raise ValueError("impact finding path target does not match its subject")
        if self.direct != (self.path.length == 1):
            raise ValueError("impact finding direct flag does not match its path length")
        if not isinstance(self.score, ImpactScore):
            raise TypeError("impact finding score must be an ImpactScore")
        _validate_confidence_result(self.confidence, "impact finding confidence")
        if self.risk_context is not None and not isinstance(
            self.risk_context, ImpactRiskContext
        ):
            raise TypeError("impact finding risk context is invalid")
        if self.breaking_change is not None and not isinstance(
            self.breaking_change, BreakingChangeAssessment
        ):
            raise TypeError("impact finding breaking assessment is invalid")
        evidence = _evidence_ids(self.evidence_ids, "impact finding evidence IDs")
        if not evidence:
            raise ValueError("impact findings require evidence")
        nested_evidence = {
            *self.path.evidence_ids,
            *self.score.evidence_ids,
            *(
                self.risk_context.evidence_ids
                if self.risk_context is not None
                else ()
            ),
            *(
                self.breaking_change.evidence_ids
                if self.breaking_change is not None
                else ()
            ),
        }
        if nested_evidence.difference(evidence):
            raise ValueError("impact finding omits evidence referenced by nested results")
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(
            self,
            "explanation",
            _safe_text(
                self.explanation,
                "impact finding explanation",
                maximum=_MAX_EXPLANATION,
            ),
        )
        object.__setattr__(
            self,
            "module",
            _optional_semantic_text(self.module, "impact finding module"),
        )
        object.__setattr__(
            self,
            "package",
            _optional_semantic_text(self.package, "impact finding package"),
        )
        object.__setattr__(
            self,
            "capability_state",
            _coerce_enum(
                self.capability_state,
                ImpactCapabilityState,
                "impact finding capability state",
            ),
        )
        if self.capability_state not in {
            ImpactCapabilityState.AVAILABLE,
            ImpactCapabilityState.PARTIAL,
        }:
            raise ValueError(
                "impact findings require an available or partial capability"
            )
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "impact finding limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )
        object.__setattr__(
            self,
            "attributes",
            _attributes(self.attributes, "impact finding attributes"),
        )
        if contains_absolute_path(self.to_dict()):
            raise ValueError("impact findings must not contain absolute paths")
        if _contains_source_shaped_text(self.to_dict()):
            raise ValueError("impact findings must not contain source-shaped text")

    @property
    def canonical_subject_id(self) -> str:
        return self.subject.canonical_id

    @property
    def coverage(self) -> float:
        return self.confidence.coverage

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject.to_dict(),
            "category": self.category.value,
            "strength": self.strength.value,
            "direct": self.direct,
            "path": self.path.to_dict(),
            "score": self.score.to_dict(),
            "confidence": self.confidence.to_dict(),
            "coverage": self.coverage,
            "evidence_ids": list(self.evidence_ids),
            "explanation": self.explanation,
            "module": self.module,
            "package": self.package,
            "risk_context": (
                self.risk_context.to_dict()
                if self.risk_context is not None
                else None
            ),
            "breaking_change": (
                self.breaking_change.to_dict()
                if self.breaking_change is not None
                else None
            ),
            "capability_state": self.capability_state.value,
            "limitations": list(self.limitations),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactFinding:
        _reject_unknown(
            value,
            frozenset({
                "subject", "category", "strength", "direct", "path", "score",
                "confidence", "coverage", "evidence_ids", "explanation", "module", "package", "risk_context",
                "breaking_change", "capability_state", "limitations", "attributes",
            }),
            "impact finding",
        )
        raw_subject = value.get("subject")
        raw_path = value.get("path")
        raw_score = value.get("score")
        raw_confidence = value.get("confidence")
        raw_risk = value.get("risk_context")
        raw_breaking = value.get("breaking_change")
        if not isinstance(raw_subject, Mapping):
            raise TypeError("impact finding subject must be an object")
        if not isinstance(raw_path, Mapping):
            raise TypeError("impact finding path must be an object")
        if not isinstance(raw_score, Mapping):
            raise TypeError("impact finding score must be an object")
        if not isinstance(raw_confidence, Mapping):
            raise TypeError("impact finding confidence must be an object")
        if raw_risk is not None and not isinstance(raw_risk, Mapping):
            raise TypeError("impact finding risk context must be an object")
        if raw_breaking is not None and not isinstance(raw_breaking, Mapping):
            raise TypeError("impact finding breaking assessment must be an object")
        result = cls(
            _subject_candidate_from_dict(raw_subject, "impact finding subject"),
            _coerce_enum(
                value.get("category", "unknown"),
                ImpactCategory,
                "impact finding category",
            ),  # type: ignore[arg-type]
            _coerce_enum(
                value.get("strength", "insufficient"),
                ImpactStrength,
                "impact finding strength",
            ),  # type: ignore[arg-type]
            _strict_boolean(value.get("direct"), "impact finding direct flag", default=False),
            ImpactPredictionPath.from_dict(raw_path),
            ImpactScore.from_dict(raw_score),
            _validated_confidence(raw_confidence),
            _evidence_ids(value.get("evidence_ids"), "impact finding evidence IDs"),
            _safe_text(
                value.get("explanation", ""),
                "impact finding explanation",
                maximum=_MAX_EXPLANATION,
            ),
            _optional_semantic_text(value.get("module"), "impact finding module"),
            _optional_semantic_text(value.get("package"), "impact finding package"),
            ImpactRiskContext.from_dict(raw_risk)
            if isinstance(raw_risk, Mapping)
            else None,
            BreakingChangeAssessment.from_dict(raw_breaking)
            if isinstance(raw_breaking, Mapping)
            else None,
            _coerce_enum(
                value.get("capability_state", "available"),
                ImpactCapabilityState,
                "impact finding capability state",
            ),  # type: ignore[arg-type]
            _strings(
                value.get("limitations"),
                "impact finding limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
            _attributes(value.get("attributes"), "impact finding attributes"),
        )
        serialized_coverage = _unit_interval(
            value.get("coverage", result.coverage), "impact finding coverage"
        )
        if serialized_coverage != result.coverage:
            raise ValueError("impact finding coverage is inconsistent")
        return result


def _finding_sort_key(item: ImpactFinding) -> tuple[object, ...]:
    return (
        not item.direct,
        item.path.length,
        -item.score.value,
        item.category.value,
        item.subject.qualified_name.casefold(),
        item.subject.qualified_name,
        item.subject.project or "",
        item.subject.kind.value,
        item.subject.canonical_id,
    )


@dataclass(frozen=True, slots=True)
class ImpactPredictionResponse:
    request: ImpactPredictionRequest
    resolution: SubjectResolution
    findings: tuple[ImpactFinding, ...]
    capabilities: tuple[ImpactCapability, ...]
    breaking_change: BreakingChangeAssessment
    evidence_index: EvidenceIndex = field(
        default_factory=lambda: EvidenceIndex().freeze()
    )
    input_fingerprint: str = "unavailable"
    graph_digest: str = "unavailable"
    lineage: str = "unavailable"
    total_candidate_count: int = 0
    omitted_count: int = 0
    visited_node_count: int = 0
    visited_edge_count: int = 0
    truncated: bool = False
    limitations: tuple[str, ...] = ()
    producer_version: str = IMPACT_PREDICTION_PRODUCER
    schema_version: int = IMPACT_PREDICTION_SCHEMA_VERSION
    additional_resolutions: tuple[SubjectResolution, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, ImpactPredictionRequest):
            raise TypeError("impact response request must be an ImpactPredictionRequest")
        _validate_subject_resolution(self.resolution)
        if self.resolution.query != self.request.subject:
            raise ValueError("impact response resolution does not match its request")
        raw_additional_resolutions = _sequence(
            self.additional_resolutions, "impact additional resolutions"
        )
        additional_resolutions = tuple(sorted(
            (
                _validate_subject_resolution(
                    item, "impact additional resolution"
                )
                for item in raw_additional_resolutions
            ),
            key=lambda item: _subject_query_sort_key(item.query),
        ))
        expected_additional = tuple(
            _subject_query_sort_key(item)
            for item in self.request.additional_subjects
        )
        actual_additional = tuple(
            _subject_query_sort_key(item.query)
            for item in additional_resolutions
        )
        if actual_additional != expected_additional:
            raise ValueError(
                "impact additional resolutions do not match additional subjects"
            )
        if any(
            item.graph_digest != self.resolution.graph_digest
            for item in additional_resolutions
        ):
            raise ValueError("impact resolutions use inconsistent graph digests")
        object.__setattr__(
            self, "additional_resolutions", additional_resolutions
        )
        raw_findings = _sequence(self.findings, "impact response findings")
        if any(not isinstance(item, ImpactFinding) for item in raw_findings):
            raise TypeError("impact response findings must be ImpactFinding values")
        findings = tuple(sorted(raw_findings, key=_finding_sort_key))
        finding_keys = {
            (item.canonical_subject_id, item.category) for item in findings
        }
        if len(finding_keys) != len(findings):
            raise ValueError("impact response contains duplicate subject categories")
        resolutions = (self.resolution, *additional_resolutions)
        resolved_sources = {
            item.subject.canonical_id
            for item in resolutions
            if item.status is ResolutionStatus.RESOLVED and item.subject is not None
        }
        if not resolved_sources and findings:
            raise ValueError("unresolved impact responses cannot contain findings")
        if any(item.path.source_subject_id not in resolved_sources for item in findings):
            raise ValueError("impact response finding paths use another source subject")
        if any(item.canonical_subject_id in resolved_sources for item in findings):
            raise ValueError("impact responses cannot report a changed source as impacted")
        if any(item.path.length > self.request.max_depth for item in findings):
            raise ValueError("impact finding exceeds the requested traversal depth")
        if len(findings) > self.request.limit:
            raise ValueError("impact response exceeds the requested result limit")
        if not self.request.include_tests and any(
            item.category is ImpactCategory.TEST for item in findings
        ):
            raise ValueError("impact response contains tests that were not requested")
        dependency_categories = {
            ImpactCategory.DEPENDENCY,
            ImpactCategory.IMPORTED_DEPENDENCY,
            ImpactCategory.PROJECT_DEPENDENT,
            ImpactCategory.MODULE_DEPENDENT,
            ImpactCategory.PACKAGE_DEPENDENT,
        }
        if not self.request.include_dependencies and any(
            item.category in dependency_categories for item in findings
        ):
            raise ValueError(
                "impact response contains dependencies that were not requested"
            )
        if self.request.relations:
            permitted_relations = {
                *self.request.relations,
                KnowledgeRelation.OWNS,
                KnowledgeRelation.MEMBER_OF,
            }
            if any(
                step.relation not in permitted_relations
                for item in findings
                for step in item.path.steps
            ):
                raise ValueError("impact response violates its relation filters")
        object.__setattr__(self, "findings", findings)

        raw_capabilities = _sequence(
            self.capabilities, "impact response capabilities"
        )
        if any(not isinstance(item, ImpactCapability) for item in raw_capabilities):
            raise TypeError(
                "impact response capabilities must be ImpactCapability values"
            )
        capabilities = tuple(sorted(
            raw_capabilities,
            key=lambda item: (
                item.name,
                item.state.value,
                item.coverage is None,
                item.coverage if item.coverage is not None else 0.0,
                item.scopes,
                item.evidence_ids,
                item.limitations,
            ),
        ))
        if len({item.name for item in capabilities}) != len(capabilities):
            raise ValueError("impact response capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)

        if not isinstance(self.breaking_change, BreakingChangeAssessment):
            raise TypeError(
                "impact response breaking change must be a "
                "BreakingChangeAssessment"
            )
        if self.breaking_change.change_kind is not self.request.change_kind:
            raise ValueError(
                "impact response breaking-change kind differs from its request"
            )
        if any(
            item.breaking_change is not None
            and item.breaking_change.change_kind is not self.request.change_kind
            for item in findings
        ):
            raise ValueError(
                "impact finding breaking-change kind differs from its request"
            )
        if (
            not findings
            and self.breaking_change.external_consumers_possible
            and EXTERNAL_CONSUMER_LIMITATION
            not in self.breaking_change.limitations
        ):
            raise ValueError(
                "impact responses with no proven in-repository consumer must "
                "preserve the exact external-consumer limitation"
            )

        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("impact response evidence index must be an EvidenceIndex")
        evidence_index = self.evidence_index.freeze()
        for record in evidence_index.records:
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
                    f"impact response contains non-canonical evidence: {record.evidence_id}"
                )
            if contains_absolute_path(record.to_dict()):
                raise ValueError("impact response evidence must be source-free")
            for name in (
                "subject_id", "producer", "snapshot_id", "scope", "language"
            ):
                _semantic_text(
                    getattr(record, name), f"impact evidence {name}", maximum=512
                )
            _evidence_source_refs(
                record.source_refs, "impact evidence source references"
            )
            _attributes(record.detail, "impact evidence detail")
            if _attributes(record.detail, "impact evidence detail") != record.detail:
                raise ValueError("impact response evidence detail is non-canonical")
        object.__setattr__(self, "evidence_index", evidence_index)
        available_evidence = {
            record.evidence_id for record in evidence_index.records
        }
        referenced_evidence = {
            evidence_id
            for finding in findings
            for evidence_id in finding.evidence_ids
        }
        referenced_evidence.update(
            evidence_id
            for capability in capabilities
            for evidence_id in capability.evidence_ids
        )
        referenced_evidence.update(self.breaking_change.evidence_ids)
        if referenced_evidence != available_evidence:
            missing = referenced_evidence.difference(available_evidence)
            extra = available_evidence.difference(referenced_evidence)
            if missing:
                raise ValueError("impact response contains unresolvable evidence IDs")
            if extra:
                raise ValueError("impact response evidence index contains unreferenced records")

        for finding in findings:
            path_records = tuple(
                evidence_index.get(evidence_id)
                for evidence_id in finding.path.evidence_ids
            )
            if not path_records or any(record is None for record in path_records):
                raise ValueError("impact finding path evidence is unavailable")
            retained_path_records = tuple(
                record for record in path_records if record is not None
            )
            expected_support = round(sum(
                record.reliability * record.specificity
                for record in retained_path_records
            ) / len(retained_path_records), 4)
            if not math.isclose(
                finding.confidence.support,
                expected_support,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "impact finding confidence is inconsistent with path evidence"
                )

        breaking_assessments = (
            self.breaking_change,
            *(
                item.breaking_change
                for item in findings
                if item.breaking_change is not None
            ),
        )
        if any(
            assessment.state is BreakingChangeState.PROVEN_BREAKING
            and not _contains_explicit_before_after_evidence(
                assessment.evidence_ids, evidence_index
            )
            for assessment in breaking_assessments
        ):
            raise ValueError(
                "proven breaking changes require compatible before/after evidence"
            )

        for name in (
            "input_fingerprint", "graph_digest", "lineage", "producer_version"
        ):
            object.__setattr__(
                self,
                name,
                _safe_text(getattr(self, name), f"impact response {name}", maximum=256),
            )
        if self.producer_version != IMPACT_PREDICTION_PRODUCER:
            raise ValueError("unsupported impact response producer")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != IMPACT_PREDICTION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported impact response schema")
        if self.lineage == "unavailable":
            if self.input_fingerprint != "unavailable" or evidence_index.records:
                raise ValueError(
                    "impact response unavailable lineage cannot retain evidence"
                )
        else:
            if _FINGERPRINT.fullmatch(self.input_fingerprint) is None:
                raise ValueError("impact response input fingerprint is malformed")
            expected_fingerprint = impact_prediction_fingerprint(
                self.lineage, self.graph_digest, self.request
            )
            if self.input_fingerprint != expected_fingerprint:
                raise ValueError("impact response input fingerprint is inconsistent")
            if any(
                record.snapshot_id != self.lineage
                for record in evidence_index.records
            ):
                raise ValueError(
                    "impact response evidence snapshot differs from its lineage"
                )
        if (
            self.resolution.graph_digest != "unavailable"
            and self.graph_digest != self.resolution.graph_digest
        ):
            raise ValueError("impact response graph digest differs from subject resolution")
        for name in (
            "total_candidate_count", "omitted_count", "visited_node_count",
            "visited_edge_count",
        ):
            count = getattr(self, name)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"impact response {name} must be non-negative")
        if self.total_candidate_count < len(findings):
            raise ValueError("impact response total candidate count is inconsistent")
        if self.omitted_count != self.total_candidate_count - len(findings):
            raise ValueError("impact response omitted count is inconsistent")
        if self.omitted_count and not self.truncated:
            raise ValueError("impact response omissions require truncation")
        if not isinstance(self.truncated, bool):
            raise TypeError("impact response truncation must be a boolean")
        object.__setattr__(
            self,
            "limitations",
            _strings(
                self.limitations,
                "impact response limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
        )
        if contains_absolute_path(self.to_dict()):
            raise ValueError("impact responses must not contain absolute paths")
        if _contains_source_shaped_text(self.to_dict()):
            raise ValueError("impact responses must not contain source-shaped text")

    @property
    def direct_impacts(self) -> tuple[ImpactFinding, ...]:
        return tuple(item for item in self.findings if item.direct)

    @property
    def transitive_impacts(self) -> tuple[ImpactFinding, ...]:
        return tuple(item for item in self.findings if not item.direct)

    @property
    def direct_impact_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            item.canonical_subject_id for item in self.direct_impacts
        }))

    @property
    def transitive_impact_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            item.canonical_subject_id for item in self.transitive_impacts
        }))

    def _subjects_for(self, *categories: ImpactCategory) -> tuple[str, ...]:
        selected = set(categories)
        return tuple(sorted({
            item.canonical_subject_id
            for item in self.findings
            if item.category in selected
        }))

    @property
    def affected_api_ids(self) -> tuple[str, ...]:
        return self._subjects_for(ImpactCategory.PUBLIC_API)

    @property
    def affected_test_ids(self) -> tuple[str, ...]:
        return self._subjects_for(ImpactCategory.TEST)

    @property
    def affected_dependency_ids(self) -> tuple[str, ...]:
        return self._subjects_for(
            ImpactCategory.DEPENDENCY, ImpactCategory.IMPORTED_DEPENDENCY
        )

    @property
    def affected_project_ids(self) -> tuple[str, ...]:
        return self._subjects_for(
            ImpactCategory.PROJECT_DEPENDENT, ImpactCategory.OWNING_PROJECT
        )

    @property
    def affected_module_ids(self) -> tuple[str, ...]:
        return self._subjects_for(
            ImpactCategory.MODULE_DEPENDENT, ImpactCategory.OWNING_MODULE
        )

    @property
    def affected_package_ids(self) -> tuple[str, ...]:
        return self._subjects_for(
            ImpactCategory.PACKAGE_DEPENDENT, ImpactCategory.OWNING_PACKAGE
        )

    @property
    def unavailable_analyses(self) -> tuple[str, ...]:
        return tuple(sorted({
            capability.name
            for capability in self.capabilities
            if capability.state in {
                ImpactCapabilityState.UNAVAILABLE,
                ImpactCapabilityState.INCOMPATIBLE,
                ImpactCapabilityState.UNSUPPORTED,
            }
        }))

    @property
    def possible_breaking_change_ids(self) -> tuple[str, ...]:
        result = {
            item.canonical_subject_id
            for item in self.findings
            if item.breaking_change is not None
            and item.breaking_change.state in {
                BreakingChangeState.PROVEN_BREAKING,
                BreakingChangeState.POTENTIALLY_BREAKING,
            }
        }
        if self.breaking_change.state in {
            BreakingChangeState.PROVEN_BREAKING,
            BreakingChangeState.POTENTIALLY_BREAKING,
        }:
            resolved_sources = {
                item.subject.canonical_id
                for item in (
                    self.resolution,
                    *self.additional_resolutions,
                )
                if item.subject is not None
            }
            result.update(
                record.subject_id
                for evidence_id in self.breaking_change.evidence_ids
                if (record := self.evidence_index.get(evidence_id)) is not None
                and record.subject_id in resolved_sources
            )
        return tuple(sorted(result))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "lineage": self.lineage,
            "request": self.request.to_dict(),
            "resolution": self.resolution.to_dict(),
            "additional_resolutions": [
                item.to_dict() for item in self.additional_resolutions
            ],
            "findings": [item.to_dict() for item in self.findings],
            "direct_impact_ids": list(self.direct_impact_ids),
            "transitive_impact_ids": list(self.transitive_impact_ids),
            "affected_api_ids": list(self.affected_api_ids),
            "affected_test_ids": list(self.affected_test_ids),
            "affected_dependency_ids": list(self.affected_dependency_ids),
            "affected_project_ids": list(self.affected_project_ids),
            "affected_module_ids": list(self.affected_module_ids),
            "affected_package_ids": list(self.affected_package_ids),
            "possible_breaking_change_ids": list(
                self.possible_breaking_change_ids
            ),
            "total_candidate_count": self.total_candidate_count,
            "returned_count": len(self.findings),
            "omitted_count": self.omitted_count,
            "visited_node_count": self.visited_node_count,
            "visited_edge_count": self.visited_edge_count,
            "truncated": self.truncated,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "unavailable_analyses": list(self.unavailable_analyses),
            "breaking_change": self.breaking_change.to_dict(),
            "evidence_index": self.evidence_index.to_dict(),
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ImpactPredictionResponse:
        _reject_unknown(
            value,
            frozenset({
                "schema_version", "producer_version", "input_fingerprint",
                "graph_digest", "lineage", "request", "resolution", "findings",
                "additional_resolutions",
                "direct_impact_ids", "transitive_impact_ids", "affected_api_ids",
                "affected_test_ids", "affected_dependency_ids",
                "affected_project_ids", "affected_module_ids",
                "affected_package_ids", "unavailable_analyses",
                "possible_breaking_change_ids", "total_candidate_count",
                "returned_count", "omitted_count", "visited_node_count",
                "visited_edge_count", "truncated", "capabilities",
                "breaking_change", "evidence_index", "limitations",
            }),
            "impact response",
        )
        raw_request = value.get("request")
        raw_resolution = value.get("resolution")
        raw_evidence = value.get("evidence_index")
        raw_breaking = value.get("breaking_change")
        if not isinstance(raw_request, Mapping):
            raise TypeError("impact response request must be an object")
        if not isinstance(raw_resolution, Mapping):
            raise TypeError("impact response resolution must be an object")
        if not isinstance(raw_evidence, Mapping):
            raise TypeError("impact response evidence index must be an object")
        if not isinstance(raw_breaking, Mapping):
            raise TypeError("impact response breaking change must be an object")
        findings = tuple(
            ImpactFinding.from_dict(item)
            for item in _mapping_items(value.get("findings"), "impact findings")
        )
        capabilities = tuple(
            ImpactCapability.from_dict(item)
            for item in _mapping_items(
                value.get("capabilities"), "impact capabilities"
            )
        )
        result = cls(
            ImpactPredictionRequest.from_dict(raw_request),
            _subject_resolution_from_dict(raw_resolution),
            findings,
            capabilities,
            BreakingChangeAssessment.from_dict(raw_breaking),
            _validated_evidence_index(raw_evidence),
            _safe_text(
                value.get("input_fingerprint", "unavailable"),
                "impact response input fingerprint",
                maximum=256,
            ),
            _safe_text(
                value.get("graph_digest", "unavailable"),
                "impact response graph digest",
                maximum=256,
            ),
            _safe_text(
                value.get("lineage", "unavailable"),
                "impact response lineage",
                maximum=256,
            ),
            _strict_integer(
                value.get("total_candidate_count"),
                "impact response total candidate count",
                default=0,
            ),
            _strict_integer(
                value.get("omitted_count"),
                "impact response omitted count",
                default=0,
            ),
            _strict_integer(
                value.get("visited_node_count"),
                "impact response visited node count",
                default=0,
            ),
            _strict_integer(
                value.get("visited_edge_count"),
                "impact response visited edge count",
                default=0,
            ),
            _strict_boolean(
                value.get("truncated"), "impact response truncation", default=False
            ),
            _strings(
                value.get("limitations"),
                "impact response limitations",
                maximum_count=_MAX_LIMITATIONS,
                maximum_length=_MAX_EXPLANATION,
            ),
            _safe_text(
                value.get("producer_version", IMPACT_PREDICTION_PRODUCER),
                "impact response producer",
                maximum=128,
            ),
            _strict_integer(
                value.get("schema_version"),
                "impact response schema version",
                default=IMPACT_PREDICTION_SCHEMA_VERSION,
            ),
            tuple(
                _subject_resolution_from_dict(
                    item, "impact additional resolution"
                )
                for item in _mapping_items(
                    value.get("additional_resolutions"),
                    "impact additional resolutions",
                )
            ),
        )
        expected = result.to_dict()
        for field_name in (
            "direct_impact_ids", "transitive_impact_ids", "affected_api_ids",
            "affected_test_ids", "affected_dependency_ids", "affected_project_ids",
            "affected_module_ids", "affected_package_ids", "unavailable_analyses",
            "possible_breaking_change_ids",
        ):
            serialized = _strings(value.get(field_name), f"impact response {field_name}")
            if serialized != tuple(expected[field_name]):
                raise ValueError(f"impact response {field_name} is inconsistent")
        returned = _strict_integer(
            value.get("returned_count"),
            "impact response returned count",
            default=len(findings),
        )
        if returned != len(result.findings):
            raise ValueError("impact response returned count is inconsistent")
        return result
