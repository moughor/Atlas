from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
import moughorai.git_diff as git_diff_module
from moughorai.agent_context import (
    AgentContextPackage,
    AgentDiscoveredRoot,
    AgentGraphConfiguration,
    AgentGraphEdge,
    AgentGraphNode,
    AgentGraphProjection,
    load_agent_context_package,
    load_agent_graph_projection,
)
from moughorai.agent_context.models import fingerprint
from moughorai.agent_review import (
    AgentReviewError,
    AgentReviewService,
    ChangedFileStatus,
    EvidenceFreshness,
    ScopeClassification,
    render_agent_post_change_review,
)
from moughorai.git_diff import (
    DiffFile,
    DiffHunk,
    GitDiff,
    GitDiffService,
    UntrackedPaths,
)
from moughorai.knowledge_graph import (
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.semantic_snapshot.store import SemanticSnapshotStore


PORTAL = (
    'portal/src/main/java/ui/PortalBOLeftPanelContent4ScopeProject.java'
)
CLIENT = 'client/src/main/java/search/IProjectSearchBean.java'
EJB = 'ejb/src/main/java/search/ProjectSearchBean.java'
TEST = 'tests/src/test/java/search/ProjectSearchBeanTest.java'
EXPANSION = 'domain/src/main/java/search/ProjectSearchCriteria.java'
CANONICAL = 'canonical/src/main/java/search/CanonicalTarget.java'
UNEXPECTED = 'other/src/main/java/unrelated/Unrelated.java'


def _knowledge_node(identifier, kind, name, project, path=None):
    metadata = (('path', path),) if path is not None else ()
    return KnowledgeNode(
        identifier,
        kind,
        name,
        metadata=metadata,
        qualified_name=name,
        project_id=project,
        language='java',
    )


def _root(identifier, name, project, path, rank, role):
    return AgentDiscoveredRoot(
        identifier,
        'source_file',
        name,
        name,
        project,
        path,
        None,
        rank,
        'candidate',
        'medium',
        'atlas-story-discovery',
        (name,),
        ('Exact represented source-name match.',),
        (),
        role,
        600 - rank,
        ('Role-diverse deterministic ranking.',),
        ('represented_source_name',),
    )


def _with_graph_fingerprint(graph):
    return replace(
        graph,
        graph_fingerprint=fingerprint(
            'agent-graph', graph.payload_without_fingerprint()
        ),
    )


def _with_context_fingerprint(context):
    return replace(
        context,
        context_fingerprint=fingerprint(
            'agent-context', context.payload_without_fingerprint()
        ),
    )


@pytest.fixture
def review_authority(tmp_path):
    root = tmp_path / 'repository'
    paths = (PORTAL, CLIENT, EJB, TEST, EXPANSION, CANONICAL, UNEXPECTED)
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            'class Fixture { String marker = SOURCE-CONTENT-MUST-NOT-LEAK; }\n',
            encoding='utf-8',
        )

    projects = {
        'portal': 'portal',
        'client': 'client',
        'ejb': 'ejb',
        'tests': 'tests',
        'domain': 'domain',
        'canonical': 'canonical',
        'other': 'other',
    }
    knowledge_nodes = [
        _knowledge_node(
            f'project:{name}', KnowledgeKind.PROJECT, name, name, path
        )
        for name, path in projects.items()
    ]
    represented = (
        ('type:client', 'search.IProjectSearchBean', 'client', CLIENT),
        ('type:ejb', 'search.ProjectSearchBean', 'ejb', EJB),
        ('test:resolve', 'search.ProjectSearchBeanTest#shouldResolveSearchBean', 'tests', TEST),
        ('type:expansion', 'search.ProjectSearchCriteria', 'domain', EXPANSION),
        ('type:canonical', 'search.CanonicalTarget', 'canonical', CANONICAL),
        ('type:unexpected', 'unrelated.Unrelated', 'other', UNEXPECTED),
    )
    knowledge_nodes.extend(
        _knowledge_node(identifier, KnowledgeKind.TYPE, name, project)
        for identifier, name, project, _ in represented
    )
    symbols = [
        {
            'id': identifier,
            'name': name.rsplit('.', 1)[-1],
            'source': path,
        }
        for identifier, name, _, path in represented
    ]
    semantic_graph = KnowledgeGraph(tuple(knowledge_nodes), ())
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            'schema_version': 1,
            'semantic_graph': semantic_graph.to_dict(),
            'symbols': symbols,
        }),
        workspace_fingerprint='pr178-pre-change-workspace',
        analyzer_version='test-pr178/1',
        history_reference=178,
    )

    roots = (
        _root(
            'source_file:portal',
            'PortalBOLeftPanelContent4ScopeProject',
            'portal', PORTAL, 1, 'ui',
        ),
        _root(
            'source_file:client', 'IProjectSearchBean',
            'client', CLIENT, 2, 'service_interface',
        ),
        _root(
            'source_file:ejb', 'ProjectSearchBean',
            'ejb', EJB, 3, 'service',
        ),
    )
    graph_nodes = [
        AgentGraphNode('story', 'story', 'SYGMA-63059', 'Jira story', None, None, None, 'story', 'high'),
        AgentGraphNode('R1', 'requirement', 'R1', 'R1', None, None, None, 'requirement_anchor', 'medium'),
        *(AgentGraphNode(
            item.canonical_subject_id, 'source_file', item.qualified_name,
            item.simple_name, item.project, item.source_path, None,
            item.role, item.confidence,
        ) for item in roots),
        AgentGraphNode('test:resolve', 'test', represented[2][1], 'shouldResolveSearchBean', 'tests', TEST, None, 'represented_test', 'medium'),
        AgentGraphNode('type:canonical', 'type', represented[4][1], 'CanonicalTarget', 'canonical', CANONICAL, None, 'collaborator', 'high'),
        AgentGraphNode('type:expansion', 'type', represented[3][1], 'ProjectSearchCriteria', 'domain', EXPANSION, None, 'domain', 'medium'),
        AgentGraphNode('type:unexpected', 'type', represented[5][1], 'Unrelated', 'other', UNEXPECTED, None, 'unknown', 'medium'),
    ]
    graph_nodes.extend(
        AgentGraphNode(
            f'project:{name}', 'project', name, name, name, path,
            None, 'project', 'high',
        )
        for name, path in projects.items()
    )
    graph_edges = [
        AgentGraphEdge('story', 'R1', 'story_requirement_relation', 'medium', 'atlas-pr172', status='NOT_PROVEN'),
        AgentGraphEdge('R1', roots[0].canonical_subject_id, 'story_requirement_relation', 'medium', 'atlas-pr172', status='NOT_PROVEN'),
        AgentGraphEdge(roots[0].canonical_subject_id, roots[1].canonical_subject_id, 'possible_call_target', 'conservative_represented_path', 'atlas-java-graph'),
        AgentGraphEdge(roots[1].canonical_subject_id, roots[2].canonical_subject_id, 'resolved_direct_call', 'high_confidence_represented_path', 'atlas-java-graph'),
        AgentGraphEdge(roots[2].canonical_subject_id, 'test:resolve', 'forward_test_reachability', 'medium', 'atlas-test-reachability'),
    ]
    graph_edges.extend(
        AgentGraphEdge(
            f'project:{root_item.project}', root_item.canonical_subject_id,
            'project_ownership', 'high', 'atlas-project-ownership',
        )
        for root_item in roots
    )
    provisional_graph = AgentGraphProjection(
        'agent-graph:v1:' + '0' * 64,
        snapshot.snapshot_id,
        'story:v1:63059',
        'story-plan:v1:63059',
        AgentGraphConfiguration(),
        tuple(item.canonical_subject_id for item in roots),
        tuple(graph_nodes),
        tuple(graph_edges),
        ('test:resolve',),
        ({
            'id': 'R1',
            'text': 'Add Topic search and selected Project behavior.',
            'classification': 'functional',
            'status': 'NOT_PROVEN',
            'linked_subjects': [item.canonical_subject_id for item in roots],
            'evidence_ids': ['story:R1'],
            'uncertainty': ['Runtime behavior requires validation.'],
        },),
        ('Candidate roots require source inspection.',),
        {
            'candidate_edges': 0,
            'direct_callees': 0,
            'direct_callers': 0,
            'edges': 0,
            'nodes': 0,
            'represented_tests': 0,
            'requirements': 0,
            'uncertainties': 0,
            'upstream_impact': 0,
            'discovery_roots': 0,
            'discovery_search_matches': 0,
        },
        roots,
    )
    graph = _with_graph_fingerprint(provisional_graph)
    reference = lambda node_id, qualified, simple, project, path, role: {
        'id': node_id,
        'qualified_name': qualified,
        'simple_name': simple,
        'project': project,
        'source_ref': path,
        'role': role,
        'confidence': 'medium',
    }
    requirement = {
        'id': 'R1',
        'text': 'Add Topic search and selected Project behavior.',
        'classification': 'functional',
        'status': 'NOT_PROVEN',
        'linked_subjects': [item.canonical_subject_id for item in roots],
        'evidence_ids': ['story:R1'],
        'uncertainty': ['Runtime behavior requires validation.'],
    }
    provisional_context = AgentContextPackage(
        context_fingerprint='agent-context:v1:' + '0' * 64,
        story={
            'normalized_text': 'SYGMA-63059 add Topic search and selected Project behavior.',
            'fingerprint': graph.story_fingerprint,
            'plan_fingerprint': graph.plan_fingerprint,
            'provider_decomposition_used': False,
        },
        repository_identity={
            'repository_root': root.as_posix(),
            'snapshot_id': snapshot.snapshot_id,
            'snapshot_schema_version': snapshot.schema_version,
            'workspace_fingerprint': snapshot.workspace_fingerprint,
            'analyzer_version': snapshot.analyzer_version,
            'history_reference': snapshot.history_reference,
            'callable_index_fingerprint': None,
            'code_graph_fingerprint': None,
            'test_evidence_fingerprint': None,
            'reachability_fingerprint': None,
        },
        authoritative_project=None,
        selected_subject=None,
        primary_implementation_surface=tuple(
            reference(
                item.canonical_subject_id, item.qualified_name, item.simple_name,
                item.project, item.source_path, item.role,
            ) for item in roots
        ),
        important_collaborators=(),
        represented_callers=(
            reference('type:canonical', represented[4][1], 'CanonicalTarget', 'canonical', CANONICAL, 'caller'),
        ),
        represented_callees=(
            reference('type:expansion', represented[3][1], 'ProjectSearchCriteria', 'domain', EXPANSION, 'callee'),
        ),
        impact_summary={
            'included_count': 0, 'omitted_count': 0,
            'subjects': [], 'direction': 'reverse_upstream',
        },
        represented_tests=(
            reference('test:resolve', represented[2][1], 'shouldResolveSearchBean', 'tests', TEST, 'represented_test'),
        ),
        requirement_reconciliation=(requirement,),
        remediation_operational_work=(),
        uncertainty=('Candidate roots require source inspection.',),
        recommended_investigation_order=(),
        validation_guidance={
            'commands': [],
            'represented_tests': ['shouldResolveSearchBean'],
            'limitations': ['Represented reachability is not runtime coverage.'],
        },
        graph_artifacts={
            'json': 'graph.json',
            'mermaid': 'graph.mmd',
            'depth': 'story',
            'fingerprint': graph.graph_fingerprint,
            'node_count': len(graph.nodes),
            'edge_count': len(graph.edges),
            'omitted_counts': graph.omitted_counts,
        },
        expected_change_surface={
            'canonical_subject_ids': ['type:canonical'],
            'source_paths': [PORTAL, CLIENT, EJB],
            'authoritative_project': None,
            'authoritative_projects': ['portal', 'client', 'ejb', 'domain', 'canonical'],
            'root_subject_ids': [item.canonical_subject_id for item in roots],
            'snapshot_id': snapshot.snapshot_id,
        },
        discovered_roots=roots,
        story_anchors=(),
        discovery_diagnostics={},
    )
    context = _with_context_fingerprint(provisional_context)
    return {
        'root': root,
        'snapshot': snapshot,
        'context': context,
        'graph': graph,
        'roots': roots,
        'paths': paths,
    }


