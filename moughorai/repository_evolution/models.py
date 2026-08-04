from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re

from moughorai.knowledge_graph import KnowledgeRelation
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
from moughorai.subject_resolution import SubjectCandidate, SubjectMatchBasis


REPOSITORY_EVOLUTION_SCHEMA_VERSION = 1
REPOSITORY_EVOLUTION_PRODUCER = "atlas-pr141/1"

_MAX_CHANGES = 5_000
_MAX_TEXT = 4_096
_SHA = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_FINGERPRINT = re.compile(r"^repository-evolution:[0-9a-f]{64}$")
_RESULT_DIGEST = re.compile(r"^repository-evolution-result:[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_MAX_LIMITATIONS = 128
_MAX_EVIDENCE_REFS = 64
_NODE_PROJECTION_FIELDS = frozenset({
    "kind", "name", "symbol_id", "metadata", "qualified_name", "project_id",
    "language",
})
_ABSENCE_LIMITATION = (
    "Absence means absent from the canonical snapshot projection; it does not "
    "prove source deletion, runtime unreachability, or developer intent."
)
_MODIFICATION_LIMITATION = (
    "A changed canonical projection does not establish the source change, "
    "runtime effect, compatibility impact, or developer intent that caused it."
)
_RELATION_EVIDENCE_LIMITATION = (
    "Only the structured evidence projection changed; the canonical relationship "
    "remains present."
)


class EvolutionState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class EvolutionChangeKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class EvolutionCapabilityKind(str, Enum):
    SNAPSHOT_PAIR = "snapshot_pair"
    CANONICAL_NODES = "canonical_nodes"
    CANONICAL_RELATIONS = "canonical_relations"
    COMMIT_ALIGNMENT = "commit_alignment"
    RENAME_TRACKING = "rename_tracking"
    API_COMPATIBILITY = "api_compatibility"
    SECURITY_EVOLUTION = "security_evolution"
    ARCHITECTURAL_DRIFT = "architectural_drift"


_FIXED_FUTURE_CAPABILITIES = {
    EvolutionCapabilityKind.RENAME_TRACKING: (
        "Stable identity absence and presence do not prove rename or move continuity."
    ),
    EvolutionCapabilityKind.API_COMPATIBILITY: (
        "No authoritative API or ABI before/after producer is available in PR141."
    ),
    EvolutionCapabilityKind.SECURITY_EVOLUTION: (
        "PR138 findings are current-state observations and cannot prove introduced or fixed security issues."
    ),
    EvolutionCapabilityKind.ARCHITECTURAL_DRIFT: (
        "Architectural drift is owned by PR143 and is not inferred from graph deltas."
    ),
}


@dataclass(frozen=True, slots=True)
class RepositoryEvolutionRequest:
    maximum_node_changes: int = 256
    maximum_relation_changes: int = 256

    def __post_init__(self) -> None:
        for name in ("maximum_node_changes", "maximum_relation_changes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"repository evolution {name} must be an integer")
            if not 1 <= value <= _MAX_CHANGES:
                raise ValueError(
                    f"repository evolution {name} must be between 1 and {_MAX_CHANGES}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "maximum_node_changes": self.maximum_node_changes,
            "maximum_relation_changes": self.maximum_relation_changes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepositoryEvolutionRequest:
        _reject_unknown(
            value,
            frozenset({"maximum_node_changes", "maximum_relation_changes"}),
            "repository evolution request",
        )
        return cls(
            _integer(value.get("maximum_node_changes", 256), "maximum node changes"),
            _integer(
                value.get("maximum_relation_changes", 256),
                "maximum relation changes",
            ),
        )


@dataclass(frozen=True, slots=True)
class EvolutionSnapshotReference:
    snapshot_id: str
    graph_digest: str
    analyzer_version: str
    git_head: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "analyzer_version",
            _text(self.analyzer_version, "analyzer version"),
        )
        if not _SHA.fullmatch(self.snapshot_id):
            raise ValueError("evolution snapshot ID must be a SHA-256 digest")
        if self.graph_digest != "unavailable" and not _SHA.fullmatch(self.graph_digest):
            raise ValueError("evolution graph digest must be SHA-256 or unavailable")
        if self.git_head is not None and not _GIT_OBJECT.fullmatch(self.git_head):
            raise ValueError("evolution Git head must be a full object identifier")

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "graph_digest": self.graph_digest,
            "analyzer_version": self.analyzer_version,
            "git_head": self.git_head,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvolutionSnapshotReference:
        _reject_unknown(
            value,
            frozenset({"snapshot_id", "graph_digest", "analyzer_version", "git_head"}),
            "evolution snapshot reference",
        )
        raw_head = value.get("git_head")
        return cls(
            _text(value.get("snapshot_id"), "snapshot ID"),
            _text(value.get("graph_digest", "unavailable"), "graph digest"),
            _text(value.get("analyzer_version"), "analyzer version"),
            _text(raw_head, "Git head") if raw_head is not None else None,
        )


@dataclass(frozen=True, order=True, slots=True)
class EvolutionCapability:
    capability: EvolutionCapabilityKind
    state: EvolutionState
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.capability, str):
            object.__setattr__(self, "capability", EvolutionCapabilityKind(self.capability))
        if isinstance(self.state, str):
            object.__setattr__(self, "state", EvolutionState(self.state))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        _strings(self.evidence_ids, "capability evidence IDs")
        _strings(
            self.limitations,
            "capability limitations",
            maximum_count=_MAX_LIMITATIONS,
        )
        if self.state is not EvolutionState.AVAILABLE and not self.limitations:
            raise ValueError("non-available evolution capabilities require a limitation")

    def to_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "state": self.state.value,
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvolutionCapability:
        _reject_unknown(
            value,
            frozenset({"capability", "state", "evidence_ids", "limitations"}),
            "evolution capability",
        )
        return cls(
            EvolutionCapabilityKind(_text(value.get("capability"), "capability")),
            EvolutionState(_text(value.get("state"), "capability state")),
            _strings(value.get("evidence_ids"), "capability evidence IDs"),
            _strings(
                value.get("limitations"),
                "capability limitations",
                maximum_count=_MAX_LIMITATIONS,
            ),
        )


@dataclass(frozen=True, slots=True)
class NodeEvolution:
    change: EvolutionChangeKind
    before: SubjectCandidate | None
    after: SubjectCandidate | None
    before_digest: str | None
    after_digest: str | None
    changed_fields: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    confidence: ConfidenceResult
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.change, str):
            object.__setattr__(self, "change", EvolutionChangeKind(self.change))
        object.__setattr__(self, "changed_fields", tuple(sorted(set(self.changed_fields))))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        _strings(self.changed_fields, "node changed fields")
        _strings(self.evidence_ids, "node evidence IDs")
        _strings(
            self.limitations,
            "node limitations",
            maximum_count=_MAX_LIMITATIONS,
        )
        for name, candidate in (("node before", self.before), ("node after", self.after)):
            if candidate is not None:
                _validate_candidate_projection(candidate, name)
        _validate_confidence_projection(self.confidence)
        if len(self.evidence_ids) != 2:
            raise ValueError("node evolution requires one base and one head evidence record")
        for digest in (self.before_digest, self.after_digest):
            if digest is not None and not _SHA.fullmatch(digest):
                raise ValueError("node projection digests must be SHA-256 values")
        if self.change is EvolutionChangeKind.ADDED:
            valid = self.before is None and self.before_digest is None and self.after is not None and self.after_digest is not None
        elif self.change is EvolutionChangeKind.REMOVED:
            valid = self.before is not None and self.before_digest is not None and self.after is None and self.after_digest is None
        else:
            valid = (
                self.before is not None
                and self.after is not None
                and self.before.canonical_id == self.after.canonical_id
                and self.before_digest is not None
                and self.after_digest is not None
                and self.before_digest != self.after_digest
                and bool(self.changed_fields)
            )
        if not valid:
            raise ValueError(f"invalid {self.change.value} node evolution projection")
        if self.change is not EvolutionChangeKind.MODIFIED and self.changed_fields:
            raise ValueError("only modified node evolution may contain changed fields")
        if set(self.changed_fields).difference(_NODE_PROJECTION_FIELDS):
            raise ValueError("node evolution contains unsupported changed fields")
        if self.change is EvolutionChangeKind.MODIFIED:
            visible = _visible_node_changed_fields(self.before, self.after)
            projected = set(self.changed_fields).intersection({
                "kind", "name", "qualified_name", "project_id", "language"
            })
            if projected != visible:
                raise ValueError("node evolution changed fields are inconsistent")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("node evolution must not contain absolute paths")

    @property
    def subject_id(self) -> str:
        candidate = self.after or self.before
        if candidate is None:  # pragma: no cover - constructor rejects this state
            raise RuntimeError("node evolution has no subject")
        return candidate.canonical_id

    def to_dict(self) -> dict[str, object]:
        return {
            "change": self.change.value,
            "before": None if self.before is None else self.before.to_dict(),
            "after": None if self.after is None else self.after.to_dict(),
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "changed_fields": list(self.changed_fields),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence.to_dict(),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> NodeEvolution:
        _reject_unknown(
            value,
            frozenset({
                "change", "before", "after", "before_digest", "after_digest",
                "changed_fields", "evidence_ids", "confidence", "limitations",
            }),
            "node evolution",
        )
        raw_before = value.get("before")
        raw_after = value.get("after")
        raw_confidence = value.get("confidence")
        if not isinstance(raw_confidence, Mapping):
            raise TypeError("node evolution confidence must be an object")
        return cls(
            EvolutionChangeKind(_text(value.get("change"), "node change")),
            _candidate_from_dict(raw_before, "node before") if isinstance(raw_before, Mapping) else None,
            _candidate_from_dict(raw_after, "node after") if isinstance(raw_after, Mapping) else None,
            _optional_text(value.get("before_digest")),
            _optional_text(value.get("after_digest")),
            _strings(value.get("changed_fields"), "node changed fields"),
            _strings(value.get("evidence_ids"), "node evidence IDs"),
            _confidence_from_dict(raw_confidence),
            _strings(
                value.get("limitations"),
                "node limitations",
                maximum_count=_MAX_LIMITATIONS,
            ),
        )


@dataclass(frozen=True, slots=True)
class RelationEvolution:
    change: EvolutionChangeKind
    relation: KnowledgeRelation
    source: SubjectCandidate
    target: SubjectCandidate
    before_evidence_digest: str | None
    after_evidence_digest: str | None
    before_evidence_count: int
    after_evidence_count: int
    evidence_ids: tuple[str, ...]
    confidence: ConfidenceResult
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.change, str):
            object.__setattr__(self, "change", EvolutionChangeKind(self.change))
        if isinstance(self.relation, str):
            object.__setattr__(self, "relation", KnowledgeRelation(self.relation))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        _strings(self.evidence_ids, "relation evidence IDs")
        _strings(
            self.limitations,
            "relation limitations",
            maximum_count=_MAX_LIMITATIONS,
        )
        _validate_candidate_projection(self.source, "relation source")
        _validate_candidate_projection(self.target, "relation target")
        _validate_confidence_projection(self.confidence)
        if len(self.evidence_ids) != 2:
            raise ValueError("relation evolution requires one base and one head evidence record")
        for count in (self.before_evidence_count, self.after_evidence_count):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("relation evidence counts must be non-negative integers")
        for digest in (self.before_evidence_digest, self.after_evidence_digest):
            if digest is not None and not _SHA.fullmatch(digest):
                raise ValueError("relation evidence digests must be SHA-256 values")
        if self.change is EvolutionChangeKind.ADDED:
            valid = self.before_evidence_digest is None and self.after_evidence_digest is not None and self.before_evidence_count == 0
        elif self.change is EvolutionChangeKind.REMOVED:
            valid = self.before_evidence_digest is not None and self.after_evidence_digest is None and self.after_evidence_count == 0
        else:
            valid = (
                self.before_evidence_digest is not None
                and self.after_evidence_digest is not None
                and self.before_evidence_digest != self.after_evidence_digest
            )
        if not valid:
            raise ValueError(f"invalid {self.change.value} relation evolution projection")
        if contains_absolute_path(self.to_dict()):
            raise ValueError("relation evolution must not contain absolute paths")

    @property
    def subject_id(self) -> str:
        identity = {
            "relation": self.relation.value,
            "source": self.source.canonical_id,
            "target": self.target.canonical_id,
        }
        return "canonical-relation:" + _digest(identity)

    def to_dict(self) -> dict[str, object]:
        return {
            "change": self.change.value,
            "relation": self.relation.value,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "before_evidence_digest": self.before_evidence_digest,
            "after_evidence_digest": self.after_evidence_digest,
            "before_evidence_count": self.before_evidence_count,
            "after_evidence_count": self.after_evidence_count,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence.to_dict(),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RelationEvolution:
        _reject_unknown(
            value,
            frozenset({
                "change", "relation", "source", "target",
                "before_evidence_digest", "after_evidence_digest",
                "before_evidence_count", "after_evidence_count", "evidence_ids",
                "confidence", "limitations",
            }),
            "relation evolution",
        )
        raw_source = value.get("source")
        raw_target = value.get("target")
        raw_confidence = value.get("confidence")
        if not isinstance(raw_source, Mapping) or not isinstance(raw_target, Mapping):
            raise TypeError("relation evolution endpoints must be objects")
        if not isinstance(raw_confidence, Mapping):
            raise TypeError("relation evolution confidence must be an object")
        return cls(
            EvolutionChangeKind(_text(value.get("change"), "relation change")),
            KnowledgeRelation(_text(value.get("relation"), "relation kind")),
            _candidate_from_dict(raw_source, "relation source"),
            _candidate_from_dict(raw_target, "relation target"),
            _optional_text(value.get("before_evidence_digest")),
            _optional_text(value.get("after_evidence_digest")),
            _integer(value.get("before_evidence_count", 0), "before evidence count"),
            _integer(value.get("after_evidence_count", 0), "after evidence count"),
            _strings(value.get("evidence_ids"), "relation evidence IDs"),
            _confidence_from_dict(raw_confidence),
            _strings(
                value.get("limitations"),
                "relation limitations",
                maximum_count=_MAX_LIMITATIONS,
            ),
        )


@dataclass(frozen=True, slots=True)
class RepositoryEvolutionResponse:
    request: RepositoryEvolutionRequest
    base: EvolutionSnapshotReference
    head: EvolutionSnapshotReference
    state: EvolutionState
    capabilities: tuple[EvolutionCapability, ...]
    node_changes: tuple[NodeEvolution, ...]
    relation_changes: tuple[RelationEvolution, ...]
    total_node_change_count: int
    omitted_node_change_count: int
    unchanged_node_count: int
    total_relation_change_count: int
    omitted_relation_change_count: int
    unchanged_relation_count: int
    evidence_index: EvidenceIndex
    input_fingerprint: str
    result_digest: str = ""
    limitations: tuple[str, ...] = ()
    producer_version: str = REPOSITORY_EVOLUTION_PRODUCER
    schema_version: int = REPOSITORY_EVOLUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, RepositoryEvolutionRequest):
            raise TypeError("repository evolution response requires a request")
        if not isinstance(self.base, EvolutionSnapshotReference) or not isinstance(
            self.head, EvolutionSnapshotReference
        ):
            raise TypeError("repository evolution response requires snapshot references")
        if isinstance(self.state, str):
            object.__setattr__(self, "state", EvolutionState(self.state))
        capabilities = tuple(self.capabilities)
        node_changes = tuple(self.node_changes)
        relation_changes = tuple(self.relation_changes)
        if any(not isinstance(item, EvolutionCapability) for item in capabilities):
            raise TypeError("repository evolution capabilities are invalid")
        if any(not isinstance(item, NodeEvolution) for item in node_changes):
            raise TypeError("repository evolution node changes are invalid")
        if any(not isinstance(item, RelationEvolution) for item in relation_changes):
            raise TypeError("repository evolution relation changes are invalid")
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("repository evolution response requires an evidence index")
        object.__setattr__(self, "capabilities", tuple(sorted(capabilities)))
        object.__setattr__(self, "node_changes", tuple(sorted(node_changes, key=_node_sort_key)))
        object.__setattr__(
            self,
            "relation_changes",
            tuple(sorted(relation_changes, key=_relation_sort_key)),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        _strings(
            self.limitations,
            "response limitations",
            maximum_count=_MAX_LIMITATIONS,
        )
        if len(capabilities) > len(EvolutionCapabilityKind):
            raise ValueError("repository evolution capabilities exceed their bound")
        if len(node_changes) > self.request.maximum_node_changes:
            raise ValueError("repository evolution node changes exceed their bound")
        if len(relation_changes) > self.request.maximum_relation_changes:
            raise ValueError("repository evolution relation changes exceed their bound")
        maximum_evidence = 6 + 2 * (len(node_changes) + len(relation_changes))
        object.__setattr__(
            self,
            "evidence_index",
            _evidence_index_from_dict(
                self.evidence_index.to_dict(),
                maximum_count=maximum_evidence,
            ),
        )
        if self.schema_version != REPOSITORY_EVOLUTION_SCHEMA_VERSION:
            raise ValueError("unsupported repository evolution schema")
        if self.producer_version != REPOSITORY_EVOLUTION_PRODUCER:
            raise ValueError("unsupported repository evolution producer")
        if not _FINGERPRINT.fullmatch(self.input_fingerprint):
            raise ValueError("repository evolution input fingerprint is invalid")
        expected_input = repository_evolution_fingerprint(self.request, self.base, self.head)
        if self.input_fingerprint != expected_input:
            raise ValueError("repository evolution input fingerprint mismatch")
        counts = (
            self.total_node_change_count,
            self.omitted_node_change_count,
            self.unchanged_node_count,
            self.total_relation_change_count,
            self.omitted_relation_change_count,
            self.unchanged_relation_count,
        )
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts):
            raise ValueError("repository evolution counts must be non-negative integers")
        if self.total_node_change_count != len(self.node_changes) + self.omitted_node_change_count:
            raise ValueError("repository evolution node counts are inconsistent")
        if self.total_relation_change_count != len(self.relation_changes) + self.omitted_relation_change_count:
            raise ValueError("repository evolution relation counts are inconsistent")
        expected_nodes = min(
            self.total_node_change_count, self.request.maximum_node_changes
        )
        expected_relations = min(
            self.total_relation_change_count, self.request.maximum_relation_changes
        )
        if len(self.node_changes) != expected_nodes:
            raise ValueError("repository evolution node truncation is inconsistent")
        if len(self.relation_changes) != expected_relations:
            raise ValueError("repository evolution relation truncation is inconsistent")
        if len({item.capability for item in self.capabilities}) != len(self.capabilities):
            raise ValueError("repository evolution capabilities must be unique")
        if {item.capability for item in self.capabilities} != set(EvolutionCapabilityKind):
            raise ValueError("repository evolution must report every capability")
        self._validate_evidence()
        self._validate_capability_contract()
        self._validate_overall_state()
        expected_result = repository_evolution_result_digest(self._result_payload())
        if self.result_digest:
            if not _RESULT_DIGEST.fullmatch(self.result_digest):
                raise ValueError("repository evolution result digest is invalid")
            if self.result_digest != expected_result:
                raise ValueError("repository evolution result digest mismatch")
        else:
            object.__setattr__(self, "result_digest", expected_result)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("repository evolution responses must remain source-free")

    def capability(self, kind: EvolutionCapabilityKind) -> EvolutionCapability:
        return next(item for item in self.capabilities if item.capability is kind)

    def _validate_evidence(self) -> None:
        records = {record.evidence_id: record for record in self.evidence_index.records}
        allowed_lineages = {self.base.snapshot_id, self.head.snapshot_id}
        for record in records.values():
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
                raise ValueError(f"non-canonical evolution evidence: {record.evidence_id}")
            if record.producer != self.producer_version:
                raise ValueError("repository evolution evidence has a foreign producer")
            if record.snapshot_id not in allowed_lineages:
                raise ValueError("repository evolution evidence has a foreign lineage")
        referenced = {
            evidence_id
            for item in self.capabilities
            for evidence_id in item.evidence_ids
        }
        for item in (*self.node_changes, *self.relation_changes):
            referenced.update(item.evidence_ids)
            selected = tuple(records.get(evidence_id) for evidence_id in item.evidence_ids)
            if any(record is None for record in selected):
                raise ValueError("repository evolution change references missing evidence")
            if any(
                record is not None and record.subject_id != item.subject_id
                for record in selected
            ):
                raise ValueError("repository evolution evidence subject does not match its change")
            lineages = {record.snapshot_id for record in selected if record is not None}
            if lineages != allowed_lineages:
                raise ValueError("repository evolution changes require base and head evidence")
            self._validate_change_evidence(item, tuple(
                record for record in selected if record is not None
            ))
            confidence = ConfidenceCalculator().calculate(
                (
                    EvidenceRole(
                        "base_projection",
                        tuple(record.evidence_id for record in selected if record is not None and record.snapshot_id == self.base.snapshot_id),
                    ),
                    EvidenceRole(
                        "head_projection",
                        tuple(record.evidence_id for record in selected if record is not None and record.snapshot_id == self.head.snapshot_id),
                    ),
                ),
                self.evidence_index,
            )
            if confidence != item.confidence:
                raise ValueError("repository evolution confidence is not reproducible")
        missing = referenced.difference(records)
        if missing:
            raise ValueError(f"repository evolution references missing evidence: {sorted(missing)}")
        if referenced != set(records):
            raise ValueError("repository evolution evidence closure is not exact")

    def _validate_change_evidence(
        self,
        item: NodeEvolution | RelationEvolution,
        selected: tuple[EvidenceRecord, ...],
    ) -> None:
        by_side: dict[str, EvidenceRecord] = {}
        for record in selected:
            detail = dict(record.detail)
            side = detail.get("side", "")
            if side not in {"base", "head"} or side in by_side:
                raise ValueError("repository evolution change evidence sides are invalid")
            by_side[side] = record
        if set(by_side) != {"base", "head"}:
            raise ValueError("repository evolution changes require base and head evidence")

        if isinstance(item, NodeEvolution):
            expected_kind = EvidenceKind.GRAPH_NODE
            before_digest = item.before_digest
            after_digest = item.after_digest
            before_count = int(item.before is not None)
            after_count = int(item.after is not None)
            expected_refs = ()
            expected_changed_fields = ",".join(item.changed_fields) or "none"
            expected_limitation = (
                (_ABSENCE_LIMITATION,)
                if item.change in {EvolutionChangeKind.ADDED, EvolutionChangeKind.REMOVED}
                else (_MODIFICATION_LIMITATION,)
            )
        else:
            expected_kind = EvidenceKind.GRAPH_EDGE
            before_digest = item.before_evidence_digest
            after_digest = item.after_evidence_digest
            before_count = item.before_evidence_count
            after_count = item.after_evidence_count
            expected_refs = (
                f"canonical-subject:{item.source.canonical_id}",
                f"canonical-subject:{item.target.canonical_id}",
                f"canonical-relation-kind:{item.relation.value}",
            )
            expected_changed_fields = None
            expected_limitation = (
                (_ABSENCE_LIMITATION,)
                if item.change in {EvolutionChangeKind.ADDED, EvolutionChangeKind.REMOVED}
                else (_RELATION_EVIDENCE_LIMITATION,)
            )
        if item.limitations != expected_limitation:
            raise ValueError("repository evolution change limitations are inconsistent")

        for side, snapshot, graph_digest, digest, count in (
            ("base", self.base, self.base.graph_digest, before_digest, before_count),
            ("head", self.head, self.head.graph_digest, after_digest, after_count),
        ):
            record = by_side[side]
            expected_detail = {
                "side": side,
                "change": item.change.value,
                "presence": "present" if digest is not None else "absent",
                "projection_digest": digest or "absent",
                "evidence_count": str(count),
            }
            if expected_changed_fields is not None:
                expected_detail["changed_fields"] = expected_changed_fields
            expected_sources = tuple(sorted({
                f"canonical-graph:{graph_digest}",
                f"snapshot:{snapshot.snapshot_id}",
                *expected_refs,
            }))
            absent_limitations = (_ABSENCE_LIMITATION,) if digest is None else ()
            if (
                record.kind is not expected_kind
                or record.snapshot_id != snapshot.snapshot_id
                or dict(record.detail) != expected_detail
                or record.source_refs != expected_sources
                or record.limitations != absent_limitations
                or record.scope != "repository"
                or record.language != "unknown"
                or record.reliability != 1.0
                or record.specificity != 1.0
            ):
                raise ValueError("repository evolution change evidence is inconsistent")

    def _validate_capability_contract(self) -> None:
        capabilities = {item.capability: item for item in self.capabilities}
        records = {item.evidence_id: item for item in self.evidence_index.records}
        snapshot = capabilities[EvolutionCapabilityKind.SNAPSHOT_PAIR]
        if (
            snapshot.state is not EvolutionState.AVAILABLE
            or snapshot.limitations
            or len(snapshot.evidence_ids) != 2
        ):
            raise ValueError("repository evolution snapshot-pair capability is inconsistent")
        self._validate_capability_records(
            snapshot, records, "repository-evolution:snapshot-pair", EvidenceKind.ANALYSIS_RESULT
        )
        self._validate_snapshot_capability_records(snapshot, records)

        nodes = capabilities[EvolutionCapabilityKind.CANONICAL_NODES]
        relations = capabilities[EvolutionCapabilityKind.CANONICAL_RELATIONS]
        if (
            nodes.state is not relations.state
            or nodes.evidence_ids != relations.evidence_ids
            or nodes.limitations != relations.limitations
        ):
            raise ValueError("repository evolution canonical capabilities disagree")
        expected_graph_records = int(self.base.graph_digest != "unavailable") + int(
            self.head.graph_digest != "unavailable"
        )
        # The service publishes canonical graph evidence only for a complete pair.
        expected_graph_records = 2 if expected_graph_records == 2 else 0
        if len(nodes.evidence_ids) != expected_graph_records:
            raise ValueError("repository evolution canonical capability evidence is inconsistent")
        self._validate_capability_records(
            nodes, records, "repository-evolution:canonical-graph", EvidenceKind.ANALYSIS_RESULT
        )
        self._validate_graph_capability_records(nodes, records)
        if (
            (self.omitted_node_change_count or self.omitted_relation_change_count)
            and nodes.state is not EvolutionState.PARTIAL
        ):
            raise ValueError("bounded repository evolution must be explicitly partial")

        commit = capabilities[EvolutionCapabilityKind.COMMIT_ALIGNMENT]
        expected_commit_records = int(self.base.git_head is not None) + int(
            self.head.git_head is not None
        )
        if len(commit.evidence_ids) != expected_commit_records:
            raise ValueError("repository evolution commit capability evidence is inconsistent")
        self._validate_capability_records(
            commit,
            records,
            "repository-evolution:commit-association",
            EvidenceKind.REPOSITORY_METADATA,
        )
        self._validate_commit_capability_records(commit, records)
        if self.base.git_head is not None and self.head.git_head is not None:
            expected_commit_state = (
                EvolutionState.INSUFFICIENT
                if self.base.git_head == self.head.git_head
                else EvolutionState.PARTIAL
            )
            if commit.state is not expected_commit_state:
                raise ValueError("repository evolution commit capability state is inconsistent")
        elif commit.state not in {EvolutionState.UNAVAILABLE, EvolutionState.INCOMPATIBLE}:
            raise ValueError("repository evolution commit capability state is inconsistent")

        for kind, limitation in _FIXED_FUTURE_CAPABILITIES.items():
            capability = capabilities[kind]
            if (
                capability.state is not EvolutionState.UNAVAILABLE
                or capability.evidence_ids
                or capability.limitations != (limitation,)
            ):
                raise ValueError(f"repository evolution {kind.value} capability is unsupported")

    @staticmethod
    def _validate_capability_records(
        capability: EvolutionCapability,
        records: Mapping[str, EvidenceRecord],
        subject_id: str,
        kind: EvidenceKind,
    ) -> None:
        selected = tuple(records.get(item) for item in capability.evidence_ids)
        if any(
            record is None
            or record.subject_id != subject_id
            or record.kind is not kind
            or record.scope != "repository"
            or record.language != "unknown"
            for record in selected
        ):
            raise ValueError("repository evolution capability evidence is inconsistent")

    def _validate_snapshot_capability_records(
        self,
        capability: EvolutionCapability,
        records: Mapping[str, EvidenceRecord],
    ) -> None:
        selected = tuple(records[item] for item in capability.evidence_ids)
        by_side = {dict(record.detail).get("side"): record for record in selected}
        if set(by_side) != {"base", "head"} or len(by_side) != len(selected):
            raise ValueError("repository evolution snapshot capability sides are inconsistent")
        for side, snapshot in (("base", self.base), ("head", self.head)):
            record = by_side[side]
            if (
                record.snapshot_id != snapshot.snapshot_id
                or record.source_refs != (f"snapshot:{snapshot.snapshot_id}",)
                or dict(record.detail) != {"side": side, "snapshot_schema": "1"}
                or record.limitations
                or record.reliability != 1.0
                or record.specificity != 1.0
            ):
                raise ValueError("repository evolution snapshot capability evidence is inconsistent")

    def _validate_graph_capability_records(
        self,
        capability: EvolutionCapability,
        records: Mapping[str, EvidenceRecord],
    ) -> None:
        if not capability.evidence_ids:
            return
        selected = tuple(records[item] for item in capability.evidence_ids)
        by_side = {dict(record.detail).get("side"): record for record in selected}
        if set(by_side) != {"base", "head"} or len(by_side) != len(selected):
            raise ValueError("repository evolution graph capability sides are inconsistent")
        for side, snapshot in (("base", self.base), ("head", self.head)):
            record = by_side[side]
            detail = dict(record.detail)
            counts = (detail.get("node_count", ""), detail.get("relation_count", ""))
            if (
                record.snapshot_id != snapshot.snapshot_id
                or record.source_refs != (f"canonical-graph:{snapshot.graph_digest}",)
                or detail.get("graph_digest") != snapshot.graph_digest
                or set(detail) != {"side", "graph_digest", "node_count", "relation_count"}
                or any(not value.isdecimal() for value in counts)
                or not set(record.limitations).issubset(capability.limitations)
                or record.reliability != 1.0
                or record.specificity != 1.0
            ):
                raise ValueError("repository evolution graph capability evidence is inconsistent")

    def _validate_commit_capability_records(
        self,
        capability: EvolutionCapability,
        records: Mapping[str, EvidenceRecord],
    ) -> None:
        selected = tuple(records[item] for item in capability.evidence_ids)
        by_side = {dict(record.detail).get("side"): record for record in selected}
        expected_sides = {
            side
            for side, snapshot in (("base", self.base), ("head", self.head))
            if snapshot.git_head is not None
        }
        if set(by_side) != expected_sides or len(by_side) != len(selected):
            raise ValueError("repository evolution commit capability sides are inconsistent")
        for side, snapshot in (("base", self.base), ("head", self.head)):
            if snapshot.git_head is None:
                continue
            record = by_side[side]
            detail = dict(record.detail)
            expected_head = f"git-head:{snapshot.git_head}"
            other_refs = tuple(item for item in record.source_refs if item != expected_head)
            if (
                record.snapshot_id != snapshot.snapshot_id
                or expected_head not in record.source_refs
                or any(_EVIDENCE_ID.fullmatch(item) is None for item in other_refs)
                or detail != {
                    "side": side,
                    "association": "analysis-time-head",
                    "graph_digest": snapshot.graph_digest,
                }
                or not record.limitations
                or not set(record.limitations).issubset(capability.limitations)
                or record.reliability != 0.8
                or record.specificity != 0.7
            ):
                raise ValueError("repository evolution commit capability evidence is inconsistent")

    def _validate_overall_state(self) -> None:
        canonical = self.capability(EvolutionCapabilityKind.CANONICAL_NODES)
        if self.base.snapshot_id == self.head.snapshot_id:
            expected = EvolutionState.INSUFFICIENT
            if (
                self.node_changes
                or self.relation_changes
                or self.total_node_change_count
                or self.total_relation_change_count
            ):
                raise ValueError("same-snapshot evolution cannot contain changes")
        elif canonical.state in {EvolutionState.UNAVAILABLE, EvolutionState.INCOMPATIBLE}:
            expected = canonical.state
        else:
            expected = EvolutionState.PARTIAL
        if self.state is not expected:
            raise ValueError("repository evolution overall state is inconsistent")

    def _result_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "request": self.request.to_dict(),
            "base": self.base.to_dict(),
            "head": self.head.to_dict(),
            "state": self.state.value,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "node_changes": [item.to_dict() for item in self.node_changes],
            "relation_changes": [item.to_dict() for item in self.relation_changes],
            "counts": {
                "total_node_change_count": self.total_node_change_count,
                "omitted_node_change_count": self.omitted_node_change_count,
                "unchanged_node_count": self.unchanged_node_count,
                "total_relation_change_count": self.total_relation_change_count,
                "omitted_relation_change_count": self.omitted_relation_change_count,
                "unchanged_relation_count": self.unchanged_relation_count,
            },
            "evidence_index": self.evidence_index.to_dict(),
            "input_fingerprint": self.input_fingerprint,
            "limitations": list(self.limitations),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._result_payload(), "result_digest": self.result_digest}

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepositoryEvolutionResponse:
        _reject_unknown(
            value,
            frozenset({
                "schema_version", "producer_version", "request", "base", "head",
                "state", "capabilities", "node_changes", "relation_changes", "counts",
                "evidence_index", "input_fingerprint", "result_digest", "limitations",
            }),
            "repository evolution response",
        )
        request = _mapping(value.get("request"), "evolution request")
        base = _mapping(value.get("base"), "base snapshot reference")
        head = _mapping(value.get("head"), "head snapshot reference")
        counts = _mapping(value.get("counts"), "evolution counts")
        evidence = _mapping(value.get("evidence_index"), "evolution evidence index")
        _reject_unknown(
            counts,
            frozenset({
                "total_node_change_count", "omitted_node_change_count",
                "unchanged_node_count", "total_relation_change_count",
                "omitted_relation_change_count", "unchanged_relation_count",
            }),
            "repository evolution counts",
        )
        restored_request = RepositoryEvolutionRequest.from_dict(request)
        raw_capabilities = _mapping_sequence(
            value.get("capabilities"),
            "capabilities",
            maximum_count=len(EvolutionCapabilityKind),
        )
        raw_nodes = _mapping_sequence(
            value.get("node_changes"),
            "node changes",
            maximum_count=restored_request.maximum_node_changes,
        )
        raw_relations = _mapping_sequence(
            value.get("relation_changes"),
            "relation changes",
            maximum_count=restored_request.maximum_relation_changes,
        )
        maximum_evidence = 6 + 2 * (len(raw_nodes) + len(raw_relations))
        return cls(
            restored_request,
            EvolutionSnapshotReference.from_dict(base),
            EvolutionSnapshotReference.from_dict(head),
            EvolutionState(_text(value.get("state"), "evolution state")),
            tuple(
                EvolutionCapability.from_dict(item)
                for item in raw_capabilities
            ),
            tuple(
                NodeEvolution.from_dict(item)
                for item in raw_nodes
            ),
            tuple(
                RelationEvolution.from_dict(item)
                for item in raw_relations
            ),
            _integer(counts.get("total_node_change_count", 0), "total node changes"),
            _integer(counts.get("omitted_node_change_count", 0), "omitted node changes"),
            _integer(counts.get("unchanged_node_count", 0), "unchanged nodes"),
            _integer(counts.get("total_relation_change_count", 0), "total relation changes"),
            _integer(counts.get("omitted_relation_change_count", 0), "omitted relation changes"),
            _integer(counts.get("unchanged_relation_count", 0), "unchanged relations"),
            _evidence_index_from_dict(evidence, maximum_count=maximum_evidence),
            _text(value.get("input_fingerprint"), "input fingerprint"),
            _text(value.get("result_digest"), "result digest"),
            _strings(
                value.get("limitations"),
                "response limitations",
                maximum_count=_MAX_LIMITATIONS,
            ),
            _text(value.get("producer_version", REPOSITORY_EVOLUTION_PRODUCER), "producer version"),
            _integer(value.get("schema_version", REPOSITORY_EVOLUTION_SCHEMA_VERSION), "schema version"),
        )


