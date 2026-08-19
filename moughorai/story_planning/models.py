'''Internal immutable contracts for session-local story planning.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import unicodedata


STORY_PLANNING_PRODUCER = 'atlas-pr172/1'


class StoryRequirementClassification(str, Enum):
    ELIGIBILITY = 'eligibility'
    COLLABORATION = 'collaboration'
    STATE_TRANSITION = 'state_transition'
    VALIDATION = 'validation'
    TEST = 'test'
    REMEDIATION = 'remediation'
    OTHER = 'other'


class StoryRequirementStatus(str, Enum):
    IMPLEMENTED = 'IMPLEMENTED'
    PARTIAL = 'PARTIAL'
    MISSING = 'MISSING'
    NOT_PROVEN = 'NOT_PROVEN'


def normalize_story_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError('story text must be a string')
    normalized = unicodedata.normalize('NFKC', value).replace('\r\n', '\n').replace(
        '\r', '\n'
    )
    normalized = '\n'.join(line.rstrip() for line in normalized.split('\n')).strip()
    if not normalized:
        raise ValueError('story text must not be blank')
    return normalized


def story_fingerprint(value: str) -> str:
    normalized = normalize_story_text(value)
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return f'story:v1:{digest}'


@dataclass(frozen=True, slots=True)
class StoryPlanningConfiguration:
    max_requirements: int = 16
    max_anchors: int = 20
    max_hits_per_anchor: int = 5
    max_source_subjects: int = 16
    max_source_lines_per_subject: int = 240
    max_source_file_bytes: int = 2_000_000
    max_represented_tests: int = 20
    max_implementation_items: int = 32
    provider_output_tokens: int = 1_024
    version: str = STORY_PLANNING_PRODUCER

    def __post_init__(self) -> None:
        for name in (
            'max_requirements', 'max_anchors', 'max_hits_per_anchor',
            'max_source_subjects', 'max_source_lines_per_subject',
            'max_source_file_bytes', 'max_represented_tests',
            'max_implementation_items', 'provider_output_tokens',
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.version != STORY_PLANNING_PRODUCER:
            raise ValueError('unsupported story-planning configuration version')

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class StoryPlanningRequest:
    story_text: str
    snapshot_id: str
    subject: str | None = None
    project: str | None = None
    configuration: StoryPlanningConfiguration = StoryPlanningConfiguration()
    discovery_anchors: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'story_text', normalize_story_text(self.story_text))
        snapshot = self.snapshot_id.strip()
        if not snapshot:
            raise ValueError('story planning requires a snapshot identity')
        object.__setattr__(self, 'snapshot_id', snapshot)
        for name in ('subject', 'project'):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)
        if self.discovery_anchors is not None:
            anchors = tuple(dict.fromkeys(
                item.strip() for item in self.discovery_anchors if item.strip()
            ))
            object.__setattr__(self, 'discovery_anchors', anchors)
        if not isinstance(self.configuration, StoryPlanningConfiguration):
            raise TypeError('story planning configuration is invalid')

    @property
    def story_fingerprint(self) -> str:
        return story_fingerprint(self.story_text)

    @property
    def plan_fingerprint(self) -> str:
        payload = {
            'story_fingerprint': self.story_fingerprint,
            'snapshot_id': self.snapshot_id,
            'subject': self.subject,
            'project': self.project,
            'configuration': self.configuration.to_dict(),
        }
        if self.discovery_anchors is not None:
            payload['discovery_anchors'] = list(self.discovery_anchors)
        digest = hashlib.sha256(json.dumps(
            payload,
            ensure_ascii=False,
            separators=(',', ':'),
            sort_keys=True,
        ).encode('utf-8')).hexdigest()
        return f'story-plan:v1:{digest}'


@dataclass(frozen=True, order=True, slots=True)
class StoryEvidence:
    evidence_id: str
    kind: str
    summary: str
    canonical_subject_id: str | None = None
    project: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ('evidence_id', 'kind', 'summary'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'story evidence {name} must not be blank')
            object.__setattr__(self, name, value.strip())


@dataclass(frozen=True, order=True, slots=True)
class StoryDiscoveryHit:
    anchor: str
    canonical_subject_id: str
    display_name: str
    kind: str
    project: str | None
    source_ref: str | None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, order=True, slots=True)
class StoryImplementationItem:
    canonical_subject_id: str
    display_name: str
    role: str
    project: str
    source_ref: str | None
    evidence_ids: tuple[str, ...] = ()
    proven: bool = False


@dataclass(frozen=True, order=True, slots=True)
class StoryRepresentedTest:
    canonical_subject_id: str
    display_name: str
    project: str
    source_ref: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class StoryRequirement:
    requirement_id: str
    text: str
    classification: StoryRequirementClassification
    status: StoryRequirementStatus
    evidence: tuple[StoryEvidence, ...] = ()
    candidate_implementation_subjects: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    decomposition_source: str = 'deterministic'

    def __post_init__(self) -> None:
        if not self.requirement_id.startswith('R') or not self.requirement_id[1:].isdigit():
            raise ValueError('story requirement ID must use R<number> form')
        text = ' '.join(self.text.split())
        if not text:
            raise ValueError('story requirement text must not be blank')
        object.__setattr__(self, 'text', text)
        if not isinstance(self.classification, StoryRequirementClassification):
            raise TypeError('story requirement classification is invalid')
        if not isinstance(self.status, StoryRequirementStatus):
            raise TypeError('story requirement status is invalid')
        object.__setattr__(self, 'evidence', tuple(sorted(set(self.evidence))))
        object.__setattr__(
            self,
            'candidate_implementation_subjects',
            tuple(sorted(set(self.candidate_implementation_subjects))),
        )
        object.__setattr__(self, 'uncertainty', tuple(sorted(set(self.uncertainty))))


@dataclass(frozen=True, slots=True)
class StoryPlan:
    story_fingerprint: str
    plan_fingerprint: str
    snapshot_id: str
    normalized_story_text: str
    requirements: tuple[StoryRequirement, ...]
    anchors: tuple[str, ...]
    discovery: tuple[StoryDiscoveryHit, ...]
    anchor_subjects: tuple[str, ...]
    implementation_surface: tuple[StoryImplementationItem, ...]
    represented_tests: tuple[StoryRepresentedTest, ...]
    unresolved_questions: tuple[str, ...]
    remediation_requirement_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    provider_decomposition_used: bool = False
    subject_resolution_status: str = 'not_selected'

    def __post_init__(self) -> None:
        object.__setattr__(
            self, 'normalized_story_text',
            normalize_story_text(self.normalized_story_text),
        )
        object.__setattr__(self, 'requirements', tuple(self.requirements))
        expected_ids = tuple(f'R{index}' for index in range(1, len(self.requirements) + 1))
        if tuple(item.requirement_id for item in self.requirements) != expected_ids:
            raise ValueError('story requirements must have stable contiguous ordering')
        object.__setattr__(self, 'anchors', tuple(dict.fromkeys(self.anchors)))
        object.__setattr__(self, 'discovery', tuple(sorted(set(self.discovery))))
        object.__setattr__(self, 'anchor_subjects', tuple(dict.fromkeys(self.anchor_subjects)))
        object.__setattr__(
            self, 'implementation_surface',
            tuple(sorted(set(self.implementation_surface), key=lambda item: (
                0 if item.role == 'primary'
                else 1 if item.role == 'collaborator'
                else 2 if item.role == 'ambiguous collaborator candidate'
                else 3,
                item.role,
                item.display_name.casefold(),
                item.canonical_subject_id,
            ))),
        )
        object.__setattr__(
            self, 'represented_tests',
            tuple(sorted(set(self.represented_tests), key=lambda item: (
                item.display_name.casefold(), item.canonical_subject_id,
            ))),
        )
        object.__setattr__(
            self, 'unresolved_questions',
            tuple(sorted(set(self.unresolved_questions))),
        )
        object.__setattr__(
            self, 'remediation_requirement_ids',
            tuple(self.remediation_requirement_ids),
        )
        object.__setattr__(self, 'limitations', tuple(sorted(set(self.limitations))))