def _diff(*files):
    return GitDiff(
        tuple(files),
        base='baseline',
        repository_head='b' * 40,
        base_commit='a' * 40,
    )


def _review(authority, diff, untracked=()):
    paths = UntrackedPaths(tuple(untracked), len(untracked), 0)
    return AgentReviewService(
        authority['snapshot'], repository_root=authority['root']
    ).review(authority['context'], authority['graph'], diff, paths)


def _write_authority(authority, directory, version=3):
    roots = authority['roots']
    graph = authority['graph']
    context = authority['context']
    if version == 1:
        graph = replace(
            graph,
            version=1,
            producer='atlas-pr175/1',
            discovered_roots=(),
            graph_fingerprint='agent-graph:v1:' + '0' * 64,
        )
        graph = _with_graph_fingerprint(graph)
        context = replace(
            context,
            version=1,
            producer='atlas-pr175/1',
            selected_subject=roots[0].canonical_subject_id,
            discovered_roots=(),
            story_anchors=(),
            discovery_diagnostics=None,
            graph_artifacts={
                **context.graph_artifacts,
                'fingerprint': graph.graph_fingerprint,
            },
            context_fingerprint='agent-context:v1:' + '0' * 64,
        )
    elif version == 2:
        legacy_roots = tuple(replace(item, contract_version=2) for item in roots)
        graph = replace(
            graph,
            version=2,
            producer='atlas-pr176/2',
            discovered_roots=legacy_roots,
            graph_fingerprint='agent-graph:v1:' + '0' * 64,
        )
        graph = _with_graph_fingerprint(graph)
        context = replace(
            context,
            version=2,
            producer='atlas-pr176/2',
            discovered_roots=legacy_roots,
            story_anchors=(),
            discovery_diagnostics=None,
            graph_artifacts={
                **context.graph_artifacts,
                'fingerprint': graph.graph_fingerprint,
            },
            context_fingerprint='agent-context:v1:' + '0' * 64,
        )
    context = _with_context_fingerprint(context)
    directory.mkdir(parents=True, exist_ok=True)
    context_path = directory / 'context.json'
    graph_path = directory / 'graph.json'
    context_path.write_text(context.to_json(), encoding='utf-8', newline='')
    graph_path.write_text(graph.to_json(), encoding='utf-8', newline='')
    return context_path, graph_path, context, graph


