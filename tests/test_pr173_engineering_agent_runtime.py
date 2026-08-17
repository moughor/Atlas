from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.engineering_agent import (
    EngineeringAgentConfiguration,
    EngineeringAgentError,
    EngineeringAgentRuntime,
    EngineeringApplyError,
    EngineeringProviderFailure,
    RequirementDisposition,
    render_engineering_diff,
    render_implementation_proposal,
    render_verification_plan,
)
from moughorai.llm import (
    LlmClient,
    LlmResponse,
    RetryPolicy,
    ScriptedLlmProvider,
)
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.story_planning import (
    StoryImplementationItem,
    StoryPlan,
    StoryPlanningRequest,
    StoryRepresentedTest,
    StoryRequirement,
    StoryRequirementClassification,
    StoryRequirementStatus,
)


PROJECT = 'fixture-module'
SOURCE_PATH = 'module/src/main/java/demo/Service.java'
TEST_PATH = 'module/src/test/java/demo/ServiceTest.java'
NOTES_PATH = 'notes.txt'
SOURCE = '''package demo;
class Service {
  boolean work(String kind) {
    return "OLD".equals(kind);
  }
}
'''
TEST_SOURCE = '''package demo;
class ServiceTest {
  void shouldWork() { new Service().work("OLD"); }
}
'''
STORY = '''- Change OLD handling to NEW.
- Keep the represented helper behavior.
- Decide the operational migration with a human.
'''


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ('git', *arguments),
        cwd=root,
        check=True,
        text=True,
        encoding='utf-8',
        capture_output=True,
    )
    return result.stdout.strip()


@pytest.fixture
def pr173_fixture(tmp_path):
    primary = tmp_path / 'primary'
    linked = tmp_path / 'linked'
    source = primary / SOURCE_PATH
    test = primary / TEST_PATH
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding='utf-8', newline='')
    test.write_text(TEST_SOURCE, encoding='utf-8', newline='')
    (primary / 'module/pom.xml').write_text(
        '<project><modelVersion>4.0.0</modelVersion>'
        '<groupId>demo</groupId><artifactId>module</artifactId>'
        '<version>1</version></project>',
        encoding='utf-8',
    )
    (primary / NOTES_PATH).write_text('fixture notes\n', encoding='utf-8')
    _git(primary, 'init')
    _git(primary, 'config', 'user.email', 'atlas@example.invalid')
    _git(primary, 'config', 'user.name', 'Atlas Fixture')
    _git(primary, 'add', '--all')
    _git(primary, 'commit', '-m', 'fixture baseline')
    _git(primary, 'worktree', 'add', '-b', 'fixture-pr173', str(linked))

    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({}),
        workspace_fingerprint='pr173-fixture',
        analyzer_version='test-pr173/1',
    )
    request = StoryPlanningRequest(
        STORY,
        snapshot.snapshot_id,
        'method:fixture-primary',
        PROJECT,
    )
    requirements = (
        StoryRequirement(
            'R1',
            'Change OLD handling to NEW.',
            StoryRequirementClassification.ELIGIBILITY,
            StoryRequirementStatus.PARTIAL,
        ),
        StoryRequirement(
            'R2',
            'Keep the represented helper behavior.',
            StoryRequirementClassification.COLLABORATION,
            StoryRequirementStatus.IMPLEMENTED,
        ),
        StoryRequirement(
            'R3',
            'Decide the operational migration with a human.',
            StoryRequirementClassification.REMEDIATION,
            StoryRequirementStatus.NOT_PROVEN,
        ),
    )
    plan = StoryPlan(
        request.story_fingerprint,
        request.plan_fingerprint,
        snapshot.snapshot_id,
        STORY,
        requirements,
        ('OLD', 'NEW'),
        (),
        ('method:fixture-primary',),
        (
            StoryImplementationItem(
                'method:fixture-primary',
                'demo.Service#work',
                'primary',
                PROJECT,
                SOURCE_PATH + '#L3C1-L5C2',
                ('evidence:primary',),
                True,
            ),
        ),
        (
            StoryRepresentedTest(
                'method:fixture-test',
                'shouldWork',
                PROJECT,
                TEST_PATH + '#L3C1-L3C60',
                'evidence:test',
            ),
        ),
        ('R3 requires a human decision.',),
        ('R3',),
        ('fixture limitation',),
        False,
        'resolved',
    )
    return {
        'primary': primary,
        'root': linked,
        'snapshot': snapshot,
        'plan': plan,
    }


