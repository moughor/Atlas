from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import public_api
from moughorai import atlas_cli
from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    EngineeringChatContextBuilder,
)
from moughorai.ai_context import SemanticContextCollector, WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    CodePathConfidence,
    CodeRelationshipRole,
    CodeSubjectResolutionStatus,
    JavaCodeIntelligenceService,
    render_code_intelligence,
)
from moughorai.impact_analysis import (
    ImpactPredictionRequest,
    ImpactPredictionService,
)
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    InvocationKind,
)
from moughorai.java_code_intelligence.code_graph import (
    CodeGraphEdgeKind,
    code_graph_from_dict,
)
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind
from moughorai.llm import LlmClient, LlmProviderError, RetryPolicy, ScriptedLlmProvider
from moughorai.semantic_snapshot import (
    AtlasSemanticSnapshot,
    SemanticSnapshotStore,
    SnapshotResolver,
)
from moughorai.structured_explanation import (
    ExplanationRequest,
    StructuredExplanationService,
)
from moughorai.subject_resolution import SubjectQuery
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
    Workspace,
)


MAIN_SOURCE = '''package demo;
class Built { Built() {} }
interface Contract { void run(); }
class ContractImpl implements Contract { public void run() {} }
class ReferenceTarget { static void target() {} }
class Target {
  static void leaf() {}
  static void changed() {
    leaf();
    external.Library.call();
    Class.forName("demo.Target");
    ReferenceTarget::target;
  }
  static void upstream() { changed(); }
  static void top() { upstream(); }
  static Built construct() { return new Built(); }
}
class Over {
  static void pick(String value) {}
  static void pick(Integer value) {}
}
'''


TEST_SOURCE = '''package demo;
@interface Test {}
class TargetTest {
  @Test void direct() { Target.changed(); }
  @Test void multiStep() { Target.top(); }
  @Test void possible(Contract value) { value.run(); }
  @Test void ambiguous() { Over.pick(null); }
  @Test void referenceOnly() { Target::changed; }
}
'''


@pytest.fixture(scope='module')
def pr159_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp('pr159-java-code-impact')
    project_root = root / 'app'
    main = project_root / 'src/main/java/demo/Target.java'
    test = project_root / 'src/test/java/demo/TargetTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(MAIN_SOURCE, encoding='utf-8')
    test.write_text(TEST_SOURCE, encoding='utf-8')
    (root / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project('app', project_root),
        (main, test),
        {},
    )
    service = WorkspaceService(root)
    run_report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    payload = SemanticContextCollector(service).collect(run_report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr159-java-code-impact',
        analyzer_version='test-pr159/1',
    )
    producer_index = document.require_artifact('java_callable_index')
    producer_graph = document.require_artifact('java_code_graph')
    index = callable_index_from_dict(payload['java_callable_index'])
    graph = code_graph_from_dict(payload['java_code_graph'], index)
    return {
        'root': root,
        'snapshot': snapshot,
        'payload': payload,
        'index': index,
        'graph': graph,
        'producer_index': producer_index,
        'producer_graph': producer_graph,
        'index_bytes': _bytes(producer_index.to_dict()),
        'graph_bytes': _bytes(producer_graph.to_dict()),
    }


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def _entry(fixture, owner: str, name: str, parameter_count: int | None = None):
    matches = tuple(
        item
        for item in fixture['index'].entries
        if item.identity.owner_type.endswith(owner)
        and item.identity.name == name
        and (
            parameter_count is None
            or len(item.identity.parameter_types) == parameter_count
        )
    )
    assert len(matches) == 1, (owner, name, matches)
    return matches[0]


def _query(fixture, owner: str, name: str, **kwargs):
    entry = _entry(fixture, owner, name)
    result = JavaCodeIntelligenceService.from_snapshot(
        fixture['snapshot']
    ).query(entry.canonical_subject_id, **kwargs)
    assert result.report is not None
    return entry, result, result.report


def _all_relationships(section):
    return tuple(section.items)


