from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.agent_context import AgentContextError, AgentContextService
from moughorai.ai_context import SemanticContextCollector, WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
)


PROJECT_A = 'sygma-topic-workflow-ejb'
PROJECT_B = 'sygma-project-workflow-ejb'

SOURCE_A = '''package discovery;
class CacheService {
 static CacheService getInstance() { return new CacheService(); }
 static Topic getTopicCacheById(Integer id) { return loadTopic(id); }
 static Topic loadTopic(Integer id) { return new Topic(); }
 static void resetSelection() { clearTopic(); }
 static void clearTopic() {}
}
class Topic {}
class TopicWorkflow {
 static void selectTopic(Topic topic) { retrieveProjects(topic); }
 static void retrieveProjects(Topic topic) {}
}
'''

SOURCE_B = '''package discovery;
class ProjectWorkflow {
 static ProjectWorkflow getInstance() { return new ProjectWorkflow(); }
 static void resetSelection() { clearProject(); }
 static void clearProject() {}
 static void selectProject(Integer id) {}
}
'''


@pytest.fixture(scope='module')
def discovery_fixture(tmp_path_factory):
    base = tmp_path_factory.mktemp('pr176-agent-discovery')
    root = base / 'repository'
    project_a = root / 'topic'
    project_b = root / 'project'
    source_a = project_a / 'src/main/java/discovery/CacheService.java'
    source_b = project_b / 'src/main/java/discovery/ProjectWorkflow.java'
    for path, source in ((source_a, SOURCE_A), (source_b, SOURCE_B)):
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding='utf-8', newline='')
        (path.parents[4] / 'pom.xml').write_text(
            '<project><modelVersion>4.0.0</modelVersion></project>',
            encoding='utf-8',
        )
    (root / 'atlas.yaml').write_text(
        'projects:\n'
        f'  - name: {PROJECT_A}\n'
        '    path: topic\n'
        f'  - name: {PROJECT_B}\n'
        '    path: project\n',
        encoding='utf-8',
    )
    documents = []
    for name, project_root, source in (
        (PROJECT_A, project_a, source_a),
        (PROJECT_B, project_b, source_b),
    ):
        document = JavaLanguageAnalyzer().analyze(
            Project(name, project_root),
            (source,),
            {},
        )
        documents.append(ProjectRun(name, ProjectRunStatus.SUCCEEDED, document))
    report = WorkspaceRunReport(
        tuple(documents),
        (PROJECT_A, PROJECT_B),
        (PROJECT_A, PROJECT_B),
    )
    payload = SemanticContextCollector(
        WorkspaceService(root)
    ).collect(report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr176-agent-discovery',
        analyzer_version='test-pr176/1',
    )
    entries = callable_index_from_dict(payload['java_callable_index']).entries
    subjects = {
        (item.project_id, item.identity.name): item.canonical_subject_id
        for item in entries
    }
    return {
        'base': base,
        'root': root,
        'snapshot': snapshot,
        'sources': (source_a, source_b),
        'subjects': subjects,
    }


def _generate(fixture, story, *, project=None, depth='story'):
    session = RepositoryRuntimeSession(workspace_root=fixture['root'])
    try:
        return AgentContextService(
            session,
            workspace_root=fixture['root'],
        ).generate(
            fixture['snapshot'],
            story_text=story,
            project=project,
            depth=depth,
        )
    finally:
        session.close()


@pytest.mark.parametrize('length', (3_001, 10_000, 25_000, 50_000))
def test_agent_story_character_boundaries_succeed(tmp_path, length) -> None:
    story = 'A' * length
    path = tmp_path / f'story-{length}.txt'
    path.write_text(story, encoding='utf-8')

    loaded = atlas_cli._read_agent_story_file(path)

    assert loaded.text == story
    assert len(loaded.text) == length
    assert loaded.byte_count == length


def test_agent_story_multibyte_boundary_and_no_truncation(tmp_path) -> None:
    story = 'é' * 50_000
    path = tmp_path / 'multibyte-story.txt'
    path.write_text(story, encoding='utf-8')

    loaded = atlas_cli._read_agent_story_file(path)

    assert loaded.text == story
    assert len(loaded.text) == 50_000
    assert loaded.byte_count == 100_000


def test_agent_story_limits_fail_explicitly_and_interactive_limit_is_unchanged(
    tmp_path,
) -> None:
    over_characters = tmp_path / 'over-characters.txt'
    over_characters.write_text('A' * 50_001, encoding='utf-8')
    over_bytes = tmp_path / 'over-bytes.txt'
    over_bytes.write_text('😀' * 65_537, encoding='utf-8')

    with pytest.raises(ValueError, match='normalized characters'):
        atlas_cli._read_agent_story_file(over_characters)
    with pytest.raises(ValueError, match='256 KiB'):
        atlas_cli._read_agent_story_file(over_bytes)
    with pytest.raises(ValueError, match='accepted maximum is 3000'):
        atlas_cli._validate_session_request_text('A' * 3_001, label='story')


