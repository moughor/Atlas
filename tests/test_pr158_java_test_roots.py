from __future__ import annotations

import json
from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.reachability_adapter import (
    build_java_reachability_adapter,
)
from moughorai.java_code_intelligence.test_evidence import (
    TestRootKind as RootKind,
    create_java_test_evidence,
)
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeNode
from moughorai.reachability import ReachabilityAnalysisService, RootCategory
from moughorai.workspace import Project


def _fixture(tmp_path: Path):
    project = tmp_path / 'project'
    main = project / 'src/main/java/demo/ApplicationTest.java'
    test = project / 'src/test/java/demo/Harness.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text('''package demo;
class Production {
  static void work() {}
  public static void main(String[] args) { work(); }
  void testByNameOnly() {}
}
class ApplicationTest { void nameIsNotEvidence() {} }
''', encoding='utf-8')
    test.write_text('''package demo;
@interface Test {}
class Harness {
  @Test void representedTest() { Production.work(); }
  public static void main(String[] args) { Production.work(); }
  void helper() { Production.work(); }
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
    evidence = create_java_test_evidence(index, metadata)
    adapter = build_java_reachability_adapter(index, code_graph, evidence)
    nodes = tuple(
        KnowledgeNode(
            item.canonical_subject_id,
            KnowledgeKind.METHOD,
            item.identity.name,
            qualified_name=item.identity.raw_signature,
            project_id=item.project_id,
            language='java',
        )
        for item in index.entries
    )
    report = ReachabilityAnalysisService().analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata,
        java_reachability=adapter,
        snapshot_lineage='test-pr158',
    )
    return index, code_graph, metadata, evidence, adapter, report


def _entry(index, owner: str, name: str):
    matches = tuple(
        item for item in index.entries
        if item.identity.owner_type.endswith(owner)
        and item.identity.name == name
    )
    assert len(matches) == 1, (owner, name, matches)
    return matches[0]


def test_authoritative_test_roots_and_name_negative(tmp_path: Path) -> None:
    index, _graph, _metadata, evidence, _adapter, _report = _fixture(
        tmp_path,
    )
    by_subject = {item.subject_id: item for item in evidence.records}
    represented = _entry(index, 'Harness', 'representedTest')
    helper = _entry(index, 'Harness', 'helper')
    misleading_method = _entry(index, 'Production', 'testByNameOnly')
    misleading_type = _entry(index, 'ApplicationTest', 'nameIsNotEvidence')

    assert by_subject[represented.canonical_subject_id].root_kind is (
        RootKind.TEST_METHOD_ROOT
    )
    assert by_subject[represented.canonical_subject_id].annotation_identities == (
        'Test',
    )
    assert by_subject[helper.canonical_subject_id].root_kind is (
        RootKind.UNKNOWN_TEST_ROOT
    )
    assert misleading_method.canonical_subject_id not in by_subject
    assert misleading_type.canonical_subject_id not in by_subject
    assert evidence.coverage.represented_test_callables == len(by_subject)
    assert evidence.coverage.represented_test_roots == 2


def test_src_test_main_is_a_test_application_not_production_root(
    tmp_path: Path,
) -> None:
    index, _graph, metadata, evidence, adapter, report = _fixture(tmp_path)
    test_main = _entry(index, 'Harness', 'main')
    production_main = _entry(index, 'Production', 'main')
    record = next(
        item for item in evidence.records
        if item.subject_id == test_main.canonical_subject_id
    )
    roots = {(item.subject_id, item.category) for item in report.roots}

    assert test_main.source_classification.value == 'test'
    assert record.root_kind is RootKind.TEST_APPLICATION_ROOT
    assert (test_main.canonical_subject_id, RootCategory.TEST) in roots
    assert (test_main.canonical_subject_id, RootCategory.APPLICATION) not in roots
    assert (production_main.canonical_subject_id, RootCategory.APPLICATION) in roots
    assert evidence.coverage.production_root_candidates == 1

    conflicting_metadata = tuple(
        {
            **item,
            'metadata': {
                **item['metadata'],
                'source_classification': 'production',
            },
        }
        if item['id'] == test_main.canonical_subject_id else item
        for item in metadata
    )
    canonical_nodes = tuple(
        KnowledgeNode(
            item.canonical_subject_id,
            KnowledgeKind.METHOD,
            item.identity.name,
            project_id=item.project_id,
            language='java',
        )
        for item in index.entries
    )
    conflict_report = ReachabilityAnalysisService().analyze(
        KnowledgeGraph(canonical_nodes, ()),
        symbol_metadata=conflicting_metadata,
        java_reachability=adapter,
        snapshot_lineage='authoritative-pr156-classification',
    )
    assert not any(
        item.subject_id == test_main.canonical_subject_id
        and item.category is RootCategory.APPLICATION
        for item in conflict_report.roots
    )


def test_test_root_ordering_and_serialization_are_deterministic(
    tmp_path: Path,
) -> None:
    index, _graph, metadata, first, _adapter, _report = _fixture(tmp_path)
    second = create_java_test_evidence(index, tuple(reversed(metadata)))
    encoded_first = json.dumps(
        first.to_dict(), ensure_ascii=False, separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    encoded_second = json.dumps(
        second.to_dict(), ensure_ascii=False, separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')

    assert first.records == tuple(sorted(first.records))
    assert first.input_fingerprint == second.input_fingerprint
    assert encoded_first == encoded_second


def test_production_root_behavior_is_unchanged_without_pr158(
    tmp_path: Path,
) -> None:
    index, _graph, metadata, _evidence, _adapter, _report = _fixture(tmp_path)
    production_main = _entry(index, 'Production', 'main')
    nodes = tuple(
        KnowledgeNode(
            item.canonical_subject_id,
            KnowledgeKind.METHOD,
            item.identity.name,
            project_id=item.project_id,
            language='java',
        )
        for item in index.entries
    )
    report = ReachabilityAnalysisService().analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata,
        snapshot_lineage='old-pr131-path',
    )

    assert any(
        item.subject_id == production_main.canonical_subject_id
        and item.category is RootCategory.APPLICATION
        for item in report.roots
    )