def test_exact_method_direction_direct_impact_and_tests(pr159_fixture) -> None:
    changed, first, report = _query(pr159_fixture, 'Target', 'changed')
    second = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(changed.canonical_subject_id)

    assert first.resolution.status is CodeSubjectResolutionStatus.RESOLVED
    assert report.subject.kind.value == 'method'
    assert first.to_json() == second.to_json()
    assert report.to_json() == second.report.to_json()

    callers = _all_relationships(report.direct_callers_high_confidence)
    assert callers
    assert all(item.canonical_target == changed.canonical_subject_id for item in callers)
    assert all(item.relation == 'calls' for item in callers)
    assert all(
        item.subject_relative_role is CodeRelationshipRole.CALLER_OF_SUBJECT
        for item in callers
    )
    assert all(
        item.edge_kind is CodeGraphEdgeKind.RESOLVED_DIRECT_CALL
        for item in callers
    )
    assert all(
        item.confidence
        is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
        for item in callers
    )

    leaf = _entry(pr159_fixture, 'Target', 'leaf')
    callees = _all_relationships(report.direct_callees_high_confidence)
    assert any(
        item.canonical_source == changed.canonical_subject_id
        and item.canonical_target == leaf.canonical_subject_id
        and item.subject_relative_role is CodeRelationshipRole.CALLEE_OF_SUBJECT
        for item in callees
    )
    assert report.direct_caller_method_references.total_count == 1
    assert all(
        not item.execution_eligible
        for item in report.direct_caller_method_references.items
    )
    assert report.direct_callee_method_references.total_count == 1

    assert report.upstream_direct.total_count >= 2
    assert report.upstream_transitive.total_count >= 2
    assert all(item.depth == 1 for item in report.upstream_direct.items)
    assert all(item.depth > 1 for item in report.upstream_transitive.items)
    assert all(
        step.canonical_source != step.canonical_target
        and step.subject_relative_role
        is CodeRelationshipRole.UPSTREAM_CONSUMER_OF_SUBJECT
        for path in (
            *report.upstream_direct.items,
            *report.upstream_transitive.items,
        )
        for step in path.steps
    )
    assert report.traversal.traversal_direction.value == 'reverse_upstream'
    assert sum(dict(report.traversal.depth_histogram).values()) == (
        report.traversal.visited_node_count - 1
    )

    assert report.direct_test_callers.total_count >= 1
    assert all(
        item.subject_relative_role is CodeRelationshipRole.TEST_CALLER_OF_SUBJECT
        for item in report.direct_test_callers.items
    )
    assert report.high_confidence_test_paths.total_count >= 2
    assert report.possible_test_paths.total_count == 0
    assert report.negative_test_statement is None
    assert all(
        item.traversal_direction.value == 'forward_test_reachability'
        and item.root_evidence_id is not None
        for item in report.high_confidence_test_paths.items
    )

    categories = {item.category: item for item in report.limitations}
    assert categories['external_sites'].total_count >= 1
    assert categories['unsupported_sites'].total_count >= 1
    assert categories['method_references'].total_count >= 1
    assert all(
        item.producer_evidence_id.startswith('evidence:')
        and not Path(item.location.path).is_absolute()
        for summary in report.limitations
        for item in summary.representatives
    )
    rendered = render_code_intelligence(first)
    assert 'canonical-direction: CALLER -> CALLEE' in rendered
    assert 'impact-traversal-direction: reverse upstream' in rendered
    assert 'represented TEST intelligence:' in rendered
    assert 'runtime-test-coverage-proven: false' in rendered
    assert MAIN_SOURCE not in rendered


def test_possible_dispatch_and_ambiguous_paths_stay_conservative(
    pr159_fixture,
) -> None:
    graph = pr159_fixture['graph']
    dispatch = next(
        item for item in graph.call_sites
        if item.request.member_name == 'run'
        and item.state is CallResolutionState.POLYMORPHIC
    )
    targets = tuple(sorted(set((
        *((dispatch.declared_target_id,) if dispatch.declared_target_id else ()),
        *dispatch.candidate_target_ids,
    ))))
    assert targets
    for target in targets:
        result = JavaCodeIntelligenceService.from_snapshot(
            pr159_fixture['snapshot']
        ).query(target)
        assert result.report is not None
        conservative = result.report.direct_callers_conservative
        assert any(
            item.producer_evidence_id == dispatch.evidence_id
            and item.edge_kind is CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET
            for item in conservative.items
        )
        assert result.report.possible_test_paths.total_count >= 1
        assert all(
            path.confidence
            is CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
            for path in result.report.possible_test_paths.items
        )

    ambiguous = next(
        item for item in graph.call_sites
        if item.request.member_name == 'pick'
        and item.state is CallResolutionState.AMBIGUOUS
    )
    assert ambiguous.candidate_target_ids
    candidate_result = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(ambiguous.candidate_target_ids[0])
    assert candidate_result.report is not None
    assert any(
        item.edge_kind is CodeGraphEdgeKind.POSSIBLE_CALL_TARGET
        and item.producer_evidence_id == ambiguous.evidence_id
        for item in candidate_result.report.direct_callers_conservative.items
    )