@pytest.mark.parametrize('version', (1, 2, 3))
def test_context_and_graph_authority_versions_round_trip(
    review_authority, tmp_path, version,
) -> None:
    context_path, graph_path, context, graph = _write_authority(
        review_authority, tmp_path / f'v{version}', version
    )

    assert load_agent_context_package(context_path).to_dict() == context.to_dict()
    assert load_agent_graph_projection(graph_path).to_dict() == graph.to_dict()


def test_context_and_graph_fingerprint_tampering_fails_closed(
    review_authority, tmp_path,
) -> None:
    context_path, graph_path, _, _ = _write_authority(
        review_authority, tmp_path / 'authority'
    )
    context_payload = json.loads(context_path.read_text(encoding='utf-8'))
    context_payload['story']['normalized_text'] = 'tampered'
    context_path.write_text(json.dumps(context_payload), encoding='utf-8')
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        load_agent_context_package(context_path)

    graph_payload = json.loads(graph_path.read_text(encoding='utf-8'))
    graph_payload['uncertainties'].append('tampered')
    graph_path.write_text(json.dumps(graph_payload), encoding='utf-8')
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        load_agent_graph_projection(graph_path)


def _modified(path, *, binary=False):
    hunks = () if binary else (DiffHunk(1, 1, 1, 1, (1,), (1,)),)
    return DiffFile(path, path, hunks, binary=binary)