def repository_evolution_fingerprint(
    request: RepositoryEvolutionRequest,
    base: EvolutionSnapshotReference,
    head: EvolutionSnapshotReference,
) -> str:
    return "repository-evolution:" + _digest({
        "producer_version": REPOSITORY_EVOLUTION_PRODUCER,
        "schema_version": REPOSITORY_EVOLUTION_SCHEMA_VERSION,
        "request": request.to_dict(),
        "base": base.to_dict(),
        "head": head.to_dict(),
    })


def repository_evolution_result_digest(payload: Mapping[str, object]) -> str:
    return "repository-evolution-result:" + _digest(payload)


def _node_sort_key(item: NodeEvolution) -> tuple[str, str, str]:
    return item.subject_id, item.change.value, item.after_digest or item.before_digest or ""


def _visible_node_changed_fields(
    before: SubjectCandidate | None,
    after: SubjectCandidate | None,
) -> set[str]:
    if before is None or after is None:
        return set()
    values = {
        "kind": (before.kind, after.kind),
        "name": (before.name, after.name),
        "qualified_name": (before.qualified_name, after.qualified_name),
        "project_id": (before.project, after.project),
        "language": (before.language, after.language),
    }
    return {name for name, (left, right) in values.items() if left != right}


def _relation_sort_key(item: RelationEvolution) -> tuple[str, str, str, str]:
    return (
        item.source.canonical_id,
        item.target.canonical_id,
        item.relation.value,
        item.change.value,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _reject_unknown(value: Mapping[str, object], allowed: frozenset[str], name: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _mapping_sequence(
    value: object,
    name: str,
    *,
    maximum_count: int = _MAX_CHANGES,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"{name} must contain objects")
    if len(value) > maximum_count:
        raise ValueError(f"{name} exceeds its maximum count")
    return tuple(value)


def _strings(
    value: object,
    name: str = "string array",
    *,
    maximum_count: int = _MAX_EVIDENCE_REFS,
    maximum_length: int = _MAX_TEXT,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"repository evolution {name} must be an array")
    if len(value) > maximum_count:
        raise ValueError(f"repository evolution {name} exceeds its maximum count")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"repository evolution {name} must contain strings")
    result = tuple(value)
    if any(not item.strip() or len(item) > maximum_length for item in result):
        raise ValueError(f"repository evolution {name} contains invalid text")
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise ValueError(f"repository evolution {name} must not be empty")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value, "optional text")


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"repository evolution {name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"repository evolution {name} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"repository evolution {name} must be between 0 and 1")
    return result


