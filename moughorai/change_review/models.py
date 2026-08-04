from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re

from moughorai.ai_ask.safety import contains_unsafe_chat_content
from moughorai.impact_analysis import (
    ImpactCapabilityState,
    ImpactCategory,
    ImpactChangeKind,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
)
from moughorai.refactoring_advisor import (
    RefactoringFamily,
    RefactoringRequest,
    RefactoringResponse,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)
from moughorai.subject_resolution import (
    PathCandidateEvidence,
    SubjectCandidate,
    SubjectQuery,
)


CHANGE_REVIEW_SCHEMA_VERSION = 1
CHANGE_REVIEW_PRODUCER = "atlas-pr140/1"

_MAX_FILES = 1_000
_MAX_SUBJECTS = 128
_MAX_TEXT = 2_048
_MAX_SECTION_ENTRIES = 131_072
_MAX_FEATURE_EVIDENCE = (2 * _MAX_FILES) + _MAX_SUBJECTS
_EVIDENCE_ID = re.compile(r"^evidence:[0-9a-f]{64}$")
_DIFF_FINGERPRINT = re.compile(r"^git-diff:[0-9a-f]{64}$")
_REVIEW_FINGERPRINT = re.compile(r"^change-review:[0-9a-f]{64}$")
_FILE_ASSOCIATION_LIMITATION = (
    "The snapshot has no declaration source spans; an exact file association "
    "does not prove that a Git hunk changed this subject."
)
_UNTRACKED_LIMITATION = (
    "Git diff collection excludes untracked files; their review state is unknown."
)


class ChangeReviewState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    NOT_REQUESTED = "not_requested"


class SnapshotAlignmentState(str, Enum):
    CURRENT = "current"
    ASSUMED_CURRENT = "assumed_current"
    STALE = "stale"
    UNKNOWN = "unknown"


class ChangeReviewDiffMode(str, Enum):
    WORKING_TREE = "working_tree"
    STAGED = "staged"
    BASE_TO_WORKING_TREE = "base_to_working_tree"
    BASE_TO_HEAD = "base_to_head"


