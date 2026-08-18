from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.agent_context import (
    AgentContextError,
    AgentContextService,
    AgentGraphDepth,
)
from moughorai.ai_context import SemanticContextCollector, WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.public_api import public_api_compatibility_issues
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
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
COLLABORATORS = (
    'certificateIsSigned',
    'completeExercise',
    'isErlSendingProject',
    'getTypeOfAgreement',
    'updateProjectStatus',
    'sendProjectClosureEventType',
    'sendProjectSignatureEventType',
)
STORY = '''Compare erlSendingIsSigned against this Jira story:

- Accept when AgreementType is CERTIFICATE, PRIZE, or EQUITY,
  OR HoponTopup is true,
  OR CallCaseType is STANDALONE_STAGE_1.
- For CERTIFICATE call certificateIsSigned.
- Set GA_PREPARATION status to GA_SIGNED.
- Close GA_PREPARATION.
- For CERTIFICATE set project status to SIGNED.
- For all other accepted cases set project status to CLOSED and Closure_Date to current date.
- Reject all other projects as an invalid ERLSending project type.
'''
DRM_STORY = STORY + (
    '- Run DRM remediation for projects created between the previous DRM '
    'and production deployment.\n'
)

MAIN_SOURCE = '''package story;
class GrantAgreementPreparationExercise {
 static final String CERTIFICATE="CERTIFICATE", PRIZE="PRIZE", EQUITY="EQUITY";
 static String getTypeOfAgreement(Long id) { return CERTIFICATE; }
 static void certificateIsSigned(Long id) { writeAudit(); }
 static void completeExercise(Long id) { setExerciseState("GA_SIGNED"); }
 static boolean isErlSendingProject(String type) { return type != null; }
 static void updateProjectStatus(String status) { writeAudit(); }
 static void sendProjectClosureEventType(Long id) { publishEvent(); }
 static void sendProjectSignatureEventType(Long id) { publishEvent(); }
 static void setExerciseState(String state) { writeAudit(); }
 static void writeAudit() {}
 static void publishEvent() { writeAudit(); }
 static void erlSendingIsSigned(Long id) {
  String type = getTypeOfAgreement(id);
  if (!isErlSendingProject(type)) throw new IllegalArgumentException("invalid");
  if (CERTIFICATE.equals(type)) {
   certificateIsSigned(id); updateProjectStatus("SIGNED");
   sendProjectSignatureEventType(id);
  } else {
   updateProjectStatus("CLOSED"); sendProjectClosureEventType(id);
  }
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
def pr175_fixture(tmp_path_factory):
    base = tmp_path_factory.mktemp('pr175-agent-context')
    root = base / 'repository'
    project_root = root / 'app'
    main = project_root / 'src/main/java/story/GrantAgreementPreparationExercise.java'
    test = project_root / 'src/test/java/story/GrantAgreementPreparationExerciseTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(MAIN_SOURCE, encoding='utf-8', newline='')
    test.write_text(TEST_SOURCE, encoding='utf-8', newline='')
    (project_root / 'pom.xml').write_text(
        '<project><modelVersion>4.0.0</modelVersion></project>',
        encoding='utf-8',
    )
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
        workspace_fingerprint='pr175-agent-context',
        analyzer_version='test-pr175/1',
    )
    index = callable_index_from_dict(payload['java_callable_index'])
    subject = next(
        item for item in index.entries
        if item.identity.name == 'erlSendingIsSigned'
        and item.project_id == PROJECT
    )
    return {
        'base': base,
        'root': root,
        'snapshot': snapshot,
        'subject': subject.canonical_subject_id,
        'sources': (main, test),
    }


def _generate(fixture, *, story=STORY, subject=True, project=PROJECT, depth='story'):
    session = RepositoryRuntimeSession(workspace_root=fixture['root'])
    try:
        artifacts = AgentContextService(
            session,
            workspace_root=fixture['root'],
        ).generate(
            fixture['snapshot'],
            story_text=story,
            subject=fixture['subject'] if subject else None,
            project=project,
            depth=depth,
        )
        statistics = session.statistics
    finally:
        session.close()
    return artifacts, statistics


def test_selected_subject_project_package_and_requirement_links(pr175_fixture) -> None:
    artifacts, statistics = _generate(pr175_fixture)
    graph = artifacts.graph
    package = artifacts.package

    assert package.selected_subject == pr175_fixture['subject']
    assert package.authoritative_project == PROJECT
    assert package.repository_identity['snapshot_id'] == pr175_fixture['snapshot'].snapshot_id
    assert package.context_fingerprint.startswith('agent-context:v1:')
    assert graph.graph_fingerprint.startswith('agent-graph:v1:')
    assert graph.root_subjects == (pr175_fixture['subject'],)
    assert statistics.runtime_build_count == 1
    assert statistics.reuse_count >= 1
    assert package.remediation_operational_work == ()

    names = {item.simple_name for item in graph.nodes}
    assert set(COLLABORATORS) <= names
    assert set(TEST_NAMES) <= names
    assert {item['status'] for item in graph.requirements} <= {
        'IMPLEMENTED', 'PARTIAL', 'MISSING', 'NOT_PROVEN'
    }
    assert any(
        item.type == 'story_requirement_relation' and item.status == 'IMPLEMENTED'
        for item in graph.edges
    )
    assert any(item.type == 'project_ownership' for item in graph.edges)
    assert any(item.type == 'reverse_upstream' for item in graph.edges)
    assert any(item.type == 'forward_test_reachability' for item in graph.edges)
    assert 'Treat Atlas canonical identities' in artifacts.context_markdown
    assert 'Candidate edges are not resolved dependencies.' in artifacts.context_markdown


def test_autonomous_discovery_and_drm_only_when_supplied(pr175_fixture) -> None:
    automatic, _ = _generate(pr175_fixture, subject=False)
    with_drm, _ = _generate(pr175_fixture, subject=False, story=DRM_STORY)

    assert automatic.package.selected_subject == pr175_fixture['subject']
    assert automatic.package.remediation_operational_work == ()
    assert [item['id'] for item in with_drm.package.remediation_operational_work] == ['R8']
    assert with_drm.package.remediation_operational_work[0]['status'] == 'NOT_PROVEN'


def test_deterministic_bytes_fingerprints_ordering_and_bounds(pr175_fixture) -> None:
    first, _ = _generate(pr175_fixture)
    second, _ = _generate(pr175_fixture)
    expanded, _ = _generate(pr175_fixture, depth=AgentGraphDepth.EXPANDED)

    assert first.package.context_fingerprint == second.package.context_fingerprint
    assert first.graph.graph_fingerprint == second.graph.graph_fingerprint
    assert first.package.to_json().encode() == second.package.to_json().encode()
    assert first.context_markdown.encode() == second.context_markdown.encode()
    assert first.graph.to_json().encode() == second.graph.to_json().encode()
    assert first.graph_mermaid.encode() == second.graph_mermaid.encode()
    assert len(first.graph.nodes) <= 100
    assert len(expanded.graph.nodes) <= 500
    assert len(expanded.graph.nodes) >= len(first.graph.nodes)
    assert first.graph.configuration.depth is AgentGraphDepth.STORY
    assert expanded.graph.configuration.depth is AgentGraphDepth.EXPANDED
    assert tuple(first.graph.nodes) == tuple(second.graph.nodes)
    assert tuple(first.graph.edges) == tuple(second.graph.edges)
    assert set(first.graph.omitted_counts) == {
        'candidate_edges', 'direct_callees', 'direct_callers', 'edges',
        'nodes', 'represented_tests', 'requirements', 'uncertainties',
        'upstream_impact',
    }


def test_edge_certainty_source_safety_and_no_full_graph_dump(pr175_fixture) -> None:
    artifacts, _ = _generate(pr175_fixture)
    graph_payload = artifacts.graph.to_json()
    call_edges = [
        item for item in artifacts.graph.edges
        if item.type in {'resolved_direct_call', 'possible_call_target'}
    ]

    assert all(
        item.confidence == 'high_confidence_represented_path'
        for item in call_edges if item.type == 'resolved_direct_call'
    )
    assert all(
        item.confidence == 'conservative_represented_path'
        for item in call_edges if item.type == 'possible_call_target'
    )
    assert MAIN_SOURCE not in graph_payload
    assert TEST_SOURCE not in graph_payload
    assert 'static void erlSendingIsSigned' not in graph_payload
    assert len(artifacts.graph.nodes) < len(
        pr175_fixture['snapshot'].semantic_context['java_callable_index']['entries']
    ) + len(artifacts.graph.requirements) + 2


def test_export_is_byte_identical_external_and_does_not_mutate_sources(pr175_fixture) -> None:
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in pr175_fixture['sources']
    }
    first_output = pr175_fixture['base'] / 'output-one'
    second_output = pr175_fixture['base'] / 'output-two'
    session = RepositoryRuntimeSession(workspace_root=pr175_fixture['root'])
    try:
        service = AgentContextService(session, workspace_root=pr175_fixture['root'])
        first = service.export(
            pr175_fixture['snapshot'],
            story_text=STORY,
            output=first_output,
            subject=pr175_fixture['subject'],
            project=PROJECT,
        )
        second = service.export(
            pr175_fixture['snapshot'],
            story_text=STORY,
            output=second_output,
            subject=pr175_fixture['subject'],
            project=PROJECT,
        )
    finally:
        session.close()

    assert {item.name for item in first_output.iterdir()} == {
        'context.json', 'context.md', 'graph.json', 'graph.mmd'
    }
    for name in ('context.json', 'context.md', 'graph.json', 'graph.mmd'):
        assert (first_output / name).read_bytes() == (second_output / name).read_bytes()
    assert first.package.context_fingerprint == second.package.context_fingerprint
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in pr175_fixture['sources']
    }
    assert all(size > 0 for _, size in first.output_files)


def test_noninteractive_cli_loads_story_without_provider_or_rescan(
    pr175_fixture,
    monkeypatch,
) -> None:
    story_file = pr175_fixture['base'] / 'story.txt'
    output = pr175_fixture['base'] / 'cli-output'
    story_file.write_text(STORY, encoding='utf-8')
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr175_fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: (_ for _ in ()).throw(AssertionError('provider must not be constructed')),
    )
    monkeypatch.setattr(
        JavaLanguageAnalyzer,
        'analyze',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('no rescan')),
    )

    result = CliRunner().invoke(atlas_cli.app, [
        'agent', 'context', str(pr175_fixture['root']),
        '--story-file', str(story_file),
        '--output', str(output),
        '--subject', pr175_fixture['subject'],
        '--project', PROJECT,
    ])

    assert result.exit_code == 0, result.output
    assert 'depth=story' in result.output
    assert {item.name for item in output.iterdir()} == {
        'context.json', 'context.md', 'graph.json', 'graph.mmd'
    }
    context = json.loads((output / 'context.json').read_text(encoding='utf-8'))
    assert context['story']['normalized_text'] == STORY.strip()


def test_wrong_project_and_repository_output_fail_closed(pr175_fixture) -> None:
    with pytest.raises(AgentContextError, match='fail-closed'):
        _generate(pr175_fixture, project='wrong-project')

    session = RepositoryRuntimeSession(workspace_root=pr175_fixture['root'])
    try:
        service = AgentContextService(session, workspace_root=pr175_fixture['root'])
        with pytest.raises(AgentContextError, match='outside'):
            service.export(
                pr175_fixture['snapshot'],
                story_text=STORY,
                output=pr175_fixture['root'] / 'context-output',
                subject=pr175_fixture['subject'],
                project=PROJECT,
            )
    finally:
        session.close()


def test_public_api_v1_unchanged() -> None:
    assert public_api_compatibility_issues() == ()
