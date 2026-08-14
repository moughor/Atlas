from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
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
    StructuredExplanation,
    StructuredExplanationService,
)
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    ResolutionStatus,
    SubjectQuery,
)
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


HIGH_FANOUT_MAIN_SOURCE = '''package fanout;
class FanoutReference { static void target() {} }
class FanoutTarget {
  static void leafOne() {}
  static void leafTwo() {}
  static void leafThree() {}
  static void changed() {
    leafOne();
    leafTwo();
    leafThree();
    external.Library.call();
    Class.forName(null);
    FanoutReference::target;
  }
  static void upstreamOne() { changed(); }
  static void upstreamTwo() { changed(); }
  static void upstreamThree() { changed(); }
  static void topOne() { upstreamOne(); }
  static void topTwo() { upstreamTwo(); }
  static void topThree() { upstreamThree(); }
}
'''


HIGH_FANOUT_TEST_SOURCE = '''package fanout;
@interface Test {}
class FanoutTargetTest {
  @Test void directOne() { FanoutTarget.changed(); }
  @Test void directTwo() { FanoutTarget.changed(); }
  @Test void directThree() { FanoutTarget.changed(); }
  @Test void transitiveOne() { FanoutTarget.topOne(); }
  @Test void transitiveTwo() { FanoutTarget.topTwo(); }
  @Test void transitiveThree() { FanoutTarget.topThree(); }
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


@pytest.fixture(scope='module')
def pr162_high_fanout_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp('pr162-high-fanout-code-impact')
    project_root = root / 'app'
    main = project_root / 'src/main/java/fanout/FanoutTarget.java'
    test = project_root / 'src/test/java/fanout/FanoutTargetTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(HIGH_FANOUT_MAIN_SOURCE, encoding='utf-8')
    test.write_text(HIGH_FANOUT_TEST_SOURCE, encoding='utf-8')
    (root / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project('app', project_root),
        (main, test),
        {},
    )
    run_report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    payload = SemanticContextCollector(
        WorkspaceService(root)
    ).collect(run_report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr162-high-fanout-code-impact',
        analyzer_version='test-pr162/1',
    )
    return {
        'root': root,
        'snapshot': snapshot,
        'payload': payload,
        'index': callable_index_from_dict(payload['java_callable_index']),
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


def _nested_evidence_ids(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            result.update(_nested_evidence_ids(item))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            result.update(_nested_evidence_ids(item))
    elif isinstance(value, str) and value.startswith('evidence:'):
        result.add(value)
    return result


def _semantic_project_mismatch_snapshot(pr159_fixture):
    payload = copy.deepcopy(pr159_fixture['payload'])
    legacy_project = 'legacy-semantic-app'
    for node in payload['semantic_graph']['nodes']:
        if node.get('project_id') == 'app':
            node['project_id'] = legacy_project
        if node.get('kind') == 'project':
            if node.get('name') == 'app':
                node['name'] = legacy_project
            if node.get('qualified_name') == 'app':
                node['qualified_name'] = legacy_project
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr163-java-project-reconciliation',
        analyzer_version='test-pr163/1',
    )
    return snapshot, payload, legacy_project


def _stale_semantic_identity_snapshot(pr159_fixture):
    payload = copy.deepcopy(pr159_fixture['payload'])
    changed = _entry(pr159_fixture, 'Target', 'changed')
    semantic_node = next(
        item for item in payload['semantic_graph']['nodes']
        if item.get('id') == changed.canonical_subject_id
    )
    semantic_node['qualified_name'] = 'demo.StaleOwner#changed()'
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr164-stale-semantic-identity',
        analyzer_version='test-pr164/1',
    )
    return snapshot, payload


def _missing_semantic_subject_snapshot(pr159_fixture):
    payload = copy.deepcopy(pr159_fixture['payload'])
    changed = _entry(pr159_fixture, 'Target', 'changed')
    payload['semantic_graph']['nodes'] = [
        item for item in payload['semantic_graph']['nodes']
        if item.get('id') != changed.canonical_subject_id
    ]
    payload['semantic_graph']['edges'] = [
        item for item in payload['semantic_graph']['edges']
        if changed.canonical_subject_id not in {
            item.get('source'), item.get('target')
        }
    ]
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr164-missing-semantic-subject',
        analyzer_version='test-pr164/1',
    )
    return snapshot, payload


def _stale_semantic_source_snapshot(pr159_fixture):
    payload = copy.deepcopy(pr159_fixture['payload'])
    changed = _entry(pr159_fixture, 'Target', 'changed')
    semantic_symbol = next(
        item for item in payload['symbols']
        if item.get('id') == changed.canonical_subject_id
    )
    semantic_symbol['source'] = 'legacy/src/main/java/demo/StaleTarget.java'
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr164-stale-semantic-source',
        analyzer_version='test-pr164/1',
    )
    return snapshot, payload


def test_stale_semantic_identity_cannot_override_exact_java_authority(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, payload = _stale_semantic_identity_snapshot(pr159_fixture)
    snapshot_before = _bytes(snapshot.to_dict())

    explanation = StructuredExplanationService(snapshot).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )
    )

    assert explanation.availability.value == 'partial'
    assert explanation.subject is not None
    assert explanation.subject.subject_id == changed.canonical_subject_id
    assert explanation.subject.project == changed.project_id
    assert explanation.subject.qualified_name == changed.identity.raw_signature
    assert any(
        item.title == 'Represented Java callable identity'
        for item in explanation.facts
    )
    assert not any(
        item.title == 'Canonical subject identity'
        for item in explanation.facts
    )
    assert any(
        'authoritative qualified identity' in item
        and 'semantic enrichment was omitted' in item
        for item in explanation.limitations
    )
    assert _bytes(payload['java_callable_index']) == _bytes(
        pr159_fixture['payload']['java_callable_index']
    )
    assert _bytes(payload['java_code_graph']) == _bytes(
        pr159_fixture['payload']['java_code_graph']
    )
    assert snapshot_before == _bytes(snapshot.to_dict())


def test_stale_semantic_source_cannot_attach_semantic_enrichment(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, payload = _stale_semantic_source_snapshot(pr159_fixture)
    snapshot_before = _bytes(snapshot.to_dict())

    first = StructuredExplanationService(snapshot).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )
    )
    second = StructuredExplanationService(snapshot).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )
    )

    assert first.to_json() == second.to_json()
    assert first.availability.value == 'partial'
    assert first.subject is not None
    assert first.subject.qualified_name == changed.identity.raw_signature
    assert any(
        item.title == 'Represented Java callable identity'
        for item in first.facts
    )
    assert not any(
        item.title == 'Canonical subject identity'
        for item in first.facts
    )
    assert any(
        'authoritative source identity' in item
        and 'semantic enrichment was omitted' in item
        for item in first.limitations
    )
    assert _bytes(payload['java_callable_index']) == _bytes(
        pr159_fixture['payload']['java_callable_index']
    )
    assert snapshot_before == _bytes(snapshot.to_dict())


def test_constructor_explain_does_not_coerce_deferred_subject_kind(
    pr159_fixture,
) -> None:
    constructor = _entry(pr159_fixture, 'Built', '<init>')
    direct = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(constructor.canonical_subject_id, project='app')
    assert direct.report is not None
    direct_before = direct.to_json()

    explanation = StructuredExplanationService(
        pr159_fixture['snapshot']
    ).explain(ExplanationRequest(
        constructor.canonical_subject_id,
        project='app',
        language='java',
    ))

    assert explanation.availability.value == 'unsupported'
    assert explanation.subject is None
    assert explanation.facts == ()
    assert not explanation.evidence_index.records
    assert any(
        'constructor Explain and Ask subjects remain deferred' in item
        for item in explanation.limitations
    )
    relationship = StructuredExplanationService(
        pr159_fixture['snapshot']
    ).explain(ExplanationRequest(
        constructor.canonical_subject_id,
        relationship_source=constructor.canonical_subject_id,
        relationship_target=_entry(
            pr159_fixture, 'Target', 'changed'
        ).canonical_subject_id,
        relationship_kind='calls',
    ))
    assert relationship.availability.value == 'unsupported'
    assert relationship.subject is None
    ask_context = EngineeringChatContextBuilder().build(
        pr159_fixture['snapshot'],
        question='If I modify this constructor, what can be affected?',
        subject=constructor.canonical_subject_id,
        project='app',
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        token_budget=5_500,
    )
    assert ask_context.subject_ids == ()
    assert not any(
        item.section_id == 'code_impact' and item.evidence_ids
        for item in ask_context.sections
    )
    code_capability = next(
        item for item in ask_context.capabilities
        if item.name == 'code_impact'
    )
    assert code_capability.state.value in {'unavailable', 'unsupported'}
    direct_after = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(constructor.canonical_subject_id, project='app')
    assert direct_after.to_json() == direct_before


def test_missing_semantic_subject_retains_java_test_evidence_and_ask(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, payload = _missing_semantic_subject_snapshot(pr159_fixture)
    snapshot_before = _bytes(snapshot.to_dict())
    service = StructuredExplanationService(snapshot)

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
    assert first.availability.value == 'partial'
    assert first.subject is not None
    assert first.subject.project == changed.project_id
    assert first.subject.qualified_name == changed.identity.raw_signature
    assert not any(
        item.title == 'Canonical subject identity' for item in first.facts
    )
    assert any(
        item.title == 'Represented Java callable identity'
        for item in first.facts
    )
    assert any('TEST' in item.title for item in first.facts)
    assert any(
        'matching semantic graph metadata is unavailable' in item
        for item in first.limitations
    )

    context = EngineeringChatContextBuilder().build(
        snapshot,
        question='If I modify this method, what can be affected?',
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        token_budget=5_500,
    )
    assert context.subject_ids == (changed.canonical_subject_id,)
    assert any(
        item.section_id == 'code_impact' and item.evidence_ids
        for item in context.sections
    )
    assert _bytes(payload['java_callable_index']) == _bytes(
        pr159_fixture['payload']['java_callable_index']
    )
    assert _bytes(payload['java_code_graph']) == _bytes(
        pr159_fixture['payload']['java_code_graph']
    )
    assert snapshot_before == _bytes(snapshot.to_dict())


def test_exact_overloads_remain_canonical_and_order_independent(
    pr159_fixture,
) -> None:
    overloads = tuple(
        item for item in pr159_fixture['index'].entries
        if item.identity.owner_type.endswith('Over')
        and item.identity.name == 'pick'
    )
    assert len(overloads) == 2
    service = StructuredExplanationService(pr159_fixture['snapshot'])
    forward = {
        entry.canonical_subject_id: service.explain(ExplanationRequest(
            entry.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )).to_json()
        for entry in overloads
    }
    reverse = {
        entry.canonical_subject_id: service.explain(ExplanationRequest(
            entry.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )).to_json()
        for entry in reversed(overloads)
    }
    assert forward == reverse
    for entry in overloads:
        explanation = StructuredExplanation.from_dict(
            json.loads(forward[entry.canonical_subject_id])
        )
        assert explanation.subject is not None
        assert explanation.subject.subject_id == entry.canonical_subject_id
        assert explanation.subject.qualified_name == entry.identity.raw_signature


def test_exact_java_project_authority_reconciles_legacy_semantic_identity(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, _payload, legacy_project = _semantic_project_mismatch_snapshot(
        pr159_fixture
    )
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)

    legacy_gate = resolver.resolve(SubjectQuery(
        changed.canonical_subject_id,
        KnowledgeKind.METHOD,
        'app',
        'java',
    ))
    assert legacy_gate.status is ResolutionStatus.NOT_FOUND
    java_resolution = JavaCodeIntelligenceService.from_snapshot(snapshot).query(
        changed.canonical_subject_id,
        project='app',
    )
    assert java_resolution.resolution.status is CodeSubjectResolutionStatus.RESOLVED

    service = StructuredExplanationService(
        snapshot,
        include_code_intelligence=False,
    )
    without_project = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        language='java',
    ))
    matching_java_project = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
    ))
    for explanation in (without_project, matching_java_project):
        assert explanation.availability.value == 'partial'
        assert explanation.subject is not None
        assert explanation.subject.subject_id == changed.canonical_subject_id
        assert explanation.subject.project == 'app'
        assert explanation.subject.qualified_name == changed.identity.raw_signature
        assert any(
            'PR156 callable project' in item
            and 'legacy-semantic-app' in item
            for item in explanation.limitations
        )

    wrong_java_project = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project=legacy_project,
        language='java',
    ))
    assert wrong_java_project.availability.value == 'not_found'
    assert wrong_java_project.subject is None
    assert any(
        'authoritative Java project' in item
        for item in wrong_java_project.limitations
    )

    fuzzy = service.explain(ExplanationRequest(
        'changed',
        kind='method',
        project='app',
        language='java',
    ))
    assert fuzzy.availability.value == 'not_found'
    assert fuzzy.subject is None


def test_reconciled_explain_keeps_java_and_semantic_provenance_separate(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, payload, legacy_project = _semantic_project_mismatch_snapshot(
        pr159_fixture
    )
    snapshot_before = _bytes(snapshot.to_dict())
    original_snapshot_id = pr159_fixture['snapshot'].snapshot_id
    original_report = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(changed.canonical_subject_id).report
    assert original_report is not None
    reconciled_before = JavaCodeIntelligenceService.from_snapshot(snapshot).query(
        changed.canonical_subject_id,
        project='app',
    ).report
    assert reconciled_before is not None

    explanation = StructuredExplanationService(snapshot).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        )
    )
    assert explanation.availability.value == 'partial'
    assert explanation.subject is not None
    assert explanation.subject.project == 'app'
    java_facts = tuple(
        item for item in explanation.facts
        if 'Java' in item.title or 'TEST' in item.title
    )
    assert java_facts
    assert all(item.evidence_ids for item in java_facts)
    semantic_identity = next(
        item for item in explanation.facts
        if item.title == 'Canonical subject identity'
    )
    semantic_attributes = {
        item.key: item.value for item in semantic_identity.attributes
    }
    assert semantic_attributes['project'] == legacy_project
    assert any(
        'semantic subject metadata uses' in item
        for item in explanation.limitations
    )

    reconciled_after = JavaCodeIntelligenceService.from_snapshot(snapshot).query(
        changed.canonical_subject_id,
        project='app',
    ).report
    assert reconciled_after is not None
    assert reconciled_after.to_dict() == reconciled_before.to_dict()
    assert (
        reconciled_after.traceability.callable_index_fingerprint
        == original_report.traceability.callable_index_fingerprint
    )
    assert (
        reconciled_after.traceability.code_graph_fingerprint
        == original_report.traceability.code_graph_fingerprint
    )
    assert (
        reconciled_after.traceability.test_evidence_fingerprint
        == original_report.traceability.test_evidence_fingerprint
    )
    assert _bytes(payload['java_callable_index']) == _bytes(
        pr159_fixture['payload']['java_callable_index']
    )
    assert _bytes(payload['java_code_graph']) == _bytes(
        pr159_fixture['payload']['java_code_graph']
    )
    assert snapshot_before == _bytes(snapshot.to_dict())
    assert pr159_fixture['snapshot'].snapshot_id == original_snapshot_id


def test_reconciled_ask_retains_code_impact_and_grounded_fallback(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, _payload, legacy_project = _semantic_project_mismatch_snapshot(
        pr159_fixture
    )

    def build(project: str):
        return EngineeringChatContextBuilder().build(
            snapshot,
            question=(
                'If I modify this method, what can be affected? Show direct and '
                'transitive callers, what it calls, represented tests that reach '
                'it, confidence, and anything Atlas cannot prove. Never reverse '
                'call direction.'
            ),
            subject=changed.canonical_subject_id,
            kind='method',
            project=project,
            language='java',
            capabilities=('code_impact',),
            result_limit=8,
            token_budget=5_500,
        )

    first = build('app')
    second = build('app')
    assert first.to_json() == second.to_json()
    assert first.subject_ids == (changed.canonical_subject_id,)
    assert first.selection.estimated_tokens <= 5_500
    code_section = next(
        item for item in first.sections if item.section_id == 'code_impact'
    )
    assert code_section.evidence_ids
    assert code_section.content['report']['subject']['project'] == 'app'
    assert code_section.content['report']['direction_contract'] == {
        'canonical_direction': 'caller_to_callee',
        'canonical_relation': 'calls',
        'impact_traversal_direction': 'reverse_upstream',
    }

    fixture = {**pr159_fixture, 'snapshot': snapshot}
    failed, _ = _ask_with_context(
        fixture,
        first,
        (LlmProviderError('provider unavailable'),),
    )
    repeated, _ = _ask_with_context(
        fixture,
        first,
        (LlmProviderError('different provider failure'),),
    )
    assert failed.answer.encode('utf-8') == repeated.answer.encode('utf-8')
    assert failed.grounding_summary is not None
    assert failed.grounding_summary.provider_grounded is False
    assert failed.grounding_summary.delivered_answer_grounded is True
    assert failed.grounding_summary.request_complete is True
    assert failed.grounding_summary.fallback_used is True

    wrong_project = build(legacy_project)
    assert wrong_project.subject_ids == ()
    wrong_capability = next(
        item for item in wrong_project.capabilities
        if item.name == 'code_impact'
    )
    assert wrong_capability.state.value in {'not_found', 'unavailable'}
    assert not any(
        item.section_id == 'code_impact' and item.evidence_ids
        for item in wrong_project.sections
    )


def test_default_ask_limit_is_budget_safe_for_high_fanout_code_impact(
    pr162_high_fanout_fixture,
) -> None:
    pr159_fixture = pr162_high_fanout_fixture
    changed = _entry(pr159_fixture, 'FanoutTarget', 'changed')
    service = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    )
    full_before = service.query(changed.canonical_subject_id)
    assert full_before.report is not None
    full_report = full_before.report

    def build_context():
        return EngineeringChatContextBuilder().build(
            pr159_fixture['snapshot'],
            question=(
                'If I modify this method, what can be affected? Show direct and '
                'transitive callers, what it calls, represented tests that reach '
                'it, confidence, and anything Atlas cannot prove. Never reverse '
                'call direction.'
            ),
            subject=changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
            capabilities=('code_impact',),
            result_limit=8,
            token_budget=5_500,
        )

    first = build_context()
    second = build_context()
    assert first.to_json() == second.to_json()
    assert first.selection.estimated_tokens <= 5_500
    assert first.selection.estimated_tokens <= first.selection.token_budget

    section = next(
        item for item in first.sections if item.section_id == 'code_impact'
    )
    compact = section.content['report']
    sections = (
        (
            compact['direct_callers']['high_confidence'],
            full_report.direct_callers_high_confidence,
        ),
        (
            compact['direct_callees']['high_confidence'],
            full_report.direct_callees_high_confidence,
        ),
        (
            compact['upstream_change_impact']['direct'],
            full_report.upstream_direct,
        ),
        (
            compact['upstream_change_impact']['transitive'],
            full_report.upstream_transitive,
        ),
        (
            compact['represented_test_intelligence']['direct_test_callers'],
            full_report.direct_test_callers,
        ),
        (
            compact['represented_test_intelligence']['high_confidence_paths'],
            full_report.high_confidence_test_paths,
        ),
    )
    for selected, complete in sections:
        assert complete.total_count > 2
        assert selected['total_count'] == complete.total_count
        assert selected['included_count'] == 2
        assert selected['omitted_count'] == complete.total_count - 2
        assert len(selected['items']) == 2

    assert compact['direction_contract'] == {
        'canonical_direction': 'caller_to_callee',
        'canonical_relation': 'calls',
        'impact_traversal_direction': 'reverse_upstream',
    }
    assert all(
        item['relation'] == 'calls'
        and item['canonical_source'] != item['canonical_target']
        for side in ('direct_callers', 'direct_callees')
        for group in compact[side].values()
        if isinstance(group, Mapping)
        for item in group.get('items', ())
    )
    assert all(
        item['traversal_direction'] == 'reverse_upstream'
        and item['canonical_direction'] == 'caller_to_callee'
        for name in ('direct', 'transitive')
        for item in compact['upstream_change_impact'][name]['items']
    )
    assert all(
        item['traversal_direction'] == 'forward_test_reachability'
        and item['canonical_direction'] == 'caller_to_callee'
        for item in compact['represented_test_intelligence'][
            'high_confidence_paths'
        ]['items']
    )
    assert compact['represented_test_intelligence'][
        'runtime_test_coverage_proven'
    ] is False

    categories = {item['category'] for item in compact['limitations']}
    assert {'external_sites', 'unsupported_sites', 'method_references'} <= categories
    assert compact['general_limitations']
    selected_evidence = set(section.evidence_ids)
    assert selected_evidence
    assert _nested_evidence_ids(compact) <= selected_evidence
    assert selected_evidence == {
        item.evidence_id for item in first.evidence_index.records
    }

    def failed_ask(message: str):
        return AskEngine(
            LlmClient(
                ScriptedLlmProvider((LlmProviderError(message),)),
                RetryPolicy(maximum_attempts=1),
            ),
            context_builder=_StaticContextBuilder(first),
        ).ask(
            pr159_fixture['snapshot'],
            AskRequest(
                'If I modify this method, what can be affected?',
                subject=changed.canonical_subject_id,
                kind='method',
                project='app',
                language='java',
                capabilities=('code_impact',),
                result_limit=8,
                maximum_input_tokens=20_000,
            ),
        )

    failed = failed_ask('provider unavailable')
    repeated = failed_ask('different provider failure')
    assert failed.context.context_digest == repeated.context.context_digest
    assert failed.answer.encode('utf-8') == repeated.answer.encode('utf-8')
    assert 'CALLER -> CALLEE' in failed.answer
    assert 'impact traversal is reverse upstream' in failed.answer
    assert 'Represented TEST reachability:' in failed.answer
    assert 'external_sites:' in failed.answer
    assert 'unsupported_sites:' in failed.answer
    assert failed.grounding_summary is not None
    assert failed.grounding_summary.provider_grounded is False
    assert failed.grounding_summary.delivered_answer_grounded is True
    assert failed.grounding_summary.request_complete is True
    assert failed.grounding_summary.fallback_used is True

    full_after = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(changed.canonical_subject_id)
    assert full_before.to_json() == full_after.to_json()


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
