from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import SemanticContextCollector, WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.llm import LlmClient, LlmResponse, RetryPolicy, ScriptedLlmProvider
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.story_planning import (
    StoryPlanningRequest,
    StoryPlanningService,
    StoryRequirementStatus,
    render_story_plan,
)
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
)


PROJECT = 'sygma-exercise-h2020-gap-sygma-exercise-h2020-gap-ejb'
TEST_NAMES = (
    'shouldAcceptCertificateProjectForErlSendingIsSigned',
    'shouldAcceptPrizeProjectForErlSendingIsSigned',
    'shouldAcceptEquityProjectForErlSendingIsSigned',
    'shouldAcceptHoponTopupProjectForErlSendingIsSigned',
    'shouldAcceptStandaloneStage1ProjectForErlSendingIsSigned',
    'shouldRejectNormalGAPProjectForErlSendingIsSigned',
    'shouldRejectNormalGrantWithNoFeaturesForErlSendingIsSigned',
)
REAL_STORY = '''Compare erlSendingIsSigned against this Jira story:

- Accept when AgreementType is CERTIFICATE, PRIZE, or EQUITY,
  OR HoponTopup is true,
  OR CallCaseType is STANDALONE_STAGE_1.
- For CERTIFICATE call certificateIsSigned.
- Set GA_PREPARATION status to GA_SIGNED.
- Close GA_PREPARATION.
- For CERTIFICATE set project status to SIGNED.
- For all other accepted cases set project status to CLOSED and Closure_Date to current date.
- Reject all other projects as an invalid ERLSending project type.
- Run DRM remediation for projects created between the previous DRM and production deployment.
'''

MAIN_SOURCE = '''package story;
class GrantAgreementPreparationExercise {
 static final String CERTIFICATE="CERTIFICATE", PRIZE="PRIZE", EQUITY="EQUITY";
 static void certificateIsSigned(Long id) {}
 static final String STANDALONE_STAGE_1="STANDALONE_STAGE_1", GA_SIGNED="GA_SIGNED";
 static final String SIGNED="SIGNED", CLOSED="CLOSED";
 static boolean isErlSendingProject(String AgreementType, boolean HoponTopup, String CallCaseType) {
  return CERTIFICATE.equals(AgreementType) || PRIZE.equals(AgreementType)
   || EQUITY.equals(AgreementType) || HoponTopup || STANDALONE_STAGE_1.equals(CallCaseType);
 }
 static void completeExercise(Long id) { setExerciseState(GA_SIGNED); }
 static void setExerciseState(String state) {}
 static void updateProjectStatus(String status) {}
 static void erlSendingIsSigned(Long id) {
  String AgreementType=CERTIFICATE; boolean HoponTopup=false; String CallCaseType=STANDALONE_STAGE_1;
  if (!isErlSendingProject(AgreementType, HoponTopup, CallCaseType))
   throw new IllegalArgumentException("invalid ERLSending project type");
  if (CERTIFICATE.equals(AgreementType)) { certificateIsSigned(id); updateProjectStatus(SIGNED); }
  else updateProjectStatus(CLOSED);
  completeExercise(id);
 }
}
'''

TEST_SOURCE = '''package story;
@interface Test {}
class GrantAgreementPreparationExerciseTest {
''' + '\n'.join(
    f' @Test void {name}() {{ GrantAgreementPreparationExercise.erlSendingIsSigned(1L); }}'
    for name in TEST_NAMES
) + '''
}
'''


@pytest.fixture(scope='module')
def pr172_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp('pr172-story-planning')
    project_root = root / 'app'
    main = project_root / 'src/main/java/story/GrantAgreementPreparationExercise.java'
    test = project_root / 'src/test/java/story/GrantAgreementPreparationExerciseTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(MAIN_SOURCE, encoding='utf-8')
    test.write_text(TEST_SOURCE, encoding='utf-8')
    (root / 'atlas.yaml').write_text(
        f'projects:\n  - name: {PROJECT}\n    path: app\n',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project(PROJECT, project_root),
        (main, test),
        {},
    )
    report = WorkspaceRunReport(
        (ProjectRun(PROJECT, ProjectRunStatus.SUCCEEDED, document),),
        (PROJECT,),
        (PROJECT,),
    )
    payload = SemanticContextCollector(
        WorkspaceService(root)
    ).collect(report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr172-story-planning',
        analyzer_version='test-pr172/1',
    )
    index = callable_index_from_dict(payload['java_callable_index'])
    entries = {
        item.identity.name: item
        for item in index.entries
        if item.identity.owner_type.endswith('GrantAgreementPreparationExercise')
    }
    return {
        'root': root,
        'snapshot': snapshot,
        'index': index,
        'subject': entries['erlSendingIsSigned'],
    }


def _request(fixture, story=REAL_STORY, *, project=PROJECT):
    return StoryPlanningRequest(
        story,
        fixture['snapshot'].snapshot_id,
        fixture['subject'].canonical_subject_id,
        project,
    )