def test_constructor_resolution_bounds_and_no_fabricated_targets(
    pr159_fixture,
) -> None:
    constructor, constructor_result, constructor_report = _query(
        pr159_fixture, 'Built', '<init>', kind='constructor',
    )
    construct = _entry(pr159_fixture, 'Target', 'construct')
    assert constructor_result.resolution.subject.kind.value == 'constructor'
    assert any(
        item.canonical_source == construct.canonical_subject_id
        and item.canonical_target == constructor.canonical_subject_id
        and item.edge_kind is CodeGraphEdgeKind.CONSTRUCTOR_CALL
        for item in constructor_report.direct_callers_high_confidence.items
    )

    changed, bounded_result, bounded = _query(
        pr159_fixture,
        'Target',
        'changed',
        configuration=CodeIntelligenceConfiguration(
            max_depth=2,
            max_nodes=3,
            max_direct_relationships=1,
            max_paths_per_section=1,
            max_limitation_representatives=1,
        ),
    )
    assert bounded.direct_callers_high_confidence.omitted_count >= 1
    assert bounded.traversal.truncated
    assert bounded_result.to_json() == JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(
        changed.canonical_subject_id,
        configuration=CodeIntelligenceConfiguration(
            max_depth=2,
            max_nodes=3,
            max_direct_relationships=1,
            max_paths_per_section=1,
            max_limitation_representatives=1,
        ),
    ).to_json()

    target_ids = {
        edge.target_subject_id for edge in pr159_fixture['graph'].edges
    }
    incomplete = tuple(
        item for item in pr159_fixture['graph'].call_sites
        if item.request.caller_subject_id == changed.canonical_subject_id
        and item.state in {
            CallResolutionState.UNRESOLVED,
            CallResolutionState.EXTERNAL,
            CallResolutionState.UNSUPPORTED,
        }
    )
    assert incomplete
    assert all(
        item.target_subject_id is None and not item.candidate_target_ids
        for item in incomplete
    )
    assert all(item.evidence_id not in target_ids for item in incomplete)


def test_old_snapshot_degrades_and_producer_identities_remain_unchanged(
    pr159_fixture,
) -> None:
    old = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            'schema_version': 1,
            'semantic_graph': KnowledgeGraph().to_dict(),
            'symbols': [],
        }),
        workspace_fingerprint='old-pr159-snapshot',
        analyzer_version='test/1',
    )
    unavailable = JavaCodeIntelligenceService.from_snapshot(old).query(
        'method:missing'
    )
    assert unavailable.resolution.status is CodeSubjectResolutionStatus.UNAVAILABLE
    assert unavailable.report is None
    assert (
        _bytes(pr159_fixture['producer_index'].to_dict())
        == pr159_fixture['index_bytes']
    )
    assert (
        _bytes(pr159_fixture['producer_graph'].to_dict())
        == pr159_fixture['graph_bytes']
    )
    assert (
        pr159_fixture['payload']['java_test_evidence']['input_fingerprint']
        == pr159_fixture['snapshot'].semantic_context[
            'java_test_evidence'
        ]['input_fingerprint']
    )
    assert not any(
        item['kind'] == 'calls'
        for item in pr159_fixture['payload']['semantic_graph']['edges']
    )


def test_safe_negative_test_claim_and_method_reference_exclusion(
    pr159_fixture,
) -> None:
    target, result, report = _query(
        pr159_fixture, 'ReferenceTarget', 'target'
    )
    reference = next(
        item for item in pr159_fixture['graph'].call_sites
        if item.request.caller_subject_id
        == _entry(pr159_fixture, 'Target', 'changed').canonical_subject_id
        and item.request.invocation_kind is InvocationKind.METHOD_REFERENCE
    )
    assert report.direct_caller_method_references.total_count == 1
    assert report.direct_caller_method_references.items[0].producer_evidence_id == (
        reference.evidence_id
    )
    assert report.upstream_direct.total_count == 0
    assert report.upstream_transitive.total_count == 0
    assert report.high_confidence_test_paths.total_count == 0
    assert report.possible_test_paths.total_count == 0
    assert report.negative_test_statement == (
        'No represented TEST-root path reaches this subject in the current artifact.'
    )
    rendered = render_code_intelligence(result).casefold()
    assert 'this code is untested' not in rendered
    assert 'no tests cover this' not in rendered
    assert target.canonical_subject_id in rendered


