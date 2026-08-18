'''Controlled proposal, apply, verification, and diff lifecycle for engineering work.'''

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import monotonic_ns

from moughorai.llm import LlmClient, LlmMessage, LlmProviderError, LlmRequest
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.story_planning import StoryPlan, StoryRequirementStatus

from .models import (
    EngineeringAgentConfiguration,
    EngineeringApplyResult,
    EngineeringDiffEntry,
    EngineeringDiffReport,
    EngineeringEdit,
    EngineeringGitState,
    EngineeringPatchProposal,
    EngineeringProviderTelemetry,
    EngineeringRequirementCoverage,
    EngineeringSourceContext,
    EngineeringValidationCommand,
    EngineeringVerificationPlan,
    RequirementDisposition,
    engineering_proposal_fingerprint,
    unresolved_requirement_ids,
)


_SOURCE_PATH = re.compile(r'^(?P<path>.*?\.java)(?:[#:]|$)')
_HASH = re.compile(r'^(?:sha256:)?[0-9a-fA-F]{64}$')
_PROVIDER_KEYS = frozenset({
    'edits', 'requirement_coverage', 'rationale', 'tests', 'uncertainties',
})
_EDIT_KEYS = frozenset({
    'relative_path', 'operation', 'expected_original_hash', 'original_text',
    'replacement_text', 'reason', 'requirement_ids',
})
_COVERAGE_KEYS = frozenset({'requirement_id', 'disposition', 'summary'})


class EngineeringAgentError(ValueError):
    '''Base error for a rejected engineering-agent operation.'''


class EngineeringProviderFailure(EngineeringAgentError):
    '''Provider output did not yield a validated patch proposal.'''


class EngineeringApplyError(EngineeringAgentError):
    '''Explicit mutation was rejected before or during safe application.'''


@dataclass(frozen=True, slots=True)
class _SourceSelection:
    relative_path: str
    roles: tuple[str, ...]
    ranges: tuple[tuple[int, int], ...]
    represented_tests: tuple[str, ...]