def _candidate_from_dict(
    value: Mapping[str, object],
    name: str,
) -> SubjectCandidate:
    _reject_unknown(
        value,
        frozenset({
            "canonical_id", "kind", "name", "qualified_name", "project",
            "language", "path", "project_scopes", "match_basis",
        }),
        f"repository evolution {name}",
    )
    for field_name in (
        "canonical_id", "kind", "name", "qualified_name", "language", "match_basis"
    ):
        _text(value.get(field_name), f"{name} {field_name}")
    for field_name in ("project", "path"):
        raw = value.get(field_name)
        if raw is not None:
            _text(raw, f"{name} {field_name}")
    _strings(
        value.get("project_scopes"),
        f"{name} project scopes",
        maximum_count=256,
    )
    # Validate the enum before delegating to the established public projection.
    SubjectMatchBasis(_text(value.get("match_basis"), f"{name} match basis"))
    return SubjectCandidate.from_dict(value)


def _validate_candidate_projection(value: SubjectCandidate, name: str) -> None:
    if not isinstance(value, SubjectCandidate):
        raise TypeError(f"repository evolution {name} must be a subject candidate")
    restored = _candidate_from_dict(value.to_dict(), name)
    if restored != value:
        raise ValueError(f"repository evolution {name} is not canonical")