def test_subject_free_one_root_and_multi_root_candidate_projection(
    discovery_fixture,
) -> None:
    one = _generate(
        discovery_fixture,
        'Change getTopicCacheById so Topic search uses the selected Topic.',
    )
    multi = _generate(
        discovery_fixture,
        (
            'Use CacheService.getTopicCacheById for Topic search, then '
            'retrieveProjects for the selected Topic and resetSelection '
            'when Reset behavior is requested.'
        ),
    )

    assert one.package.version == one.graph.version == 3
    assert one.package.selected_subject == discovery_fixture['subjects'][
        (PROJECT_A, 'getTopicCacheById')
    ]
    assert one.graph.discovered_roots[0].classification == 'resolved'
    assert one.graph.discovered_roots[0].simple_name == 'getTopicCacheById'
    assert len(multi.graph.discovered_roots) >= 3
    assert multi.graph.discovered_roots[0].simple_name == 'getTopicCacheById'
    assert any(
        item.classification == 'candidate'
        for item in multi.graph.discovered_roots
    )
    assert all(
        'CacheService#getInstance' in item.qualified_name
        for item in multi.graph.discovered_roots
        if item.simple_name == 'getInstance'
    )
    assert {
        item.canonical_subject_id for item in multi.graph.discovered_roots
    } <= set(multi.graph.root_subjects)
    assert '## Discovered roots' in multi.context_markdown
    assert '### Authoritative / resolved roots' in multi.context_markdown
    assert '### Candidate / uncertain roots' in multi.context_markdown
    assert 'Start with Atlas ranked roots.' in multi.context_markdown
    assert len(multi.graph.nodes) <= 100
    assert len(multi.graph.edges) <= 600
    assert multi.graph.omitted_counts['discovery_search_matches'] >= 0
    assert multi.package.story_anchors
    assert multi.package.discovery_diagnostics['search_stage_order'] == [
        'strong_anchor_extraction',
        'exact_identity',
        'represented_source_name',
        'semantic_search',
        'role_diversity',
        'graph_expansion',
    ]
    assert multi.package.discovery_diagnostics['weak_matches_penalized'] >= 0
    assert multi.package.to_dict()['story_anchors']
    assert 'External/unresolved technical anchors' in multi.context_markdown or (
        not any(item.role == 'external_symbol' for item in multi.graph.discovered_roots)
    )


def test_ambiguous_and_no_useful_root_packages_remain_conservative(
    discovery_fixture,
) -> None:
    ambiguous = _generate(
        discovery_fixture,
        'Change resetSelection behavior after Reset.',
    )
    no_root = _generate(
        discovery_fixture,
        'Change the screen behavior described by this business request.',
    )

    reset_roots = tuple(
        item for item in ambiguous.graph.discovered_roots
        if item.simple_name == 'resetSelection'
    )
    assert len(reset_roots) == 2
    assert all(item.classification == 'candidate' for item in reset_roots)
    assert ambiguous.package.selected_subject is None
    assert no_root.graph.root_subjects == ()
    assert no_root.graph.discovered_roots == ()
    assert no_root.package.selected_subject is None
    assert any(
        'No sufficiently authoritative' in item
        for item in no_root.package.uncertainty
    )
    assert {item.kind for item in no_root.graph.nodes} <= {'story', 'requirement'}


def test_project_scope_resolves_ambiguity_and_wrong_project_fails_closed(
    discovery_fixture,
) -> None:
    scoped = _generate(
        discovery_fixture,
        'Change resetSelection behavior after Reset.',
        project=PROJECT_A,
    )

    assert scoped.package.authoritative_project == PROJECT_A
    assert scoped.package.selected_subject == discovery_fixture['subjects'][
        (PROJECT_A, 'resetSelection')
    ]
    assert {item.project for item in scoped.graph.discovered_roots} == {PROJECT_A}
    with pytest.raises(AgentContextError, match='fail-closed'):
        _generate(
            discovery_fixture,
            'Change getTopicCacheById.',
            project='wrong-project',
        )


def test_subject_free_output_is_deterministic_provider_free_and_read_only(
    discovery_fixture,
    monkeypatch,
) -> None:
    story = (
        'Use CacheService.getTopicCacheById for Topic search, '
        'retrieveProjects for the selected Topic, and resetSelection on Reset.'
    )
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in discovery_fixture['sources']
    }
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: (_ for _ in ()).throw(AssertionError('provider constructed')),
    )
    monkeypatch.setattr(
        JavaLanguageAnalyzer,
        'analyze',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('rescan')),
    )

    first = _generate(discovery_fixture, story)
    second = _generate(discovery_fixture, story)

    assert first.package.to_json().encode() == second.package.to_json().encode()
    assert first.context_markdown.encode() == second.context_markdown.encode()
    assert first.graph.to_json().encode() == second.graph.to_json().encode()
    assert first.graph_mermaid.encode() == second.graph_mermaid.encode()
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in discovery_fixture['sources']
    }
    assert all(
        item.classification == 'candidate'
        for item in first.graph.discovered_roots
        if item.classification != 'resolved'
    )


def test_cli_accepts_long_subject_free_story_without_provider(
    discovery_fixture,
    monkeypatch,
) -> None:
    story = 'Change getTopicCacheById.\n\n' + ('business context ' * 700)
    story_file = discovery_fixture['base'] / 'long-story.txt'
    story_file.write_text(story, encoding='utf-8')
    output = discovery_fixture['base'] / 'long-story-output'
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: discovery_fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: (_ for _ in ()).throw(AssertionError('provider constructed')),
    )

    result = CliRunner().invoke(atlas_cli.app, [
        'agent', 'context', str(discovery_fixture['root']),
        '--story-file', str(story_file),
        '--output', str(output),
        '--depth', 'story',
    ])

    assert result.exit_code == 0, result.output
    assert len(atlas_cli._read_agent_story_file(story_file).text) > 10_000
    assert {item.name for item in output.iterdir()} == {
        'context.json', 'context.md', 'graph.json', 'graph.mmd'
    }
