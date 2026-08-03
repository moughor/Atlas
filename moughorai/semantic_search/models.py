from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import math
from pathlib import Path

from moughorai.dependency_graph import DependencyKind
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind, SymbolId
from moughorai.knowledge_graph import KnowledgeKind, KnowledgeRelation
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
)


# PR25 compatibility contracts. Field order and defaults are intentionally unchanged.
@dataclass(frozen=True)
class SemanticSearchQuery:
    text: str | None = None
    kinds: frozenset[GlobalSymbolKind] = frozenset()
    source_prefix: Path | None = None
    owner_id: SymbolId | None = None
    related_to: SymbolId | None = None
    relation_kinds: frozenset[DependencyKind] = frozenset()
    reverse_relation: bool = False
    transitive: bool = False
    limit: int | None = None


@dataclass(frozen=True)
class SemanticSearchHit:
    symbol: GlobalSymbol
    score: int
    reasons: tuple[str, ...]


class SearchIntent(str, Enum):
    EXACT_IDENTITY = "exact_identity"
    CONCEPT = "concept"
    SUBJECT_KIND = "subject_kind"
    RELATIONAL = "relational"
    COMPOUND = "compound"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class SearchCapabilityState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED = "unsupported"


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an array")
    return tuple(value)


def _strings(value: object, name: str = "string sequence") -> tuple[str, ...]:
    values = _sequence(value, name)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"{name} entries must be strings")
    return tuple(sorted({item.strip() for item in values if item.strip()}))


def _ordered_strings(value: object, name: str) -> tuple[str, ...]:
    values = _sequence(value, name)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"{name} entries must be strings")
    return tuple(item.strip() for item in values if item.strip())


def _mapping_items(
    value: object,
    name: str,
) -> tuple[Mapping[str, object], ...]:
    values = _sequence(value, name)
    if any(not isinstance(item, Mapping) for item in values):
        raise TypeError(f"{name} entries must be objects")
    return tuple(values)


def _validated_evidence_index(value: Mapping[str, object]) -> EvidenceIndex:
    """Restore evidence without trusting serialized deterministic identities."""

    schema_version = _strict_integer(
        value.get("schema_version"),
        "semantic search evidence schema version",
        default=EvidenceIndex.SCHEMA_VERSION,
    )
    if schema_version != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported evidence index schema")
    restored = []
    for item in _mapping_items(
        value.get("records"), "semantic search evidence records",
    ):
        raw_detail = item.get("detail", {})
        if not isinstance(raw_detail, Mapping):
            raise TypeError("semantic search evidence detail must be an object")
        for name in (
            "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
            "scope", "language",
        ):
            if name in item and not isinstance(item.get(name), str):
                raise TypeError(f"semantic search evidence {name} must be a string")
        for name in ("evidence_id", "kind", "subject_id", "producer", "snapshot_id"):
            if name not in item:
                raise TypeError(f"semantic search evidence {name} must be a string")
        source_refs = _strings(
            item.get("source_refs"), "semantic search evidence source references",
        )
        limitations = _strings(
            item.get("limitations"), "semantic search evidence limitations",
        )
        record = EvidenceRecord.create(
            EvidenceKind(item["kind"]),
            item["subject_id"],
            item["producer"],
            item["snapshot_id"],
            source_refs=source_refs,
            scope=str(item.get("scope", "repository")),
            language=str(item.get("language", "unknown")),
            detail=raw_detail,
            limitations=limitations,
            reliability=_strict_number(
                item.get("reliability"),
                "semantic search evidence reliability",
                default=1.0,
            ),
            specificity=_strict_number(
                item.get("specificity"),
                "semantic search evidence specificity",
                default=1.0,
            ),
        )
        if record.evidence_id != item["evidence_id"]:
            raise ValueError("semantic search evidence ID is inconsistent")
        restored.append(record)
    return EvidenceIndex(restored, frozen=True)