def _source_hash(root: Path) -> str:
    return 'sha256:' + hashlib.sha256((root / SOURCE_PATH).read_bytes()).hexdigest()


def _valid_payload(root: Path, *, test_name: str = 'shouldWork') -> str:
    return json.dumps({
        'edits': [{
            'relative_path': SOURCE_PATH,
            'operation': 'replace',
            'expected_original_hash': _source_hash(root),
            'original_text': 'return "OLD".equals(kind);',
            'replacement_text': 'return "NEW".equals(kind);',
            'reason': 'Implement the bounded R1 behavior.',
            'requirement_ids': ['R1'],
        }],
        'requirement_coverage': [
            {
                'requirement_id': 'R1',
                'disposition': 'proposed_change',
                'summary': 'Replace the represented condition.',
            },
            {
                'requirement_id': 'R2',
                'disposition': 'already_satisfied',
                'summary': 'Atlas already represents this behavior.',
            },
            {
                'requirement_id': 'R3',
                'disposition': 'needs_human_decision',
                'summary': 'No deterministic operational procedure is represented.',
            },
        ],
        'rationale': ['Apply the smallest exact replacement.'],
        'tests': [test_name],
        'uncertainties': ['R3 remains outside the source patch.'],
    })


def _runtime(fixture, outcomes, *, configuration=None):
    provider = ScriptedLlmProvider(outcomes)
    session = RepositoryRuntimeSession(workspace_root=fixture['root'])
    runtime = EngineeringAgentRuntime(
        session,
        workspace_root=fixture['root'],
        llm_client=LlmClient(provider, RetryPolicy(maximum_attempts=1)),
        configuration=configuration,
    )
    return runtime, provider, session


def _proposal(fixture):
    runtime, provider, session = _runtime(
        fixture,
        (LlmResponse(_valid_payload(fixture['root']), 'scripted', 'engineer'),),
    )
    proposal = runtime.propose(fixture['snapshot'], fixture['plan'])
    return runtime, provider, session, proposal


def test_proposal_references_story_plan_snapshot_and_is_preview_only(pr173_fixture) -> None:
    before = (pr173_fixture['root'] / SOURCE_PATH).read_bytes()
    _, _, _, proposal = _proposal(pr173_fixture)

    assert proposal.story_fingerprint == pr173_fixture['plan'].story_fingerprint
    assert proposal.plan_fingerprint == pr173_fixture['plan'].plan_fingerprint
    assert proposal.snapshot_id == pr173_fixture['snapshot'].snapshot_id
    assert proposal.proposal_fingerprint.startswith('engineering-proposal:v1:')
    assert (pr173_fixture['root'] / SOURCE_PATH).read_bytes() == before
    assert 'PREVIEW ONLY' in render_implementation_proposal(proposal)


def test_source_reads_are_bounded_and_only_plan_authorized(pr173_fixture) -> None:
    configuration = EngineeringAgentConfiguration(
        max_source_characters_per_file=1_000,
        max_total_source_characters=2_000,
    )
    runtime, _, _ = _runtime(pr173_fixture, (), configuration=configuration)
    contexts = runtime.source_contexts(pr173_fixture['plan'])

    assert {item.relative_path for item in contexts} == {SOURCE_PATH, TEST_PATH}
    assert all(len(item.text) <= 1_000 for item in contexts)
    assert NOTES_PATH not in {item.relative_path for item in contexts}
    assert any(item.represented_tests == ('shouldWork',) for item in contexts)


def test_workspace_path_escape_is_fail_closed(pr173_fixture) -> None:
    escaped = replace(
        pr173_fixture['plan'],
        implementation_surface=(replace(
            pr173_fixture['plan'].implementation_surface[0],
            source_ref='../outside.java#L1-L2',
        ),),
    )
    runtime, provider, _ = _runtime(pr173_fixture, ())

    with pytest.raises(EngineeringAgentError, match='no authoritative primary'):
        runtime.propose(pr173_fixture['snapshot'], escaped)
    assert provider.calls == []


@pytest.mark.parametrize('output', ('', '{}', 'not json'))
def test_empty_or_invalid_provider_output_never_mutates(pr173_fixture, output) -> None:
    before = (pr173_fixture['root'] / SOURCE_PATH).read_bytes()
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(output, 'scripted', 'engineer'),),
    )

    with pytest.raises(EngineeringProviderFailure):
        runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])
    assert (pr173_fixture['root'] / SOURCE_PATH).read_bytes() == before
    assert runtime.telemetry.failure_count == 1
    assert runtime.telemetry.fallback_count == 1