class _TelemetryRecorder:
    def __init__(self, client: LlmClient) -> None:
        provider = client.provider
        self.provider = str(getattr(provider, 'name', 'unknown') or 'unknown')
        configured = getattr(provider, 'model', None)
        if configured is None:
            configured = getattr(getattr(provider, 'config', None), 'model', None)
        self.model = str(configured or 'unknown')
        self.device = 'unknown'
        self.request_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.fallback_count = 0
        self.total_latency_ms = 0
        self.last_latency_ms: int | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.input_tokens_estimated = False
        self.output_tokens_estimated = False

    def begin(self) -> int:
        self.request_count += 1
        return monotonic_ns()

    def success(self, started: int, request: LlmRequest, response) -> None:
        self.success_count += 1
        self._finish(started)
        self.provider = response.provider
        self.model = response.model
        self._tokens(request, response)
        for key in ('device', 'processor', 'compute_device'):
            value = response.metadata.get(key)
            if isinstance(value, str) and value.strip():
                self.device = value.strip()
                break

    def failure(self, started: int, request: LlmRequest, response=None) -> None:
        self.failure_count += 1
        self.fallback_count += 1
        self._finish(started)
        if response is not None:
            self.provider = response.provider
            self.model = response.model
            self._tokens(request, response)
        else:
            self.input_tokens += _estimate_tokens(_request_text(request))
            self.input_tokens_estimated = True

    def _finish(self, started: int) -> None:
        latency = max(0, (monotonic_ns() - started) // 1_000_000)
        self.last_latency_ms = latency
        self.total_latency_ms += latency

    def _tokens(self, request: LlmRequest, response) -> None:
        if response.input_tokens is None:
            self.input_tokens += _estimate_tokens(_request_text(request))
            self.input_tokens_estimated = True
        else:
            self.input_tokens += response.input_tokens
        if response.output_tokens is None:
            self.output_tokens += _estimate_tokens(response.text)
            self.output_tokens_estimated = True
        else:
            self.output_tokens += response.output_tokens

    @property
    def snapshot(self) -> EngineeringProviderTelemetry:
        return EngineeringProviderTelemetry(
            self.provider,
            self.model,
            self.device,
            self.request_count,
            self.success_count,
            self.failure_count,
            self.fallback_count,
            self.total_latency_ms,
            self.last_latency_ms,
            self.input_tokens,
            self.output_tokens,
            self.input_tokens_estimated,
            self.output_tokens_estimated,
        )


class EngineeringAgentRuntime:
    '''One bounded engineering proposal/apply/review runtime for a repository session.'''

    def __init__(
        self,
        runtime_session: RepositoryRuntimeSession,
        *,
        workspace_root: str | Path,
        llm_client: LlmClient,
        configuration: EngineeringAgentConfiguration | None = None,
    ) -> None:
        if not isinstance(runtime_session, RepositoryRuntimeSession):
            raise TypeError('engineering agent requires a repository runtime session')
        if not isinstance(llm_client, LlmClient):
            raise TypeError('engineering agent requires an LlmClient')
        self._session = runtime_session
        self._root = Path(workspace_root).expanduser().resolve()
        if not self._root.is_dir():
            raise ValueError('engineering workspace root must be a directory')
        self._client = llm_client
        self._configuration = configuration or EngineeringAgentConfiguration()
        self._telemetry = _TelemetryRecorder(llm_client)

    @property
    def telemetry(self) -> EngineeringProviderTelemetry:
        return self._telemetry.snapshot

    def propose(
        self,
        snapshot: AtlasSemanticSnapshot,
        plan: StoryPlan,
    ) -> EngineeringPatchProposal:
        self._require_plan(snapshot, plan)
        self._session.runtime_for(snapshot)
        contexts = self.source_contexts(plan)
        if not any('primary' in item.roles for item in contexts):
            raise EngineeringAgentError(
                'story plan has no authoritative primary source file; no proposal requested'
            )
        verification = self.verification_plan(plan)
        request = _provider_request(plan, contexts, self._configuration)
        started = self._telemetry.begin()
        response = None
        try:
            response = self._client.complete(request)
            if not response.text.strip():
                raise EngineeringProviderFailure(
                    'engineering provider returned empty output; no proposal created'
                )
            parsed = self._parse_provider_output(
                response.text,
                plan,
                contexts,
            )
        except (LlmProviderError, TimeoutError) as exc:
            self._telemetry.failure(started, request)
            raise EngineeringProviderFailure(
                f'engineering provider failed ({type(exc).__name__}); no proposal created'
            ) from exc
        except (EngineeringAgentError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._telemetry.failure(started, request, response)
            if isinstance(exc, EngineeringProviderFailure):
                raise
            raise EngineeringProviderFailure(
                f'engineering provider output was rejected: {exc}; no proposal created'
            ) from exc
        self._telemetry.success(started, request, response)

        edits, coverage, rationale, tests, uncertainties = parsed
        source_hashes = tuple(sorted(
            (item.relative_path, item.original_hash) for item in contexts
        ))
        fingerprint = engineering_proposal_fingerprint(
            story_fingerprint=plan.story_fingerprint,
            plan_fingerprint=plan.plan_fingerprint,
            snapshot_id=plan.snapshot_id,
            source_hashes=source_hashes,
            edits=edits,
            coverage=coverage,
            rationale=rationale,
            proposed_tests=tests,
            uncertainties=uncertainties,
            configuration=self._configuration,
        )
        primary = tuple(
            item.relative_path for item in contexts if 'primary' in item.roles
        )
        candidates = tuple(
            item.relative_path for item in contexts
            if 'candidate' in item.roles and item.relative_path not in primary
        )
        test_files = tuple(
            item.relative_path for item in contexts if 'test' in item.roles
        )
        return EngineeringPatchProposal(
            plan.story_fingerprint,
            plan.plan_fingerprint,
            plan.snapshot_id,
            fingerprint,
            source_hashes,
            primary,
            candidates,
            test_files,
            edits,
            coverage,
            rationale,
            tests,
            uncertainties,
            verification.commands,
            response.provider,
            response.model,
        )

    def source_contexts(self, plan: StoryPlan) -> tuple[EngineeringSourceContext, ...]:
        selections = _source_selections(plan, self._configuration)
        contexts: list[EngineeringSourceContext] = []
        total = 0
        for selection in selections:
            context = _read_source_context(
                self._root,
                selection,
                self._configuration,
            )
            if total + len(context.text) > self._configuration.max_total_source_characters:
                continue
            contexts.append(context)
            total += len(context.text)
        return tuple(contexts)

    def apply(
        self,
        plan: StoryPlan,
        proposal: EngineeringPatchProposal,
    ) -> EngineeringApplyResult:
        _require_current_proposal(plan, proposal)
        _require_proposal_integrity(proposal, self._configuration)
        if not proposal.edits:
            raise EngineeringApplyError(
                'proposal contains no source-changing edits; nothing to apply'
            )
        _require_isolated_linked_worktree(self._root)
        before = self.git_state()
        if before.dirty_paths:
            raise EngineeringApplyError(
                'engineering workspace is dirty; refusing to overlap or assume ownership of: '
                + ', '.join(before.dirty_paths)
            )
        current = _verified_current_sources(
            self._root,
            proposal.source_hashes,
            self._configuration,
        )
        proposed = _apply_edits_in_memory(
            current,
            proposal.edits,
            self._configuration,
        )
        if tuple(sorted(proposed)) != proposal.files:
            raise EngineeringApplyError('proposal file projection is inconsistent')
        _atomic_replace(self._root, current, proposed)
        try:
            after = self.git_state()
            changed = tuple(sorted(after.unstaged_paths))
            if changed != proposal.files or after.staged_paths or after.untracked_paths:
                raise EngineeringApplyError(
                    'post-apply Git state escaped the validated proposal scope'
                )
        except Exception:
            _atomic_replace(self._root, proposed, {
                path: current[path] for path in proposed
            })
            raise
        return EngineeringApplyResult(
            proposal.proposal_fingerprint,
            changed,
            before,
            after,
        )

    def verification_plan(self, plan: StoryPlan) -> EngineeringVerificationPlan:
        return build_engineering_verification_plan(self._root, plan)

    def diff_report(
        self,
        plan: StoryPlan,
        proposal: EngineeringPatchProposal,
    ) -> EngineeringDiffReport:
        _require_current_proposal(plan, proposal)
        _require_proposal_integrity(proposal, self._configuration)
        state = self.git_state()
        changed = tuple(sorted(set(state.unstaged_paths + state.staged_paths)))
        entries = _git_numstat(self._root)
        drift = tuple(sorted(set(changed + state.untracked_paths) - set(proposal.files)))
        addressed = tuple(sorted({
            requirement_id
            for edit in proposal.edits
            for requirement_id in edit.requirement_ids
            if edit.relative_path in changed
        }))
        return EngineeringDiffReport(
            proposal.proposal_fingerprint,
            changed,
            entries,
            addressed,
            tuple(item.display_name for item in plan.represented_tests),
            drift,
            unresolved_requirement_ids(plan, proposal.requirement_coverage),
        )

    def git_state(self) -> EngineeringGitState:
        top = _git(self._root, ('rev-parse', '--show-toplevel')).strip()
        if Path(top).resolve() != self._root:
            raise EngineeringApplyError(
                'engineering workspace root must be the Git worktree root'
            )
        branch_status = _git(
            self._root,
            ('status', '--short', '--branch', '--untracked-files=all'),
        ).splitlines()[0]
        return EngineeringGitState(
            branch_status,
            _git_paths(self._root, ('diff', '--name-only', '-z', '--')),
            _git_paths(self._root, ('diff', '--cached', '--name-only', '-z', '--')),
            _git_paths(
                self._root,
                ('ls-files', '--others', '--exclude-standard', '-z', '--'),
            ),
        )

    @staticmethod
    def _require_plan(snapshot: AtlasSemanticSnapshot, plan: StoryPlan) -> None:
        if not isinstance(plan, StoryPlan):
            raise TypeError('engineering agent requires a StoryPlan')
        if plan.snapshot_id != snapshot.snapshot_id:
            raise EngineeringAgentError('story plan belongs to another snapshot')
        if plan.subject_resolution_status != 'resolved':
            raise EngineeringAgentError(
                'story plan has no resolved authoritative subject; implementation is closed'
            )

    def _parse_provider_output(
        self,
        raw: str,
        plan: StoryPlan,
        contexts: tuple[EngineeringSourceContext, ...],
    ) -> tuple[
        tuple[EngineeringEdit, ...],
        tuple[EngineeringRequirementCoverage, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        if len(raw) > 256_000:
            raise EngineeringAgentError('provider response exceeds the proposal bound')
        payload = json.loads(raw)
        if not isinstance(payload, Mapping) or set(payload) != _PROVIDER_KEYS:
            raise EngineeringAgentError('provider response must use the exact proposal schema')
        contexts_by_path = {item.relative_path: item for item in contexts}
        requirement_by_id = {
            item.requirement_id: item for item in plan.requirements
        }
        proposed_coverage = _parse_coverage(
            payload['requirement_coverage'],
            requirement_by_id,
            self._configuration,
        )
        edits = _parse_edits(
            payload['edits'],
            contexts_by_path,
            requirement_by_id,
            self._root,
            self._configuration,
        )
        coverage = _authoritative_coverage(
            requirement_by_id,
            proposed_coverage,
            edits,
        )
        _validate_coverage_edits(coverage, edits)
        rationale = _plain_text_items(
            payload['rationale'], 'provider rationale', self._configuration,
        )
        uncertainties = _plain_text_items(
            payload['uncertainties'], 'provider uncertainty', self._configuration,
            allow_empty=True,
        )
        tests = _parse_test_selection(
            payload['tests'], plan, self._configuration,
        )
        return edits, coverage, rationale, tests, uncertainties


def _request_text(request: LlmRequest) -> str:
    return '\n'.join(item.content for item in request.messages)


def _estimate_tokens(value: str) -> int:
    return (len(value) + 3) // 4


def _provider_request(
    plan: StoryPlan,
    contexts: tuple[EngineeringSourceContext, ...],
    configuration: EngineeringAgentConfiguration,
) -> LlmRequest:
    context = {
        'story': {
            'text': plan.normalized_story_text,
            'story_fingerprint': plan.story_fingerprint,
            'plan_fingerprint': plan.plan_fingerprint,
            'snapshot_id': plan.snapshot_id,
        },
        'requirements': [
            {
                'id': item.requirement_id,
                'text': item.text,
                'atlas_status': item.status.value,
                'classification': item.classification.value,
                'uncertainty': item.uncertainty,
            }
            for item in plan.requirements
        ],
        'approved_source': [
            {
                'relative_path': item.relative_path,
                'expected_original_hash': item.original_hash,
                'line_range': [item.start_line, item.end_line],
                'roles': item.roles,
                'represented_tests': item.represented_tests,
                'content': item.text,
            }
            for item in contexts
        ],
        'represented_tests': [
            {
                'name': item.display_name,
                'path': _path_from_source_ref(item.source_ref),
                'canonical_subject_id': item.canonical_subject_id,
            }
            for item in plan.represented_tests
        ],
        'limitations': plan.limitations,
    }
    schema = {
        'edits': [{
            'relative_path': 'exact approved relative path',
            'operation': 'replace',
            'expected_original_hash': 'exact supplied sha256 value',
            'original_text': 'exact unique text from supplied content',
            'replacement_text': 'bounded replacement text',
            'reason': 'short reason',
            'requirement_ids': ['R1'],
        }],
        'requirement_coverage': [{
            'requirement_id': 'R1',
            'disposition': (
                'already_satisfied | proposed_change | intentionally_untouched | '
                'needs_human_decision'
            ),
            'summary': 'short explanation',
        }],
        'rationale': ['provider-authored explanation'],
        'tests': ['exact represented test name selected above'],
        'uncertainties': ['remaining uncertainty'],
    }
    system = (
        'You are the bounded Atlas engineering agent. Return one strict JSON object '
        'and no markdown. Use exactly the supplied schema keys. Repository identities, '
        'paths, hashes, requirement IDs, Atlas statuses, and represented test names are '
        'authoritative and must not be renamed or invented. Propose only exact replace '
        'edits whose original_text occurs uniquely in the supplied source content. '
        'Cover every requirement exactly once. already_satisfied is permitted only for '
        'Atlas IMPLEMENTED requirements. NOT_PROVEN requirements must be intentionally_'
        'untouched or needs_human_decision and must not be edited. Tests must be selected '
        'only from represented_tests. Do not emit commands, shell, Git operations, file '
        'creation, deletion, or paths outside approved_source.'
    )
    return LlmRequest(
        (
            LlmMessage('system', system + '\nSchema:\n' + json.dumps(schema)),
            LlmMessage(
                'user',
                json.dumps(context, ensure_ascii=False, separators=(',', ':'), sort_keys=True),
            ),
        ),
        temperature=0.0,
        maximum_output_tokens=configuration.provider_output_tokens,
        metadata={
            'consumer': 'engineering-agent-proposal',
            'story_fingerprint': plan.story_fingerprint,
            'plan_fingerprint': plan.plan_fingerprint,
        },
    )


def _source_selections(
    plan: StoryPlan,
    configuration: EngineeringAgentConfiguration,
) -> tuple[_SourceSelection, ...]:
    values: dict[str, dict[str, object]] = {}

    def retain(source_ref: str | None, role: str, test_name: str | None = None) -> None:
        path = _path_from_source_ref(source_ref)
        if path is None:
            return
        state = values.setdefault(path, {'roles': set(), 'ranges': [], 'tests': set()})
        state['roles'].add(role)
        source_range = _range_from_source_ref(source_ref)
        if source_range is not None:
            state['ranges'].append(source_range)
        if test_name is not None:
            state['tests'].add(test_name)

    for item in plan.implementation_surface:
        path = _path_from_source_ref(item.source_ref)
        if path is not None and '/src/test/' in path:
            continue
        retain(item.source_ref, 'primary' if item.role == 'primary' else 'candidate')
    for item in plan.represented_tests:
        retain(item.source_ref, 'test', item.display_name)

    selections = [
        _SourceSelection(
            path,
            tuple(sorted(state['roles'])),
            tuple(sorted(set(state['ranges']))),
            tuple(sorted(state['tests'])),
        )
        for path, state in values.items()
    ]
    primary = sorted(
        (item for item in selections if 'primary' in item.roles),
        key=lambda item: item.relative_path,
    )[:configuration.max_primary_files]
    candidate = sorted(
        (
            item for item in selections
            if 'candidate' in item.roles and item.relative_path not in {
                selected.relative_path for selected in primary
            }
        ),
        key=lambda item: item.relative_path,
    )[:configuration.max_candidate_files]
    tests = sorted(
        (
            item for item in selections
            if 'test' in item.roles and item.relative_path not in {
                selected.relative_path for selected in primary + candidate
            }
        ),
        key=lambda item: item.relative_path,
    )[:configuration.max_test_files]
    return tuple((primary + candidate + tests)[:configuration.max_source_files])


def _path_from_source_ref(source_ref: str | None) -> str | None:
    if not source_ref:
        return None
    match = _SOURCE_PATH.match(source_ref.replace('\\', '/'))
    if match is None:
        return None
    path = match.group('path')
    candidate = Path(path)
    if candidate.is_absolute() or '..' in candidate.parts:
        return None
    return '/'.join(candidate.parts)


def _range_from_source_ref(source_ref: str | None) -> tuple[int, int] | None:
    if not source_ref:
        return None
    hash_match = re.search(r'#L(\d+)(?:C\d+)?(?:-L(\d+))?', source_ref)
    if hash_match:
        start = int(hash_match.group(1))
        return start, int(hash_match.group(2) or start)
    compact = re.search(r'\.java:(\d+)(?::\d+)?(?:-(\d+)(?::\d+)?)?', source_ref)
    if compact:
        start = int(compact.group(1))
        return start, int(compact.group(2) or start)
    return None


def _workspace_file(root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace('\\', '/')
    unresolved = root / Path(*normalized.split('/'))
    if unresolved.is_symlink():
        raise EngineeringAgentError(
            f'engineering source must not be a symbolic link: {relative_path}'
        )
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EngineeringAgentError(
            f'engineering path escapes the workspace: {relative_path}'
        ) from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise EngineeringAgentError(
            f'engineering source is not a regular workspace file: {relative_path}'
        )
    return candidate


def _read_source_context(
    root: Path,
    selection: _SourceSelection,
    configuration: EngineeringAgentConfiguration,
) -> EngineeringSourceContext:
    path = _workspace_file(root, selection.relative_path)
    payload = _read_bounded_source_bytes(
        path,
        selection.relative_path,
        configuration.max_source_file_bytes,
    )
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise EngineeringAgentError(
            f'engineering source is not UTF-8: {selection.relative_path}'
        ) from exc
    lines = text.splitlines(keepends=True)
    if not lines:
        raise EngineeringAgentError(
            f'engineering source is empty: {selection.relative_path}'
        )
    if len(text) <= configuration.max_source_characters_per_file:
        start, end = 1, len(lines)
        excerpt = text
    else:
        ranges = selection.ranges or ((1, 1),)
        start = max(1, min(item[0] for item in ranges) - 60)
        end = min(len(lines), max(item[1] for item in ranges) + 60)
        excerpt_lines = lines[start - 1:end]
        while (
            len(''.join(excerpt_lines)) > configuration.max_source_characters_per_file
            and len(excerpt_lines) > 1
        ):
            excerpt_lines.pop()
            end -= 1
        excerpt = ''.join(excerpt_lines)
    if not excerpt:
        raise EngineeringAgentError(
            f'engineering source excerpt is empty: {selection.relative_path}'
        )
    return EngineeringSourceContext(
        selection.relative_path,
        'sha256:' + hashlib.sha256(payload).hexdigest(),
        excerpt,
        start,
        end,
        selection.roles,
        selection.represented_tests,
    )


def _parse_coverage(
    raw: object,
    requirements: Mapping[str, object],
    configuration: EngineeringAgentConfiguration,
) -> tuple[EngineeringRequirementCoverage, ...]:
    items = _sequence(raw, 'requirement_coverage')
    if len(items) != len(requirements):
        raise EngineeringAgentError('provider must cover every StoryPlan requirement exactly once')
    values = []
    for raw_item in items:
        if not isinstance(raw_item, Mapping) or set(raw_item) != _COVERAGE_KEYS:
            raise EngineeringAgentError('provider requirement coverage item is invalid')
        requirement_id = raw_item['requirement_id']
        if not isinstance(requirement_id, str) or requirement_id not in requirements:
            raise EngineeringAgentError('provider coverage references an unknown requirement')
        try:
            disposition = RequirementDisposition(str(raw_item['disposition']))
        except ValueError as exc:
            raise EngineeringAgentError('provider coverage disposition is invalid') from exc
        values.append(EngineeringRequirementCoverage(
            requirement_id,
            disposition,
            _bounded_string(raw_item['summary'], 'coverage summary', 2_000),
        ))
    if len({item.requirement_id for item in values}) != len(values):
        raise EngineeringAgentError('provider coverage contains duplicate requirement IDs')
    return tuple(sorted(values, key=lambda item: int(item.requirement_id[1:])))


def _parse_edits(
    raw: object,
    contexts: Mapping[str, EngineeringSourceContext],
    requirements: Mapping[str, object],
    root: Path,
    configuration: EngineeringAgentConfiguration,
) -> tuple[EngineeringEdit, ...]:
    items = _sequence(raw, 'edits')
    if len(items) > configuration.max_edits:
        raise EngineeringAgentError(
            f'provider must return at most {configuration.max_edits} exact replace edits'
        )
    values = []
    intervals: dict[str, list[tuple[int, int]]] = {}
    full_texts: dict[str, str] = {}
    for raw_item in items:
        if not isinstance(raw_item, Mapping) or set(raw_item) != _EDIT_KEYS:
            raise EngineeringAgentError('provider edit item is invalid')
        path = _bounded_string(raw_item['relative_path'], 'edit path', 1_000).replace('\\', '/')
        context = contexts.get(path)
        if context is None:
            raise EngineeringAgentError(f'provider edit path is not approved: {path}')
        expected_hash = _bounded_string(
            raw_item['expected_original_hash'], 'source hash', 80,
        )
        if not _HASH.fullmatch(expected_hash) or (
            expected_hash.removeprefix('sha256:').casefold()
            != context.original_hash.removeprefix('sha256:')
        ):
            raise EngineeringAgentError(f'provider source hash is invalid for {path}')
        original = _bounded_source_text(
            raw_item['original_text'], 'original text', configuration.max_edit_characters,
            allow_empty=False,
        )
        replacement = _bounded_source_text(
            raw_item['replacement_text'], 'replacement text', configuration.max_edit_characters,
            allow_empty=True,
        )
        if original == replacement:
            continue
        if context.text.count(original) != 1:
            raise EngineeringAgentError(
                f'provider original text is not unique inside the approved excerpt: {path}'
            )
        requirement_ids = _requirement_ids(raw_item['requirement_ids'], requirements)
        if any(
            requirements[item].status is StoryRequirementStatus.NOT_PROVEN
            for item in requirement_ids
        ):
            raise EngineeringAgentError(
                'NOT_PROVEN requirements cannot be edited automatically'
            )
        edit = EngineeringEdit(
            path,
            _bounded_string(raw_item['operation'], 'edit operation', 20),
            expected_hash,
            original,
            replacement,
            _bounded_string(raw_item['reason'], 'edit reason', 2_000),
            requirement_ids,
        )
        if path not in full_texts:
            payload = _read_bounded_source_bytes(
                _workspace_file(root, path),
                path,
                configuration.max_source_file_bytes,
            )
            actual_hash = 'sha256:' + hashlib.sha256(payload).hexdigest()
            if actual_hash != context.original_hash:
                raise EngineeringAgentError(
                    f'source changed while proposal was generated: {path}'
                )
            full_texts[path] = payload.decode('utf-8-sig')
        full_text = full_texts[path]
        if full_text.count(original) != 1:
            raise EngineeringAgentError(
                f'provider original text is not unique in the current file: {path}'
            )
        start = full_text.index(original)
        end = start + len(original)
        if any(start < other_end and other_start < end for other_start, other_end in intervals.setdefault(path, [])):
            raise EngineeringAgentError(f'provider edits overlap in {path}')
        intervals[path].append((start, end))
        values.append(edit)
    return tuple(values)


def _authoritative_coverage(
    requirements: Mapping[str, object],
    proposed: tuple[EngineeringRequirementCoverage, ...],
    edits: tuple[EngineeringEdit, ...],
) -> tuple[EngineeringRequirementCoverage, ...]:
    proposed_by_id = {item.requirement_id: item for item in proposed}
    edited = {
        requirement_id
        for edit in edits
        for requirement_id in edit.requirement_ids
    }
    values = []
    for requirement_id, requirement in requirements.items():
        provider_value = proposed_by_id[requirement_id]
        if requirement_id in edited:
            disposition = RequirementDisposition.PROPOSED_CHANGE
            summary = 'Validated exact replacement edit(s) reference this requirement.'
        elif requirement.status is StoryRequirementStatus.NOT_PROVEN:
            disposition = (
                RequirementDisposition.INTENTIONALLY_UNTOUCHED
                if provider_value.disposition
                is RequirementDisposition.INTENTIONALLY_UNTOUCHED
                else RequirementDisposition.NEEDS_HUMAN_DECISION
            )
            summary = (
                'StoryPlan status is NOT_PROVEN; no source edit is accepted for '
                'this requirement.'
            )
        elif (
            requirement.status is StoryRequirementStatus.IMPLEMENTED
            and provider_value.disposition
            is RequirementDisposition.ALREADY_SATISFIED
        ):
            disposition = RequirementDisposition.ALREADY_SATISFIED
            summary = 'StoryPlan status is IMPLEMENTED; no source edit is proposed.'
        elif provider_value.disposition in {
            RequirementDisposition.INTENTIONALLY_UNTOUCHED,
            RequirementDisposition.NEEDS_HUMAN_DECISION,
        }:
            disposition = provider_value.disposition
            summary = (
                f'No validated edit references this requirement; Atlas status remains '
                f'{requirement.status.value}.'
            )
        else:
            disposition = RequirementDisposition.NEEDS_HUMAN_DECISION
            summary = (
                f'Provider coverage conflicted with deterministic Atlas status '
                f'{requirement.status.value}; no validated edit addresses it.'
            )
        values.append(EngineeringRequirementCoverage(
            requirement_id,
            disposition,
            summary,
        ))
    return tuple(values)


def _validate_coverage_edits(
    coverage: tuple[EngineeringRequirementCoverage, ...],
    edits: tuple[EngineeringEdit, ...],
) -> None:
    edited = {
        requirement_id
        for item in edits
        for requirement_id in item.requirement_ids
    }
    proposed = {
        item.requirement_id
        for item in coverage
        if item.disposition is RequirementDisposition.PROPOSED_CHANGE
    }
    if edited != proposed:
        raise EngineeringAgentError(
            'proposed_change coverage must exactly match edited requirement IDs'
        )


def _parse_test_selection(
    raw: object,
    plan: StoryPlan,
    configuration: EngineeringAgentConfiguration,
) -> tuple[str, ...]:
    items = _plain_text_items(
        raw, 'test selection', configuration, allow_empty=True,
    )
    represented = {item.display_name for item in plan.represented_tests}
    unsupported = tuple(item for item in items if item not in represented)
    if unsupported:
        raise EngineeringAgentError(
            'provider selected unsupported TEST identities: ' + ', '.join(unsupported)
        )
    return items


def _plain_text_items(
    raw: object,
    label: str,
    configuration: EngineeringAgentConfiguration,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    values = _sequence(raw, label)
    if not allow_empty and not values:
        raise EngineeringAgentError(f'{label} must not be empty')
    if len(values) > configuration.max_text_items:
        raise EngineeringAgentError(f'{label} exceeds its item bound')
    return tuple(dict.fromkeys(
        _bounded_string(item, label, 2_000) for item in values
    ))


def _sequence(raw: object, label: str) -> Sequence[object]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise EngineeringAgentError(f'{label} must be an array')
    return raw


def _bounded_string(raw: object, label: str, maximum: int) -> str:
    if not isinstance(raw, str):
        raise EngineeringAgentError(f'{label} must be text')
    value = ' '.join(raw.split())
    if not value or len(value) > maximum:
        raise EngineeringAgentError(f'{label} must contain 1-{maximum} characters')
    return value


def _bounded_source_text(
    raw: object,
    label: str,
    maximum: int,
    *,
    allow_empty: bool,
) -> str:
    if not isinstance(raw, str):
        raise EngineeringAgentError(f'{label} must be text')
    if (not allow_empty and not raw) or len(raw) > maximum:
        raise EngineeringAgentError(f'{label} exceeds its character bound')
    return raw


def _requirement_ids(
    raw: object,
    requirements: Mapping[str, object],
) -> tuple[str, ...]:
    values = _sequence(raw, 'edit requirement_ids')
    if not values:
        raise EngineeringAgentError('each edit requires at least one requirement ID')
    result = tuple(dict.fromkeys(
        _bounded_string(item, 'requirement ID', 16) for item in values
    ))
    if any(item not in requirements for item in result):
        raise EngineeringAgentError('edit references an unknown requirement ID')
    return result


def _require_current_proposal(
    plan: StoryPlan,
    proposal: EngineeringPatchProposal,
) -> None:
    if not isinstance(plan, StoryPlan) or not isinstance(proposal, EngineeringPatchProposal):
        raise TypeError('apply/review requires a StoryPlan and EngineeringPatchProposal')
    if (
        proposal.story_fingerprint != plan.story_fingerprint
        or proposal.plan_fingerprint != plan.plan_fingerprint
        or proposal.snapshot_id != plan.snapshot_id
    ):
        raise EngineeringApplyError(
            'engineering proposal is stale for the current story, plan, or snapshot'
        )


def _require_proposal_integrity(
    proposal: EngineeringPatchProposal,
    configuration: EngineeringAgentConfiguration,
) -> None:
    expected = engineering_proposal_fingerprint(
        story_fingerprint=proposal.story_fingerprint,
        plan_fingerprint=proposal.plan_fingerprint,
        snapshot_id=proposal.snapshot_id,
        source_hashes=proposal.source_hashes,
        edits=proposal.edits,
        coverage=proposal.requirement_coverage,
        rationale=proposal.rationale,
        proposed_tests=proposal.proposed_tests,
        uncertainties=proposal.uncertainties,
        configuration=configuration,
    )
    if proposal.proposal_fingerprint != expected:
        raise EngineeringApplyError(
            'engineering proposal fingerprint is invalid; regenerate the proposal'
        )


def _require_isolated_linked_worktree(root: Path) -> None:
    git_marker = root / '.git'
    if not git_marker.is_file():
        raise EngineeringApplyError(
            'PR173 apply requires an isolated linked Git worktree; primary '
            'checkouts remain read-only'
        )
    try:
        marker = git_marker.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError) as exc:
        raise EngineeringApplyError(
            'isolated Git worktree metadata is unreadable'
        ) from exc
    if not marker.casefold().startswith('gitdir:'):
        raise EngineeringApplyError(
            'PR173 apply requires an isolated linked Git worktree'
        )


def _verified_current_sources(
    root: Path,
    source_hashes: tuple[tuple[str, str], ...],
    configuration: EngineeringAgentConfiguration,
) -> dict[str, bytes]:
    values = {}
    for relative_path, expected in source_hashes:
        payload = _read_bounded_source_bytes(
            _workspace_file(root, relative_path),
            relative_path,
            configuration.max_source_file_bytes,
        )
        actual = 'sha256:' + hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise EngineeringApplyError(
                f'source hash mismatch; regenerate proposal: {relative_path}'
            )
        values[relative_path] = payload
    return values


def _read_bounded_source_bytes(
    path: Path,
    relative_path: str,
    maximum_bytes: int,
) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EngineeringAgentError(
            f'engineering source is unreadable: {relative_path}'
        ) from exc
    if size > maximum_bytes:
        raise EngineeringAgentError(
            f'engineering source exceeds the byte bound: {relative_path}'
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise EngineeringAgentError(
            f'engineering source is unreadable: {relative_path}'
        ) from exc
    if len(payload) > maximum_bytes:
        raise EngineeringAgentError(
            f'engineering source exceeds the byte bound: {relative_path}'
        )
    return payload


def _apply_edits_in_memory(
    current: Mapping[str, bytes],
    edits: tuple[EngineeringEdit, ...],
    configuration: EngineeringAgentConfiguration,
) -> dict[str, bytes]:
    by_path: dict[str, list[EngineeringEdit]] = {}
    for edit in edits:
        by_path.setdefault(edit.relative_path, []).append(edit)
    result = {}
    for path, path_edits in by_path.items():
        payload = current[path]
        bom = payload.startswith(b'\xef\xbb\xbf')
        text = payload.decode('utf-8-sig')
        positions = []
        for edit in path_edits:
            if len(edit.original_text) > configuration.max_edit_characters or len(edit.replacement_text) > configuration.max_edit_characters:
                raise EngineeringApplyError('proposal edit exceeds its bound')
            if text.count(edit.original_text) != 1:
                raise EngineeringApplyError(
                    f'exact original text no longer matches once: {path}'
                )
            start = text.index(edit.original_text)
            positions.append((start, start + len(edit.original_text), edit))
        ordered = sorted(positions)
        for previous, current_item in zip(ordered, ordered[1:]):
            if current_item[0] < previous[1]:
                raise EngineeringApplyError(f'proposal edits overlap in {path}')
        for start, end, edit in reversed(ordered):
            text = text[:start] + edit.replacement_text + text[end:]
        result[path] = text.encode('utf-8-sig' if bom else 'utf-8')
    return result


def _atomic_replace(
    root: Path,
    originals: Mapping[str, bytes],
    replacements: Mapping[str, bytes],
) -> None:
    staged: dict[str, Path] = {}
    replaced: list[str] = []
    try:
        for relative_path, payload in replacements.items():
            target = _workspace_file(root, relative_path)
            descriptor, name = tempfile.mkstemp(
                prefix=target.name + '.', suffix='.atlas-pr173.tmp', dir=target.parent,
            )
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, 'wb') as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, target.stat().st_mode)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            staged[relative_path] = temporary
        try:
            for relative_path in sorted(replacements):
                os.replace(staged[relative_path], _workspace_file(root, relative_path))
                replaced.append(relative_path)
        except Exception:
            for relative_path in replaced:
                _workspace_file(root, relative_path).write_bytes(originals[relative_path])
            raise
    except Exception as exc:
        raise EngineeringApplyError(
            f'atomic proposal application failed ({type(exc).__name__})'
        ) from exc
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def _git(root: Path, arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        ('git', '-c', 'core.quotepath=false', *arguments),
        cwd=root,
        text=True,
        encoding='utf-8',
        errors='replace',
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise EngineeringApplyError(
            completed.stderr.strip() or f'Git command failed: {arguments[0]}'
        )
    return completed.stdout


def _git_paths(root: Path, arguments: tuple[str, ...]) -> tuple[str, ...]:
    output = _git(root, arguments)
    return tuple(sorted(
        item.replace('\\', '/') for item in output.split('\0') if item
    ))


def _git_numstat(root: Path) -> tuple[EngineeringDiffEntry, ...]:
    output = _git(root, ('diff', '--numstat', '--'))
    values = []
    for line in output.splitlines():
        parts = line.split('\t', 2)
        if len(parts) != 3:
            continue
        insertions = int(parts[0]) if parts[0].isdigit() else None
        deletions = int(parts[1]) if parts[1].isdigit() else None
        values.append(EngineeringDiffEntry(
            parts[2].replace('\\', '/'), insertions, deletions,
        ))
    return tuple(sorted(values, key=lambda item: item.relative_path))


def _verification_commands(
    root: Path,
    plan: StoryPlan,
) -> tuple[tuple[EngineeringValidationCommand, ...], tuple[str, ...]]:
    executable = (
        'mvnw.cmd' if (root / 'mvnw.cmd').is_file()
        else './mvnw' if (root / 'mvnw').is_file()
        else 'mvn'
    )
    by_test: dict[tuple[str, str], list[str]] = {}
    modules: set[str] = set()
    for item in plan.represented_tests:
        path = _path_from_source_ref(item.source_ref)
        if path is None:
            continue
        module = _module_for_path(root, path)
        if module is None:
            continue
        modules.add(module)
        by_test.setdefault((module, Path(path).stem), []).append(item.display_name)
    for item in plan.implementation_surface:
        path = _path_from_source_ref(item.source_ref)
        if path is not None:
            module = _module_for_path(root, path)
            if module is not None:
                modules.add(module)
    commands = []
    for (module, test_class), methods in sorted(by_test.items())[:4]:
        selector = test_class + '#' + '+'.join(sorted(set(methods))[:20])
        args = [executable]
        if module != '.':
            args.extend(('-pl', module, '-am'))
        args.extend((f'-Dtest={selector}', 'test'))
        commands.append(EngineeringValidationCommand(
            f'focused represented tests in {module}',
            tuple(args),
            '.',
            'Run the represented TEST methods associated with the selected subject first.',
        ))
    if not commands:
        for module in sorted(modules)[:2]:
            args = [executable]
            if module != '.':
                args.extend(('-pl', module, '-am'))
            args.extend(('-DskipTests', 'compile'))
            commands.append(EngineeringValidationCommand(
                f'compile {module}',
                tuple(args),
                '.',
                'Compile the narrowest represented Maven module because no focused TEST selector was available.',
            ))
    limitations = []
    if not commands:
        limitations.append(
            'No represented Maven module/test command could be derived; choose validation manually.'
        )
    limitations.append(
        'PR173 presents validation argv only; /verify run is intentionally unavailable.'
    )
    return tuple(commands), tuple(limitations)


def build_engineering_verification_plan(
    workspace_root: str | Path,
    plan: StoryPlan,
) -> EngineeringVerificationPlan:
    '''Build PR173 validation guidance without constructing or invoking a provider.'''
    if not isinstance(plan, StoryPlan):
        raise TypeError('verification planning requires a StoryPlan')
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('engineering workspace root must be a directory')
    commands, limitations = _verification_commands(root, plan)
    return EngineeringVerificationPlan(
        plan.story_fingerprint,
        plan.plan_fingerprint,
        commands,
        tuple(item.display_name for item in plan.represented_tests),
        limitations,
    )


def _module_for_path(root: Path, relative_path: str) -> str | None:
    path = relative_path.replace('\\', '/')
    prefix, marker, _ = path.partition('/src/')
    module = prefix if marker else '.'
    directory = root if module == '.' else root / Path(*module.split('/'))
    if (directory / 'pom.xml').is_file():
        return module
    return None