def test_sygma_63059_known_three_file_benchmark(review_authority) -> None:
    review = _review(
        review_authority,
        _diff(_modified(PORTAL), _modified(CLIENT), _modified(EJB)),
    )

    assert [item.scope_classification for item in review.changed_files] == [
        ScopeClassification.WITHIN_EXPECTED_SURFACE,
        ScopeClassification.WITHIN_EXPECTED_SURFACE,
        ScopeClassification.WITHIN_EXPECTED_SURFACE,
    ]
    assert [item.simple_name for item in review.matched_roots] == [
        'PortalBOLeftPanelContent4ScopeProject',
        'IProjectSearchBean',
        'ProjectSearchBean',
    ]
    assert all(item.classification == 'candidate' for item in review.matched_roots)
    assert review.project_expansion == ()
    assert {item.simple_name for item in review.represented_tests} == {
        'shouldResolveSearchBean'
    }
    assert [(item.requirement_id, item.status) for item in review.related_requirements] == [
        ('R1', 'NOT_PROVEN')
    ]
    assert EvidenceFreshness.STALE_FOR_CURRENT_SEMANTICS in review.evidence_freshness
    assert review.base_provenance.value == 'UNKNOWN_BASE_PROVENANCE'
    assert 'correct' not in (review.overall_scope.value if review.overall_scope else '').lower()


