"""Immutable, source-safe contracts for deterministic engineering answers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json


ENGINEERING_ANSWER_PRODUCER = "atlas-pr167/1"
ENGINEERING_ANSWER_SCHEMA_VERSION = 1


def _text(value: object, label: str, maximum: int = 4_096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} is empty or oversized")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{label} contains control characters")
    return normalized


def _strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    return tuple(sorted(set(_text(item, label) for item in values)))


def _count(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, order=True, slots=True)
class EngineeringAnswerSubject:
    canonical_id: str
    qualified_name: str
    kind: str
    project: str
    source_classification: str
    source_ref: str

    def __post_init__(self) -> None:
        for name in (
            "canonical_id",
            "qualified_name",
            "kind",
            "project",
            "source_classification",
            "source_ref",
        ):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"answer subject {name}",
            ))

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "project": self.project,
            "source_classification": self.source_classification,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, order=True, slots=True)
class EngineeringAnswerItem:
    canonical_reference: str
    category: str
    confidence: str
    source_ref: str
    evidence_ids: tuple[str, ...]
    canonical_source: str | None = None
    canonical_target: str | None = None
    relationship_kind: str | None = None
    depth: int | None = None
    total_candidate_count: int = 0
    candidate_target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "canonical_reference", "category", "confidence", "source_ref",
        ):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"answer item {name}",
            ))
        for name in (
            "canonical_source", "canonical_target", "relationship_kind",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(
                    value, f"answer item {name}",
                ))
        if self.depth is not None:
            if (
                isinstance(self.depth, bool)
                or not isinstance(self.depth, int)
                or self.depth < 1
            ):
                raise ValueError("answer item depth must be positive")
        total_candidates = _count(
            self.total_candidate_count, "answer item candidate total",
        )
        candidates = _strings(
            self.candidate_target_ids, "answer item candidate target",
        )
        if total_candidates < len(candidates):
            raise ValueError("answer item candidate counts are inconsistent")
        evidence_ids = _strings(self.evidence_ids, "answer item evidence ID")
        if not evidence_ids:
            raise ValueError("answer items require authoritative evidence")
        object.__setattr__(self, "candidate_target_ids", candidates)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    @property
    def omitted_candidate_count(self) -> int:
        return self.total_candidate_count - len(self.candidate_target_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_reference": self.canonical_reference,
            "category": self.category,
            "confidence": self.confidence,
            "source_ref": self.source_ref,
            "evidence_ids": list(self.evidence_ids),
            "canonical_source": self.canonical_source,
            "canonical_target": self.canonical_target,
            "relationship_kind": self.relationship_kind,
            "depth": self.depth,
            "total_candidate_count": self.total_candidate_count,
            "included_candidate_count": len(self.candidate_target_ids),
            "omitted_candidate_count": self.omitted_candidate_count,
            "candidate_target_ids": list(self.candidate_target_ids),
        }


@dataclass(frozen=True, slots=True)
class EngineeringAnswerSection:
    section_id: str
    total_count: int
    items: tuple[EngineeringAnswerItem, ...] = ()
    candidate_projection_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _text(
            self.section_id, "answer section ID", 128,
        ))
        total = _count(self.total_count, "answer section total")
        candidates = _count(
            self.candidate_projection_count,
            "answer section candidate projection total",
        )
        items = tuple(self.items)
        if any(not isinstance(item, EngineeringAnswerItem) for item in items):
            raise TypeError("answer section contains an invalid item")
        if total < len(items):
            raise ValueError("answer section counts are inconsistent")
        included_candidates = sum(
            len(item.candidate_target_ids) for item in items
        )
        if candidates < included_candidates:
            raise ValueError("answer section candidate counts are inconsistent")
        object.__setattr__(self, "items", items)

    @property
    def included_count(self) -> int:
        return len(self.items)

    @property
    def omitted_count(self) -> int:
        return self.total_count - self.included_count

    @property
    def included_candidate_count(self) -> int:
        return sum(len(item.candidate_target_ids) for item in self.items)

    @property
    def omitted_candidate_count(self) -> int:
        return self.candidate_projection_count - self.included_candidate_count

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "total_count": self.total_count,
            "included_count": self.included_count,
            "omitted_count": self.omitted_count,
            "candidate_projection_count": self.candidate_projection_count,
            "included_candidate_count": self.included_candidate_count,
            "omitted_candidate_count": self.omitted_candidate_count,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class EngineeringTraversalSummary:
    direction: str
    configured_max_depth: int
    configured_max_nodes: int
    visited_node_count: int
    visited_edge_count: int
    depth_histogram: tuple[tuple[int, int], ...]
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", _text(
            self.direction, "answer traversal direction", 64,
        ))
        if self.configured_max_depth < 1 or self.configured_max_nodes < 1:
            raise ValueError("answer traversal bounds must be positive")
        _count(self.visited_node_count, "answer traversal visited nodes")
        _count(self.visited_edge_count, "answer traversal visited edges")
        histogram = tuple(sorted(self.depth_histogram))
        if any(depth < 1 or count < 1 for depth, count in histogram):
            raise ValueError("answer traversal histogram is invalid")
        if not isinstance(self.truncated, bool):
            raise TypeError("answer traversal truncation must be a boolean")
        object.__setattr__(self, "depth_histogram", histogram)

    def to_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction,
            "canonical_direction": "caller_to_callee",
            "configured_max_depth": self.configured_max_depth,
            "configured_max_nodes": self.configured_max_nodes,
            "visited_node_count": self.visited_node_count,
            "visited_edge_count": self.visited_edge_count,
            "depth_histogram": {
                str(depth): count for depth, count in self.depth_histogram
            },
            "truncated": self.truncated,
        }


@dataclass(frozen=True, order=True, slots=True)
class EngineeringInspectItem:
    priority: int
    reason: str
    canonical_reference: str
    source_ref: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority < 1
        ):
            raise ValueError("inspect-first priority must be positive")
        for name in ("reason", "canonical_reference", "source_ref"):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"inspect-first {name}",
            ))
        evidence_ids = _strings(
            self.evidence_ids, "inspect-first evidence ID",
        )
        if not evidence_ids:
            raise ValueError("inspect-first items require evidence")
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "priority": self.priority,
            "reason": self.reason,
            "canonical_reference": self.canonical_reference,
            "source_ref": self.source_ref,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class EngineeringAnswerTraceability:
    snapshot_id: str
    code_impact_fingerprint: str
    callable_index_fingerprint: str
    code_graph_fingerprint: str
    test_evidence_fingerprint: str
    reachability_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id", "code_impact_fingerprint",
            "callable_index_fingerprint", "code_graph_fingerprint",
            "test_evidence_fingerprint",
        ):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"answer traceability {name}", 512,
            ))
        if self.reachability_fingerprint is not None:
            object.__setattr__(self, "reachability_fingerprint", _text(
                self.reachability_fingerprint,
                "answer traceability reachability fingerprint", 512,
            ))

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "code_impact_fingerprint": self.code_impact_fingerprint,
            "callable_index_fingerprint": self.callable_index_fingerprint,
            "code_graph_fingerprint": self.code_graph_fingerprint,
            "test_evidence_fingerprint": self.test_evidence_fingerprint,
            "reachability_fingerprint": self.reachability_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class EngineeringAnswer:
    subject: EngineeringAnswerSubject
    change_risk_summary: tuple[str, ...]
    direct_callers_high_confidence: EngineeringAnswerSection
    direct_caller_conservative_sites: EngineeringAnswerSection
    direct_caller_method_references: EngineeringAnswerSection
    upstream_direct: EngineeringAnswerSection
    upstream_transitive: EngineeringAnswerSection
    direct_callees_high_confidence: EngineeringAnswerSection
    direct_callee_conservative_sites: EngineeringAnswerSection
    direct_callee_method_references: EngineeringAnswerSection
    direct_test_callers: EngineeringAnswerSection
    high_confidence_test_paths: EngineeringAnswerSection
    possible_test_paths: EngineeringAnswerSection
    uncertainty: tuple[EngineeringAnswerSection, ...]
    traversal: EngineeringTraversalSummary
    inspect_first: tuple[EngineeringInspectItem, ...]
    limitations: tuple[str, ...]
    traceability: EngineeringAnswerTraceability
    producer_version: str = ENGINEERING_ANSWER_PRODUCER
    schema_version: int = ENGINEERING_ANSWER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.subject, EngineeringAnswerSubject):
            raise TypeError("engineering answer subject is invalid")
        summaries = tuple(_text(
            item, "change-risk summary", 1_024,
        ) for item in self.change_risk_summary)
        if not summaries:
            raise ValueError("engineering answer requires a change-risk summary")
        object.__setattr__(self, "change_risk_summary", summaries)
        sections = (
            self.direct_callers_high_confidence,
            self.direct_caller_conservative_sites,
            self.direct_caller_method_references,
            self.upstream_direct,
            self.upstream_transitive,
            self.direct_callees_high_confidence,
            self.direct_callee_conservative_sites,
            self.direct_callee_method_references,
            self.direct_test_callers,
            self.high_confidence_test_paths,
            self.possible_test_paths,
            *self.uncertainty,
        )
        if any(not isinstance(item, EngineeringAnswerSection) for item in sections):
            raise TypeError("engineering answer section is invalid")
        if len({item.section_id for item in self.uncertainty}) != len(self.uncertainty):
            raise ValueError("engineering answer uncertainty categories must be unique")
        if not isinstance(self.traversal, EngineeringTraversalSummary):
            raise TypeError("engineering answer traversal is invalid")
        inspect = tuple(sorted(self.inspect_first))
        if len({item.priority for item in inspect}) != len(inspect):
            raise ValueError("inspect-first priorities must be unique")
        object.__setattr__(self, "inspect_first", inspect)
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "engineering answer limitation",
        ))
        if not isinstance(self.traceability, EngineeringAnswerTraceability):
            raise TypeError("engineering answer traceability is invalid")
        if (
            self.producer_version != ENGINEERING_ANSWER_PRODUCER
            or self.schema_version != ENGINEERING_ANSWER_SCHEMA_VERSION
        ):
            raise ValueError("unsupported engineering-answer schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "section_priority": [
                "subject_identity",
                "upstream_direct_count",
                "upstream_transitive_count",
                "direct_callers",
                "represented_test_summary",
                "direct_callees",
                "conservative_call_groups",
                "uncertainty",
                "representative_paths",
            ],
            "subject": self.subject.to_dict(),
            "change_risk_summary": list(self.change_risk_summary),
            "direct_callers": {
                "high_confidence": self.direct_callers_high_confidence.to_dict(),
                "conservative_call_sites": self.direct_caller_conservative_sites.to_dict(),
                "method_references": self.direct_caller_method_references.to_dict(),
            },
            "upstream_change_impact": {
                "direct": self.upstream_direct.to_dict(),
                "transitive": self.upstream_transitive.to_dict(),
                "traversal": self.traversal.to_dict(),
            },
            "direct_dependencies": {
                "high_confidence": self.direct_callees_high_confidence.to_dict(),
                "conservative_call_sites": self.direct_callee_conservative_sites.to_dict(),
                "method_references": self.direct_callee_method_references.to_dict(),
            },
            "represented_test_signal": {
                "direct_test_callers": self.direct_test_callers.to_dict(),
                "high_confidence_paths": self.high_confidence_test_paths.to_dict(),
                "possible_paths": self.possible_test_paths.to_dict(),
                "runtime_test_coverage_proven": False,
                "absence_proves_untested": False,
            },
            "uncertainty": [item.to_dict() for item in self.uncertainty],
            "inspect_first": [item.to_dict() for item in self.inspect_first],
            "limitations": list(self.limitations),
            "traceability": self.traceability.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True,
        )
    @property
    def deterministic_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EngineeringAnswerSynthesis:
    query: str
    resolution_status: str
    snapshot_id: str
    answer: EngineeringAnswer | None = None
    candidates: tuple[EngineeringAnswerSubject, ...] = ()
    total_candidate_count: int = 0
    omitted_candidate_count: int = 0
    limitations: tuple[str, ...] = ()
    producer_version: str = ENGINEERING_ANSWER_PRODUCER
    schema_version: int = ENGINEERING_ANSWER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("query", "resolution_status", "snapshot_id"):
            object.__setattr__(self, name, _text(
                getattr(self, name), f"engineering synthesis {name}", 512,
            ))
        candidates = tuple(sorted(
            self.candidates, key=lambda item: item.canonical_id,
        ))
        if any(not isinstance(item, EngineeringAnswerSubject) for item in candidates):
            raise TypeError("engineering synthesis candidate is invalid")
        total = _count(
            self.total_candidate_count, "engineering synthesis candidate total",
        )
        omitted = _count(
            self.omitted_candidate_count,
            "engineering synthesis omitted candidate count",
        )
        if total != len(candidates) + omitted:
            raise ValueError("engineering synthesis candidate counts are inconsistent")
        if self.resolution_status == "resolved":
            if self.answer is None or candidates or total or omitted:
                raise ValueError("resolved engineering synthesis is inconsistent")
        elif self.answer is not None:
            raise ValueError("unresolved engineering synthesis cannot contain an answer")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "engineering synthesis limitation",
        ))
        if (
            self.producer_version != ENGINEERING_ANSWER_PRODUCER
            or self.schema_version != ENGINEERING_ANSWER_SCHEMA_VERSION
        ):
            raise ValueError("unsupported engineering synthesis schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "query": self.query,
            "resolution_status": self.resolution_status,
            "snapshot_id": self.snapshot_id,
            "answer": self.answer.to_dict() if self.answer is not None else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "total_candidate_count": self.total_candidate_count,
            "omitted_candidate_count": self.omitted_candidate_count,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True,
        )