def test_provider_cannot_inject_unsupported_test_identity(pr173_fixture) -> None:
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(
            _valid_payload(pr173_fixture['root'], test_name='inventedTest'),
            'scripted',
            'engineer',
        ),),
    )

    with pytest.raises(EngineeringProviderFailure, match='unsupported TEST'):
        runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])


def test_provider_cannot_edit_unapproved_workspace_path(pr173_fixture) -> None:
    payload = json.loads(_valid_payload(pr173_fixture['root']))
    payload['edits'][0]['relative_path'] = NOTES_PATH
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(json.dumps(payload), 'scripted', 'engineer'),),
    )

    with pytest.raises(EngineeringProviderFailure, match='not approved'):
        runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])


def test_not_proven_requirement_cannot_be_edited(pr173_fixture) -> None:
    payload = json.loads(_valid_payload(pr173_fixture['root']))
    payload['edits'][0]['requirement_ids'] = ['R3']
    payload['requirement_coverage'][0]['disposition'] = 'intentionally_untouched'
    payload['requirement_coverage'][2]['disposition'] = 'proposed_change'
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(json.dumps(payload), 'scripted', 'engineer'),),
    )

    with pytest.raises(EngineeringProviderFailure, match='NOT_PROVEN'):
        runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])


def test_requirement_coverage_and_represented_tests_are_preserved(pr173_fixture) -> None:
    _, _, _, proposal = _proposal(pr173_fixture)

    assert [item.requirement_id for item in proposal.requirement_coverage] == [
        'R1', 'R2', 'R3'
    ]
    assert proposal.requirement_coverage[0].disposition is (
        RequirementDisposition.PROPOSED_CHANGE
    )
    assert proposal.proposed_tests == ('shouldWork',)


def test_provider_coverage_labels_cannot_override_atlas_status_or_validated_edits(
    pr173_fixture,
) -> None:
    payload = json.loads(_valid_payload(pr173_fixture['root']))
    payload['requirement_coverage'][0] = {
        'requirement_id': 'R1',
        'disposition': 'already_satisfied',
        'summary': 'Unsupported claim that R1 is complete.',
    }
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(json.dumps(payload), 'scripted', 'engineer'),),
    )

    proposal = runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])

    r1 = proposal.requirement_coverage[0]
    assert r1.disposition is RequirementDisposition.PROPOSED_CHANGE
    assert 'Unsupported claim' not in r1.summary


def test_literal_provider_noop_is_discarded_without_weakening_real_edits(
    pr173_fixture,
) -> None:
    payload = json.loads(_valid_payload(pr173_fixture['root']))
    payload['edits'].append({
        'relative_path': SOURCE_PATH,
        'operation': 'replace',
        'expected_original_hash': _source_hash(pr173_fixture['root']),
        'original_text': 'class Service {',
        'replacement_text': 'class Service {',
        'reason': 'No-op provider noise.',
        'requirement_ids': ['R2'],
    })
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(json.dumps(payload), 'scripted', 'engineer'),),
    )

    proposal = runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])

    assert len(proposal.edits) == 1
    assert proposal.edits[0].requirement_ids == ('R1',)


def test_valid_no_change_proposal_is_previewable_but_not_applicable(
    pr173_fixture,
) -> None:
    payload = json.loads(_valid_payload(pr173_fixture['root']))
    payload['edits'] = []
    payload['requirement_coverage'][0]['disposition'] = 'already_satisfied'
    runtime, _, _ = _runtime(
        pr173_fixture,
        (LlmResponse(json.dumps(payload), 'scripted', 'engineer'),),
    )
    before = (pr173_fixture['root'] / SOURCE_PATH).read_bytes()

    proposal = runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])

    assert proposal.edits == ()
    assert 'no source-changing validated edit' in render_implementation_proposal(proposal)
    assert runtime.telemetry.success_count == 1
    with pytest.raises(EngineeringApplyError, match='nothing to apply'):
        runtime.apply(pr173_fixture['plan'], proposal)
    assert (pr173_fixture['root'] / SOURCE_PATH).read_bytes() == before


