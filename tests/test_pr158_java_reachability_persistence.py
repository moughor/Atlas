from __future__ import annotations

import json
from pathlib import Path

from moughorai import public_api
from moughorai.ai_context import (
    SemanticContextCollector,
    WorkspaceSemanticContext,
)
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.code_graph import code_graph_to_dict
from moughorai.java_code_intelligence.reachability_adapter import (
    build_java_reachability_adapter,
)
from moughorai.java_code_intelligence.test_evidence import (
    JAVA_TEST_EVIDENCE_FORMAT,
    create_java_test_evidence,
    java_test_evidence_from_dict,
)
from moughorai.reachability import DeadCodeReport, ReachabilityAnalysisService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    Workspace,
    WorkspaceRunReport,
    WorkspaceService,
)


def _document(tmp_path: Path):
    project = tmp_path / 'app'
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
        ' @Test void verifies() { Service.run(); } }',
        encoding='utf-8',
    )
    return JavaLanguageAnalyzer().analyze(
        Project('app', project), (main, test), {},
    )


def _metadata(document) -> tuple[dict[str, object], ...]:
    return tuple({
        'id': str(item.id),
        'metadata': dict(item.metadata),
    } for item in document.require_artifact('global_symbols'))


def _bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    ).encode('utf-8')


def test_test_evidence_round_trip_is_strict_and_byte_deterministic(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    index = document.require_artifact('java_callable_index')
    evidence = create_java_test_evidence(index, _metadata(document))
    payload = evidence.to_dict()
    restored = java_test_evidence_from_dict(payload, index)

    assert restored == evidence
    assert payload['format'] == JAVA_TEST_EVIDENCE_FORMAT
    assert _bytes(restored.to_dict()) == _bytes(payload)
    assert restored.callable_index_fingerprint == index.input_fingerprint
    assert restored.path_scope == index.path_scope


def test_pr156_and_pr157_artifacts_are_unchanged_by_pr158(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    index = document.require_artifact('java_callable_index')
    code_graph = document.require_artifact('java_code_graph')
    index_before = _bytes(index.to_dict())
    graph_before = _bytes(code_graph_to_dict(code_graph))

    evidence = create_java_test_evidence(index, _metadata(document))
    adapter = build_java_reachability_adapter(index, code_graph, evidence)

    assert _bytes(index.to_dict()) == index_before
    assert _bytes(code_graph_to_dict(code_graph)) == graph_before
    assert adapter.callable_index.input_fingerprint == index.input_fingerprint
    assert adapter.code_graph.input_fingerprint == code_graph.input_fingerprint


def test_workspace_context_persists_test_evidence_additively(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'app'
    (tmp_path / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n', encoding='utf-8',
    )
    document = _document(tmp_path)
    service = WorkspaceService(tmp_path)
    report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    payload = SemanticContextCollector(service).collect(report).context.to_dict()

    assert payload['java_test_evidence']['format'] == JAVA_TEST_EVIDENCE_FORMAT
    assert payload['reachability']['producer_version'] == 'atlas-pr131/1'
    assert payload['reachability']['schema_version'] == 1
    assert not any(
        item['kind'] == 'calls'
        for item in payload['semantic_graph']['edges']
    )
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr158-additive-fixture',
        analyzer_version='test-analyzer/1',
    )
    assert snapshot.semantic_context['java_test_evidence'] == (
        payload['java_test_evidence']
    )


def test_old_pr131_ass_and_public_api_remain_readable() -> None:
    report = ReachabilityAnalysisService().analyze(
        __import__(
            'moughorai.knowledge_graph', fromlist=['KnowledgeGraph']
        ).KnowledgeGraph(),
        snapshot_lineage='old-pr131-fixture',
    )
    restored = DeadCodeReport.from_dict(report.to_dict(grouped=True))
    fixtures = Path(__file__).parent / 'fixtures'
    ass = fixtures / 'semantic_snapshot_v1_minimal.ass'
    snapshot = SemanticSnapshotStore(
        Workspace(fixtures, ()), fixtures,
    ).load(ass)
    expected_api = json.loads(
        (fixtures / 'public_api_v1.json').read_text(encoding='utf-8')
    )

    assert restored.to_dict(grouped=True) == report.to_dict(grouped=True)
    assert snapshot is not None
    assert 'java_test_evidence' not in snapshot.semantic_context
    assert expected_api['public_api_version'] == public_api.PUBLIC_API_VERSION
    assert expected_api['signatures'] == public_api.public_api_manifest()
    assert public_api.public_api_compatibility_issues() == ()
