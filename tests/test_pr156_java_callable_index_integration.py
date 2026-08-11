from __future__ import annotations

import json
from pathlib import Path

from moughorai import public_api
from moughorai.ai_context import SemanticContextCollector
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.global_symbols import GlobalSymbolKind
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import (
    ProjectRun,
    ProjectRunStatus,
    Workspace,
    WorkspaceRunReport,
    WorkspaceService,
)


SOURCE = '''package demo;
class Concrete { Concrete() {} void run() {} void spread(String... values) {} }
interface Contract { void execute(); }
enum Mode { VALUE; void select() {} }
record Item(int value) { void validate() {} }
'''


def _workspace(tmp_path: Path):
    project = tmp_path / 'app'
    source = project / 'src/main/java/demo/Types.java'
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding='utf-8')
    (tmp_path / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n',
        encoding='utf-8',
    )
    service = WorkspaceService(tmp_path)
    document = JavaLanguageAnalyzer().analyze(
        service.project('app'),
        (source,),
        {},
    )
    return service, document


def test_type_kind_survives_active_symbol_and_callable_pipeline(
    tmp_path: Path,
) -> None:
    _service, document = _workspace(tmp_path)
    symbols = document.require_artifact('global_symbols')
    type_kinds = {
        item.name: dict(item.metadata)['type_kind']
        for item in symbols
        if item.kind is GlobalSymbolKind.TYPE
    }
    artifact = document.require_artifact('java_callable_index')
    owner_kinds = {
        item.identity.owner_type: item.type_kind for item in artifact.entries
    }

    assert type_kinds == {
        'Concrete': 'class',
        'Contract': 'interface',
        'Item': 'record',
        'Mode': 'enum',
    }
    assert owner_kinds['demo.Concrete'] == 'class'
    assert owner_kinds['demo.Contract'] == 'interface'
    assert owner_kinds['demo.Mode'] == 'enum'
    assert owner_kinds['demo.Item'] == 'record'


def test_collector_persists_workspace_scoped_complete_index(
    tmp_path: Path,
) -> None:
    service, document = _workspace(tmp_path)
    report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    payload = SemanticContextCollector(service).collect(report).context.to_dict()
    artifact = payload['java_callable_index']
    callable_symbols = {
        item['id']
        for item in payload['symbols']
        if item['kind'] in {'method', 'constructor'}
    }
    indexed = {
        item['canonical_subject_id'] for item in artifact['entries']
    }

    assert artifact['format'] == 'moughorai.java-callable-index.v1'
    assert artifact['path_scope'] == 'workspace'
    assert artifact['lineage'].startswith('semantic-graph:')
    assert indexed == callable_symbols
    assert len(indexed) == len(artifact['entries'])
    assert artifact['coverage']['represented_callables'] == len(callable_symbols)
    assert artifact['coverage']['unindexed_callables'] == 0
    assert all(
        item['source']['path'].startswith('app/src/main/java/')
        for item in artifact['entries']
    )


def test_old_ass_and_public_api_v1_remain_compatible() -> None:
    fixtures = Path(__file__).parent / 'fixtures'
    ass = fixtures / 'semantic_snapshot_v1_minimal.ass'
    store = SemanticSnapshotStore(Workspace(fixtures, ()), fixtures)
    snapshot = store.load(ass)
    expected_api = json.loads(
        (fixtures / 'public_api_v1.json').read_text(encoding='utf-8')
    )

    assert snapshot is not None
    assert 'java_callable_index' not in snapshot.semantic_context
    assert SemanticSnapshotStore._serialize(snapshot) == ass.read_text(
        encoding='utf-8'
    )
    assert expected_api['public_api_version'] == public_api.PUBLIC_API_VERSION
    assert expected_api['signatures'] == public_api.public_api_manifest()
    assert public_api.public_api_compatibility_issues() == ()