def test_stale_plan_rejects_apply_without_mutation(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    stale = replace(pr173_fixture['plan'], plan_fingerprint='story-plan:v1:' + '0' * 64)
    before = (pr173_fixture['root'] / SOURCE_PATH).read_bytes()

    with pytest.raises(EngineeringApplyError, match='stale'):
        runtime.apply(stale, proposal)
    assert (pr173_fixture['root'] / SOURCE_PATH).read_bytes() == before


def test_tampered_proposal_fingerprint_rejects_apply(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    forged = replace(
        proposal,
        proposal_fingerprint='engineering-proposal:v1:' + '0' * 64,
    )

    with pytest.raises(EngineeringApplyError, match='fingerprint is invalid'):
        runtime.apply(pr173_fixture['plan'], forged)


def test_source_hash_mismatch_rejects_clean_changed_commit(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    source = pr173_fixture['root'] / SOURCE_PATH
    source.write_text(SOURCE.replace('OLD', 'CHANGED'), encoding='utf-8', newline='')
    _git(pr173_fixture['root'], 'add', SOURCE_PATH)
    _git(pr173_fixture['root'], 'commit', '-m', 'change after proposal')

    with pytest.raises(EngineeringApplyError, match='source hash mismatch'):
        runtime.apply(pr173_fixture['plan'], proposal)


def test_dirty_overlapping_worktree_is_rejected(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    source = pr173_fixture['root'] / SOURCE_PATH
    source.write_text(SOURCE + '// user change\n', encoding='utf-8', newline='')

    with pytest.raises(EngineeringApplyError, match='workspace is dirty'):
        runtime.apply(pr173_fixture['plan'], proposal)


def test_non_overlapping_dirty_file_is_still_conservatively_rejected(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    (pr173_fixture['root'] / NOTES_PATH).write_text('user notes\n', encoding='utf-8')

    with pytest.raises(EngineeringApplyError, match=NOTES_PATH):
        runtime.apply(pr173_fixture['plan'], proposal)


def test_primary_checkout_is_structurally_read_only(pr173_fixture) -> None:
    primary_fixture = dict(pr173_fixture)
    primary_fixture['root'] = pr173_fixture['primary']
    runtime, _, _, proposal = _proposal(primary_fixture)

    with pytest.raises(EngineeringApplyError, match='isolated linked Git worktree'):
        runtime.apply(primary_fixture['plan'], proposal)


def test_apply_changes_exact_proposal_only_without_commit_or_push(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    head = _git(pr173_fixture['root'], 'rev-parse', 'HEAD')

    result = runtime.apply(pr173_fixture['plan'], proposal)

    assert result.changed_files == (SOURCE_PATH,)
    assert 'return "NEW".equals(kind);' in (
        pr173_fixture['root'] / SOURCE_PATH
    ).read_text(encoding='utf-8')
    assert _git(pr173_fixture['root'], 'rev-parse', 'HEAD') == head
    assert _git(pr173_fixture['root'], 'remote') == ''
    assert _git(pr173_fixture['root'], 'diff', '--name-only') == SOURCE_PATH


def test_verify_plans_literal_focused_maven_argv_without_running(pr173_fixture) -> None:
    runtime, _, _ = _runtime(pr173_fixture, ())
    verification = runtime.verification_plan(pr173_fixture['plan'])
    rendered = render_verification_plan(verification)

    assert len(verification.commands) == 1
    command = verification.commands[0]
    assert command.argv[0] == 'mvn'
    assert '-pl' in command.argv
    assert 'module' in command.argv
    assert '-Dtest=ServiceTest#shouldWork' in command.argv
    assert 'preview only' in rendered


def test_diff_reports_scope_requirements_tests_and_no_completion(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    runtime.apply(pr173_fixture['plan'], proposal)

    report = runtime.diff_report(pr173_fixture['plan'], proposal)
    rendered = render_engineering_diff(report)

    assert report.changed_files == (SOURCE_PATH,)
    assert report.addressed_requirement_ids == ('R1',)
    assert report.represented_tests == ('shouldWork',)
    assert report.scope_drift == ()
    assert report.unresolved_requirement_ids == ('R3',)
    assert 'completion is not inferred' in rendered


def test_diff_warns_on_scope_drift(pr173_fixture) -> None:
    runtime, _, _, proposal = _proposal(pr173_fixture)
    runtime.apply(pr173_fixture['plan'], proposal)
    (pr173_fixture['root'] / NOTES_PATH).write_text('scope drift\n', encoding='utf-8')

    report = runtime.diff_report(pr173_fixture['plan'], proposal)

    assert report.scope_drift == (NOTES_PATH,)


def test_provider_telemetry_reports_observed_values_and_unknown_device(
    pr173_fixture,
) -> None:
    response = LlmResponse(
        _valid_payload(pr173_fixture['root']),
        'scripted-provider',
        'engineering-model',
        input_tokens=321,
        output_tokens=123,
    )
    runtime, _, _ = _runtime(pr173_fixture, (response,))

    runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])
    telemetry = runtime.telemetry

    assert telemetry.provider == 'scripted-provider'
    assert telemetry.model == 'engineering-model'
    assert telemetry.device == 'unknown'
    assert telemetry.request_count == telemetry.success_count == 1
    assert telemetry.failure_count == telemetry.fallback_count == 0
    assert telemetry.input_tokens == 321
    assert telemetry.output_tokens == 123


def test_repeated_proposals_reuse_single_repository_runtime(pr173_fixture) -> None:
    outcome = LlmResponse(_valid_payload(pr173_fixture['root']), 'scripted', 'engineer')
    runtime, _, session = _runtime(pr173_fixture, (outcome, outcome))

    first = runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])
    second = runtime.propose(pr173_fixture['snapshot'], pr173_fixture['plan'])

    assert first.proposal_fingerprint == second.proposal_fingerprint
    assert session.statistics.runtime_build_count == 1
    assert session.statistics.reuse_count == 1


class _RecordingAskEngine:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def ask(self, _snapshot, _request):
        return SimpleNamespace(answer='story accepted', conversation_id=1)


def _session(monkeypatch, fixture, commands: str):
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: ScriptedLlmProvider(()),
    )
    monkeypatch.setattr(atlas_cli, 'AskEngine', _RecordingAskEngine)
    return CliRunner().invoke(
        atlas_cli.app,
        ['ai', 'session', str(fixture['root'])],
        input=commands,
    )


def test_implement_requires_loaded_story(pr173_fixture, monkeypatch) -> None:
    result = _session(monkeypatch, pr173_fixture, '/implement\n/exit\n')

    assert result.exit_code == 0, result.output
    assert 'error: no story loaded' in result.output


def test_implement_requires_explicit_current_plan(pr173_fixture, monkeypatch) -> None:
    result = _session(
        monkeypatch,
        pr173_fixture,
        '/story\n- Change behavior.\n/end\n/implement\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert 'error: no current story plan; run /plan first' in result.output
    assert 'story accepted' in result.output


def test_stats_exposes_engineering_provider_telemetry(pr173_fixture) -> None:
    runtime, _, session = _runtime(pr173_fixture, ())
    payload = json.loads(atlas_cli._runtime_statistics_json(
        session,
        runtime.telemetry,
    ))

    assert payload['engineering_provider']['provider'] == 'scripted'
    assert payload['engineering_provider']['device'] == 'unknown'
    assert payload['engineering_provider']['request_count'] == 0


def test_interactive_preview_uses_retained_plan_once_and_keeps_source_clean(
    pr173_fixture,
    monkeypatch,
) -> None:
    provider = ScriptedLlmProvider((
        LlmResponse(_valid_payload(pr173_fixture['root']), 'scripted', 'engineer'),
    ))

    class FixedPlanner:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def plan(self, _snapshot, request):
            assert request.plan_fingerprint == pr173_fixture['plan'].plan_fingerprint
            return pr173_fixture['plan']

    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr173_fixture['snapshot'],
    )
    monkeypatch.setattr(atlas_cli, '_ai_provider_factory', lambda: provider)
    monkeypatch.setattr(atlas_cli, 'AskEngine', _RecordingAskEngine)
    monkeypatch.setattr(atlas_cli, 'StoryPlanningService', FixedPlanner)
    before = (pr173_fixture['root'] / SOURCE_PATH).read_bytes()
    commands = (
        '/story\n' + STORY + '/end\n/plan\n/implement\n/verify\n/diff\n/stats\n/exit\n'
    )
    result = CliRunner().invoke(
        atlas_cli.app,
        [
            'ai', 'session', str(pr173_fixture['root']),
            '--subject', 'method:fixture-primary',
            '--project', PROJECT,
        ],
        input=commands,
    )

    assert result.exit_code == 0, result.output
    assert result.output.count('IMPLEMENTATION PROPOSAL') == 1
    assert result.output.count('VALIDATION PLAN') == 1
    assert result.output.count('ENGINEERING DIFF REVIEW') == 1
    assert 'PREVIEW ONLY; no source was modified' in result.output
    assert len(provider.calls) == 1
    assert (pr173_fixture['root'] / SOURCE_PATH).read_bytes() == before
    statistics = next(
        json.loads(line)
        for line in result.output.splitlines()
        if line.startswith('{') and 'engineering_provider' in line
    )
    assert statistics['runtime_build_count'] == 1
    assert statistics['engineering_provider']['request_count'] == 1