def test_deterministic_json_human_order_and_no_source_contents(
    review_authority,
) -> None:
    diff = _diff(_modified(EJB), _modified(PORTAL), _modified(CLIENT))
    first = _review(review_authority, diff)
    second = _review(
        review_authority,
        _diff(_modified(CLIENT), _modified(PORTAL), _modified(EJB)),
    )

    assert first.review_fingerprint == second.review_fingerprint
    assert first.to_json().encode() == second.to_json().encode()
    assert render_agent_post_change_review(first).encode() == (
        render_agent_post_change_review(second).encode()
    )
    assert 'SOURCE-CONTENT-MUST-NOT-LEAK' not in first.to_json()
    assert 'PASS' not in render_agent_post_change_review(first)
    assert 'FAIL' not in render_agent_post_change_review(first)


def test_exact_subject_project_expansion_unexpected_and_unrepresented(
    review_authority,
) -> None:
    canonical = _review(review_authority, _diff(_modified(CANONICAL)))
    plausible = _review(review_authority, _diff(_modified(EXPANSION)))
    unexpected = _review(review_authority, _diff(_modified(UNEXPECTED)))
    unrepresented = _review(
        review_authority,
        _diff(),
        ('new/src/main/java/NewTopicView.java',),
    )

    assert canonical.changed_files[0].scope_classification is (
        ScopeClassification.WITHIN_EXPECTED_SURFACE
    )
    assert canonical.changed_files[0].matched_expected_subjects == ('type:canonical',)
    assert plausible.changed_files[0].scope_classification is (
        ScopeClassification.PLAUSIBLE_SCOPE_EXPANSION
    )
    assert unexpected.changed_files[0].scope_classification is (
        ScopeClassification.UNEXPECTED_SCOPE
    )
    assert unexpected.project_expansion == ('other',)
    new_file = unrepresented.changed_files[0]
    assert new_file.status is ChangedFileStatus.UNTRACKED
    assert new_file.scope_classification is ScopeClassification.UNREPRESENTED_CHANGE
    assert new_file.evidence_freshness is EvidenceFreshness.NO_PRE_CHANGE_EVIDENCE
    assert new_file.canonical_subjects == ()
    assert new_file.project_fallbacks == ()


@pytest.mark.parametrize(
    ('file', 'status'),
    (
        (DiffFile(PORTAL, 'portal/src/main/java/ui/RenamedPortal.java', (), renamed=True), ChangedFileStatus.RENAMED),
        (DiffFile(EJB, None), ChangedFileStatus.DELETED),
        (_modified(CLIENT, binary=True), ChangedFileStatus.MODIFIED),
        (DiffFile(None, 'new/Added.java'), ChangedFileStatus.ADDED),
    ),
)
def test_rename_delete_binary_and_added_are_conservative(
    review_authority, file, status,
) -> None:
    review = _review(review_authority, _diff(file))
    changed = review.changed_files[0]

    assert changed.status is status
    if status in {ChangedFileStatus.RENAMED, ChangedFileStatus.DELETED}:
        assert changed.scope_classification is ScopeClassification.WITHIN_EXPECTED_SURFACE
    if status is ChangedFileStatus.ADDED:
        assert changed.scope_classification is ScopeClassification.UNREPRESENTED_CHANGE
    if file.binary:
        assert any('Binary content' in item for item in changed.limitations)


def test_project_fallback_is_explicit_and_never_a_canonical_subject(
    review_authority,
) -> None:
    review = _review(review_authority, _diff(_modified(PORTAL)))
    changed = review.changed_files[0]

    assert changed.scope_classification is ScopeClassification.WITHIN_EXPECTED_SURFACE
    assert changed.project_fallbacks == ('portal',)
    assert changed.canonical_subjects == ()
    assert any('not exact Java declaration' in item for item in changed.limitations)