def _plan(fixture, story=REAL_STORY, *, provider=None, project=PROJECT):
    session = RepositoryRuntimeSession(workspace_root=fixture['root'])
    client = LlmClient(
        provider,
        RetryPolicy(maximum_attempts=1),
    ) if provider is not None else None
    service = StoryPlanningService(
        session,
        workspace_root=fixture['root'],
        llm_client=client,
    )
    plan = service.plan(
        fixture['snapshot'],
        _request(fixture, story, project=project),
    )
    return plan, session


def test_real_story_requirement_order_status_contract_and_drm(pr172_fixture) -> None:
    plan, _ = _plan(pr172_fixture)

    assert [item.requirement_id for item in plan.requirements] == [
        f'R{index}' for index in range(1, 9)
    ]
    assert {item.status for item in plan.requirements}.issubset(
        set(StoryRequirementStatus)
    )
    assert plan.requirements[1].status is StoryRequirementStatus.IMPLEMENTED
    assert plan.requirements[0].status is StoryRequirementStatus.PARTIAL
    assert plan.requirements[7].classification.value == 'remediation'
    assert plan.requirements[7].status is StoryRequirementStatus.NOT_PROVEN
    assert plan.remediation_requirement_ids == ('R8',)


def test_autonomous_discovery_surface_and_seven_represented_tests(
    pr172_fixture,
) -> None:
    plan, _ = _plan(pr172_fixture)

    required_anchors = {
        'erlSendingIsSigned', 'certificateIsSigned', 'AgreementType',
        'CERTIFICATE', 'PRIZE', 'EQUITY', 'HoponTopup', 'CallCaseType',
        'STANDALONE_STAGE_1', 'GA_PREPARATION', 'GA_SIGNED', 'SIGNED',
        'CLOSED', 'Closure_Date',
    }
    assert required_anchors.issubset(set(plan.anchors))
    assert any(
        item.anchor == 'certificateIsSigned'
        and item.project == PROJECT
        for item in plan.discovery
    )
    assert any(
        item.role == 'primary'
        and item.canonical_subject_id == pr172_fixture['subject'].canonical_subject_id
        for item in plan.implementation_surface
    )
    assert any(
        item.display_name.endswith('#certificateIsSigned')
        for item in plan.implementation_surface
    )
    assert {item.display_name for item in plan.represented_tests} == set(TEST_NAMES)


def test_test_names_are_not_behavioral_proof(pr172_fixture) -> None:
    plan, _ = _plan(pr172_fixture)

    implemented = {
        item.requirement_id
        for item in plan.requirements
        if item.status is StoryRequirementStatus.IMPLEMENTED
    }
    assert implemented == {'R2'}
    assert all(
        evidence.kind != 'represented_test'
        for requirement in plan.requirements
        for evidence in requirement.evidence
    )


def test_status_contract_includes_missing_and_not_proven(pr172_fixture) -> None:
    story = '''
- Call certificateIsSigned.
- Call absentHelper.
- Set project status to CLOSED.
- Document ordinary policy behavior.
'''
    plan, _ = _plan(pr172_fixture, story)

    assert [item.status for item in plan.requirements] == [
        StoryRequirementStatus.IMPLEMENTED,
        StoryRequirementStatus.MISSING,
        StoryRequirementStatus.PARTIAL,
        StoryRequirementStatus.NOT_PROVEN,
    ]


def test_provider_empty_output_retains_usable_fallback(pr172_fixture) -> None:
    provider = ScriptedLlmProvider((LlmResponse('', 'scripted', 'test'),))
    plan, _ = _plan(
        pr172_fixture,
        'Improve ordinary behavior safely without a structured list.',
        provider=provider,
    )

    assert len(provider.calls) == 1
    assert len(plan.requirements) == 1
    assert plan.requirements[0].status is StoryRequirementStatus.NOT_PROVEN
    assert plan.normalized_story_text.startswith('Improve ordinary behavior')
    assert not plan.provider_decomposition_used
    assert any('returned no validated story quotes' in item for item in plan.limitations)


def test_unsupported_provider_repository_claim_is_rejected(pr172_fixture) -> None:
    payload = json.dumps({
        'requirements': [{
            'source_quote': 'Improve ordinary behavior safely.',
            'classification': 'other',
            'repository_claim': 'FakeService#inventedMethod',
        }],
    })
    provider = ScriptedLlmProvider((LlmResponse(payload, 'scripted', 'test'),))
    plan, _ = _plan(
        pr172_fixture,
        'Improve ordinary behavior safely.',
        provider=provider,
    )
    rendered = render_story_plan(plan, view='detail')

    assert 'FakeService' not in rendered
    assert 'inventedMethod' not in rendered
    assert not plan.provider_decomposition_used


