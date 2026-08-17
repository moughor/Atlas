'''Internal immutable contracts for the controlled engineering-agent runtime.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath

from moughorai.story_planning import StoryPlan, StoryRequirementStatus


ENGINEERING_AGENT_PRODUCER = 'atlas-pr173/1'


class RequirementDisposition(str, Enum):
    ALREADY_SATISFIED = 'already_satisfied'
    PROPOSED_CHANGE = 'proposed_change'
    INTENTIONALLY_UNTOUCHED = 'intentionally_untouched'
    NEEDS_HUMAN_DECISION = 'needs_human_decision'


@dataclass(frozen=True, slots=True)
class EngineeringAgentConfiguration:
    max_source_files: int = 12
    max_primary_files: int = 4
    max_candidate_files: int = 4
    max_test_files: int = 8
    max_source_file_bytes: int = 512_000
    max_source_characters_per_file: int = 24_000
    max_total_source_characters: int = 80_000
    max_edits: int = 16
    max_edit_characters: int = 16_000
    max_text_items: int = 24
    provider_output_tokens: int = 8_192
    version: str = ENGINEERING_AGENT_PRODUCER

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == 'version':
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.version != ENGINEERING_AGENT_PRODUCER:
            raise ValueError('unsupported engineering-agent configuration version')

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('engineering path must not be blank')
    normalized = value.strip().replace('\\', '/')
    candidate = PurePosixPath(normalized)
    if (
        candidate.is_absolute()
        or normalized.startswith('//')
        or (candidate.parts and ':' in candidate.parts[0])
        or '..' in candidate.parts
        or '.' in candidate.parts
    ):
        raise ValueError(f'engineering path is not workspace-relative: {value}')
    if normalized != candidate.as_posix():
        raise ValueError(f'engineering path is not canonical: {value}')
    return normalized


def _sha256(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError('source hash must be text')
    normalized = value.strip().casefold()
    if normalized.startswith('sha256:'):
        normalized = normalized[7:]
    if len(normalized) != 64 or any(character not in '0123456789abcdef' for character in normalized):
        raise ValueError('source hash must be a SHA-256 value')
    return f'sha256:{normalized}'


def _one_line(value: str, label: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{label} must be text')
    normalized = ' '.join(value.split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f'{label} must contain 1-{maximum} characters')
    return normalized


@dataclass(frozen=True, slots=True)
class EngineeringSourceContext:
    relative_path: str
    original_hash: str
    text: str
    start_line: int
    end_line: int
    roles: tuple[str, ...]
    represented_tests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'relative_path', _relative_path(self.relative_path))
        object.__setattr__(self, 'original_hash', _sha256(self.original_hash))
        if not isinstance(self.text, str) or not self.text:
            raise ValueError('engineering source context must not be empty')
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError('engineering source line range is invalid')
        object.__setattr__(self, 'roles', tuple(sorted(set(self.roles))))
        object.__setattr__(
            self, 'represented_tests', tuple(sorted(set(self.represented_tests))),
        )


@dataclass(frozen=True, slots=True)
class EngineeringEdit:
    relative_path: str
    operation: str
    expected_original_hash: str
    original_text: str
    replacement_text: str
    reason: str
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'relative_path', _relative_path(self.relative_path))
        if self.operation != 'replace':
            raise ValueError('PR173 accepts only exact replace edits')
        object.__setattr__(
            self, 'expected_original_hash', _sha256(self.expected_original_hash),
        )
        if not isinstance(self.original_text, str) or not self.original_text:
            raise ValueError('replace edit requires non-empty original text')
        if not isinstance(self.replacement_text, str):
            raise TypeError('replace edit replacement must be text')
        if self.original_text == self.replacement_text:
            raise ValueError('replace edit must change its source text')
        object.__setattr__(self, 'reason', _one_line(self.reason, 'edit reason'))
        requirement_ids = tuple(dict.fromkeys(self.requirement_ids))
        if not requirement_ids or any(
            not item.startswith('R') or not item[1:].isdigit()
            for item in requirement_ids
        ):
            raise ValueError('edit requirement IDs must use R<number> form')
        object.__setattr__(self, 'requirement_ids', requirement_ids)


@dataclass(frozen=True, slots=True)
class EngineeringRequirementCoverage:
    requirement_id: str
    disposition: RequirementDisposition
    summary: str

    def __post_init__(self) -> None:
        if not self.requirement_id.startswith('R') or not self.requirement_id[1:].isdigit():
            raise ValueError('coverage requirement ID must use R<number> form')
        if not isinstance(self.disposition, RequirementDisposition):
            raise TypeError('coverage disposition is invalid')
        object.__setattr__(self, 'summary', _one_line(self.summary, 'coverage summary'))


@dataclass(frozen=True, slots=True)
class EngineeringValidationCommand:
    label: str
    argv: tuple[str, ...]
    working_directory: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'label', _one_line(self.label, 'validation label', 200))
        if not self.argv or any(
            not isinstance(item, str) or not item or '\n' in item or '\r' in item
            for item in self.argv
        ):
            raise ValueError('validation argv must contain bounded literal arguments')
        object.__setattr__(
            self, 'working_directory',
            '.' if self.working_directory == '.' else _relative_path(self.working_directory),
        )
        object.__setattr__(self, 'reason', _one_line(self.reason, 'validation reason'))


@dataclass(frozen=True, slots=True)
class EngineeringVerificationPlan:
    story_fingerprint: str
    plan_fingerprint: str
    commands: tuple[EngineeringValidationCommand, ...]
    represented_tests: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineeringPatchProposal:
    story_fingerprint: str
    plan_fingerprint: str
    snapshot_id: str
    proposal_fingerprint: str
    source_hashes: tuple[tuple[str, str], ...]
    primary_files: tuple[str, ...]
    candidate_files: tuple[str, ...]
    test_files: tuple[str, ...]
    edits: tuple[EngineeringEdit, ...]
    requirement_coverage: tuple[EngineeringRequirementCoverage, ...]
    rationale: tuple[str, ...]
    proposed_tests: tuple[str, ...]
    uncertainties: tuple[str, ...]
    validation_commands: tuple[EngineeringValidationCommand, ...]
    provider: str
    model: str

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted({item.relative_path for item in self.edits}))


@dataclass(frozen=True, slots=True)
class EngineeringGitState:
    branch_status: str
    unstaged_paths: tuple[str, ...]
    staged_paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]

    @property
    def dirty_paths(self) -> tuple[str, ...]:
        return tuple(sorted(set(
            self.unstaged_paths + self.staged_paths + self.untracked_paths
        )))


@dataclass(frozen=True, slots=True)
class EngineeringApplyResult:
    proposal_fingerprint: str
    changed_files: tuple[str, ...]
    before: EngineeringGitState
    after: EngineeringGitState


@dataclass(frozen=True, slots=True)
class EngineeringDiffEntry:
    relative_path: str
    insertions: int | None
    deletions: int | None


@dataclass(frozen=True, slots=True)
class EngineeringDiffReport:
    proposal_fingerprint: str
    changed_files: tuple[str, ...]
    entries: tuple[EngineeringDiffEntry, ...]
    addressed_requirement_ids: tuple[str, ...]
    represented_tests: tuple[str, ...]
    scope_drift: tuple[str, ...]
    unresolved_requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineeringProviderTelemetry:
    provider: str
    model: str
    device: str
    request_count: int
    success_count: int
    failure_count: int
    fallback_count: int
    total_latency_ms: int
    last_latency_ms: int | None
    input_tokens: int
    output_tokens: int
    input_tokens_estimated: bool
    output_tokens_estimated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


def engineering_proposal_fingerprint(
    *,
    story_fingerprint: str,
    plan_fingerprint: str,
    snapshot_id: str,
    source_hashes: tuple[tuple[str, str], ...],
    edits: tuple[EngineeringEdit, ...],
    coverage: tuple[EngineeringRequirementCoverage, ...],
    rationale: tuple[str, ...],
    proposed_tests: tuple[str, ...],
    uncertainties: tuple[str, ...],
    configuration: EngineeringAgentConfiguration,
) -> str:
    payload = {
        'story_fingerprint': story_fingerprint,
        'plan_fingerprint': plan_fingerprint,
        'snapshot_id': snapshot_id,
        'source_hashes': source_hashes,
        'edits': [
            {
                'relative_path': item.relative_path,
                'operation': item.operation,
                'expected_original_hash': item.expected_original_hash,
                'original_text': item.original_text,
                'replacement_text': item.replacement_text,
                'reason': item.reason,
                'requirement_ids': item.requirement_ids,
            }
            for item in edits
        ],
        'coverage': [
            {
                'requirement_id': item.requirement_id,
                'disposition': item.disposition.value,
                'summary': item.summary,
            }
            for item in coverage
        ],
        'rationale': rationale,
        'proposed_tests': proposed_tests,
        'uncertainties': uncertainties,
        'configuration': configuration.to_dict(),
    }
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')).hexdigest()
    return f'engineering-proposal:v1:{digest}'


def unresolved_requirement_ids(
    plan: StoryPlan,
    coverage: tuple[EngineeringRequirementCoverage, ...],
) -> tuple[str, ...]:
    by_id = {item.requirement_id: item for item in coverage}
    return tuple(
        requirement.requirement_id
        for requirement in plan.requirements
        if requirement.status is not StoryRequirementStatus.IMPLEMENTED
        and by_id[requirement.requirement_id].disposition
        is not RequirementDisposition.PROPOSED_CHANGE
    )