def test_structured_explanation_exposes_bounded_traceable_code_facts(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    service = StructuredExplanationService(pr159_fixture['snapshot'])
    first = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
    ))
    second = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
    ))
    assert first.to_json() == second.to_json()
    code_facts = tuple(
        item for item in first.facts
        if 'Java' in item.title or 'TEST' in item.title
    )
    assert code_facts
    assert any('caller' in item.title.casefold() for item in code_facts)
    assert any('callee' in item.title.casefold() for item in code_facts)
    assert any('upstream' in item.title.casefold() for item in code_facts)
    assert any('TEST' in item.title for item in code_facts)
    for fact in code_facts:
        assert fact.evidence_ids
        for evidence_id in fact.evidence_ids:
            record = first.evidence_index.get(evidence_id)
            assert record is not None
            assert record.source_refs
    capability = next(
        item for item in first.capabilities
        if item.name == 'java_code_intelligence'
    )
    assert capability.availability.value in {'available', 'partial'}
    assert all(not Path(ref).is_absolute() for ref in first.citations)


class _StaticContextBuilder:
    def __init__(self, context):
        self.context = context

    def build(self, *_args, **_kwargs):
        return self.context


def _code_context(pr159_fixture, *, capabilities=('code_impact',)):
    changed = _entry(pr159_fixture, 'Target', 'changed')
    return EngineeringChatContextBuilder().build(
        pr159_fixture['snapshot'],
        question=(
            'If I modify this method, what can be affected and which represented '
            'tests reach it?'
        ),
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        capabilities=capabilities,
        result_limit=2,
        token_budget=5_500,
    )


def _ask_with_context(pr159_fixture, context, outcomes):
    changed = _entry(pr159_fixture, 'Target', 'changed')
    provider = ScriptedLlmProvider(outcomes)
    result = AskEngine(
        LlmClient(
            provider,
            RetryPolicy(maximum_attempts=1),
        ),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        pr159_fixture['snapshot'],
        AskRequest(
            'If I modify this method, what can be affected?',
            subject=changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
            capabilities=('code_impact',),
            result_limit=2,
            maximum_input_tokens=20_000,
        ),
    )
    return result, provider


def test_ask_context_is_bounded_and_provider_failure_preserves_code_evidence(
    pr159_fixture,
) -> None:
    context = _code_context(pr159_fixture)
    section = next(item for item in context.sections if item.section_id == 'code_impact')
    capability = next(
        item for item in context.capabilities if item.name == 'code_impact'
    )
    assert section.evidence_ids
    assert section.total_item_count == section.included_item_count == 1
    assert capability.state.value in {'available', 'partial'}
    serialized = context.to_json()
    assert MAIN_SOURCE not in serialized
    assert str(pr159_fixture['root'].resolve()) not in serialized

    ungrounded, _provider = _ask_with_context(
        pr159_fixture,
        context,
        ('Unsupported provider prose without evidence.',),
    )
    repeated, _ = _ask_with_context(
        pr159_fixture,
        context,
        ('Different unsupported provider prose.',),
    )
    assert ungrounded.answer == repeated.answer
    assert 'Unsupported provider prose' not in ungrounded.answer
    assert 'Atlas deterministic Java code-impact answer' in ungrounded.answer
    assert 'CALLER -> CALLEE' in ungrounded.answer
    assert 'represented TEST path' in ungrounded.answer
    assert 'external_sites:' in ungrounded.answer
    assert 'unsupported_sites:' in ungrounded.answer
    assert ungrounded.citations.valid
    assert ungrounded.citations.unknown_citation_ids == ()
    assert ungrounded.grounded is True
    assert ungrounded.grounding_summary is not None
    assert ungrounded.grounding_summary.provider_grounded is False
    assert ungrounded.grounding_summary.delivered_answer_grounded is True
    assert ungrounded.grounding_summary.request_complete is True
    assert ungrounded.grounding_summary.fallback_used is True
    status = next(
        item for item in ungrounded.grounding_summary.capability_statuses
        if item.capability == 'code_impact'
    )
    assert status.requested and status.computed and status.delivered and status.grounded

    failed, _ = _ask_with_context(
        pr159_fixture,
        context,
        (LlmProviderError('provider unavailable'),),
    )
    assert failed.answer == ungrounded.answer
    assert failed.grounded is True
    assert failed.grounding_summary is not None
    assert failed.grounding_summary.fallback_used is True

    evidence_id = section.evidence_ids[0]
    provider_answer = f'Grounded code-impact answer. {evidence_id}'
    grounded, _ = _ask_with_context(
        pr159_fixture,
        context,
        (provider_answer,),
    )
    assert grounded.answer == provider_answer
    assert grounded.grounded is True
    assert grounded.grounding_summary is not None
    assert grounded.grounding_summary.provider_grounded is True
    assert grounded.grounding_summary.fallback_used is False