def _confidence_from_dict(value: Mapping[str, object]) -> ConfidenceResult:
    _reject_unknown(
        value,
        frozenset({
            "score", "tier", "support", "coverage", "agreement",
            "contradiction_penalty", "ambiguity_penalty", "missing_roles",
            "model_version",
        }),
        "repository evolution confidence",
    )
    model_version = _integer(value.get("model_version"), "confidence model version")
    return ConfidenceResult(
        _number(value.get("score"), "confidence score"),
        ConfidenceTier(_text(value.get("tier"), "confidence tier")),
        _number(value.get("support"), "confidence support"),
        _number(value.get("coverage"), "confidence coverage"),
        _number(value.get("agreement"), "confidence agreement"),
        _number(value.get("contradiction_penalty"), "confidence contradiction penalty"),
        _number(value.get("ambiguity_penalty"), "confidence ambiguity penalty"),
        _strings(value.get("missing_roles"), "confidence missing roles"),
        model_version,
    )


def _validate_confidence_projection(value: ConfidenceResult) -> None:
    if not isinstance(value, ConfidenceResult):
        raise TypeError("repository evolution confidence is invalid")
    restored = _confidence_from_dict(value.to_dict())
    if restored != value:
        raise ValueError("repository evolution confidence is not canonical")


def _evidence_index_from_dict(
    value: Mapping[str, object],
    *,
    maximum_count: int,
) -> EvidenceIndex:
    _reject_unknown(
        value,
        frozenset({"schema_version", "records"}),
        "repository evolution evidence index",
    )
    schema = _integer(value.get("schema_version"), "evidence schema version")
    if schema != EvidenceIndex.SCHEMA_VERSION:
        raise ValueError("unsupported repository evolution evidence schema")
    raw_records = _mapping_sequence(
        value.get("records"),
        "evidence records",
        maximum_count=maximum_count,
    )
    records: list[EvidenceRecord] = []
    seen: set[str] = set()
    for item in raw_records:
        _reject_unknown(
            item,
            frozenset({
                "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
                "source_refs", "scope", "language", "detail", "limitations",
                "reliability", "specificity",
            }),
            "repository evolution evidence record",
        )
        evidence_id = _text(item.get("evidence_id"), "evidence ID")
        if not _EVIDENCE_ID.fullmatch(evidence_id) or evidence_id in seen:
            raise ValueError("repository evolution evidence identity is invalid")
        detail = _mapping(item.get("detail"), "evidence detail")
        if len(detail) > 16:
            raise ValueError("repository evolution evidence detail exceeds its bound")
        if any(not isinstance(key, str) or not isinstance(data, str) for key, data in detail.items()):
            raise TypeError("repository evolution evidence detail must contain strings")
        normalized_detail = {
            _text(key, "evidence detail key"): _text(data, "evidence detail value")
            for key, data in detail.items()
        }
        record = EvidenceRecord.create(
            EvidenceKind(_text(item.get("kind"), "evidence kind")),
            _text(item.get("subject_id"), "evidence subject"),
            _text(item.get("producer"), "evidence producer"),
            _text(item.get("snapshot_id"), "evidence snapshot"),
            source_refs=_strings(
                item.get("source_refs"),
                "evidence source references",
                maximum_count=_MAX_EVIDENCE_REFS,
                maximum_length=512,
            ),
            scope=_text(item.get("scope"), "evidence scope"),
            language=_text(item.get("language"), "evidence language"),
            detail=normalized_detail,
            limitations=_strings(
                item.get("limitations"),
                "evidence limitations",
                maximum_count=_MAX_LIMITATIONS,
            ),
            reliability=_number(item.get("reliability"), "evidence reliability"),
            specificity=_number(item.get("specificity"), "evidence specificity"),
        )
        if record.evidence_id != evidence_id:
            raise ValueError(f"non-canonical evolution evidence: {evidence_id}")
        seen.add(evidence_id)
        records.append(record)
    return EvidenceIndex(records, frozen=True)
