from __future__ import annotations

from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    InvocationKind,
)
from moughorai.java_code_intelligence.reachability_adapter import (
    build_java_reachability_adapter,
)
from moughorai.java_code_intelligence.test_evidence import (
    create_java_test_evidence,
)
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeNode
from moughorai.reachability import (
    ReachabilityAnalysisService,
    ReachabilityConfiguration,
)
from moughorai.workspace import Project


def _fixture(tmp_path: Path, *, max_path_depth: int = 64):
    project = tmp_path / 'project'
    main = project / 'src/main/java/demo/Production.java'
    test = project / 'src/test/java/demo/ProductionTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text('''package demo;
class Built { Built() {} }
class Service {
  static void start() { middle(); }
  static void middle() { new Built(); }
}
interface Contract { void run(); }
class ContractImpl implements Contract { public void run() {} }
class Over {
  static void pick(String value) {}
  static void pick(Integer value) {}
}
class ReferenceTarget { static void target() {} }
''', encoding='utf-8')
    test.write_text('''package demo;
@interface Test {}
class ProductionTest {
  @Test void direct() { Service.start(); }
  @Test void possible(Contract value) { value.run(); }
  @Test void ambiguous() { Over.pick(null); }
  @Test void referenceOnly() { ReferenceTarget::target; }
  @Test void incomplete() {
    external.Library.call();
    Class.forName("demo.Service");
  }
}
''', encoding='utf-8')
    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project), (main, test), {},
    )
    index = document.require_artifact('java_callable_index')
    code_graph = document.require_artifact('java_code_graph')
    symbols = document.require_artifact('global_symbols')
    metadata = tuple({
        'id': str(item.id),
        'metadata': dict(item.metadata),
    } for item in symbols)
    test_evidence = create_java_test_evidence(index, metadata)
    adapter = build_java_reachability_adapter(
        index, code_graph, test_evidence,
    )
    graph = KnowledgeGraph(tuple(
        KnowledgeNode(
            item.canonical_subject_id,
            KnowledgeKind.METHOD,
            item.identity.name,
            qualified_name=item.identity.raw_signature,
            project_id=item.project_id,
            language='java',
        )
        for item in index.entries
    ), ())
    report = ReachabilityAnalysisService().analyze(
        graph,
        symbol_metadata=metadata,
        java_reachability=adapter,
        configuration=ReachabilityConfiguration(
            max_path_depth=max_path_depth,
        ),
        snapshot_lineage='test-pr158-call-reachability',
    )
    return index, code_graph, adapter, report


def _entry(index, owner: str, name: str):
    matches = tuple(
        item for item in index.entries
        if item.identity.owner_type.endswith(owner)
        and item.identity.name == name
    )
    assert len(matches) == 1, (owner, name, matches)
    return matches[0]


def _path(report, subject_id: str):
    matches = tuple(
        item for item in report.paths
        if item.scope == 'test' and item.target_subject_id == subject_id
    )
    assert len(matches) == 1, (subject_id, matches)
    return matches[0]


def test_resolved_and_constructor_edges_traverse_forward(
    tmp_path: Path,
) -> None:
    index, code_graph, adapter, report = _fixture(tmp_path)
    start = _entry(index, 'Service', 'start')
    middle = _entry(index, 'Service', 'middle')
    constructor = _entry(index, 'Built', '<init>')

    assert _path(report, start.canonical_subject_id).relationship_sequence == (
        'calls',
    )
    assert _path(report, middle.canonical_subject_id).relationship_sequence == (
        'calls', 'calls',
    )
    assert _path(report, constructor.canonical_subject_id).relationship_sequence == (
        'calls', 'calls', 'constructor',
    )
    assert adapter.coverage.direct_test_to_production_calls >= 1
    assert report.coverage.subject_counts
    assert len(report.paths) <= len(report.findings) * 2

    direct_site = next(
        item for item in code_graph.call_sites
        if item.request.member_name == 'start'
    )
    relation_record = next(
        record for record in report.evidence_index.records
        if direct_site.evidence_id in record.source_refs
    )
    assert relation_record.producer == 'moughorai.java-code-graph.v1'
    assert direct_site.evidence_id in relation_record.source_refs


def test_possible_dispatch_and_ambiguous_targets_preserve_uncertainty(
    tmp_path: Path,
) -> None:
    index, code_graph, _adapter, report = _fixture(tmp_path)
    dispatch = next(
        item for item in code_graph.call_sites
        if item.request.member_name == 'run'
    )
    ambiguous = next(
        item for item in code_graph.call_sites
        if item.request.member_name == 'pick'
    )

    assert dispatch.state is CallResolutionState.POLYMORPHIC
    assert ambiguous.state is CallResolutionState.AMBIGUOUS
    for subject_id in {
        dispatch.declared_target_id,
        *dispatch.candidate_target_ids,
    }:
        path = _path(report, subject_id)
        assert path.relationship_sequence[-1] == 'possible_dispatch'
        assert any('not a resolved runtime target' in item for item in path.limitations)
    for subject_id in ambiguous.candidate_target_ids:
        path = _path(report, subject_id)
        assert path.relationship_sequence[-1] == 'possible_call'
        assert any('not a resolved target' in item for item in path.limitations)

    counts = dict(report.coverage.subject_counts)
    assert counts['possible_call_edges'] >= 4
    assert counts['unresolved_call_sites'] >= 0


def test_method_references_and_unrepresented_states_do_not_traverse(
    tmp_path: Path,
) -> None:
    index, code_graph, adapter, report = _fixture(tmp_path)
    target = _entry(index, 'ReferenceTarget', 'target')
    reference = next(
        item for item in code_graph.call_sites
        if item.request.invocation_kind is InvocationKind.METHOD_REFERENCE
    )
    incomplete = tuple(
        item for item in code_graph.call_sites
        if item.request.member_name in {'call', 'forName'}
    )

    assert reference.state is CallResolutionState.RESOLVED
    assert not any(
        item.target_subject_id == target.canonical_subject_id
        and item.scope == 'test'
        for item in report.paths
    )
    assert {item.state for item in incomplete} == {
        CallResolutionState.EXTERNAL,
        CallResolutionState.UNSUPPORTED,
    }
    assert all(
        relation.evidence_id != reference.evidence_id
        for relation in adapter.eligible_relations()
    )
    counts = dict(report.coverage.subject_counts)
    assert counts['external_call_sites'] == 1
    assert counts['unsupported_call_sites'] == 1
    assert counts['method_reference_sites'] == 1


def test_path_depth_bound_is_deterministic(tmp_path: Path) -> None:
    index, _code_graph, adapter, first = _fixture(
        tmp_path / 'first', max_path_depth=2,
    )
    constructor = _entry(index, 'Built', '<init>')
    path = _path(first, constructor.canonical_subject_id)

    assert path.truncated
    assert len(path.relationship_sequence) == 2
    assert path.limitations
    relations = tuple(adapter.eligible_relations())
    assert relations == tuple(sorted(relations))