def test_valid_provider_decomposition_can_only_select_exact_story_quotes(
    pr172_fixture,
) -> None:
    story = 'Accept the request safely. Reject invalid requests.'
    payload = json.dumps({
        'requirements': [
            {'source_quote': 'Accept the request safely.', 'classification': 'eligibility'},
            {'source_quote': 'Reject invalid requests.', 'classification': 'validation'},
        ],
    })
    provider = ScriptedLlmProvider((LlmResponse(payload, 'scripted', 'test'),))
    plan, _ = _plan(pr172_fixture, story, provider=provider)

    assert plan.provider_decomposition_used
    assert [item.text for item in plan.requirements] == [
        'Accept the request safely.',
        'Reject invalid requests.',
    ]
    assert all(
        item.decomposition_source == 'provider_proposed_story_quote'
        for item in plan.requirements
    )
    assert all(
        item.status is StoryRequirementStatus.NOT_PROVEN
        for item in plan.requirements
    )


def test_story_and_plan_fingerprints_are_normalized_and_deterministic(
    pr172_fixture,
) -> None:
    first = _request(pr172_fixture, REAL_STORY.replace('\n', '\r\n'))
    second = _request(pr172_fixture, REAL_STORY)
    changed_project = _request(pr172_fixture, REAL_STORY, project='other-project')

    assert first.story_fingerprint == second.story_fingerprint
    assert first.plan_fingerprint == second.plan_fingerprint
    assert first.plan_fingerprint != changed_project.plan_fingerprint


def test_repeated_plan_bytes_and_runtime_components_are_reused(pr172_fixture) -> None:
    session = RepositoryRuntimeSession(workspace_root=pr172_fixture['root'])
    service = StoryPlanningService(session, workspace_root=pr172_fixture['root'])
    request = _request(pr172_fixture)

    first = service.plan(pr172_fixture['snapshot'], request)
    second = service.plan(pr172_fixture['snapshot'], request)

    assert render_story_plan(first) == render_story_plan(second)
    statistics = session.statistics
    assert statistics.runtime_build_count == 1
    assert statistics.reuse_count == 1
    assert max(dict(statistics.component_build_counts).values()) == 1


def test_wrong_project_remains_fail_closed(pr172_fixture) -> None:
    plan, _ = _plan(pr172_fixture, project='wrong-project')

    assert plan.subject_resolution_status == 'not_found'
    assert plan.implementation_surface == ()
    assert plan.represented_tests == ()
    assert all(
        item.status is StoryRequirementStatus.NOT_PROVEN
        for item in plan.requirements
    )


class _RecordingAskEngine:
    requests = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.__class__.requests = []

    def ask(self, _snapshot, request):
        self.__class__.requests.append(request)
        return SimpleNamespace(answer='recorded story ask', conversation_id=1)


def _invoke_session(monkeypatch, fixture, commands: str):
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
        [
            'ai', 'session', str(fixture['root']),
            '--subject', fixture['subject'].canonical_subject_id,
            '--project', PROJECT,
            '--capability', 'code_impact',
        ],
        input=commands,
    )


def test_story_file_is_retained_for_plan_and_pr171_submission_is_atomic(
    pr172_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / 'Jira story with spaces.txt'
    path.write_text(REAL_STORY, encoding='utf-8')

    result = _invoke_session(
        monkeypatch,
        pr172_fixture,
        f'/story-file {path}\n/plan\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert len(_RecordingAskEngine.requests) == 1
    assert _RecordingAskEngine.requests[0].question == (
        path.read_bytes().decode('utf-8').strip()
    )
    assert result.output.count('STORY PLAN') == 1
    assert 'runtime_build_count' in result.output


def test_multiline_story_is_retained_and_repeated_plan_uses_cache(
    pr172_fixture,
    monkeypatch,
) -> None:
    commands = '/story\n- Call certificateIsSigned.\n/end\n/plan\n/plan\n/exit\n'
    result = _invoke_session(monkeypatch, pr172_fixture, commands)

    assert result.exit_code == 0, result.output
    assert len(_RecordingAskEngine.requests) == 1
    assert _RecordingAskEngine.requests[0].question == '- Call certificateIsSigned.'
    assert result.output.count('STORY PLAN') == 2
    blocks = result.output.split('STORY PLAN')[1:]
    first_fingerprint = next(
        line for line in blocks[0].splitlines() if 'plan fingerprint:' in line
    )
    second_fingerprint = next(
        line for line in blocks[1].splitlines() if 'plan fingerprint:' in line
    )
    assert first_fingerprint == second_fingerprint


def test_plan_without_story_and_invalid_view_fail_cleanly(
    pr172_fixture,
    monkeypatch,
) -> None:
    result = _invoke_session(
        monkeypatch,
        pr172_fixture,
        '/plan\n/plan enormous\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert 'error: no story loaded; use /story or /story-file first' in result.output
    assert 'error: usage: /plan [detail]' in result.output
    assert _RecordingAskEngine.requests == []


def test_session_story_state_is_disposable_and_replacement_clears_cache() -> None:
    state = atlas_cli._SessionStoryState()
    state.load('First\r\nstory')
    first = state.fingerprint
    state.load('Second story')

    assert state.text == 'Second story'
    assert state.fingerprint != first
