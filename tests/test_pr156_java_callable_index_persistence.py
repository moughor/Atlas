from __future__ import annotations

import json
from pathlib import Path

from moughorai.ai_context import (
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence import (
    JavaCallableIndex,
    callable_index_from_dict,
    callable_index_to_dict,
)
from moughorai.semantic import SemanticDocument
from moughorai.workspace import Project


def _document(tmp_path: Path) -> SemanticDocument:
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/App.java'
    source.parent.mkdir(parents=True)
    source.write_text(
        'package demo; class App {'
        ' void work(String value) { System.out.println(value); } }',
        encoding='utf-8',
    )
    return JavaLanguageAnalyzer().analyze(
        Project('demo', project),
        (source,),
        {},
    )


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def test_callable_index_round_trip_is_byte_identical(tmp_path: Path) -> None:
    artifact = _document(tmp_path).require_artifact('java_callable_index')
    encoded = callable_index_to_dict(artifact)
    restored = callable_index_from_dict(encoded)

    assert isinstance(restored, JavaCallableIndex)
    assert restored == artifact
    assert _bytes(callable_index_to_dict(restored)) == _bytes(encoded)


def test_semantic_document_persists_index_additively(tmp_path: Path) -> None:
    original = _document(tmp_path)
    encoded = encode_analysis_result(original)
    restored = decode_analysis_result(encoded)

    assert isinstance(restored, SemanticDocument)
    assert restored.require_artifact('java_callable_index') == (
        original.require_artifact('java_callable_index')
    )
    assert encoded['$type'] == 'atlas.semantic-document.v1'


def test_pre_pr156_semantic_document_remains_readable(tmp_path: Path) -> None:
    encoded = encode_analysis_result(_document(tmp_path))
    encoded.pop('java_callable_index')

    restored = decode_analysis_result(encoded)

    assert isinstance(restored, SemanticDocument)
    assert restored.get_artifact('java_callable_index') is None


def test_persistence_is_source_safe(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    artifact = _document(tmp_path).require_artifact('java_callable_index')
    serialized = _bytes(callable_index_to_dict(artifact)).decode('utf-8')

    assert str(project.resolve()) not in serialized
    assert 'System.out.println' not in serialized
    assert 'src/main/java/demo/App.java' in serialized
    assert 'demo.App#work(String)' in serialized