def _finite_unit(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _strict_boolean(value: object, name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _strict_integer(value: object, name: str, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _strict_number(value: object, name: str, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    return float(value)


def _validated_confidence(value: Mapping[str, object]) -> ConfidenceResult:
    tier = value.get("tier", ConfidenceTier.INSUFFICIENT.value)
    if not isinstance(tier, str):
        raise TypeError("search hit confidence tier must be a string")
    return ConfidenceResult(
        _strict_number(value.get("score"), "confidence score", default=0.0),
        ConfidenceTier(tier),
        _strict_number(value.get("support"), "confidence support", default=0.0),
        _strict_number(value.get("coverage"), "confidence coverage", default=0.0),
        _strict_number(value.get("agreement"), "confidence agreement", default=1.0),
        _strict_number(
            value.get("contradiction_penalty"),
            "confidence contradiction penalty",
            default=0.0,
        ),
        _strict_number(
            value.get("ambiguity_penalty"),
            "confidence ambiguity penalty",
            default=0.0,
        ),
        _strings(value.get("missing_roles"), "confidence missing roles"),
        _strict_integer(
            value.get("model_version"), "confidence model version", default=1,
        ),
    )


@dataclass(frozen=True, slots=True)
class SemanticSearchRequest:
    text: str
    kinds: tuple[KnowledgeKind, ...] = ()
    project: str | None = None
    module: str | None = None
    package: str | None = None
    language: str | None = None
    relation: KnowledgeRelation | None = None
    minimum_confidence: float = 0.0
    limit: int = 20

    def __post_init__(self) -> None:
        text = self.text.strip()
        if not text:
            raise ValueError("semantic search query must not be empty")
        if len(text) > 4_096:
            raise ValueError("semantic search query is too long")
        raw_kinds = _sequence(self.kinds, "semantic search kinds")
        kinds = tuple(sorted(
            {
                item if isinstance(item, KnowledgeKind) else KnowledgeKind(str(item))
                for item in raw_kinds
            },
            key=lambda item: item.value,
        ))
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "kinds", kinds)
        if isinstance(self.relation, str):
            object.__setattr__(self, "relation", KnowledgeRelation(self.relation))
        for name in ("project", "module", "package", "language"):
            raw = getattr(self, name)
            value = raw.strip() if raw and raw.strip() else None
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "minimum_confidence", _finite_unit(self.minimum_confidence, "minimum confidence")
        )
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 100:
            raise ValueError("semantic search limit must be between 1 and 100")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("semantic search requests must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "kinds": [item.value for item in self.kinds],
            "project": self.project,
            "module": self.module,
            "package": self.package,
            "language": self.language,
            "relation": self.relation.value if self.relation is not None else None,
            "minimum_confidence": self.minimum_confidence,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SemanticSearchRequest:
        raw_relation = value.get("relation")
        return cls(
            str(value.get("text", "")),
            tuple(KnowledgeKind(item) for item in _strings(
                value.get("kinds"), "semantic search kinds",
            )),
            str(value["project"]) if value.get("project") is not None else None,
            str(value["module"]) if value.get("module") is not None else None,
            str(value["package"]) if value.get("package") is not None else None,
            str(value["language"]) if value.get("language") is not None else None,
            KnowledgeRelation(str(raw_relation)) if raw_relation is not None else None,
            _strict_number(
                value.get("minimum_confidence"),
                "minimum confidence",
                default=0.0,
            ),
            _strict_integer(value.get("limit"), "search limit", default=20),
        )


@dataclass(frozen=True, slots=True)
class QueryInterpretation:
    raw_query: str
    normalized_query: str
    terms: tuple[str, ...]
    intents: tuple[SearchIntent, ...]
    concepts: tuple[str, ...] = ()
    subject_terms: tuple[str, ...] = ()
    relation: KnowledgeRelation | None = None
    filters: tuple[tuple[str, str], ...] = ()
    alternatives: tuple[str, ...] = ()
    unsupported_terms: tuple[str, ...] = ()
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if not self.raw_query.strip() or not self.normalized_query.strip():
            raise ValueError("query interpretation text must not be empty")
        if not isinstance(self.ambiguous, bool):
            raise TypeError("query interpretation ambiguity must be a boolean")
        object.__setattr__(
            self, "terms", _ordered_strings(self.terms, "query terms"),
        )
        object.__setattr__(self, "intents", tuple(sorted(set(
            item if isinstance(item, SearchIntent) else SearchIntent(str(item))
            for item in _sequence(self.intents, "query intents")
        ), key=lambda item: item.value)))
        for name in ("concepts", "subject_terms", "alternatives", "unsupported_terms"):
            object.__setattr__(
                self, name, _strings(getattr(self, name), f"query {name}")
            )
        raw_filters = _sequence(self.filters, "query filters")
        if any(
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes, bytearray))
            or len(item) != 2
            for item in raw_filters
        ):
            raise TypeError("query filter entries must be key/value pairs")
        filters = tuple(sorted({
            (str(item[0]).strip(), str(item[1]).strip())
            for item in raw_filters if str(item[0]).strip() and str(item[1]).strip()
        }))
        if len({key for key, _ in filters}) != len(filters):
            raise ValueError("query interpretation filter names must be unique")
        object.__setattr__(self, "filters", filters)
        if isinstance(self.relation, str):
            object.__setattr__(self, "relation", KnowledgeRelation(self.relation))
        if not self.intents:
            raise ValueError("query interpretation requires an intent")
        if self.ambiguous and SearchIntent.AMBIGUOUS not in self.intents:
            raise ValueError("ambiguous interpretations require the ambiguous intent")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("query interpretations must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_query": self.raw_query,
            "normalized_query": self.normalized_query,
            "terms": list(self.terms),
            "intents": [item.value for item in self.intents],
            "concepts": list(self.concepts),
            "subject_terms": list(self.subject_terms),
            "relation": self.relation.value if self.relation is not None else None,
            "filters": {key: value for key, value in self.filters},
            "alternatives": list(self.alternatives),
            "unsupported_terms": list(self.unsupported_terms),
            "ambiguous": self.ambiguous,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> QueryInterpretation:
        raw_filters = value.get("filters")
        relation = value.get("relation")
        if raw_filters is not None and not isinstance(raw_filters, Mapping):
            raise TypeError("query filters must be an object")
        return cls(
            str(value.get("raw_query", "")),
            str(value.get("normalized_query", "")),
            _ordered_strings(value.get("terms"), "query terms"),
            tuple(SearchIntent(item) for item in _strings(
                value.get("intents"), "query intents",
            )),
            _strings(value.get("concepts"), "query concepts"),
            _strings(value.get("subject_terms"), "query subject terms"),
            KnowledgeRelation(str(relation)) if relation is not None else None,
            tuple((str(k), str(v)) for k, v in raw_filters.items()) if isinstance(raw_filters, Mapping) else (),
            _strings(value.get("alternatives"), "query alternatives"),
            _strings(value.get("unsupported_terms"), "query unsupported terms"),
            _strict_boolean(
                value.get("ambiguous"), "query ambiguity", default=False,
            ),
        )


@dataclass(frozen=True, order=True, slots=True)
class ScoreComponent:
    name: str
    value: float
    weight: float
    contribution: float
    available: bool = True
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("score component name must not be empty")
        if not isinstance(self.available, bool):
            raise TypeError("score component availability must be a boolean")
        for name in ("value", "weight", "contribution"):
            object.__setattr__(self, name, _finite_unit(getattr(self, name), f"score component {name}"))
        if not math.isclose(
            self.contribution,
            self.value * self.weight,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("score component contribution is inconsistent")
        object.__setattr__(
            self,
            "evidence_ids",
            _strings(self.evidence_ids, "score component evidence IDs"),
        )
        if not self.available and (
            self.weight != 0.0
            or self.contribution != 0.0
            or self.evidence_ids
        ):
            raise ValueError(
                "unavailable score components cannot contribute or reference evidence"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "available": self.available,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ScoreComponent:
        return cls(
            str(value.get("name", "")),
            _strict_number(value.get("value"), "score component value", default=0.0),
            _strict_number(value.get("weight"), "score component weight", default=0.0),
            _strict_number(
                value.get("contribution"),
                "score component contribution",
                default=0.0,
            ),
            _strict_boolean(
                value.get("available"),
                "score component availability",
                default=True,
            ),
            _strings(value.get("evidence_ids"), "score component evidence IDs"),
        )


@dataclass(frozen=True, order=True, slots=True)
class SearchCapability:
    name: str
    state: SearchCapabilityState
    coverage: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("search capability name must not be empty")
        if isinstance(self.state, str):
            object.__setattr__(self, "state", SearchCapabilityState(self.state))
        if self.coverage is not None:
            object.__setattr__(self, "coverage", _finite_unit(self.coverage, "capability coverage"))
        object.__setattr__(
            self, "limitations", _strings(self.limitations, "capability limitations")
        )
        if contains_absolute_path(self.to_dict()):
            raise ValueError("search capabilities must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "state": self.state.value, "coverage": self.coverage,
                "limitations": list(self.limitations)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SearchCapability:
        raw_coverage = value.get("coverage")
        return cls(str(value.get("name", "")), SearchCapabilityState(str(value.get("state", "unavailable"))),
                   _strict_number(raw_coverage, "capability coverage", default=0.0)
                   if raw_coverage is not None else None,
                   _strings(value.get("limitations"), "capability limitations"))


@dataclass(frozen=True, slots=True)
class StructuredSearchHit:
    canonical_subject_id: str
    display_name: str
    qualified_name: str
    kind: KnowledgeKind
    score: float
    score_components: tuple[ScoreComponent, ...]
    confidence: ConfidenceResult
    project: str | None = None
    module: str | None = None
    package: str | None = None
    language: str = "unknown"
    source_classifications: tuple[str, ...] = ()
    matched_concepts: tuple[str, ...] = ()
    capability_sources: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    risk: tuple[tuple[str, str], ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("canonical_subject_id", "display_name", "qualified_name", "language"):
            if not getattr(self, name).strip():
                raise ValueError(f"search hit {name} must not be empty")
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", KnowledgeKind(self.kind))
        object.__setattr__(self, "score", _finite_unit(self.score, "search hit score"))
        raw_components = _sequence(
            self.score_components, "search hit score components",
        )
        if any(not isinstance(item, ScoreComponent) for item in raw_components):
            raise TypeError("search hit score components must be ScoreComponent values")
        components = tuple(sorted(raw_components))
        if len({item.name for item in components}) != len(components):
            raise ValueError("search hit score component names must be unique")
        if not math.isclose(
            self.score,
            sum(item.contribution for item in components),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("search hit score is inconsistent with its components")
        object.__setattr__(self, "score_components", components)
        for name in (
            "source_classifications", "matched_concepts", "capability_sources",
            "evidence_ids", "relationships", "limitations",
        ):
            object.__setattr__(
                self, name, _strings(getattr(self, name), f"search hit {name}")
            )
        risk = tuple(sorted((str(k), str(v)) for k, v in self.risk))
        if len({key for key, _ in risk}) != len(risk):
            raise ValueError("search hit risk attribute names must be unique")
        object.__setattr__(self, "risk", risk)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("semantic search hits must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_subject_id": self.canonical_subject_id,
            "display_name": self.display_name,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "project": self.project,
            "module": self.module,
            "package": self.package,
            "language": self.language,
            "source_classifications": list(self.source_classifications),
            "score": self.score,
            "score_components": [item.to_dict() for item in self.score_components],
            "matched_concepts": list(self.matched_concepts),
            "capability_sources": list(self.capability_sources),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence.to_dict(),
            "relationships": list(self.relationships),
            "risk": {key: value for key, value in self.risk},
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> StructuredSearchHit:
        raw_confidence = value.get("confidence")
        raw_risk = value.get("risk")
        if not isinstance(raw_confidence, Mapping):
            raise TypeError("search hit confidence must be an object")
        if raw_risk is not None and not isinstance(raw_risk, Mapping):
            raise TypeError("search hit risk must be an object")
        return cls(
            str(value.get("canonical_subject_id", "")), str(value.get("display_name", "")),
            str(value.get("qualified_name", "")), KnowledgeKind(str(value.get("kind", "symbol"))),
            _strict_number(value.get("score"), "search hit score", default=0.0),
            tuple(ScoreComponent.from_dict(item) for item in _mapping_items(
                value.get("score_components"), "search hit score components",
            )),
            _validated_confidence(raw_confidence),
            str(value["project"]) if value.get("project") is not None else None,
            str(value["module"]) if value.get("module") is not None else None,
            str(value["package"]) if value.get("package") is not None else None,
            str(value.get("language", "unknown")),
            _strings(value.get("source_classifications"), "search hit source classifications"),
            _strings(value.get("matched_concepts"), "search hit matched concepts"),
            _strings(value.get("capability_sources"), "search hit capability sources"),
            _strings(value.get("evidence_ids"), "search hit evidence IDs"),
            _strings(value.get("relationships"), "search hit relationships"),
            tuple((str(k), str(v)) for k, v in raw_risk.items()) if isinstance(raw_risk, Mapping) else (),
            _strings(value.get("limitations"), "search hit limitations"),
        )


@dataclass(frozen=True, slots=True)
class SemanticSearchResponse:
    request: SemanticSearchRequest
    interpretation: QueryInterpretation
    hits: tuple[StructuredSearchHit, ...]
    total_candidate_count: int
    omitted_count: int
    capabilities: tuple[SearchCapability, ...]
    index_id: str
    evidence_index: EvidenceIndex = field(default_factory=lambda: EvidenceIndex().freeze())
    limitations: tuple[str, ...] = ()
    producer: str = "atlas-pr135/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.request, SemanticSearchRequest):
            raise TypeError("search response request must be a SemanticSearchRequest")
        if not isinstance(self.interpretation, QueryInterpretation):
            raise TypeError("search response interpretation must be a QueryInterpretation")
        hits = tuple(self.hits)
        if any(not isinstance(item, StructuredSearchHit) for item in hits):
            raise TypeError("search response hits must be StructuredSearchHit values")
        if len({item.canonical_subject_id for item in hits}) != len(hits):
            raise ValueError("search response canonical subject IDs must be unique")
        object.__setattr__(self, "hits", hits)
        for name in ("total_candidate_count", "omitted_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"search response {name} must be non-negative")
        if self.total_candidate_count < len(self.hits):
            raise ValueError("search response candidate count is inconsistent")
        if self.omitted_count != self.total_candidate_count - len(self.hits):
            raise ValueError("search response omitted count is inconsistent")
        raw_capabilities = _sequence(
            self.capabilities, "search response capabilities",
        )
        if any(not isinstance(item, SearchCapability) for item in raw_capabilities):
            raise TypeError("search response capabilities must be SearchCapability values")
        capabilities = tuple(sorted(raw_capabilities, key=lambda item: item.name))
        if len({item.name for item in capabilities}) != len(capabilities):
            raise ValueError("search response capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("search response evidence index must be an EvidenceIndex")
        object.__setattr__(self, "evidence_index", self.evidence_index.freeze())
        available_evidence = {
            record.evidence_id for record in self.evidence_index.records
        }
        missing_evidence = {
            evidence_id
            for hit in self.hits
            for evidence_id in hit.evidence_ids
            if evidence_id not in available_evidence
        }
        if missing_evidence:
            raise ValueError("search response contains unresolvable evidence IDs")
        component_evidence = {
            evidence_id
            for hit in self.hits
            for component in hit.score_components
            for evidence_id in component.evidence_ids
        }
        hit_evidence = {
            evidence_id for hit in self.hits for evidence_id in hit.evidence_ids
        }
        if component_evidence.difference(available_evidence):
            raise ValueError(
                "search response score components contain unresolvable evidence IDs"
            )
        if component_evidence != hit_evidence:
            raise ValueError(
                "search response hit and score-component evidence IDs are inconsistent"
            )
        object.__setattr__(
            self,
            "limitations",
            _strings(self.limitations, "search response limitations"),
        )
        if (
            not self.index_id.strip()
            or not self.producer.strip()
            or isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("invalid semantic search response identity")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("semantic search responses must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "index_id": self.index_id,
            "request": self.request.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "hits": [item.to_dict() for item in self.hits],
            "total_candidate_count": self.total_candidate_count,
            "returned_count": len(self.hits),
            "omitted_count": self.omitted_count,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SemanticSearchResponse:
        request = value.get("request")
        interpretation = value.get("interpretation")
        if not isinstance(request, Mapping) or not isinstance(interpretation, Mapping):
            raise TypeError("semantic search response request and interpretation must be objects")
        hits = tuple(StructuredSearchHit.from_dict(item) for item in _mapping_items(
            value.get("hits"), "semantic search hits",
        ))
        raw_evidence = value.get("evidence_index", {})
        if not isinstance(raw_evidence, Mapping):
            raise TypeError("semantic search response evidence index must be an object")
        raw_returned = value.get("returned_count")
        returned = _strict_integer(
            raw_returned, "semantic search returned count", default=len(hits),
        )
        if returned != len(hits):
            raise ValueError("semantic search returned count is inconsistent")
        return cls(
            SemanticSearchRequest.from_dict(request), QueryInterpretation.from_dict(interpretation), hits,
            _strict_integer(
                value.get("total_candidate_count"),
                "semantic search candidate count",
                default=0,
            ),
            _strict_integer(
                value.get("omitted_count"),
                "semantic search omitted count",
                default=0,
            ),
            tuple(SearchCapability.from_dict(item) for item in _mapping_items(
                value.get("capabilities"), "semantic search capabilities",
            )),
            str(value.get("index_id", "")), _validated_evidence_index(raw_evidence),
            _strings(value.get("limitations"), "semantic search limitations"),
            str(value.get("producer", "atlas-pr135/1")),
            _strict_integer(
                value.get("schema_version"),
                "semantic search schema version",
                default=1,
            ),
        )