def test_candidate_and_resolved_graph_relations_remain_distinct(
    review_authority,
) -> None:
    review = _review(
        review_authority,
        _diff(_modified(PORTAL), _modified(CLIENT)),
    )
    relation_types = {item.type for item in review.graph_relations}

    assert 'possible_call_target' in relation_types
    assert 'resolved_direct_call' in relation_types
    assert all(item.classification == 'candidate' for item in review.matched_roots)


def test_unexpected_change_does_not_inherit_story_tests_or_requirements(
    review_authority,
) -> None:
    review = _review(review_authority, _diff(_modified(UNEXPECTED)))

    assert review.represented_tests == ()
    assert review.related_requirements == ()
    assert review.changed_files[0].scope_classification is ScopeClassification.UNEXPECTED_SCOPE


def test_snapshot_repository_and_graph_mismatches_fail_closed(
    review_authority, tmp_path,
) -> None:
    other_snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({'schema_version': 1}),
        workspace_fingerprint='other',
        analyzer_version='test-pr178/1',
    )
    with pytest.raises(AgentReviewError, match='snapshot does not match'):
        AgentReviewService(
            other_snapshot, repository_root=review_authority['root']
        ).review(
            review_authority['context'], review_authority['graph'],
            _diff(_modified(PORTAL)), UntrackedPaths((), 0, 0),
        )

    other_root = tmp_path / 'other-root'
    other_root.mkdir()
    with pytest.raises(AgentReviewError, match='repository root'):
        AgentReviewService(
            review_authority['snapshot'], repository_root=other_root
        ).review(
            review_authority['context'], review_authority['graph'],
            _diff(_modified(PORTAL)), UntrackedPaths((), 0, 0),
        )

    wrong_graph = replace(
        review_authority['graph'], story_fingerprint='story:v1:wrong'
    )
    with pytest.raises(AgentReviewError, match='story fingerprints'):
        _review_with_graph(review_authority, wrong_graph)


def _review_with_graph(authority, graph):
    return AgentReviewService(
        authority['snapshot'], repository_root=authority['root']
    ).review(
        authority['context'], graph, _diff(_modified(PORTAL)),
        UntrackedPaths((), 0, 0),
    )


def test_required_resolved_base_and_bounds_are_explicit(review_authority) -> None:
    with pytest.raises(AgentReviewError, match='explicit resolved Git base'):
        _review(review_authority, GitDiff((_modified(PORTAL),)))

    files = tuple(
        DiffFile(f'unknown/File{index:03d}.java', f'unknown/File{index:03d}.java')
        for index in range(260)
    )
    review = _review(review_authority, _diff(*files))
    omitted = dict(review.omitted_counts)

    assert len(review.changed_files) == 256
    assert omitted['changed_files'] == 4
    assert all(
        item.scope_classification is ScopeClassification.UNREPRESENTED_CHANGE
        for item in review.changed_files
    )


def test_changed_line_metadata_is_bounded_and_reported(review_authority) -> None:
    lines = tuple(range(1, 1501))
    diff_file = DiffFile(
        CLIENT,
        CLIENT,
        (DiffHunk(1, 1500, 1, 1500, lines, lines),),
    )
    review = _review(review_authority, _diff(diff_file))
    changed = review.changed_files[0]

    assert len(changed.added_lines) + len(changed.removed_lines) == 2_048
    assert dict(review.omitted_counts)['line_numbers'] == 952


def _git(root, *arguments):
    return subprocess.run(
        ['git', *arguments],
        cwd=root,
        check=True,
        text=True,
        encoding='utf-8',
        capture_output=True,
    ).stdout.strip()


