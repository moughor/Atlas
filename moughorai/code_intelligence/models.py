"""Immutable user-facing contracts for represented Java code intelligence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    InvocationKind,
)
from moughorai.java_code_intelligence.code_graph import CodeGraphEdgeKind
from moughorai.java_code_intelligence.models import (
    CallableKind,
    SourceClassification,
    SourceRange,
)


CODE_INTELLIGENCE_PRODUCER = "atlas-pr159/1"
CODE_INTELLIGENCE_SCHEMA_VERSION = 1


class CodeIntelligenceAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CodeSubjectResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class CodePathConfidence(str, Enum):
    HIGH_CONFIDENCE_REPRESENTED_PATH = "high_confidence_represented_path"
    CONSERVATIVE_REPRESENTED_PATH = "conservative_represented_path"
    METHOD_REFERENCE_ONLY = "method_reference_only"


class CodeRelationshipRole(str, Enum):
    CALLER_OF_SUBJECT = "caller_of_subject"
    CALLEE_OF_SUBJECT = "callee_of_subject"
    TEST_CALLER_OF_SUBJECT = "test_caller_of_subject"
    UPSTREAM_CONSUMER_OF_SUBJECT = "upstream_consumer_of_subject"
    TEST_REACHES_SUBJECT = "test_reaches_subject"


class CodeTraversalDirection(str, Enum):
    REVERSE_UPSTREAM = "reverse_upstream"
    FORWARD_TEST_REACHABILITY = "forward_test_reachability"


_HIGH_CONFIDENCE_KINDS = frozenset({
    CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
    CodeGraphEdgeKind.CONSTRUCTOR_CALL,
})
_CONSERVATIVE_KINDS = frozenset({
    CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
    CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
})


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


def _non_negative(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, order=True, slots=True)
class CodeSourceReference:
    path: str
    source_range: SourceRange

    def __post_init__(self) -> None:
        path = _text(self.path, "source path", 2_048)
        if "\\" in path or path.startswith("/") or ":" in path.split("/", 1)[0]:
            raise ValueError("code-intelligence source paths must be workspace-relative")
        if any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError("code-intelligence source path is invalid")
        if not isinstance(self.source_range, SourceRange):
            raise TypeError("code-intelligence source range is invalid")
        object.__setattr__(self, "path", path)

    @property
    def compact(self) -> str:
        start = self.source_range.start
        end = self.source_range.end
        return (
            f"{self.path}#L{start.line}C{start.column}"
            f"-L{end.line}C{end.column}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "range": self.source_range.to_dict(),
            "source_ref": self.compact,
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeSubject:
    canonical_id: str
    project: str
    kind: CallableKind
    owner_type: str
    name: str
    normalized_key: str
    source_classification: SourceClassification
    source: CodeSourceReference
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_id", _text(
            self.canonical_id, "callable canonical ID", 256,
        ))
        object.__setattr__(self, "project", _text(self.project, "project", 256))
        if not isinstance(self.kind, CallableKind):
            raise TypeError("code subject kind must be method or constructor")
        object.__setattr__(self, "owner_type", _text(
            self.owner_type, "callable owner", 1_024,
        ))
        object.__setattr__(self, "name", _text(self.name, "callable name", 256))
        object.__setattr__(self, "normalized_key", _text(
            self.normalized_key, "callable normalized key",
        ))
        if not isinstance(self.source_classification, SourceClassification):
            raise TypeError("code subject source classification is invalid")
        if not isinstance(self.source, CodeSourceReference):
            raise TypeError("code subject source reference is invalid")
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "code subject limitation",
        ))

    @property
    def display_name(self) -> str:
        return f"{self.owner_type}#{self.name}"

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "project": self.project,
            "kind": self.kind.value,
            "owner_type": self.owner_type,
            "name": self.name,
            "display_name": self.display_name,
            "normalized_key": self.normalized_key,
            "source_classification": self.source_classification.value,
            "source": self.source.to_dict(),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class CodeSubjectResolution:
    status: CodeSubjectResolutionStatus
    query: str
    subject: CodeSubject | None = None
    candidates: tuple[CodeSubject, ...] = ()
    total_candidate_count: int = 0
    omitted_candidate_count: int = 0
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, CodeSubjectResolutionStatus):
            raise TypeError("code subject resolution status is invalid")
        object.__setattr__(self, "query", _text(self.query, "code subject query"))
        candidates = tuple(sorted(self.candidates, key=lambda item: item.canonical_id))
        if any(not isinstance(item, CodeSubject) for item in candidates):
            raise TypeError("code subject candidates are invalid")
        total = _non_negative(self.total_candidate_count, "candidate total")
        omitted = _non_negative(self.omitted_candidate_count, "omitted candidates")
        if total != len(candidates) + omitted:
            raise ValueError("code subject candidate counts are inconsistent")
        if self.status is CodeSubjectResolutionStatus.RESOLVED:
            if self.subject is None or candidates or total or omitted:
                raise ValueError("resolved code subject coverage is inconsistent")
        elif self.subject is not None:
            raise ValueError("unresolved code subject cannot contain a subject")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "code subject resolution limitation",
        ))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "query": self.query,
            "subject": self.subject.to_dict() if self.subject is not None else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "total_candidate_count": self.total_candidate_count,
            "omitted_candidate_count": self.omitted_candidate_count,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeCallRelationship:
    canonical_source: str
    canonical_target: str
    subject_relative_role: CodeRelationshipRole
    edge_kind: CodeGraphEdgeKind
    producer_evidence_id: str
    project: str
    location: CodeSourceReference
    confidence: CodePathConfidence
    limitations: tuple[str, ...] = ()
    relation: str = "calls"

    def __post_init__(self) -> None:
        source = _text(self.canonical_source, "canonical caller", 256)
        target = _text(self.canonical_target, "canonical callee", 256)
        if not isinstance(self.subject_relative_role, CodeRelationshipRole):
            raise TypeError("call relationship role is invalid")
        if not isinstance(self.edge_kind, CodeGraphEdgeKind):
            raise TypeError("call edge kind is invalid")
        evidence = _text(self.producer_evidence_id, "call evidence ID", 96)
        if not evidence.startswith("evidence:") or len(evidence) != 73:
            raise ValueError("call evidence ID is malformed")
        if self.relation != "calls":
            raise ValueError("canonical Java code relationship must be calls")
        expected_confidence = (
            CodePathConfidence.METHOD_REFERENCE_ONLY
            if self.edge_kind is CodeGraphEdgeKind.METHOD_REFERENCE
            else CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            if self.edge_kind in _HIGH_CONFIDENCE_KINDS
            else CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
        )
        if self.confidence is not expected_confidence:
            raise ValueError("call relationship confidence conflicts with edge kind")
        if self.edge_kind not in (
            *_HIGH_CONFIDENCE_KINDS,
            *_CONSERVATIVE_KINDS,
            CodeGraphEdgeKind.METHOD_REFERENCE,
        ):
            raise ValueError("unsupported call relationship edge kind")
        object.__setattr__(self, "canonical_source", source)
        object.__setattr__(self, "canonical_target", target)
        object.__setattr__(self, "producer_evidence_id", evidence)
        object.__setattr__(self, "project", _text(self.project, "call project", 256))
        if not isinstance(self.location, CodeSourceReference):
            raise TypeError("call relationship location is invalid")
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "call relationship limitation",
        ))

    @property
    def execution_eligible(self) -> bool:
        return self.edge_kind is not CodeGraphEdgeKind.METHOD_REFERENCE

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_source": self.canonical_source,
            "canonical_target": self.canonical_target,
            "relation": self.relation,
            "subject_relative_role": self.subject_relative_role.value,
            "edge_kind": self.edge_kind.value,
            "producer_evidence_id": self.producer_evidence_id,
            "project": self.project,
            "location": self.location.to_dict(),
            "confidence": self.confidence.value,
            "execution_eligible": self.execution_eligible,
            "runtime_invocation_proven": False,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class BoundedRelationships:
    total_count: int
    items: tuple[CodeCallRelationship, ...] = ()

    def __post_init__(self) -> None:
        total = _non_negative(self.total_count, "relationship total")
        items = tuple(sorted(self.items))
        if any(not isinstance(item, CodeCallRelationship) for item in items):
            raise TypeError("bounded relationships contain invalid items")
        if total < len(items):
            raise ValueError("bounded relationship total is inconsistent")
        object.__setattr__(self, "items", items)

    @property
    def omitted_count(self) -> int:
        return self.total_count - len(self.items)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_count": self.total_count,
            "included_count": len(self.items),
            "omitted_count": self.omitted_count,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class AmbiguousCallGroup:
    """Bounded developer presentation for one conservative source call site."""

    canonical_source: str
    project: str
    location: CodeSourceReference
    producer_evidence_id: str
    invocation_kind: InvocationKind
    resolution_state: CallResolutionState
    subject_relative_role: CodeRelationshipRole
    confidence: CodePathConfidence
    edge_kinds: tuple[CodeGraphEdgeKind, ...]
    total_candidate_count: int
    included_candidate_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    relation: str = "calls"

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_source", _text(
            self.canonical_source, "ambiguous call caller", 256,
        ))
        object.__setattr__(self, "project", _text(
            self.project, "ambiguous call project", 256,
        ))
        if not isinstance(self.location, CodeSourceReference):
            raise TypeError("ambiguous call source reference is invalid")
        evidence = _text(
            self.producer_evidence_id, "ambiguous call evidence ID", 96,
        )
        if not evidence.startswith("evidence:") or len(evidence) != 73:
            raise ValueError("ambiguous call evidence ID is malformed")
        if not isinstance(self.invocation_kind, InvocationKind):
            raise TypeError("ambiguous call invocation kind is invalid")
        if self.invocation_kind is InvocationKind.METHOD_REFERENCE:
            raise ValueError("method references cannot be ambiguous execution groups")
        if self.resolution_state not in {
            CallResolutionState.AMBIGUOUS,
            CallResolutionState.POLYMORPHIC,
        }:
            raise ValueError("ambiguous call group requires a conservative state")
        if self.subject_relative_role not in {
            CodeRelationshipRole.CALLER_OF_SUBJECT,
            CodeRelationshipRole.CALLEE_OF_SUBJECT,
        }:
            raise ValueError("ambiguous call group requires a direct relationship role")
        if self.confidence is not CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH:
            raise ValueError("ambiguous call group confidence must remain conservative")
        edge_kinds = tuple(sorted(set(self.edge_kinds), key=lambda item: item.value))
        if not edge_kinds or any(
            item not in _CONSERVATIVE_KINDS for item in edge_kinds
        ):
            raise ValueError("ambiguous call group edge kinds must remain conservative")
        total = _non_negative(self.total_candidate_count, "candidate projection total")
        candidates = _strings(
            self.included_candidate_ids, "included candidate target",
        )
        if total < len(candidates):
            raise ValueError("ambiguous call candidate counts are inconsistent")
        if self.relation != "calls":
            raise ValueError("canonical Java code relationship must be calls")
        object.__setattr__(self, "producer_evidence_id", evidence)
        object.__setattr__(self, "edge_kinds", edge_kinds)
        object.__setattr__(self, "included_candidate_ids", candidates)
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "ambiguous call limitation",
        ))

    @property
    def included_candidate_count(self) -> int:
        return len(self.included_candidate_ids)

    @property
    def omitted_candidate_count(self) -> int:
        return self.total_candidate_count - self.included_candidate_count

    @property
    def canonical_direction(self) -> str:
        return "caller_to_callee"

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.location.compact,
            self.canonical_source,
            self.producer_evidence_id,
            self.invocation_kind.value,
            self.resolution_state.value,
            self.subject_relative_role.value,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_source": self.canonical_source,
            "project": self.project,
            "canonical_direction": self.canonical_direction,
            "relation": self.relation,
            "subject_relative_role": self.subject_relative_role.value,
            "source_ref": self.location.compact,
            "producer_evidence_id": self.producer_evidence_id,
            "invocation_kind": self.invocation_kind.value,
            "resolution_state": self.resolution_state.value,
            "confidence": self.confidence.value,
            "edge_kinds": [item.value for item in self.edge_kinds],
            "total_candidate_count": self.total_candidate_count,
            "included_candidate_count": self.included_candidate_count,
            "omitted_candidate_count": self.omitted_candidate_count,
            "included_candidate_ids": list(self.included_candidate_ids),
            "limitations": list(self.limitations),
            "runtime_invocation_proven": False,
        }


@dataclass(frozen=True, slots=True)
class BoundedAmbiguousCallGroups:
    call_site_count: int
    candidate_projection_count: int
    items: tuple[AmbiguousCallGroup, ...] = ()

    def __post_init__(self) -> None:
        call_sites = _non_negative(self.call_site_count, "conservative call-site total")
        projections = _non_negative(
            self.candidate_projection_count, "candidate projection total",
        )
        raw_items = tuple(self.items)
        if any(not isinstance(item, AmbiguousCallGroup) for item in raw_items):
            raise TypeError("bounded ambiguous calls contain invalid groups")
        items = tuple(sorted(raw_items, key=lambda item: item.sort_key))
        if call_sites < len(items):
            raise ValueError("bounded ambiguous call-site total is inconsistent")
        if projections < sum(item.total_candidate_count for item in items):
            raise ValueError("bounded candidate projection total is inconsistent")
        object.__setattr__(self, "items", items)

    @property
    def omitted_call_site_count(self) -> int:
        return self.call_site_count - len(self.items)

    @property
    def included_candidate_count(self) -> int:
        return sum(item.included_candidate_count for item in self.items)

    @property
    def omitted_candidate_count(self) -> int:
        return self.candidate_projection_count - self.included_candidate_count

    def to_dict(self) -> dict[str, object]:
        return {
            "call_site_count": self.call_site_count,
            "included_call_site_count": len(self.items),
            "omitted_call_site_count": self.omitted_call_site_count,
            "candidate_projection_count": self.candidate_projection_count,
            "included_candidate_count": self.included_candidate_count,
            "omitted_candidate_count": self.omitted_candidate_count,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeImpactPath:
    consumer_subject_id: str
    subject_id: str
    depth: int
    confidence: CodePathConfidence
    steps: tuple[CodeCallRelationship, ...]
    traversal_direction: CodeTraversalDirection
    root_evidence_id: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        consumer = _text(self.consumer_subject_id, "path consumer", 256)
        subject = _text(self.subject_id, "path subject", 256)
        depth = _non_negative(self.depth, "path depth")
        steps = tuple(self.steps)
        if any(not isinstance(item, CodeCallRelationship) for item in steps):
            raise TypeError("code path steps are invalid")
        if depth != len(steps):
            raise ValueError("code path depth is inconsistent")
        if steps:
            if steps[0].canonical_source != consumer:
                raise ValueError("code path does not start at its consumer")
            if steps[-1].canonical_target != subject:
                raise ValueError("code path does not end at its subject")
            if any(
                left.canonical_target != right.canonical_source
                for left, right in zip(steps, steps[1:])
            ):
                raise ValueError("code path steps are not contiguous")
            expected = (
                CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
                if any(
                    item.confidence
                    is CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
                    for item in steps
                )
                else CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            )
            if self.confidence is not expected:
                raise ValueError("code path confidence propagation is inconsistent")
        elif consumer != subject:
            raise ValueError("zero-length path must start at the subject")
        if self.confidence is CodePathConfidence.METHOD_REFERENCE_ONLY:
            raise ValueError("method references cannot form execution impact paths")
        if not isinstance(self.traversal_direction, CodeTraversalDirection):
            raise TypeError("code path traversal direction is invalid")
        root_evidence = self.root_evidence_id
        if root_evidence is not None:
            root_evidence = _text(root_evidence, "TEST root evidence ID", 96)
            if not root_evidence.startswith("evidence:"):
                raise ValueError("TEST root evidence ID is malformed")
        object.__setattr__(self, "consumer_subject_id", consumer)
        object.__setattr__(self, "subject_id", subject)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "root_evidence_id", root_evidence)
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "code path limitation",
        ))

    @property
    def producer_evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            *(item.producer_evidence_id for item in self.steps),
            *((self.root_evidence_id,) if self.root_evidence_id else ()),
        }))

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer_subject_id": self.consumer_subject_id,
            "subject_id": self.subject_id,
            "depth": self.depth,
            "confidence": self.confidence.value,
            "traversal_direction": self.traversal_direction.value,
            "canonical_direction": "caller_to_callee",
            "canonical_relation": "calls",
            "steps": [item.to_dict() for item in self.steps],
            "root_evidence_id": self.root_evidence_id,
            "producer_evidence_ids": list(self.producer_evidence_ids),
            "runtime_execution_proven": False,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class BoundedPaths:
    total_count: int
    items: tuple[CodeImpactPath, ...] = ()

    def __post_init__(self) -> None:
        total = _non_negative(self.total_count, "path total")
        items = tuple(sorted(
            self.items,
            key=lambda item: (
                item.depth,
                0 if item.confidence
                is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
                else 1,
                item.consumer_subject_id,
                item.producer_evidence_ids,
            ),
        ))
        if any(not isinstance(item, CodeImpactPath) for item in items):
            raise TypeError("bounded paths contain invalid items")
        if total < len(items):
            raise ValueError("bounded path total is inconsistent")
        object.__setattr__(self, "items", items)

    @property
    def omitted_count(self) -> int:
        return self.total_count - len(self.items)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_count": self.total_count,
            "included_count": len(self.items),
            "omitted_count": self.omitted_count,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeSiteEvidence:
    category: str
    caller_subject_id: str
    producer_evidence_id: str
    location: CodeSourceReference
    invocation_kind: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _text(
            self.category, "limitation category", 96,
        ))
        object.__setattr__(self, "caller_subject_id", _text(
            self.caller_subject_id, "limitation caller", 256,
        ))
        evidence = _text(self.producer_evidence_id, "limitation evidence", 96)
        if not evidence.startswith("evidence:"):
            raise ValueError("limitation evidence ID is malformed")
        object.__setattr__(self, "producer_evidence_id", evidence)
        if not isinstance(self.location, CodeSourceReference):
            raise TypeError("limitation source location is invalid")
        object.__setattr__(self, "invocation_kind", _text(
            self.invocation_kind, "invocation kind", 64,
        ))
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "site limitation",
        ))

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "caller_subject_id": self.caller_subject_id,
            "producer_evidence_id": self.producer_evidence_id,
            "location": self.location.to_dict(),
            "invocation_kind": self.invocation_kind,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeLimitationSummary:
    category: str
    total_count: int
    representatives: tuple[CodeSiteEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _text(
            self.category, "limitation summary category", 96,
        ))
        total = _non_negative(self.total_count, "limitation total")
        representatives = tuple(sorted(self.representatives))
        if total < len(representatives):
            raise ValueError("limitation representative count is inconsistent")
        object.__setattr__(self, "representatives", representatives)

    @property
    def omitted_count(self) -> int:
        return self.total_count - len(self.representatives)

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "total_count": self.total_count,
            "included_count": len(self.representatives),
            "omitted_count": self.omitted_count,
            "representatives": [item.to_dict() for item in self.representatives],
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeCapability:
    name: str
    availability: CodeIntelligenceAvailability
    producer_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "capability name", 64))
        if not isinstance(self.availability, CodeIntelligenceAvailability):
            raise TypeError("code capability availability is invalid")
        object.__setattr__(self, "producer_ids", _strings(
            self.producer_ids, "capability producer",
        ))
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "capability limitation",
        ))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "availability": self.availability.value,
            "producer_ids": list(self.producer_ids),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class CodeTraversalSummary:
    traversal_direction: CodeTraversalDirection
    configured_max_depth: int
    configured_max_nodes: int
    visited_node_count: int
    visited_edge_count: int
    depth_histogram: tuple[tuple[int, int], ...]
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.traversal_direction, CodeTraversalDirection):
            raise TypeError("traversal direction is invalid")
        if self.configured_max_depth < 1 or self.configured_max_nodes < 1:
            raise ValueError("traversal bounds must be positive")
        _non_negative(self.visited_node_count, "visited nodes")
        _non_negative(self.visited_edge_count, "visited edges")
        histogram = tuple(sorted(self.depth_histogram))
        if any(depth < 1 or count < 1 for depth, count in histogram):
            raise ValueError("depth histogram is invalid")
        if sum(count for _, count in histogram) != max(
            0, self.visited_node_count - 1
        ):
            raise ValueError("depth histogram does not match visited nodes")
        if not isinstance(self.truncated, bool):
            raise TypeError("traversal truncation flag is invalid")
        object.__setattr__(self, "depth_histogram", histogram)

    def to_dict(self) -> dict[str, object]:
        return {
            "traversal_direction": self.traversal_direction.value,
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


@dataclass(frozen=True, slots=True)
class CodeTraceability:
    snapshot_id: str
    callable_index_fingerprint: str
    code_graph_fingerprint: str
    test_evidence_fingerprint: str
    reachability_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _text(
            self.snapshot_id, "snapshot identity", 512,
        ))
        for name, prefix in (
            ("callable_index_fingerprint", "java-callable-index:"),
            ("code_graph_fingerprint", "java-code-graph:"),
            ("test_evidence_fingerprint", "java-test-evidence:"),
        ):
            value = _text(getattr(self, name), name, 128)
            if not value.startswith(prefix):
                raise ValueError(f"{name} is malformed")
            object.__setattr__(self, name, value)
        if self.reachability_fingerprint is not None:
            object.__setattr__(self, "reachability_fingerprint", _text(
                self.reachability_fingerprint, "reachability fingerprint", 256,
            ))

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "callable_index_fingerprint": self.callable_index_fingerprint,
            "code_graph_fingerprint": self.code_graph_fingerprint,
            "test_evidence_fingerprint": self.test_evidence_fingerprint,
            "reachability_fingerprint": self.reachability_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class JavaCodeIntelligenceReport:
    subject: CodeSubject
    direct_callers_high_confidence: BoundedRelationships
    direct_callers_conservative: BoundedRelationships
    direct_caller_method_references: BoundedRelationships
    direct_callees_high_confidence: BoundedRelationships
    direct_callees_conservative: BoundedRelationships
    direct_callee_method_references: BoundedRelationships
    upstream_direct: BoundedPaths
    upstream_transitive: BoundedPaths
    direct_test_callers: BoundedRelationships
    high_confidence_test_paths: BoundedPaths
    possible_test_paths: BoundedPaths
    limitations: tuple[CodeLimitationSummary, ...]
    capability_availability: tuple[CodeCapability, ...]
    traversal: CodeTraversalSummary
    traceability: CodeTraceability
    negative_test_statement: str | None = None
    general_limitations: tuple[str, ...] = ()
    producer_version: str = CODE_INTELLIGENCE_PRODUCER
    schema_version: int = CODE_INTELLIGENCE_SCHEMA_VERSION
    direct_caller_conservative_groups: BoundedAmbiguousCallGroups = (
        BoundedAmbiguousCallGroups(0, 0)
    )
    direct_callee_conservative_groups: BoundedAmbiguousCallGroups = (
        BoundedAmbiguousCallGroups(0, 0)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.subject, CodeSubject):
            raise TypeError("code intelligence subject is invalid")
        bounded = (
            self.direct_callers_high_confidence,
            self.direct_callers_conservative,
            self.direct_caller_method_references,
            self.direct_callees_high_confidence,
            self.direct_callees_conservative,
            self.direct_callee_method_references,
            self.upstream_direct,
            self.upstream_transitive,
            self.direct_test_callers,
            self.high_confidence_test_paths,
            self.possible_test_paths,
        )
        if any(not isinstance(item, (BoundedRelationships, BoundedPaths)) for item in bounded):
            raise TypeError("code intelligence bounded section is invalid")
        groups = (
            self.direct_caller_conservative_groups,
            self.direct_callee_conservative_groups,
        )
        if any(not isinstance(item, BoundedAmbiguousCallGroups) for item in groups):
            raise TypeError("code intelligence conservative call groups are invalid")
        if (
            self.direct_caller_conservative_groups.candidate_projection_count
            != self.direct_callers_conservative.total_count
            or self.direct_callee_conservative_groups.candidate_projection_count
            != self.direct_callees_conservative.total_count
        ):
            raise ValueError("grouped and machine-level conservative counts disagree")
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations)))
        capabilities = tuple(sorted(
            self.capability_availability, key=lambda item: item.name,
        ))
        if len({item.name for item in capabilities}) != len(capabilities):
            raise ValueError("code capability names must be unique")
        object.__setattr__(self, "capability_availability", capabilities)
        if not isinstance(self.traversal, CodeTraversalSummary):
            raise TypeError("code intelligence traversal is invalid")
        if not isinstance(self.traceability, CodeTraceability):
            raise TypeError("code intelligence traceability is invalid")
        if self.negative_test_statement is not None:
            statement = _text(
                self.negative_test_statement, "negative TEST statement", 512,
            )
            forbidden = ("untested", "no tests cover", "not covered by tests")
            if any(item in statement.casefold() for item in forbidden):
                raise ValueError("negative TEST statement overclaims coverage")
            object.__setattr__(self, "negative_test_statement", statement)
        object.__setattr__(self, "general_limitations", _strings(
            self.general_limitations, "general code-intelligence limitation",
        ))
        if (
            self.producer_version != CODE_INTELLIGENCE_PRODUCER
            or self.schema_version != CODE_INTELLIGENCE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported code-intelligence schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "subject": self.subject.to_dict(),
            "direction_contract": {
                "canonical_direction": "caller_to_callee",
                "canonical_relation": "calls",
                "impact_traversal_direction": "reverse_upstream",
            },
            "direct_callers": {
                "high_confidence": self.direct_callers_high_confidence.to_dict(),
                "conservative": self.direct_callers_conservative.to_dict(),
                "method_references": self.direct_caller_method_references.to_dict(),
            },
            "direct_callees": {
                "high_confidence": self.direct_callees_high_confidence.to_dict(),
                "conservative": self.direct_callees_conservative.to_dict(),
                "method_references": self.direct_callee_method_references.to_dict(),
            },
            "upstream_change_impact": {
                "direct": self.upstream_direct.to_dict(),
                "transitive": self.upstream_transitive.to_dict(),
                "traversal": self.traversal.to_dict(),
            },
            "represented_test_intelligence": {
                "direct_test_callers": self.direct_test_callers.to_dict(),
                "high_confidence_paths": self.high_confidence_test_paths.to_dict(),
                "possible_paths": self.possible_test_paths.to_dict(),
                "negative_statement": self.negative_test_statement,
                "runtime_test_coverage_proven": False,
            },
            "limitations": [item.to_dict() for item in self.limitations],
            "general_limitations": list(self.general_limitations),
            "capability_availability": [
                item.to_dict() for item in self.capability_availability
            ],
            "traceability": self.traceability.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )

    @property
    def input_fingerprint(self) -> str:
        payload = {
            "snapshot_id": self.traceability.snapshot_id,
            "subject_id": self.subject.canonical_id,
            "callable_index": self.traceability.callable_index_fingerprint,
            "code_graph": self.traceability.code_graph_fingerprint,
            "test_evidence": self.traceability.test_evidence_fingerprint,
            "traversal": self.traversal.to_dict(),
            "producer": self.producer_version,
        }
        digest = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")).hexdigest()
        return f"java-code-intelligence:{digest}"


@dataclass(frozen=True, slots=True)
class JavaCodeIntelligenceResult:
    resolution: CodeSubjectResolution
    snapshot_id: str
    report: JavaCodeIntelligenceReport | None = None
    limitations: tuple[str, ...] = ()
    producer_version: str = CODE_INTELLIGENCE_PRODUCER
    schema_version: int = CODE_INTELLIGENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, CodeSubjectResolution):
            raise TypeError("code intelligence result resolution is invalid")
        object.__setattr__(self, "snapshot_id", _text(
            self.snapshot_id, "code intelligence snapshot", 512,
        ))
        if self.resolution.status is CodeSubjectResolutionStatus.RESOLVED:
            if self.report is None or self.report.subject != self.resolution.subject:
                raise ValueError("resolved code intelligence result lacks its report")
        elif self.report is not None:
            raise ValueError("unresolved code intelligence result cannot have a report")
        object.__setattr__(self, "limitations", _strings(
            self.limitations, "code intelligence result limitation",
        ))
        if (
            self.producer_version != CODE_INTELLIGENCE_PRODUCER
            or self.schema_version != CODE_INTELLIGENCE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported code intelligence result schema")

    @property
    def availability(self) -> CodeIntelligenceAvailability:
        if self.report is None:
            return CodeIntelligenceAvailability.UNAVAILABLE
        if any(
            item.availability is CodeIntelligenceAvailability.PARTIAL
            for item in self.report.capability_availability
        ):
            return CodeIntelligenceAvailability.PARTIAL
        return CodeIntelligenceAvailability.AVAILABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "snapshot_id": self.snapshot_id,
            "availability": self.availability.value,
            "resolution": self.resolution.to_dict(),
            "report": self.report.to_dict() if self.report is not None else None,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )
