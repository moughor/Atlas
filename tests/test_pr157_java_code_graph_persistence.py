from __future__ import annotations

import json
from pathlib import Path

from moughorai import public_api
from moughorai.ai_context import (
    SemanticContextCollector,
    WorkspaceSemanticContext,
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.impact_analysis import (
    ImpactCapabilityState,
    ImpactPredictionRequest,
    ImpactPredictionService,
)
from moughorai.java_code_intelligence.code_graph import (
    JavaCodeGraph,
    code_graph_from_dict,
    code_graph_to_dict,
)
from moughorai.java_code_intelligence.call_sites import call_evidence_to_dict
from moughorai.java_code_intelligence.persistence import (
    callable_index_from_dict,
)
from moughorai.semantic import SemanticDocument
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.subject_resolution import SubjectQuery
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    Workspace,
    WorkspaceRunReport,
    WorkspaceService,
)


SOURCE = '''package demo;
class Helper { static void target() {} }
class App { void caller() { Helper.target(); external.Library.call(); } }
'''


def _document(tmp_path: Path) -> tuple[WorkspaceService, SemanticDocument]:
    project = tmp_path / 'app'
    source = project / 'src/main/java/demo/App.java'
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding='utf-8')
    (tmp_path / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n',
        encoding='utf-8',
    )
    service = WorkspaceService(tmp_path)
    document = JavaLanguageAnalyzer().analyze(
        service.project('app'), (source,), {},
    )
    return service, document


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def test_code_graph_round_trip_and_semantic_document_are_additive(
    tmp_path: Path,
) -> None:
    _service, document = _document(tmp_path)
    artifact = document.require_artifact('java_code_graph')
    callable_index = document.require_artifact('java_callable_index')
    encoded_artifact = code_graph_to_dict(artifact)
    restored_artifact = code_graph_from_dict(
        encoded_artifact, callable_index,
    )

    assert isinstance(restored_artifact, JavaCodeGraph)
    assert restored_artifact == artifact
    assert _bytes(code_graph_to_dict(restored_artifact)) == _bytes(encoded_artifact)

    encoded_document = encode_analysis_result(document)
    restored_document = decode_analysis_result(encoded_document)
    assert encoded_document['$type'] == 'atlas.semantic-document.v1'
    assert restored_document.require_artifact('java_code_graph') == artifact

    encoded_document.pop('java_code_graph')
    old_document = decode_analysis_result(encoded_document)
    assert isinstance(old_document, SemanticDocument)
    assert old_document.get_artifact('java_code_graph') is None

    orphaned_document = encode_analysis_result(document)
    orphaned_document.pop('java_callable_index')
    restored_orphan = decode_analysis_result(orphaned_document)
    assert isinstance(restored_orphan, SemanticDocument)
    assert restored_orphan.get_artifact('java_code_graph') is None


def test_workspace_artifact_is_separate_from_pr131_and_pr136(
    tmp_path: Path,
) -> None:
    service, document = _document(tmp_path)
    report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    collected = SemanticContextCollector(service).collect(report)
    payload = collected.context.to_dict()
    artifact = payload['java_code_graph']
    callable_index = callable_index_from_dict(payload['java_callable_index'])
    logical_graph = code_graph_from_dict(artifact, callable_index)
    legacy_encoded = encode_analysis_result(document)
    legacy_encoded.pop('java_code_graph')
    legacy_document = decode_analysis_result(legacy_encoded)
    legacy_report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, legacy_document),),
        ('app',),
        ('app',),
    )
    legacy_payload = SemanticContextCollector(service).collect(
        legacy_report
    ).context.to_dict()

    assert artifact['format'] == 'moughorai.java-code-graph.v1'
    assert artifact['path_scope'] == 'workspace'
    assert artifact['coverage']['total_call_sites'] == 2
    assert artifact['encoding'] == 'canonical-row-json-v1'
    assert all(isinstance(item, str) for item in artifact['call_sites'])
    assert all(
        item.request.source_path.startswith('app/src/main/java/')
        for item in logical_graph.call_sites
    )
    assert not any(
        item['kind'] == 'calls'
        for item in payload['semantic_graph']['edges']
    )
    assert payload['semantic_graph'] == legacy_payload['semantic_graph']
    assert payload['reachability'] == legacy_payload['reachability']
    assert (
        payload['java_callable_index']['digest']
        == legacy_payload['java_callable_index']['digest']
    )
    assert 'moughorai.java-code-graph.v1' not in json.dumps(
        payload['reachability'], sort_keys=True,
    )

    target_id = next(
        item.target_subject_id
        for item in logical_graph.call_sites
        if item.request.member_name == 'target'
    )
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr157-compatibility-fixture',
        analyzer_version='test-analyzer/1',
    )
    response = ImpactPredictionService.from_snapshot(snapshot).predict(
        ImpactPredictionRequest(SubjectQuery(target_id))
    )
    calls = next(item for item in response.capabilities if item.name == 'calls')
    assert calls.state is ImpactCapabilityState.UNAVAILABLE
    assert calls.coverage is None


