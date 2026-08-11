from __future__ import annotations

from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.global_symbols import GlobalSymbolKind
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_ast import JavaParser
from moughorai.java_code_intelligence import CallableIndexBuilder
from moughorai.java_symbols import JavaSymbolIndexBuilder
from moughorai.workspace import Project


SOURCE = '''package demo;
import java.util.List;
class Target {}
class Sample<T> {
    Sample(String value) {}
    void run(String value) {}
    void run(int value) {}
    void arrayRun(Target[] values) {}
    void varargRun(Target... values) {}
    void imported(List<T> values) {}
    void qualified(java.util.List<T> values) {}
    <U> void generic(U value) {}
    <V> void genericSpelling(V value) {}
    void unresolved(Missing value) {}
    class Nested {
        void nested(Target value) {}
        void outerGeneric(T value) {}
    }
}
'''


def _index(tmp_path: Path):
    root = tmp_path / 'project'
    source = root / 'src/main/java/demo/Sample.java'
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding='utf-8')
    unit = JavaParser().parse_source(SOURCE)
    symbols = JavaSymbolIndexBuilder().build(
        (unit,),
        (source,),
        project_id='demo',
    )
    canonical = GlobalSymbolDatabaseBuilder().build(symbols).snapshot().symbols
    artifact = CallableIndexBuilder().build(
        symbols,
        (unit,),
        (source,),
        canonical,
        project_id='demo',
        project_root=root,
        lineage='project:demo',
    )
    return symbols, canonical, artifact


def _entry(artifact, name: str):
    return next(item for item in artifact.entries if item.identity.name == name)


def test_normalized_identity_covers_overloads_constructors_and_nested_types(
    tmp_path: Path,
) -> None:
    _symbols, canonical, artifact = _index(tmp_path)

    run_keys = {
        item.identity.normalized_key
        for item in artifact.entries
        if item.identity.name == 'run'
    }
    constructor = _entry(artifact, '<init>')
    nested = _entry(artifact, 'nested')

    assert len(run_keys) == 2
    assert constructor.identity.raw_signature == 'demo.Sample#<init>(String)'
    assert constructor.identity.normalized_key.startswith(
        'java-callable:v1:demo.Sample#<init>('
    )
    assert nested.identity.owner_type == 'demo.Sample.Nested'
    assert _entry(artifact, 'outerGeneric').identity.parameter_types == (
        'typevar:enclosing:0:0',
    )
    assert {item.canonical_subject_id for item in artifact.entries} <= {
        str(item.id) for item in canonical
    }


def test_imported_and_fully_qualified_generic_types_normalize_equally(
    tmp_path: Path,
) -> None:
    _symbols, _canonical, artifact = _index(tmp_path)

    imported = _entry(artifact, 'imported').identity.parameter_types
    qualified = _entry(artifact, 'qualified').identity.parameter_types

    assert imported == qualified
    assert imported == ('external:java.util.List<typevar:owner:0>',)
    assert _entry(artifact, 'generic').identity.parameter_types == (
        'typevar:callable:0',
    )
    assert _entry(artifact, 'genericSpelling').identity.parameter_types == (
        'typevar:callable:0',
    )
    assert _entry(artifact, 'generic').identity.raw_signature != (
        _entry(artifact, 'genericSpelling').identity.raw_signature
    )


def test_arrays_and_varargs_have_distinct_normalized_identity(
    tmp_path: Path,
) -> None:
    _symbols, _canonical, artifact = _index(tmp_path)

    array = _entry(artifact, 'arrayRun').identity.parameter_types
    varargs = _entry(artifact, 'varargRun').identity.parameter_types

    assert array == ('type:demo.Target[]',)
    assert varargs == ('type:demo.Target...',)
    assert array != varargs


def test_unresolved_parameter_identity_is_retained_with_limitation(
    tmp_path: Path,
) -> None:
    _symbols, _canonical, artifact = _index(tmp_path)
    entry = _entry(artifact, 'unresolved')

    assert entry.identity.parameter_types == ('unresolved:Missing',)
    assert entry.identity.limitations == (
        'Parameter type could not be resolved without fabrication.',
    )
    assert any(
        item.code == 'unresolved_parameter_type'
        and item.subject_id == entry.canonical_subject_id
        for item in artifact.diagnostics
    )


def test_existing_scoped_canonical_ids_remain_fixed(tmp_path: Path) -> None:
    root = tmp_path / 'project'
    source = root / 'src/main/java/demo/Sample.java'
    source.parent.mkdir(parents=True)
    source.write_text(
        'package demo; class Sample {'
        ' Sample(String value) {} void run(String value) {} }',
        encoding='utf-8',
    )

    document = JavaLanguageAnalyzer().analyze(
        Project('demo', root),
        (source,),
        {},
    )
    symbols = document.get_artifact('global_symbols')
    identities = {
        (item.kind, item.qualified_name): str(item.id) for item in symbols
    }

    assert identities[(
        GlobalSymbolKind.METHOD,
        'demo.Sample#run(String)',
    )] == 'method:9b41a14ca5ec0a06e86e493a'
    assert identities[(
        GlobalSymbolKind.CONSTRUCTOR,
        'demo.Sample#<init>(String)',
    )] == 'constructor:b758598e5c00cd072b52ed26'