class ChangedFileStatus(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class ChangeReviewRequest:
    change_kind: ImpactChangeKind = ImpactChangeKind.UNKNOWN
    maximum_files: int = 256
    maximum_subjects_per_file: int = 32
    maximum_subjects: int = 64
    impact_depth: int = 4
    impact_limit: int = 100
    architecture_subject_limit: int = 8
    architecture_advice_limit: int = 8
    include_architecture: bool = True
    assume_snapshot_current: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.change_kind, str):
            object.__setattr__(self, "change_kind", ImpactChangeKind(self.change_kind))
        if not isinstance(self.change_kind, ImpactChangeKind):
            raise TypeError("change review kind must be an ImpactChangeKind")
        bounds = {
            "maximum_files": (1, _MAX_FILES),
            "maximum_subjects_per_file": (1, _MAX_SUBJECTS),
            "maximum_subjects": (1, _MAX_SUBJECTS),
            "impact_depth": (1, 64),
            "impact_limit": (1, 1_000),
            "architecture_subject_limit": (1, 32),
            "architecture_advice_limit": (1, 100),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"change review {name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"change review {name} must be between {minimum} and {maximum}"
                )
        for name in ("include_architecture", "assume_snapshot_current"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"change review {name} must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "change_kind": self.change_kind.value,
            "maximum_files": self.maximum_files,
            "maximum_subjects_per_file": self.maximum_subjects_per_file,
            "maximum_subjects": self.maximum_subjects,
            "impact_depth": self.impact_depth,
            "impact_limit": self.impact_limit,
            "architecture_subject_limit": self.architecture_subject_limit,
            "architecture_advice_limit": self.architecture_advice_limit,
            "include_architecture": self.include_architecture,
            "assume_snapshot_current": self.assume_snapshot_current,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChangeReviewRequest:
        _reject_unknown(value, frozenset({
            "change_kind", "maximum_files", "maximum_subjects_per_file",
            "maximum_subjects", "impact_depth", "impact_limit",
            "architecture_subject_limit", "architecture_advice_limit",
            "include_architecture", "assume_snapshot_current",
        }), "change review request")
        return cls(
            ImpactChangeKind(_text(value.get("change_kind", "unknown"), "change kind")),
            _integer(value.get("maximum_files", 256), "maximum files"),
            _integer(value.get("maximum_subjects_per_file", 32), "subjects per file"),
            _integer(value.get("maximum_subjects", 64), "maximum subjects"),
            _integer(value.get("impact_depth", 4), "impact depth"),
            _integer(value.get("impact_limit", 100), "impact limit"),
            _integer(value.get("architecture_subject_limit", 8), "architecture subject limit"),
            _integer(value.get("architecture_advice_limit", 8), "architecture advice limit"),
            _boolean(value.get("include_architecture", True), "include architecture"),
            _boolean(value.get("assume_snapshot_current", False), "assume current snapshot"),
        )


@dataclass(frozen=True, slots=True)
class ChangeReviewDiff:
    mode: ChangeReviewDiffMode
    fingerprint: str
    base: str | None = None
    head: str | None = None
    repository_head: str | None = None
    base_commit: str | None = None
    head_commit: str | None = None
    workspace_prefix: str = "."
    total_file_count: int = 0
    selected_file_count: int = 0
    omitted_file_count: int = 0
    untracked_files_included: bool = False
    source_content_retained: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            object.__setattr__(self, "mode", ChangeReviewDiffMode(self.mode))
        if _DIFF_FINGERPRINT.fullmatch(self.fingerprint) is None:
            raise ValueError("change review diff fingerprint is malformed")
        for name in ("base", "head", "repository_head", "base_commit", "head_commit"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, f"diff {name}", maximum=512))
        for name in ("repository_head", "base_commit", "head_commit"):
            value = getattr(self, name)
            if value is not None and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value) is None:
                raise ValueError(f"diff {name} must be a full Git commit ID")
            if value is not None:
                object.__setattr__(self, name, value.lower())
        mode_fields = {
            ChangeReviewDiffMode.WORKING_TREE: (
                self.base is None and self.head is None
                and self.base_commit is None and self.head_commit is None
            ),
            ChangeReviewDiffMode.STAGED: (
                self.head is None and self.head_commit is None
                and (self.base is None or self.base_commit is not None)
            ),
            ChangeReviewDiffMode.BASE_TO_WORKING_TREE: (
                self.base is not None and self.head is None
                and self.base_commit is not None and self.head_commit is None
            ),
            ChangeReviewDiffMode.BASE_TO_HEAD: (
                self.base is not None and self.head is not None
                and self.base_commit is not None and self.head_commit is not None
            ),
        }
        if not mode_fields[self.mode]:
            raise ValueError("change review diff mode and revisions are inconsistent")
        object.__setattr__(self, "workspace_prefix", _relative_path(self.workspace_prefix, allow_dot=True))
        total = _integer(self.total_file_count, "diff total file count")
        selected = _integer(self.selected_file_count, "diff selected file count")
        omitted = _integer(self.omitted_file_count, "diff omitted file count")
        if min(total, selected, omitted) < 0 or selected + omitted != total:
            raise ValueError("change review diff file counts are inconsistent")
        if not isinstance(self.untracked_files_included, bool) or not isinstance(
            self.source_content_retained, bool
        ):
            raise TypeError("change review diff retention flags must be booleans")
        if self.untracked_files_included or self.source_content_retained:
            raise ValueError("PR140 diff metadata must exclude untracked files and source content")
        if contains_unsafe_chat_content(self.to_dict()):
            raise ValueError("change review diff metadata must be source-free and private-data-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "fingerprint": self.fingerprint,
            "base": self.base,
            "head": self.head,
            "repository_head": self.repository_head,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "workspace_prefix": self.workspace_prefix,
            "total_file_count": self.total_file_count,
            "selected_file_count": self.selected_file_count,
            "omitted_file_count": self.omitted_file_count,
            "untracked_files_included": self.untracked_files_included,
            "source_content_retained": self.source_content_retained,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChangeReviewDiff:
        _reject_unknown(value, frozenset({
            "mode", "fingerprint", "base", "head", "repository_head",
            "base_commit", "head_commit", "workspace_prefix", "total_file_count",
            "selected_file_count", "omitted_file_count", "untracked_files_included",
            "source_content_retained",
        }), "change review diff")
        return cls(
            ChangeReviewDiffMode(_text(value.get("mode", "working_tree"), "diff mode")),
            _text(value.get("fingerprint", ""), "diff fingerprint"),
            _optional_text(value.get("base"), "diff base"),
            _optional_text(value.get("head"), "diff head"),
            _optional_text(value.get("repository_head"), "repository head"),
            _optional_text(value.get("base_commit"), "base commit"),
            _optional_text(value.get("head_commit"), "head commit"),
            _text(value.get("workspace_prefix", "."), "workspace prefix"),
            _integer(value.get("total_file_count", 0), "total file count"),
            _integer(value.get("selected_file_count", 0), "selected file count"),
            _integer(value.get("omitted_file_count", 0), "omitted file count"),
            _boolean(value.get("untracked_files_included", False), "untracked flag"),
            _boolean(value.get("source_content_retained", False), "source flag"),
        )


@dataclass(frozen=True, slots=True)
class ChangedFileReview:
    path: str
    old_path: str | None
    new_path: str | None
    status: ChangedFileStatus
    binary: bool
    hunk_count: int
    added_line_count: int
    removed_line_count: int
    subjects: tuple[SubjectCandidate, ...] = ()
    candidate_evidence: tuple[PathCandidateEvidence, ...] = ()
    total_subject_count: int = 0
    omitted_subject_count: int = 0
    project_fallback: bool = False
    semantic_confidence: ConfidenceResult = field(
        default_factory=lambda: ConfidenceCalculator().calculate(
            (EvidenceRole("exact_path_identity", (), True),),
            EvidenceIndex().freeze(),
            coverage=0.0,
        )
    )
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path))
        for name in ("old_path", "new_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _relative_path(value))
        if isinstance(self.status, str):
            object.__setattr__(self, "status", ChangedFileStatus(self.status))
        valid_identity = {
            ChangedFileStatus.ADDED: (
                self.old_path is None and self.new_path == self.path
            ),
            ChangedFileStatus.DELETED: (
                self.old_path == self.path and self.new_path is None
            ),
            ChangedFileStatus.MODIFIED: (
                self.old_path == self.path and self.new_path == self.path
            ),
            ChangedFileStatus.RENAMED: (
                self.old_path is not None
                and self.new_path == self.path
                and self.old_path != self.new_path
            ),
        }
        if not valid_identity[self.status]:
            raise ValueError("changed file status and paths are inconsistent")
        if not isinstance(self.binary, bool) or not isinstance(self.project_fallback, bool):
            raise TypeError("changed file flags must be booleans")
        for name in ("hunk_count", "added_line_count", "removed_line_count"):
            count = _integer(getattr(self, name), f"changed file {name}")
            if count < 0:
                raise ValueError(f"changed file {name} must not be negative")
        if self.binary and any(
            getattr(self, name)
            for name in ("hunk_count", "added_line_count", "removed_line_count")
        ):
            raise ValueError("binary changed files cannot retain text hunk facts")
        subjects = tuple(sorted(self.subjects, key=lambda item: item.canonical_id))
        if any(not isinstance(item, SubjectCandidate) for item in subjects):
            raise TypeError("changed file subjects must be SubjectCandidate values")
        if len({item.canonical_id for item in subjects}) != len(subjects):
            raise ValueError("changed file subject IDs must be unique")
        candidate_evidence = tuple(sorted(
            self.candidate_evidence,
            key=lambda item: item.canonical_id,
        ))
        if any(not isinstance(item, PathCandidateEvidence) for item in candidate_evidence):
            raise TypeError("changed file candidate evidence entries are invalid")
        if len({item.canonical_id for item in candidate_evidence}) != len(
            candidate_evidence
        ):
            raise ValueError("changed file candidate evidence IDs must be unique")
        if {item.canonical_id for item in candidate_evidence} != {
            item.canonical_id for item in subjects
        }:
            raise ValueError(
                "changed file candidate evidence must exactly cover returned subjects"
            )
        total = _integer(self.total_subject_count, "changed file total subjects")
        omitted = _integer(self.omitted_subject_count, "changed file omitted subjects")
        if min(total, omitted) < 0 or total != len(subjects) + omitted:
            raise ValueError("changed file subject counts are inconsistent")
        if not isinstance(self.semantic_confidence, ConfidenceResult):
            raise TypeError("changed file semantic confidence is invalid")
        evidence = _evidence_ids(self.evidence_ids, "changed file evidence IDs")
        if not evidence:
            raise ValueError("changed file facts require Git evidence")
        object.__setattr__(self, "subjects", subjects)
        object.__setattr__(self, "candidate_evidence", candidate_evidence)
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(self, "limitations", _strings(self.limitations, "changed file limitations"))
        if contains_absolute_path(self.to_dict()):
            raise ValueError("changed file reviews must not contain absolute paths")
        if contains_unsafe_chat_content(self.to_dict()):
            raise ValueError("changed file reviews must be source-free and private-data-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "status": self.status.value,
            "binary": self.binary,
            "hunk_count": self.hunk_count,
            "added_line_count": self.added_line_count,
            "removed_line_count": self.removed_line_count,
            "subjects": [item.to_dict() for item in self.subjects],
            "candidate_evidence": [
                item.to_dict() for item in self.candidate_evidence
            ],
            "total_subject_count": self.total_subject_count,
            "returned_subject_count": len(self.subjects),
            "omitted_subject_count": self.omitted_subject_count,
            "project_fallback": self.project_fallback,
            "semantic_confidence": self.semantic_confidence.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChangedFileReview:
        _reject_unknown(value, frozenset({
            "path", "old_path", "new_path", "status", "binary", "hunk_count",
            "added_line_count", "removed_line_count", "subjects",
            "candidate_evidence",
            "total_subject_count", "returned_subject_count", "omitted_subject_count",
            "project_fallback", "evidence_ids", "limitations",
            "semantic_confidence",
        }), "changed file review")
        raw_subjects = _mappings(
            value.get("subjects"),
            "changed file subjects",
            maximum_count=_MAX_SUBJECTS,
        )
        subjects = tuple(SubjectCandidate.from_dict(item) for item in raw_subjects)
        candidate_evidence = tuple(
            PathCandidateEvidence.from_dict(item)
            for item in _mappings(
                value.get("candidate_evidence"),
                "changed file candidate evidence",
                maximum_count=_MAX_SUBJECTS,
            )
        )
        returned = _integer(value.get("returned_subject_count", len(subjects)), "returned subjects")
        if returned != len(subjects):
            raise ValueError("changed file returned subject count is inconsistent")
        raw_confidence = _mapping(
            value.get("semantic_confidence"),
            "changed file semantic confidence",
        )
        return cls(
            _text(value.get("path", ""), "changed file path"),
            _optional_text(value.get("old_path"), "changed file old path"),
            _optional_text(value.get("new_path"), "changed file new path"),
            ChangedFileStatus(_text(value.get("status", "modified"), "changed file status")),
            _boolean(value.get("binary", False), "changed file binary"),
            _integer(value.get("hunk_count", 0), "changed file hunk count"),
            _integer(value.get("added_line_count", 0), "changed file added count"),
            _integer(value.get("removed_line_count", 0), "changed file removed count"),
            subjects,
            candidate_evidence,
            _integer(value.get("total_subject_count", 0), "changed file total subjects"),
            _integer(value.get("omitted_subject_count", 0), "changed file omitted subjects"),
            _boolean(value.get("project_fallback", False), "project fallback"),
            ConfidenceResult.from_dict(raw_confidence),
            _evidence_ids(value.get("evidence_ids"), "changed file evidence IDs"),
            _strings(value.get("limitations"), "changed file limitations"),
        )


@dataclass(frozen=True, order=True, slots=True)
class ChangeReviewSection:
    name: str
    state: ChangeReviewState
    item_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = _text(self.name, "review section name", maximum=128)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("review section name must be a portable identifier")
        object.__setattr__(self, "name", name)
        if isinstance(self.state, str):
            object.__setattr__(self, "state", ChangeReviewState(self.state))
        object.__setattr__(
            self,
            "item_ids",
            _strings(
                self.item_ids,
                "review section item IDs",
                maximum_count=_MAX_SECTION_ENTRIES,
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _evidence_ids(
                self.evidence_ids,
                "review section evidence IDs",
                maximum_count=_MAX_SECTION_ENTRIES,
            ),
        )
        limitations = _strings(self.limitations, "review section limitations")
        if self.state not in {ChangeReviewState.AVAILABLE} and not limitations:
            raise ValueError("non-available review sections require a limitation")
        object.__setattr__(self, "limitations", limitations)
        if contains_unsafe_chat_content(self.to_dict()):
            raise ValueError("change review sections must be source-free and private-data-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "item_ids": list(self.item_ids),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChangeReviewSection:
        _reject_unknown(value, frozenset({
            "name", "state", "item_ids", "evidence_ids", "limitations",
        }), "change review section")
        return cls(
            _text(value.get("name", ""), "section name"),
            ChangeReviewState(_text(value.get("state", "unavailable"), "section state")),
            _strings(
                value.get("item_ids"),
                "section item IDs",
                maximum_count=_MAX_SECTION_ENTRIES,
            ),
            _evidence_ids(
                value.get("evidence_ids"),
                "section evidence IDs",
                maximum_count=_MAX_SECTION_ENTRIES,
            ),
            _strings(value.get("limitations"), "section limitations"),
        )


_SECTION_NAMES = frozenset({
    "git_diff", "snapshot_alignment", "subject_mapping", "impact",
    "architecture", "tests", "risk", "migration",
})


@dataclass(frozen=True, slots=True)
class ChangeReviewResponse:
    request: ChangeReviewRequest
    diff: ChangeReviewDiff
    alignment: SnapshotAlignmentState
    changed_files: tuple[ChangedFileReview, ...]
    sections: tuple[ChangeReviewSection, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    lineage: str
    workspace_fingerprint: str
    current_workspace_fingerprint: str | None = None
    impact: ImpactPredictionResponse | None = None
    architecture_reviews: tuple[RefactoringResponse, ...] = ()
    total_subject_count: int = 0
    omitted_subject_count: int = 0
    limitations: tuple[str, ...] = ()
    producer_version: str = CHANGE_REVIEW_PRODUCER
    schema_version: int = CHANGE_REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChangeReviewRequest) or not isinstance(self.diff, ChangeReviewDiff):
            raise TypeError("change review response request and diff are invalid")
        if isinstance(self.alignment, str):
            object.__setattr__(self, "alignment", SnapshotAlignmentState(self.alignment))
        files = tuple(sorted(self.changed_files, key=lambda item: (item.path, item.old_path or "", item.new_path or "")))
        if any(not isinstance(item, ChangedFileReview) for item in files):
            raise TypeError("change review files are invalid")
        if len({(item.old_path, item.new_path) for item in files}) != len(files):
            raise ValueError("change review files must be unique")
        if len({item.path for item in files}) != len(files):
            raise ValueError("change review selected file paths must be unique")
        if len(files) != self.diff.selected_file_count:
            raise ValueError("change review selected file count is inconsistent")
        if len(files) > self.request.maximum_files:
            raise ValueError("change review files exceed the request bound")
        if any(
            len(item.subjects) > self.request.maximum_subjects_per_file
            for item in files
        ):
            raise ValueError("changed file subjects exceed the per-file request bound")
        sections = tuple(sorted(self.sections, key=lambda item: item.name))
        if any(not isinstance(item, ChangeReviewSection) for item in sections):
            raise TypeError("change review sections are invalid")
        if {item.name for item in sections} != _SECTION_NAMES:
            raise ValueError("change review response must report every capability section")
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("change review response requires an EvidenceIndex")
        evidence = self.evidence_index.freeze()
        for record in evidence.records:
            canonical = EvidenceRecord.create(
                record.kind, record.subject_id, record.producer, record.snapshot_id,
                source_refs=record.source_refs, scope=record.scope, language=record.language,
                detail=record.detail, limitations=record.limitations,
                reliability=record.reliability, specificity=record.specificity,
            )
            if canonical != record or record.snapshot_id != self.lineage:
                raise ValueError("change review evidence identity or lineage is inconsistent")
        if self.impact is not None:
            if self.impact.lineage != self.lineage or self.impact.graph_digest != self.graph_digest:
                raise ValueError("change review impact lineage is inconsistent")
        architecture = tuple(sorted(self.architecture_reviews, key=lambda item: item.input_fingerprint))
        if any(not isinstance(item, RefactoringResponse) for item in architecture):
            raise TypeError("change review architecture responses are invalid")
        if any(item.lineage != self.lineage or item.graph_digest != self.graph_digest for item in architecture):
            raise ValueError("change review architecture lineage is inconsistent")
        available_evidence = {item.evidence_id for item in evidence.records}
        if self.impact is not None:
            available_evidence.update(item.evidence_id for item in self.impact.evidence_index.records)
        for response in architecture:
            available_evidence.update(item.evidence_id for item in response.evidence_index.records)
        referenced = {
            evidence_id
            for item in (*files, *sections)
            for evidence_id in item.evidence_ids
        }
        if not referenced.issubset(available_evidence):
            raise ValueError("change review contains dangling evidence references")
        if not {item.evidence_id for item in evidence.records}.issubset(referenced):
            raise ValueError("change review contains unused feature evidence")
        total = _integer(self.total_subject_count, "review total subject count")
        omitted = _integer(self.omitted_subject_count, "review omitted subject count")
        returned = sum(len(item.subjects) for item in files)
        if min(total, omitted) < 0 or total != returned + omitted:
            raise ValueError("change review subject counts are inconsistent")
        if returned > self.request.maximum_subjects:
            raise ValueError("change review subjects exceed the request bound")
        graph_digest = _text(self.graph_digest, "review graph digest", maximum=256)
        lineage = _text(self.lineage, "review lineage", maximum=256)
        workspace_fingerprint = _text(self.workspace_fingerprint, "workspace fingerprint", maximum=256)
        current = _optional_text(self.current_workspace_fingerprint, "current workspace fingerprint", maximum=256)
        response_limitations = _strings(
            self.limitations, "change review limitations"
        )
        if contains_unsafe_chat_content({
            "changed_files": [item.to_dict() for item in files],
            "sections": [item.to_dict() for item in sections],
            "limitations": list(response_limitations),
        }):
            raise ValueError(
                "change review feature data must be source-free and private-data-free"
            )
        expected_alignment = (
            SnapshotAlignmentState.CURRENT
            if current is not None and current == workspace_fingerprint
            else SnapshotAlignmentState.STALE
            if current is not None
            else SnapshotAlignmentState.ASSUMED_CURRENT
            if self.request.assume_snapshot_current
            else SnapshotAlignmentState.UNKNOWN
        )
        if self.alignment is not expected_alignment:
            raise ValueError("change review snapshot alignment is inconsistent")
        _validate_feature_projection(
            self.request,
            self.diff,
            self.alignment,
            files,
            sections,
            evidence,
            self.impact,
            architecture,
            graph_digest=graph_digest,
            response_limitations=response_limitations,
        )
        expected = change_review_fingerprint(
            self.request, self.diff, lineage, graph_digest,
            self.alignment, current,
        )
        if _REVIEW_FINGERPRINT.fullmatch(self.input_fingerprint) is None or self.input_fingerprint != expected:
            raise ValueError("change review input fingerprint is inconsistent")
        if self.alignment in {SnapshotAlignmentState.STALE, SnapshotAlignmentState.UNKNOWN} and (
            self.impact is not None or architecture
        ):
            raise ValueError("stale or unknown snapshots cannot produce semantic change review conclusions")
        if self.producer_version != CHANGE_REVIEW_PRODUCER or self.schema_version != CHANGE_REVIEW_SCHEMA_VERSION:
            raise ValueError("unsupported change review producer or schema")
        object.__setattr__(self, "changed_files", files)
        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(self, "architecture_reviews", architecture)
        object.__setattr__(self, "graph_digest", graph_digest)
        object.__setattr__(self, "lineage", lineage)
        object.__setattr__(self, "workspace_fingerprint", workspace_fingerprint)
        object.__setattr__(self, "current_workspace_fingerprint", current)
        object.__setattr__(self, "limitations", response_limitations)
        if contains_absolute_path(self.to_dict()):
            raise ValueError("change review responses must not contain absolute paths")
        feature_payload = {
            "request": self.request.to_dict(),
            "diff": self.diff.to_dict(),
            "changed_files": [item.to_dict() for item in files],
            "sections": [item.to_dict() for item in sections],
            "evidence_index": evidence.to_dict(),
            "limitations": list(self.limitations),
        }
        if contains_unsafe_chat_content(feature_payload):
            raise ValueError("change review feature data must be source-free and private-data-free")

    def section(self, name: str) -> ChangeReviewSection:
        return next(item for item in self.sections if item.name == name)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "lineage": self.lineage,
            "workspace_fingerprint": self.workspace_fingerprint,
            "current_workspace_fingerprint": self.current_workspace_fingerprint,
            "alignment": self.alignment.value,
            "request": self.request.to_dict(),
            "diff": self.diff.to_dict(),
            "changed_files": [item.to_dict() for item in self.changed_files],
            "sections": [item.to_dict() for item in self.sections],
            "impact": self.impact.to_dict() if self.impact is not None else None,
            "architecture_reviews": [item.to_dict() for item in self.architecture_reviews],
            "evidence_index": self.evidence_index.to_dict(),
            "total_subject_count": self.total_subject_count,
            "returned_subject_count": sum(len(item.subjects) for item in self.changed_files),
            "omitted_subject_count": self.omitted_subject_count,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChangeReviewResponse:
        _reject_unknown(value, frozenset({
            "schema_version", "producer_version", "input_fingerprint", "graph_digest",
            "lineage", "workspace_fingerprint", "current_workspace_fingerprint",
            "alignment", "request", "diff", "changed_files", "sections", "impact",
            "architecture_reviews", "evidence_index", "total_subject_count",
            "returned_subject_count", "omitted_subject_count", "limitations",
        }), "change review response")
        raw_request = _mapping(value.get("request"), "change review request")
        request = ChangeReviewRequest.from_dict(raw_request)
        raw_diff = _mapping(value.get("diff"), "change review diff")
        raw_evidence = _mapping(value.get("evidence_index"), "change review evidence index")
        raw_impact = value.get("impact")
        if raw_impact is not None and not isinstance(raw_impact, Mapping):
            raise TypeError("change review impact must be an object or null")
        files = tuple(
            ChangedFileReview.from_dict(item)
            for item in _mappings(
                value.get("changed_files"),
                "changed files",
                maximum_count=request.maximum_files,
            )
        )
        returned = _integer(value.get("returned_subject_count", sum(len(item.subjects) for item in files)), "returned subject count")
        if returned != sum(len(item.subjects) for item in files):
            raise ValueError("change review returned subject count is inconsistent")
        evidence = _evidence_index_from_dict(
            raw_evidence,
            maximum_count=_MAX_FEATURE_EVIDENCE,
        )
        return cls(
            request,
            ChangeReviewDiff.from_dict(raw_diff),
            SnapshotAlignmentState(_text(value.get("alignment", "unknown"), "snapshot alignment")),
            files,
            tuple(
                ChangeReviewSection.from_dict(item)
                for item in _mappings(
                    value.get("sections"), "review sections", maximum_count=8
                )
            ),
            evidence,
            _text(value.get("input_fingerprint", ""), "input fingerprint"),
            _text(value.get("graph_digest", ""), "graph digest"),
            _text(value.get("lineage", ""), "lineage"),
            _text(value.get("workspace_fingerprint", ""), "workspace fingerprint"),
            _optional_text(value.get("current_workspace_fingerprint"), "current workspace fingerprint"),
            ImpactPredictionResponse.from_dict(raw_impact) if isinstance(raw_impact, Mapping) else None,
            tuple(
                RefactoringResponse.from_dict(item)
                for item in _mappings(
                    value.get("architecture_reviews"),
                    "architecture reviews",
                    maximum_count=request.architecture_subject_limit,
                )
            ),
            _integer(value.get("total_subject_count", 0), "total subject count"),
            _integer(value.get("omitted_subject_count", 0), "omitted subject count"),
            _strings(value.get("limitations"), "change review limitations"),
            _text(value.get("producer_version", CHANGE_REVIEW_PRODUCER), "producer version"),
            _integer(value.get("schema_version", CHANGE_REVIEW_SCHEMA_VERSION), "schema version"),
        )


def change_review_fingerprint(
    request: ChangeReviewRequest,
    diff: ChangeReviewDiff,
    lineage: str,
    graph_digest: str,
    alignment: SnapshotAlignmentState,
    current_workspace_fingerprint: str | None,
) -> str:
    if not isinstance(request, ChangeReviewRequest):
        raise TypeError("change review fingerprint requires a request")
    if not isinstance(diff, ChangeReviewDiff):
        raise TypeError("change review fingerprint requires normalized diff metadata")
    if isinstance(alignment, str):
        alignment = SnapshotAlignmentState(alignment)
    payload = {
        "producer": CHANGE_REVIEW_PRODUCER,
        "schema_version": CHANGE_REVIEW_SCHEMA_VERSION,
        "request": request.to_dict(),
        "diff": diff.to_dict(),
        "lineage": _text(lineage, "lineage"),
        "graph_digest": _text(graph_digest, "graph digest"),
        "alignment": alignment.value,
        "current_workspace_fingerprint": current_workspace_fingerprint,
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return f"change-review:{digest}"


def _git_evidence_record(
    *,
    lineage: str,
    diff_fingerprint: str,
    path: str,
    old_path: str | None,
    new_path: str | None,
    status: ChangedFileStatus,
    binary: bool,
    hunk_count: int,
    added_line_count: int,
    removed_line_count: int,
) -> EvidenceRecord:
    subject_digest = hashlib.sha256(
        f"{old_path}|{new_path}".encode("utf-8")
    ).hexdigest()
    return EvidenceRecord.create(
        EvidenceKind.REPOSITORY_METADATA,
        f"changed-file:{subject_digest}",
        CHANGE_REVIEW_PRODUCER,
        lineage,
        source_refs=(diff_fingerprint,),
        scope="git-diff",
        detail={
            "path": path,
            "old_path": old_path or "<none>",
            "new_path": new_path or "<none>",
            "status": status.value,
            "binary": str(binary).lower(),
            "hunk_count": hunk_count,
            "added_line_count": added_line_count,
            "removed_line_count": removed_line_count,
        },
        limitations=(
            "Observed Git metadata contains no source content or semantic change classification.",
            _UNTRACKED_LIMITATION,
        ),
        reliability=1.0,
        specificity=1.0,
    )


def _mapping_evidence_record(
    *,
    lineage: str,
    file_record: EvidenceRecord,
    path: str,
    total_subject_count: int,
    returned_subject_count: int,
    project_fallback: bool,
    alignment: SnapshotAlignmentState,
) -> EvidenceRecord:
    return EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        file_record.subject_id,
        CHANGE_REVIEW_PRODUCER,
        lineage,
        source_refs=(file_record.evidence_id,),
        scope="change-review-path",
        detail={
            "path": path,
            "total_subject_count": total_subject_count,
            "returned_subject_count": returned_subject_count,
            "omitted_subject_count": total_subject_count - returned_subject_count,
            "project_fallback": str(project_fallback).lower(),
            "snapshot_alignment": alignment.value,
        },
        limitations=(
            _FILE_ASSOCIATION_LIMITATION,
            (
                "Containing-project fallback is structural context, not exact subject identity."
                if project_fallback
                else "Only exact persisted paths can establish current file association."
            ),
        ),
        reliability=1.0,
        specificity=0.50 if project_fallback else 1.0,
    )


def _association_evidence_record(
    *,
    lineage: str,
    file_record: EvidenceRecord,
    candidate: SubjectCandidate,
    path: str,
    project_fallback: bool,
    path_source_refs: tuple[str, ...],
) -> EvidenceRecord:
    return EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        candidate.canonical_id,
        CHANGE_REVIEW_PRODUCER,
        lineage,
        source_refs=(file_record.evidence_id, *path_source_refs),
        scope=candidate.project or "repository",
        language=candidate.language,
        detail={
            "path": path,
            "association": (
                "containing_project" if project_fallback else "exact_declared_path"
            ),
        },
        limitations=(
            (
                "Project containment is structural context only and was not used as proof of a changed subject."
                if project_fallback
                else _FILE_ASSOCIATION_LIMITATION
            ),
        ),
        reliability=1.0,
        specificity=0.50 if project_fallback else 0.70,
    )


def _validate_feature_projection(
    request: ChangeReviewRequest,
    diff: ChangeReviewDiff,
    alignment: SnapshotAlignmentState,
    files: tuple[ChangedFileReview, ...],
    sections: tuple[ChangeReviewSection, ...],
    evidence: EvidenceIndex,
    impact: ImpactPredictionResponse | None,
    architecture: tuple[RefactoringResponse, ...],
    *,
    graph_digest: str,
    response_limitations: tuple[str, ...],
) -> None:
    """Reject self-consistent IDs whose serialized facts were re-projected."""

    feature_records = {item.evidence_id: item for item in evidence.records}
    file_evidence: set[str] = set()
    git_ids: list[str] = []
    mapping_ids: list[str] = []
    exact_roots: set[str] = set()
    architecture_roots: set[str] = set()
    subject_ids: set[str] = set()

    for item in files:
        records = tuple(
            feature_records[evidence_id]
            for evidence_id in item.evidence_ids
            if evidence_id in feature_records
        )
        if len(records) != len(item.evidence_ids):
            raise ValueError("changed file evidence must be owned by PR140")
        git_records = tuple(
            record for record in records if record.scope == "git-diff"
        )
        map_records = tuple(
            record for record in records if record.scope == "change-review-path"
        )
        association_records = tuple(
            record
            for record in records
            if record.scope not in {"git-diff", "change-review-path"}
        )
        if len(git_records) != 1 or len(map_records) != 1:
            raise ValueError("changed file evidence projection is incomplete")
        expected_git = _git_evidence_record(
            lineage=git_records[0].snapshot_id,
            diff_fingerprint=diff.fingerprint,
            path=item.path,
            old_path=item.old_path,
            new_path=item.new_path,
            status=item.status,
            binary=item.binary,
            hunk_count=item.hunk_count,
            added_line_count=item.added_line_count,
            removed_line_count=item.removed_line_count,
        )
        if git_records[0] != expected_git:
            raise ValueError("changed file Git evidence projection is inconsistent")
        expected_mapping = _mapping_evidence_record(
            lineage=map_records[0].snapshot_id,
            file_record=expected_git,
            path=item.path,
            total_subject_count=item.total_subject_count,
            returned_subject_count=len(item.subjects),
            project_fallback=item.project_fallback,
            alignment=alignment,
        )
        if map_records[0] != expected_mapping:
            raise ValueError("changed file mapping evidence projection is inconsistent")

        provenance = {
            entry.canonical_id: entry.source_refs
            for entry in item.candidate_evidence
        }
        allowed_path_refs = {
            "global_symbol.metadata:source",
            "semantic_graph.node.metadata:path",
            f"declared_dependency.source:{item.path}",
        }
        for source_refs in provenance.values():
            refs = set(source_refs)
            if item.project_fallback:
                if (
                    "canonical_subject_resolver:project_path_containment" not in refs
                    or not refs.difference({
                        "canonical_subject_resolver:project_path_containment"
                    })
                    or not refs.difference({
                        "canonical_subject_resolver:project_path_containment"
                    }).issubset(allowed_path_refs)
                ):
                    raise ValueError("project fallback provenance is inconsistent")
            elif (
                "canonical_subject_resolver:project_path_containment" in refs
                or not refs
                or not refs.issubset(allowed_path_refs)
            ):
                raise ValueError("exact path provenance is inconsistent")
        expected_associations = tuple(
            _association_evidence_record(
                lineage=expected_git.snapshot_id,
                file_record=expected_git,
                candidate=candidate,
                path=item.path,
                project_fallback=item.project_fallback,
                path_source_refs=provenance[candidate.canonical_id],
            )
            for candidate in item.subjects
        )
        if tuple(sorted(association_records)) != tuple(sorted(expected_associations)):
            raise ValueError("changed file subject evidence projection is inconsistent")
        expected_ids = {
            expected_git.evidence_id,
            expected_mapping.evidence_id,
            *(record.evidence_id for record in expected_associations),
        }
        if set(item.evidence_ids) != expected_ids:
            raise ValueError("changed file evidence references are inconsistent")

        exact_association_ids = (
            tuple(record.evidence_id for record in expected_associations)
            if not item.project_fallback
            else ()
        )
        expected_confidence = ConfidenceCalculator().calculate(
            (
                EvidenceRole("git_change", (expected_git.evidence_id,), True),
                EvidenceRole("path_mapping", (expected_mapping.evidence_id,), True),
                EvidenceRole("exact_path_identity", exact_association_ids, True),
            ),
            evidence,
            coverage=(
                len(item.subjects) / item.total_subject_count
                if item.total_subject_count else 0.0
            ),
            ambiguity_penalty=(
                0.10
                if item.total_subject_count > 1 and not item.project_fallback
                else 0.0
            ),
        )
        if item.semantic_confidence != expected_confidence:
            raise ValueError("changed file semantic confidence is inconsistent")
        if item.limitations != _expected_file_limitations(item, alignment):
            raise ValueError("changed file limitations are inconsistent")

        file_evidence.update(expected_ids)
        git_ids.append(expected_git.evidence_id)
        mapping_ids.extend((
            expected_mapping.evidence_id,
            *(record.evidence_id for record in expected_associations),
        ))
        subject_ids.update(candidate.canonical_id for candidate in item.subjects)
        architecture_roots.update(candidate.canonical_id for candidate in item.subjects)
        if not item.project_fallback:
            exact_roots.update(candidate.canonical_id for candidate in item.subjects)

    if file_evidence != set(feature_records):
        raise ValueError("change review feature evidence is not file-scoped")

    ordered_exact_roots = tuple(sorted(exact_roots))
    semantic_enabled = alignment in {
        SnapshotAlignmentState.CURRENT,
        SnapshotAlignmentState.ASSUMED_CURRENT,
    }
    if semantic_enabled and ordered_exact_roots and graph_digest != "unavailable":
        if impact is None:
            raise ValueError("change review impact response is missing")
        expected_impact_request = ImpactPredictionRequest(
            SubjectQuery(ordered_exact_roots[0]),
            request.change_kind,
            max_depth=request.impact_depth,
            limit=request.impact_limit,
            include_tests=True,
            include_dependencies=True,
            include_risk=True,
            additional_subjects=tuple(
                SubjectQuery(subject_id)
                for subject_id in ordered_exact_roots[1:]
            ),
        )
        if impact.request != expected_impact_request:
            raise ValueError("change review impact request is inconsistent")
    elif impact is not None:
        raise ValueError("change review impact response has no valid changed root")

    allowed_architecture_roots = set(
        sorted(architecture_roots)[: request.architecture_subject_limit]
    )
    architecture_subjects: set[str] = set()
    advice_count = 0
    for response in architecture:
        nested_request = response.request
        subject_id = nested_request.subject.identifier
        if (
            not request.include_architecture
            or not semantic_enabled
            or subject_id not in allowed_architecture_roots
            or subject_id in architecture_subjects
            or nested_request.subject != SubjectQuery(subject_id)
            or nested_request.families != (RefactoringFamily.CYCLE_BREAKING,)
            or nested_request.include_impact
            or nested_request.impact_depth != request.impact_depth
            or nested_request.limit > request.architecture_advice_limit
            or not response.advice
        ):
            raise ValueError("change review architecture request is inconsistent")
        architecture_subjects.add(subject_id)
        advice_count += len(response.advice)
    if advice_count > request.architecture_advice_limit:
        raise ValueError("change review architecture advice exceeds the request bound")

    expected_response_limitations = {
        _UNTRACKED_LIMITATION,
        "PR140 reviews current snapshot evidence; it does not compare semantic state before and after the diff.",
    }
    if diff.omitted_file_count:
        expected_response_limitations.add(
            f"{diff.omitted_file_count} changed file(s) were omitted by the deterministic request bound."
        )
    total_subjects = sum(item.total_subject_count for item in files)
    returned_subjects = sum(len(item.subjects) for item in files)
    if total_subjects > returned_subjects:
        expected_response_limitations.add(
            f"{total_subjects - returned_subjects} file-associated subject(s) were omitted by deterministic bounds."
        )
    if alignment is SnapshotAlignmentState.ASSUMED_CURRENT:
        expected_response_limitations.add(
            "Snapshot currency was explicitly assumed by the caller and was not independently verified."
        )
    elif alignment is SnapshotAlignmentState.UNKNOWN:
        expected_response_limitations.add(
            "Snapshot currency is unknown; semantic enrichment was disabled."
        )
    elif alignment is SnapshotAlignmentState.STALE:
        expected_response_limitations.add(
            "The supplied workspace fingerprint differs from the snapshot; semantic enrichment was disabled."
        )
    if graph_digest == "unavailable":
        expected_response_limitations.add(
            "The canonical PR129 graph is unavailable or incompatible."
        )
    if response_limitations != tuple(sorted(expected_response_limitations)):
        raise ValueError("change review response limitations are inconsistent")

    by_name = {item.name: item for item in sections}
    git_limitations = {_UNTRACKED_LIMITATION}
    if diff.omitted_file_count:
        git_limitations.add(
            "Changed files were deterministically truncated before semantic review."
        )
    _require_section_projection(
        by_name["git_diff"],
        ChangeReviewState.PARTIAL if diff.omitted_file_count else ChangeReviewState.AVAILABLE,
        (item.path for item in files),
        git_ids,
        git_limitations,
    )
    alignment_state = {
        SnapshotAlignmentState.CURRENT: ChangeReviewState.AVAILABLE,
        SnapshotAlignmentState.ASSUMED_CURRENT: ChangeReviewState.PARTIAL,
        SnapshotAlignmentState.STALE: ChangeReviewState.STALE,
        SnapshotAlignmentState.UNKNOWN: ChangeReviewState.UNAVAILABLE,
    }[alignment]
    alignment_limitations = {
        SnapshotAlignmentState.CURRENT: (),
        SnapshotAlignmentState.ASSUMED_CURRENT: (
            "Snapshot currency was explicitly assumed and not independently verified.",
        ),
        SnapshotAlignmentState.STALE: (
            "Current workspace content differs from the semantic snapshot fingerprint.",
        ),
        SnapshotAlignmentState.UNKNOWN: (
            "No current workspace fingerprint was supplied and currency was not assumed.",
        ),
    }[alignment]
    _require_section_projection(
        by_name["snapshot_alignment"],
        alignment_state,
        (),
        (),
        alignment_limitations,
    )
    if alignment is SnapshotAlignmentState.STALE:
        mapping_state = ChangeReviewState.STALE
        mapping_limitations = (
            "Stale snapshot subjects were not associated with current changes.",
        )
    elif alignment is SnapshotAlignmentState.UNKNOWN:
        mapping_state = ChangeReviewState.UNAVAILABLE
        mapping_limitations = (
            "Snapshot currency is unknown; exact subject association was disabled.",
        )
    elif graph_digest == "unavailable":
        mapping_state = ChangeReviewState.UNAVAILABLE
        mapping_limitations = (
            "The canonical PR129 graph is unavailable or incompatible.",
        )
    elif exact_roots:
        mapping_state = ChangeReviewState.PARTIAL
        mapping_limitations_set = {_FILE_ASSOCIATION_LIMITATION}
        semantic_files = tuple(
            item
            for item in files
            if not item.binary and item.status is not ChangedFileStatus.DELETED
        )
        if any(not item.subjects or item.project_fallback for item in semantic_files):
            mapping_limitations_set.add(
                "Some changed paths had no exact canonical subject association."
            )
        if any(item.omitted_subject_count for item in files):
            mapping_limitations_set.add(
                "Some file-associated subjects were omitted by bounds."
            )
        mapping_limitations = tuple(sorted(mapping_limitations_set))
    else:
        mapping_state = ChangeReviewState.INSUFFICIENT
        mapping_limitations_set = {
            _FILE_ASSOCIATION_LIMITATION,
            "No exact changed-path subject was available for downstream analysis.",
        }
        semantic_files = tuple(
            item
            for item in files
            if not item.binary and item.status is not ChangedFileStatus.DELETED
        )
        if any(not item.subjects or item.project_fallback for item in semantic_files):
            mapping_limitations_set.add(
                "Some changed paths had no exact canonical subject association."
            )
        if any(item.omitted_subject_count for item in files):
            mapping_limitations_set.add(
                "Some file-associated subjects were omitted by bounds."
            )
        mapping_limitations = tuple(sorted(mapping_limitations_set))
    _require_section_projection(
        by_name["subject_mapping"],
        mapping_state,
        subject_ids,
        mapping_ids,
        mapping_limitations,
    )

    impact_evidence = (
        tuple(record.evidence_id for record in impact.evidence_index.records)
        if impact is not None else ()
    )
    impact_items = (
        tuple(item.subject.canonical_id for item in impact.findings)
        if impact is not None else ()
    )
    if alignment is SnapshotAlignmentState.STALE:
        impact_state = ChangeReviewState.STALE
        impact_limitations = (
            "Impact was not evaluated against stale semantic identity.",
        )
    elif alignment is SnapshotAlignmentState.UNKNOWN:
        impact_state = ChangeReviewState.UNAVAILABLE
        impact_limitations = (
            "Impact requires a current or explicitly assumed-current snapshot.",
        )
    elif impact is None or not exact_roots:
        impact_state = ChangeReviewState.INSUFFICIENT
        impact_limitations = (
            "No exact current-snapshot subject was available as an impact root.",
        )
    elif impact.findings:
        impact_state = ChangeReviewState.PARTIAL
        impact_limitations = tuple(sorted({
            *impact.limitations,
            "Impact is limited to authoritative relationships represented in the current canonical graph.",
        }))
    else:
        impact_state = ChangeReviewState.INSUFFICIENT
        impact_limitations = tuple(sorted({
            *impact.limitations,
            "No represented in-repository impact was proven; external and unrepresented consumers remain possible.",
        }))
    _require_section_projection(
        by_name["impact"],
        impact_state,
        impact_items,
        impact_evidence,
        impact_limitations,
    )

    test_findings = tuple(
        item
        for item in (impact.findings if impact is not None else ())
        if item.category is ImpactCategory.TEST
    )
    risk_findings = tuple(
        item
        for item in (impact.findings if impact is not None else ())
        if item.risk_context is not None
    )
    tests_state = _derived_finding_state(
        "tests", alignment, impact, bool(test_findings)
    )
    risk_state = _derived_finding_state(
        "risk", alignment, impact, bool(risk_findings)
    )
    tests_capability = next(
        (item for item in impact.capabilities if item.name == "tests"),
        None,
    ) if impact is not None else None
    risk_capability = next(
        (item for item in impact.capabilities if item.name == "risk"),
        None,
    ) if impact is not None else None
    if alignment is SnapshotAlignmentState.STALE:
        tests_limitations = (
            "Targeted tests were not selected from stale semantic evidence.",
        )
        risk_limitations = (
            "Current-snapshot risk was not attached to a stale change scope.",
        )
    elif impact is None:
        tests_limitations = (
            "Targeted test selection requires exact subjects and compatible PR131/PR136 evidence.",
            "No evidence-backed targeted test was returned; missing call or test coverage must not be interpreted as evidence that no tests are required.",
        )
        risk_limitations = (
            "Risk requires compatible PR132 evidence attached to an exact subject or proven impact.",
        )
    elif test_findings:
        tests_limitations = tuple(sorted({
            *(tests_capability.limitations if tests_capability is not None else ()),
            "Recommendations cover only tests linked by compatible structured evidence.",
        }))
        risk_limitations = (
            "Risk values are existing PR132 current-snapshot context; the diff is not claimed to have introduced them.",
        ) if risk_findings else tuple(sorted({
            *(risk_capability.limitations if risk_capability is not None else ()),
            "No compatible risk context was attached; absence is not evidence of low risk.",
        }))
    else:
        tests_limitations = tuple(sorted({
            *(tests_capability.limitations if tests_capability is not None else ()),
            "No evidence-backed targeted test was returned; missing call or test coverage must not be interpreted as evidence that no tests are required.",
        }))
        risk_limitations = (
            "Risk values are existing PR132 current-snapshot context; the diff is not claimed to have introduced them.",
        ) if risk_findings else tuple(sorted({
            *(risk_capability.limitations if risk_capability is not None else ()),
            "No compatible risk context was attached; absence is not evidence of low risk.",
        }))
    _require_section_projection(
        by_name["tests"],
        tests_state,
        (item.subject.canonical_id for item in test_findings),
        (
            evidence_id
            for item in test_findings
            for evidence_id in item.evidence_ids
        ),
        tests_limitations,
    )
    _require_section_projection(
        by_name["risk"],
        risk_state,
        (item.subject.canonical_id for item in risk_findings),
        (
            evidence_id
            for item in risk_findings
            if item.risk_context is not None
            for evidence_id in item.risk_context.evidence_ids
        ),
        risk_limitations,
    )

    advice = tuple(item for response in architecture for item in response.advice)
    architecture_evidence = tuple(
        record.evidence_id
        for response in architecture
        for record in response.evidence_index.records
    )
    advice_ids = tuple(item.advice_id for item in advice)
    if not request.include_architecture:
        architecture_state = migration_state = ChangeReviewState.NOT_REQUESTED
        architecture_limitations = ("Architecture review was not requested.",)
        migration_limitations = (
            "Migration context was not requested with architecture review.",
        )
    elif alignment is SnapshotAlignmentState.STALE:
        architecture_state = migration_state = ChangeReviewState.STALE
        architecture_limitations = (
            "Architecture context was not evaluated against stale semantic evidence.",
        )
        migration_limitations = (
            "Migration context was not evaluated against stale semantic evidence.",
        )
    elif alignment is SnapshotAlignmentState.UNKNOWN:
        architecture_state = migration_state = ChangeReviewState.UNAVAILABLE
        architecture_limitations = (
            "Architecture context requires a current or explicitly assumed-current snapshot.",
        )
        migration_limitations = (
            "Migration context requires a current or explicitly assumed-current snapshot.",
        )
    elif advice:
        architecture_state = migration_state = ChangeReviewState.PARTIAL
        common_architecture_limitations = {
            *(limitation for response in architecture for limitation in response.limitations),
            "These are existing fully revalidated dependency-cycle seams in the analyzed snapshot; the diff is not claimed to have introduced them.",
        }
        if len(architecture_roots) > request.architecture_subject_limit:
            common_architecture_limitations.add(
                "Architecture review subjects were deterministically bounded."
            )
        if advice_count >= request.architecture_advice_limit:
            common_architecture_limitations.add(
                "Architecture advice reached its deterministic global result bound; additional compatible advice may exist."
            )
        architecture_limitations = tuple(sorted(common_architecture_limitations))
        migration_limitations = tuple(sorted({
            *common_architecture_limitations,
            "Only PR137 evidence-backed preconditions and verification steps are available; no general migration plan was generated.",
        }))
    elif architecture_roots:
        architecture_state = ChangeReviewState.INSUFFICIENT
        migration_state = ChangeReviewState.UNSUPPORTED
        architecture_limitations_set = {
            "No fully revalidated PR137 cycle seam intersected the exact changed scope; no clean-architecture claim is implied.",
        }
        if len(architecture_roots) > request.architecture_subject_limit:
            architecture_limitations_set.add(
                "Architecture review subjects were deterministically bounded."
            )
        architecture_limitations = tuple(sorted(architecture_limitations_set))
        migration_limitations = (
            "General migration planning is unsupported without verified cycle-seam or semantic before/after evidence.",
        )
    else:
        architecture_state = ChangeReviewState.INSUFFICIENT
        migration_state = ChangeReviewState.UNSUPPORTED
        architecture_limitations = (
            "No exact changed subject was available for architecture scope intersection.",
        )
        migration_limitations = (
            "General migration planning is unsupported without verified PR137 cycle-seam evidence.",
        )
    _require_section_projection(
        by_name["architecture"],
        architecture_state,
        advice_ids,
        architecture_evidence,
        architecture_limitations,
    )
    _require_section_projection(
        by_name["migration"],
        migration_state,
        advice_ids,
        architecture_evidence,
        migration_limitations,
    )


def _derived_finding_state(
    capability_name: str,
    alignment: SnapshotAlignmentState,
    impact: ImpactPredictionResponse | None,
    has_findings: bool,
) -> ChangeReviewState:
    if alignment is SnapshotAlignmentState.STALE:
        return ChangeReviewState.STALE
    if impact is None:
        return ChangeReviewState.UNAVAILABLE
    if has_findings:
        return ChangeReviewState.PARTIAL
    capability = next(
        (item for item in impact.capabilities if item.name == capability_name),
        None,
    )
    state = {
        ImpactCapabilityState.AVAILABLE: ChangeReviewState.AVAILABLE,
        ImpactCapabilityState.PARTIAL: ChangeReviewState.PARTIAL,
        ImpactCapabilityState.UNAVAILABLE: ChangeReviewState.UNAVAILABLE,
        ImpactCapabilityState.INCOMPATIBLE: ChangeReviewState.INCOMPATIBLE,
        ImpactCapabilityState.UNSUPPORTED: ChangeReviewState.UNSUPPORTED,
    }.get(getattr(capability, "state", None), ChangeReviewState.UNAVAILABLE)
    return ChangeReviewState.INSUFFICIENT if state is ChangeReviewState.AVAILABLE else state


def _require_section_projection(
    section: ChangeReviewSection,
    state: ChangeReviewState,
    item_ids: Iterable[str],
    evidence_ids: Iterable[str],
    limitations: Iterable[str],
) -> None:
    expected_items = tuple(sorted(set(item_ids)))
    expected_evidence = tuple(sorted(set(evidence_ids)))
    expected_limitations = tuple(sorted(set(limitations)))
    if (
        section.state is not state
        or section.item_ids != expected_items
        or section.evidence_ids != expected_evidence
        or section.limitations != expected_limitations
    ):
        raise ValueError(f"change review {section.name} projection is inconsistent")


def _expected_file_limitations(
    item: ChangedFileReview,
    alignment: SnapshotAlignmentState,
) -> tuple[str, ...]:
    limitations = {_FILE_ASSOCIATION_LIMITATION}
    if item.binary:
        limitations.add(
            "Binary changes have no source-free declaration attribution."
        )
    elif item.status is ChangedFileStatus.DELETED:
        limitations.add(
            "Deleted subjects require a compatible base snapshot; current-snapshot identity was not guessed."
        )
    elif alignment is SnapshotAlignmentState.STALE:
        limitations.add(
            "Semantic association was disabled because the snapshot is stale."
        )
    elif alignment is SnapshotAlignmentState.UNKNOWN:
        limitations.add(
            "Semantic association was disabled because snapshot currency is unknown."
        )
    else:
        if item.total_subject_count == 0:
            limitations.add(
                "No exact current-snapshot subject was associated with this path; absence is not proof of no impact."
            )
        if item.project_fallback:
            limitations.add(
                "Only containing-project context was available; it was not used as an exact changed-subject impact root."
            )
        elif item.total_subject_count > 1:
            limitations.add(
                "The exact path is associated with multiple canonical subjects; path evidence does not identify which declaration a hunk changed."
            )
    if item.total_subject_count > len(item.subjects):
        limitations.add(
            "File-associated subjects were deterministically bounded before downstream analysis."
        )
    if item.status is ChangedFileStatus.RENAMED:
        limitations.add(
            "Git rename metadata does not prove semantic identity continuity between old and new subjects."
        )
    return tuple(sorted(limitations))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _evidence_index_from_dict(
    value: Mapping[str, object],
    *,
    maximum_count: int = _MAX_FEATURE_EVIDENCE,
) -> EvidenceIndex:
    _reject_unknown(
        value,
        frozenset({"schema_version", "records"}),
        "change review evidence index",
    )
    if _integer(value.get("schema_version", 1), "evidence schema version") != 1:
        raise ValueError("unsupported change review evidence schema")
    records = []
    seen: set[str] = set()
    expected = frozenset({
        "evidence_id", "kind", "subject_id", "producer", "snapshot_id",
        "source_refs", "scope", "language", "detail", "limitations",
        "reliability", "specificity",
    })
    for item in _mappings(
        value.get("records"),
        "change review evidence records",
        maximum_count=maximum_count,
    ):
        _reject_unknown(item, expected, "change review evidence record")
        missing = expected.difference(item)
        if missing:
            raise ValueError(
                "missing change review evidence fields: "
                + ", ".join(sorted(missing))
            )
        record = EvidenceRecord.from_dict(item)
        if record.evidence_id in seen:
            raise ValueError("change review evidence IDs must be unique")
        seen.add(record.evidence_id)
        records.append(record)
    return EvidenceIndex(records, frozen=True)


def _mappings(
    value: object,
    label: str,
    *,
    maximum_count: int = _MAX_SECTION_ENTRIES,
) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be an array")
    if len(value) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    if any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"{label} entries must be objects")
    return tuple(item for item in value if isinstance(item, Mapping))


def _text(value: object, label: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    text = value.strip()
    if (
        not text
        or len(text) > maximum
        or any(
            ord(character) < 32
            or ord(character) == 127
            or character == "\ufffd"
            for character in text
        )
    ):
        raise ValueError(f"{label} must be a bounded non-empty one-line string")
    return text


def _optional_text(value: object, label: str, *, maximum: int = _MAX_TEXT) -> str | None:
    if value is None:
        return None
    return _text(value, label, maximum=maximum)


def _relative_path(value: object, *, allow_dot: bool = False) -> str:
    from pathlib import PurePosixPath

    text = _text(value, "relative path", maximum=4_096).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if allow_dot and text in {"", "."}:
        return "."
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", text):
        raise ValueError("change review paths must be workspace-relative")
    return path.as_posix()


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _strings(
    value: object,
    label: str,
    *,
    maximum_count: int = 512,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be an array")
    result = tuple(sorted({_text(item, f"{label} entry") for item in value}))
    if len(result) > maximum_count:
        raise ValueError(f"{label} contains too many entries")
    return result


def _evidence_ids(
    value: object,
    label: str,
    *,
    maximum_count: int = 512,
) -> tuple[str, ...]:
    result = _strings(value, label, maximum_count=maximum_count)
    if any(_EVIDENCE_ID.fullmatch(item) is None for item in result):
        raise ValueError(f"{label} contains a malformed evidence ID")
    return result


def _reject_unknown(value: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(sorted(unknown))}")