def test_old_ass_and_public_api_v1_remain_compatible() -> None:
    fixtures = Path(__file__).parent / 'fixtures'
    ass = fixtures / 'semantic_snapshot_v1_minimal.ass'
    store = SemanticSnapshotStore(Workspace(fixtures, ()), fixtures)
    snapshot = store.load(ass)
    expected_api = json.loads(
        (fixtures / 'public_api_v1.json').read_text(encoding='utf-8')
    )

    assert snapshot is not None
    assert 'java_code_graph' not in snapshot.semantic_context
    assert SemanticSnapshotStore._serialize(snapshot) == ass.read_text(
        encoding='utf-8'
    )
    assert expected_api['public_api_version'] == public_api.PUBLIC_API_VERSION
    assert expected_api['signatures'] == public_api.public_api_manifest()
    assert public_api.public_api_compatibility_issues() == ()


def test_code_graph_persistence_is_source_safe(tmp_path: Path) -> None:
    service, document = _document(tmp_path)
    serialized = _bytes(code_graph_to_dict(
        document.require_artifact('java_code_graph')
    )).decode('utf-8')

    assert str(service.workspace.root.resolve()) not in serialized
    assert 'Helper.target();' not in serialized
    assert 'external.Library.call();' not in serialized
    assert 'src/main/java/demo/App.java' in serialized


def test_compact_tables_are_sorted_and_scale_fixture_is_materially_smaller(
    tmp_path: Path,
    capsys,
) -> None:
    calls = '\n'.join(
        'Helper.target(); external.Library.call();' for _ in range(256)
    )
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/Scale.java'
    source.parent.mkdir(parents=True)
    source.write_text(
        'package demo; class Helper { static void target() {} } '
        f'class Scale {{ void caller() {{ {calls} }} }}',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project('project', project), (source,), {},
    )
    graph = document.require_artifact('java_code_graph')
    compact = code_graph_to_dict(graph)
    uncertain = tuple(
        item for item in graph.call_sites if item.target_subject_id is None
    )
    verbose = {
        'call_sites': [call_evidence_to_dict(item) for item in graph.call_sites],
        'edges': [item.to_dict() for item in graph.edges],
        'diagnostics': [
            {
                'code': f'call_site_{item.state.value}',
                'message': (
                    f'Represented call site has {item.state.value} target '
                    'resolution.'
                ),
                'project_id': item.request.project_id,
                'caller_subject_id': item.request.caller_subject_id,
                'evidence_id': item.evidence_id,
                'source_path': item.request.source_path,
                'source_range': item.request.source_range.to_dict(),
                'mandatory': True,
            }
            for item in uncertain
        ],
        'coverage': graph.coverage.to_dict(),
    }
    verbose_bytes = len(json.dumps(
        verbose, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode('utf-8'))
    compact_bytes = len(json.dumps(
        compact, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode('utf-8'))

    assert compact['subjects'] == sorted(set(compact['subjects']))
    assert compact['files'] == sorted(set(compact['files']))
    assert compact['lexical'] == sorted(set(compact['lexical']))
    assert compact['reasons'] == sorted(set(compact['reasons']))
    assert compact_bytes < verbose_bytes * 0.35
    print(
        f'PR157 scale fixture: verbose={verbose_bytes} compact={compact_bytes} '
        f'reduction={(1 - compact_bytes / verbose_bytes) * 100:.2f}%'
    )