def test_mixed_grounding_and_pr136_behavior_remain_compatible(
    pr159_fixture,
) -> None:
    context = _code_context(
        pr159_fixture,
        capabilities=('code_impact', 'refactoring'),
    )
    changed = _entry(pr159_fixture, 'Target', 'changed')
    provider = ScriptedLlmProvider(('Ungrounded mixed provider prose.',))
    mixed = AskEngine(
        LlmClient(provider),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        pr159_fixture['snapshot'],
        AskRequest(
            'Assess this method impact and suggest refactoring.',
            subject=changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
            capabilities=('code_impact', 'refactoring'),
            maximum_input_tokens=20_000,
        ),
    )
    assert mixed.grounding_summary is not None
    assert mixed.grounding_summary.delivered_answer_grounded is True
    assert mixed.grounding_summary.request_complete is False
    assert mixed.grounding_summary.fallback_used is True
    assert 'code_impact' in mixed.grounding_summary.delivered_capabilities
    assert 'refactoring_advisor' in (
        mixed.grounding_summary.omitted_requested_capabilities
    )

    impact = ImpactPredictionService.from_snapshot(pr159_fixture['snapshot'])
    request = ImpactPredictionRequest(
        SubjectQuery(changed.canonical_subject_id, KnowledgeKind.METHOD),
        max_depth=2,
        limit=8,
    )
    before = impact.predict(request).to_json()
    code_result = impact.predict_code_impact(changed.canonical_subject_id)
    after = impact.predict(request).to_json()
    assert code_result.report is not None
    assert before == after


def test_public_api_v1_manifest_is_unchanged() -> None:
    fixture = Path(__file__).parent / 'fixtures/public_api_v1.json'
    expected = json.loads(fixture.read_text(encoding='utf-8'))
    assert expected['public_api_version'] == public_api.PUBLIC_API_VERSION
    assert expected['signatures'] == public_api.public_api_manifest()
    assert public_api.public_api_compatibility_issues() == ()


def test_code_impact_cli_uses_existing_snapshot_without_source_output(
    pr159_fixture,
    monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda _root, _path: pr159_fixture['snapshot'],
    )
    result = CliRunner().invoke(
        atlas_cli.app,
        (
            'code-impact',
            changed.canonical_subject_id,
            str(pr159_fixture['root']),
            '--project',
            'app',
            '--depth',
            '2',
            '--limit',
            '1',
            '--json',
        ),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['resolution']['status'] == 'resolved'
    assert payload['report']['direction_contract'] == {
        'canonical_direction': 'caller_to_callee',
        'canonical_relation': 'calls',
        'impact_traversal_direction': 'reverse_upstream',
    }
    assert MAIN_SOURCE not in result.stdout
    assert str(pr159_fixture['root'].resolve()) not in result.stdout


def test_pr160_active_resolution_preserves_pr159_code_impact_stdout(
    pr159_fixture,
    tmp_path,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    root = pr159_fixture['root']
    external_store = SemanticSnapshotStore(
        Workspace(root, ()),
        directory=tmp_path / 'saved' / 'ass',
    )
    external_store.save(pr159_fixture['snapshot'])
    saved = external_store.latest_path

    explicit = CliRunner().invoke(
        atlas_cli.app,
        (
            'code-impact',
            changed.canonical_subject_id,
            str(root),
            '--snapshot',
            str(saved),
            '--project',
            'app',
            '--depth',
            '2',
            '--limit',
            '2',
            '--json',
        ),
    )
    SnapshotResolver(root).activate(saved)
    active = CliRunner().invoke(
        atlas_cli.app,
        (
            'code-impact',
            changed.canonical_subject_id,
            str(root),
            '--project',
            'app',
            '--depth',
            '2',
            '--limit',
            '2',
            '--json',
        ),
    )

    assert explicit.exit_code == active.exit_code == 0
    assert explicit.stdout == active.stdout
    assert json.loads(active.stdout)['report']['direction_contract'] == {
        'canonical_direction': 'caller_to_callee',
        'canonical_relation': 'calls',
        'impact_traversal_direction': 'reverse_upstream',
    }
    assert 'snapshot-resolution: explicit' in explicit.stderr
    assert 'snapshot-resolution: configured-active' in active.stderr
