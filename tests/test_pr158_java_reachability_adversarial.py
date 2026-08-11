from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.reachability_adapter import (
    build_java_reachability_adapter,
)
from moughorai.java_code_intelligence.test_evidence import (
    create_java_test_evidence,
    java_test_evidence_from_dict,
)
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeNode
from moughorai.reachability import CoverageStatus, ReachabilityAnalysisService
from moughorai.workspace import Project


def _document(tmp_path: Path, project_id: str = 'demo'):
    project = tmp_path / project_id
    main = project / 'src/main/java/demo/Service.java'
    test = project / 'src/test/java/demo/ServiceTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(
        'package demo; class Service { static void run() {} }',
        encoding='utf-8',
    )
    test.write_text(
        'package demo; @interface Test {} class ServiceTest {'
        ' @Test void represented() { external.Api.call(); }'
        ' void helper() {} }',
        encoding='utf-8',
    )
    return JavaLanguageAnalyzer().analyze(
        Project(project_id, project), (main, test), {},
    )


def _metadata(document):
    return tuple({
        'id': str(item.id),
        'metadata': dict(item.metadata),
    } for item in document.require_artifact('global_symbols'))


def _graph(index) -> KnowledgeGraph:
    return KnowledgeGraph(tuple(
        KnowledgeNode(
            item.canonical_subject_id,
            KnowledgeKind.METHOD,
            item.identity.name,
            project_id=item.project_id,
            language='java',
        )
        for item in index.entries
    ), ())


def test_malformed_or_cross_bound_test_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path / 'first')
    index = document.require_artifact('java_callable_index')
    evidence = create_java_test_evidence(index, _metadata(document))
    payload = evidence.to_dict()

    missing = dict(payload)
    missing['records'] = list(payload['records'][:-1])
    with pytest.raises(ValueError):
        java_test_evidence_from_dict(missing, index)

    duplicate = dict(payload)
    duplicate['records'] = [*payload['records'], payload['records'][0]]
    with pytest.raises(ValueError):
        java_test_evidence_from_dict(duplicate, index)

    other_document = _document(tmp_path / 'second', 'other')
    other_index = other_document.require_artifact('java_callable_index')
    with pytest.raises(ValueError):
        java_test_evidence_from_dict(payload, other_index)
    with pytest.raises(ValueError):
        build_java_reachability_adapter(
            index,
            other_document.require_artifact('java_code_graph'),
            evidence,
        )


def test_missing_code_graph_keeps_reachability_unknown(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    index = document.require_artifact('java_callable_index')
    metadata = _metadata(document)
    report = ReachabilityAnalysisService().analyze(
        _graph(index),
        symbol_metadata=metadata,
        snapshot_lineage='missing-pr157-input',
    )

    assert report.coverage.projects[0].calls is CoverageStatus.UNAVAILABLE
    assert not any(item.category.value == 'test' for item in report.roots)
    assert all(not item.test_reachable for item in report.findings)


def test_incomplete_call_coverage_and_negative_wording_are_conservative(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    index = document.require_artifact('java_callable_index')
    code_graph = document.require_artifact('java_code_graph')
    test_evidence = create_java_test_evidence(index, _metadata(document))
    adapter = build_java_reachability_adapter(
        index, code_graph, test_evidence,
    )
    report = ReachabilityAnalysisService().analyze(
        _graph(index),
        symbol_metadata=_metadata(document),
        java_reachability=adapter,
        snapshot_lineage='incomplete-pr158-input',
    )

    assert report.coverage.projects[0].calls is CoverageStatus.PARTIAL
    assert any(
        item.startswith('No represented TEST-root path')
        for item in report.limitations
    )
    assert 'No tests cover.' not in report.limitations
    assert all(
        'behavioral test coverage' not in item
        or 'not runtime execution' in item
        for item in report.limitations
    )
    assert dict(report.coverage.subject_counts)['external_call_sites'] == 1


def test_persisted_and_reachability_evidence_are_source_safe(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    index = document.require_artifact('java_callable_index')
    code_graph = document.require_artifact('java_code_graph')
    test_evidence = create_java_test_evidence(index, _metadata(document))
    adapter = build_java_reachability_adapter(
        index, code_graph, test_evidence,
    )
    report = ReachabilityAnalysisService().analyze(
        _graph(index),
        symbol_metadata=_metadata(document),
        java_reachability=adapter,
        snapshot_lineage='source-safe-pr158-input',
    )
    payload = json.dumps({
        'test_evidence': test_evidence.to_dict(),
        'reachability': report.to_dict(grouped=True),
    }, ensure_ascii=False, sort_keys=True)

    assert str(tmp_path.resolve()) not in payload
    assert 'external.Api.call();' not in payload
    assert 'source_body' not in payload
    assert 'snippet' not in payload
    assert 'arbitrary_expression' not in payload
    assert all(
        not reference.startswith(('C:\\', '/'))
        for record in report.evidence_index.records
        for reference in record.source_refs
    )