def test_git_diff_collects_tracked_staged_added_deleted_renamed_binary_and_untracked(
    tmp_path,
) -> None:
    root = tmp_path / 'git-repository'
    root.mkdir()
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.email', 'atlas@example.invalid')
    _git(root, 'config', 'user.name', 'Atlas Test')
    for name in ('modified.txt', 'staged.txt', 'deleted.txt', 'old.txt'):
        (root / name).write_text(f'{name} baseline\n', encoding='utf-8')
    (root / 'binary.bin').write_bytes(b'\x00baseline')
    (root / '.gitignore').write_text('ignored.tmp\n', encoding='utf-8')
    _git(root, 'add', '--', '.')
    _git(root, 'commit', '-q', '-m', 'baseline')
    base = _git(root, 'rev-parse', 'HEAD')

    (root / 'modified.txt').write_text('modified\n', encoding='utf-8')
    (root / 'staged.txt').write_text('staged\n', encoding='utf-8')
    _git(root, 'add', '--', 'staged.txt')
    (root / 'added.txt').write_text('added\n', encoding='utf-8')
    _git(root, 'add', '--', 'added.txt')
    (root / 'deleted.txt').unlink()
    _git(root, 'mv', '--', 'old.txt', 'renamed.txt')
    (root / 'binary.bin').write_bytes(b'\x00changed')
    (root / 'new.java').write_text('class New {}\n', encoding='utf-8')
    (root / 'ignored.tmp').write_text('ignored\n', encoding='utf-8')
    before = hashlib.sha256((root / 'new.java').read_bytes()).hexdigest()

    service = GitDiffService(root)
    diff = service.collect(base=base)
    untracked = service.collect_untracked_paths()
    paths = {item.path: item for item in diff.files}

    assert {'modified.txt', 'staged.txt', 'added.txt', 'deleted.txt', 'renamed.txt', 'binary.bin'} <= set(paths)
    assert paths['added.txt'].old_path is None
    assert paths['deleted.txt'].new_path is None
    assert paths['renamed.txt'].renamed
    assert paths['binary.bin'].binary
    assert untracked.paths == ('new.java',)
    assert 'ignored.tmp' not in untracked.paths
    assert before == hashlib.sha256((root / 'new.java').read_bytes()).hexdigest()


def test_pr175_explicit_context_shape_remains_reviewable(
    review_authority, tmp_path,
) -> None:
    context_path, graph_path, _, _ = _write_authority(
        review_authority, tmp_path / 'v1', version=1
    )
    context = load_agent_context_package(context_path)
    graph = load_agent_graph_projection(graph_path)
    review = AgentReviewService(
        review_authority['snapshot'], repository_root=review_authority['root']
    ).review(
        context, graph, _diff(_modified(PORTAL)), UntrackedPaths((), 0, 0)
    )

    assert context.version == graph.version == 1
    assert review.changed_files[0].scope_classification is ScopeClassification.WITHIN_EXPECTED_SURFACE
    assert review.review_fingerprint.startswith('agent-review:v1:')


def test_cli_requires_base_and_is_provider_free_read_only(
    review_authority, tmp_path, monkeypatch,
) -> None:
    root = review_authority['root']
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.email', 'atlas@example.invalid')
    _git(root, 'config', 'user.name', 'Atlas Test')
    _git(root, 'add', '--', '.')
    _git(root, 'commit', '-q', '-m', 'baseline')
    base = _git(root, 'rev-parse', 'HEAD')
    portal = root / PORTAL
    portal.write_text('class ChangedPortal {}\n', encoding='utf-8')
    before = hashlib.sha256(portal.read_bytes()).hexdigest()
    context_path, _, _, _ = _write_authority(
        review_authority, tmp_path / 'context'
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: (_ for _ in ()).throw(AssertionError('provider constructed')),
    )
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: review_authority['snapshot'],
    )
    monkeypatch.setattr(
        JavaLanguageAnalyzer,
        'analyze',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('rescan')),
    )
    monkeypatch.setattr(
        SemanticSnapshotStore,
        'save',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('snapshot publish')),
    )
    original_run = subprocess.run

    def git_only(command, *args, **kwargs):
        assert command[0] == 'git'
        assert command[1:3] != ['reset', '--hard']
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(git_diff_module.subprocess, 'run', git_only)
    runner = CliRunner()

    missing = runner.invoke(atlas_cli.app, [
        'agent', 'review', str(root), '--context', str(context_path),
    ])
    result = runner.invoke(atlas_cli.app, [
        'agent', 'review', str(root), '--context', str(context_path),
        '--base', base, '--json',
    ])

    assert missing.exit_code == 2
    assert '--base' in missing.output
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['format'] == 'atlas-agent-review'
    assert payload['base_provenance'] == 'UNKNOWN_BASE_PROVENANCE'
    assert payload['changed_files'][0]['scope_classification'] == 'WITHIN_EXPECTED_SURFACE'
    assert before == hashlib.sha256(portal.read_bytes()).hexdigest()
