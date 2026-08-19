'''Immutable deterministic contracts for Atlas agent post-change review.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib

from moughorai.agent_context.models import canonical_json


AGENT_REVIEW_FORMAT = 'atlas-agent-review'
AGENT_REVIEW_VERSION = 1
AGENT_REVIEW_PRODUCER = 'atlas-pr178/1'


class ScopeClassification(str, Enum):
    WITHIN_EXPECTED_SURFACE = 'WITHIN_EXPECTED_SURFACE'
    PLAUSIBLE_SCOPE_EXPANSION = 'PLAUSIBLE_SCOPE_EXPANSION'
    UNEXPECTED_SCOPE = 'UNEXPECTED_SCOPE'
    UNREPRESENTED_CHANGE = 'UNREPRESENTED_CHANGE'


class EvidenceFreshness(str, Enum):
    PRE_CHANGE_EVIDENCE = 'PRE_CHANGE_EVIDENCE'
    STALE_FOR_CURRENT_SEMANTICS = 'STALE_FOR_CURRENT_SEMANTICS'
    NO_PRE_CHANGE_EVIDENCE = 'NO_PRE_CHANGE_EVIDENCE'


class BaseProvenance(str, Enum):
    UNKNOWN_BASE_PROVENANCE = 'UNKNOWN_BASE_PROVENANCE'


class ChangedFileStatus(str, Enum):
    MODIFIED = 'modified'
    ADDED = 'added'
    DELETED = 'deleted'
    RENAMED = 'renamed'
    UNTRACKED = 'untracked'


@dataclass(frozen=True, slots=True)
class AgentReviewConfiguration:
    maximum_changed_files: int = 256
    maximum_subjects_per_file: int = 32
    maximum_graph_relations: int = 256
    maximum_tests: int = 128
    maximum_requirements: int = 128
    maximum_line_numbers_per_file: int = 2_048

    def __post_init__(self) -> None:
        expected = (256, 32, 256, 128, 128, 2_048)
        actual = tuple(getattr(self, name) for name in (
            'maximum_changed_files', 'maximum_subjects_per_file',
            'maximum_graph_relations', 'maximum_tests',
            'maximum_requirements', 'maximum_line_numbers_per_file',
        ))
        if actual != expected:
            raise ValueError('agent review v1 must use the versioned bounds')

    def to_dict(self) -> dict[str, int]:
        return {
            'maximum_changed_files': self.maximum_changed_files,
            'maximum_subjects_per_file': self.maximum_subjects_per_file,
            'maximum_graph_relations': self.maximum_graph_relations,
            'maximum_tests': self.maximum_tests,
            'maximum_requirements': self.maximum_requirements,
            'maximum_line_numbers_per_file': self.maximum_line_numbers_per_file,
        }


@dataclass(frozen=True, slots=True)
class AgentReviewSubject:
    canonical_id: str
    kind: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_path: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            'canonical_id': self.canonical_id,
            'kind': self.kind,
            'qualified_name': self.qualified_name,
            'simple_name': self.simple_name,
            'project': self.project,
            'source_path': self.source_path,
            'mapping': 'exact_pre_change_subject',
        }


@dataclass(frozen=True, slots=True)
class AgentReviewRoot:
    canonical_subject_id: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_path: str | None
    rank: int
    classification: str
    role: str
    confidence: str
    authority: str

    def to_dict(self) -> dict[str, object]:
        return {
            'canonical_subject_id': self.canonical_subject_id,
            'qualified_name': self.qualified_name,
            'simple_name': self.simple_name,
            'project': self.project,
            'source_path': self.source_path,
            'rank': self.rank,
            'classification': self.classification,
            'role': self.role,
            'confidence': self.confidence,
            'authority': self.authority,
        }


@dataclass(frozen=True, slots=True)
class AgentReviewReference:
    canonical_id: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_ref: str | None
    role: str | None
    confidence: str | None
    edge_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            'id': self.canonical_id,
            'qualified_name': self.qualified_name,
            'simple_name': self.simple_name,
            'project': self.project,
            'source_ref': self.source_ref,
            'role': self.role,
            'confidence': self.confidence,
        }
        if self.edge_type is not None:
            value['edge_type'] = self.edge_type
        return value


@dataclass(frozen=True, slots=True)
class AgentReviewGraphRelation:
    source: str
    target: str
    type: str
    confidence: str
    authority: str
    status: str | None
    depth: int | None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            'from': self.source,
            'to': self.target,
            'type': self.type,
            'confidence': self.confidence,
            'authority': self.authority,
        }
        if self.status is not None:
            value['status'] = self.status
        if self.depth is not None:
            value['depth'] = self.depth
        return value


@dataclass(frozen=True, slots=True)
class AgentReviewRequirement:
    requirement_id: str
    text: str
    status: str
    classification: str
    linked_subjects: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            'id': self.requirement_id,
            'text': self.text,
            'status': self.status,
            'classification': self.classification,
            'linked_subjects': list(self.linked_subjects),
            'evidence_ids': list(self.evidence_ids),
            'evidence_freshness': EvidenceFreshness.PRE_CHANGE_EVIDENCE.value,
        }


@dataclass(frozen=True, slots=True)
class AgentChangedFileReview:
    path: str
    old_path: str | None
    new_path: str | None
    status: ChangedFileStatus
    binary: bool
    hunk_count: int
    added_lines: tuple[int, ...]
    removed_lines: tuple[int, ...]
    scope_classification: ScopeClassification
    evidence_freshness: EvidenceFreshness
    matched_expected_paths: tuple[str, ...]
    matched_expected_subjects: tuple[str, ...]
    matched_roots: tuple[AgentReviewRoot, ...]
    canonical_subjects: tuple[AgentReviewSubject, ...]
    project_fallbacks: tuple[str, ...]
    projects: tuple[str, ...]
    justifications: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            'path': self.path,
            'old_path': self.old_path,
            'new_path': self.new_path,
            'status': self.status.value,
            'binary': self.binary,
            'hunk_count': self.hunk_count,
            'added_lines': list(self.added_lines),
            'removed_lines': list(self.removed_lines),
            'scope_classification': self.scope_classification.value,
            'evidence_freshness': self.evidence_freshness.value,
            'matched_expected_paths': list(self.matched_expected_paths),
            'matched_expected_subjects': list(self.matched_expected_subjects),
            'matched_roots': [item.to_dict() for item in self.matched_roots],
            'canonical_subjects': [item.to_dict() for item in self.canonical_subjects],
            'project_fallbacks': list(self.project_fallbacks),
            'projects': list(self.projects),
            'justifications': list(self.justifications),
            'limitations': list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class AgentPostChangeReview:
    review_fingerprint: str
    context_fingerprint: str
    graph_fingerprint: str
    diff_fingerprint: str
    story_fingerprint: str
    plan_fingerprint: str | None
    story_summary: str
    snapshot_id: str
    repository_root: str
    requested_base: str
    resolved_base: str
    current_head: str | None
    base_provenance: BaseProvenance
    configuration: AgentReviewConfiguration
    expected_paths: tuple[str, ...]
    expected_subjects: tuple[str, ...]
    expected_roots: tuple[AgentReviewRoot, ...]
    expected_projects: tuple[str, ...]
    changed_files: tuple[AgentChangedFileReview, ...]
    overall_scope: ScopeClassification | None
    scope_summary: tuple[tuple[str, int], ...]
    changed_projects: tuple[str, ...]
    project_expansion: tuple[str, ...]
    matched_roots: tuple[AgentReviewRoot, ...]
    relevant_callers: tuple[AgentReviewReference, ...]
    relevant_callees: tuple[AgentReviewReference, ...]
    graph_relations: tuple[AgentReviewGraphRelation, ...]
    represented_tests: tuple[AgentReviewReference, ...]
    related_requirements: tuple[AgentReviewRequirement, ...]
    evidence_freshness: tuple[EvidenceFreshness, ...]
    omitted_counts: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]
    cannot_prove: tuple[str, ...]
    format: str = AGENT_REVIEW_FORMAT
    version: int = AGENT_REVIEW_VERSION
    producer: str = AGENT_REVIEW_PRODUCER

    def payload_without_fingerprint(self) -> dict[str, object]:
        return {
            'format': self.format,
            'version': self.version,
            'producer': self.producer,
            'context_fingerprint': self.context_fingerprint,
            'graph_fingerprint': self.graph_fingerprint,
            'diff_fingerprint': self.diff_fingerprint,
            'story_fingerprint': self.story_fingerprint,
            'plan_fingerprint': self.plan_fingerprint,
            'story_summary': self.story_summary,
            'snapshot_id': self.snapshot_id,
            'repository_root': self.repository_root,
            'requested_base': self.requested_base,
            'resolved_base': self.resolved_base,
            'current_head': self.current_head,
            'base_provenance': self.base_provenance.value,
            'configuration': self.configuration.to_dict(),
            'expected_surface': {
                'paths': list(self.expected_paths),
                'canonical_subject_ids': list(self.expected_subjects),
                'roots': [item.to_dict() for item in self.expected_roots],
                'projects': list(self.expected_projects),
            },
            'changed_files': [item.to_dict() for item in self.changed_files],
            'overall_scope': self.overall_scope.value if self.overall_scope else None,
            'scope_summary': dict(self.scope_summary),
            'changed_projects': list(self.changed_projects),
            'project_expansion': list(self.project_expansion),
            'matched_roots': [item.to_dict() for item in self.matched_roots],
            'relevant_pre_change_callers': [
                item.to_dict() for item in self.relevant_callers
            ],
            'relevant_pre_change_callees': [
                item.to_dict() for item in self.relevant_callees
            ],
            'relevant_pre_change_graph_relations': [
                item.to_dict() for item in self.graph_relations
            ],
            'represented_tests_to_inspect_run': [
                item.to_dict() for item in self.represented_tests
            ],
            'related_requirements': [
                item.to_dict() for item in self.related_requirements
            ],
            'evidence_freshness': [item.value for item in self.evidence_freshness],
            'omitted_counts': dict(self.omitted_counts),
            'limitations': list(self.limitations),
            'cannot_prove': list(self.cannot_prove),
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_without_fingerprint()
        payload['review_fingerprint'] = self.review_fingerprint
        return payload

    def to_json(self) -> str:
        return canonical_json(self.to_dict()) + '\n'


def agent_review_fingerprint(value: AgentPostChangeReview) -> str:
    digest = hashlib.sha256(
        canonical_json(value.payload_without_fingerprint()).encode('utf-8')
    ).hexdigest()
    return f'agent-review:v1:{digest}'
