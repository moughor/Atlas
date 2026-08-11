from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_ast import JavaParser
from moughorai.java_code_intelligence import (
    CallableIndexBuilder,
    CallableIndexDiagnostic,
    PathScope,
    callable_index_from_dict,
    callable_index_to_dict,
    create_callable_index,
)
from moughorai.java_symbols import CallableSymbol, JavaSymbolIndexBuilder
from moughorai.java_symbols.index import JavaSymbolIndex
from moughorai.workspace import Project


def _valid_artifact(tmp_path: Path):
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/App.java'
    source.parent.mkdir(parents=True)
    source.write_text(
        'package demo; class App {'
        ' void run(int value) {} void unresolved(Missing value) {} }',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project),
        (source,),
        {},
    )
    return document.require_artifact('java_callable_index')


@pytest.mark.parametrize(
    'mutation',
    ('unknown', 'digest', 'absolute', 'ordering'),
)
def test_malformed_artifact_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    value = deepcopy(_valid_artifact(tmp_path).to_dict())
    if mutation == 'unknown':
        value['unexpected'] = True
    elif mutation == 'digest':
        value['digest'] = '0' * 64
    elif mutation == 'absolute':
        value['entries'][0]['source']['path'] = 'C:/private/App.java'
    else:
        value['entries'].reverse()

    with pytest.raises((TypeError, ValueError)):
        callable_index_from_dict(value)


def test_diagnostics_are_bounded_ordered_and_deterministic() -> None:
    diagnostics = tuple(
        CallableIndexDiagnostic(
            'unresolved_parameter_type',
            'Parameter type could not be deterministically resolved.',
            'demo',
            subject_id=f'method:{index:08d}',
        )
        for index in range(4_120)
    )
    first = create_callable_index(
        lineage='project:demo',
        path_scope=PathScope.PROJECT,
        entries=(),
        diagnostics=diagnostics,
        selected_source_files=0,
        parsed_source_files=0,
        represented_callables=0,
        unindexed_callables=0,
        represented_methods=0,
        represented_constructors=0,
    )
    second = create_callable_index(
        lineage='project:demo',
        path_scope=PathScope.PROJECT,
        entries=(),
        diagnostics=reversed(diagnostics),
        selected_source_files=0,
        parsed_source_files=0,
        represented_callables=0,
        unindexed_callables=0,
        represented_methods=0,
        represented_constructors=0,
    )

    assert first == second
    assert len(first.diagnostics) == 4_096
    assert first.coverage.omitted_diagnostic_count == 24
    assert tuple(item.subject_id for item in first.diagnostics) == tuple(
        sorted(item.subject_id for item in first.diagnostics)
    )


def test_unindexed_accounting_survives_generic_bound_and_persistence() -> None:
    noisy = tuple(
        CallableIndexDiagnostic(
            'unresolved_parameter_type',
            'Parameter type could not be deterministically resolved.',
            'demo',
            subject_id=f'method:indexed-{index:08d}',
        )
        for index in range(4_120)
    )
    mandatory = tuple(
        diagnostic
        for index in range(2)
        for diagnostic in (
            CallableIndexDiagnostic(
                'source_range_unavailable',
                'Callable declaration range is unavailable.',
                'demo',
                subject_id=f'method:unindexed-{index}',
                source_path=f'src/main/java/demo/Missing{index}.java',
            ),
            CallableIndexDiagnostic(
                'represented_callable_unindexed',
                'Represented Java callable has no callable-index entry.',
                'demo',
                subject_id=f'method:unindexed-{index}',
                source_path=f'src/main/java/demo/Missing{index}.java',
            ),
        )
    )

    def build(diagnostics):
        return create_callable_index(
            lineage='workspace:test',
            path_scope=PathScope.WORKSPACE,
            entries=(),
            diagnostics=diagnostics,
            selected_source_files=2,
            parsed_source_files=2,
            represented_callables=2,
            unindexed_callables=2,
            represented_methods=2,
            represented_constructors=0,
        )

    first = build((*noisy, *mandatory))
    reordered = build(reversed((*noisy, *mandatory)))
    restored = callable_index_from_dict(callable_index_to_dict(first))

    assert first == reordered == restored
    assert len(first.diagnostics) == 4_096 + len(mandatory)
    assert sum(
        item.code == 'unresolved_parameter_type'
        for item in first.diagnostics
    ) == 4_096
    assert first.coverage.omitted_diagnostic_count == 24
    assert tuple(
        item for item in first.diagnostics
        if item.code in {
            'represented_callable_unindexed',
            'source_range_unavailable',
        }
    ) == tuple(sorted(mandatory, key=lambda item: (
        item.code,
        item.project_id,
        item.source_path or '',
        item.line or 0,
        item.column or 0,
        item.subject_id or '',
        item.message,
    )))
    serialized = repr(callable_index_to_dict(first))
    assert 'C:\\' not in serialized
    assert 'source_text' not in serialized

    changed = build((
        *noisy,
        *mandatory[:-1],
        replace(
            mandatory[-1],
            message='Represented callable remains deterministically unindexed.',
        ),
    ))
    assert changed.digest != first.digest


def test_workspace_unindexed_accounting_fails_closed() -> None:
    with pytest.raises(
        ValueError,
        match='workspace unindexed-callable accounting is inconsistent',
    ):
        create_callable_index(
            lineage='workspace:test',
            path_scope=PathScope.WORKSPACE,
            entries=(),
            diagnostics=(),
            selected_source_files=1,
            parsed_source_files=1,
            represented_callables=1,
            unindexed_callables=1,
            represented_methods=1,
            represented_constructors=0,
        )


def test_unindexable_represented_callable_is_never_silently_dropped(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/App.java'
    source.parent.mkdir(parents=True)
    text = 'package demo; class App { void run(int value) {} }'
    source.write_text(text, encoding='utf-8')
    unit = JavaParser().parse_source(text)
    original = JavaSymbolIndexBuilder().build(
        (unit,),
        (source,),
        project_id='demo',
    )
    malformed = JavaSymbolIndex(
        (
            replace(item, declaration_span=None)
            if isinstance(item, CallableSymbol)
            else item
            for item in original.symbols
        ),
        project_id='demo',
    )
    canonical = GlobalSymbolDatabaseBuilder().build(
        malformed
    ).snapshot().symbols
    artifact = CallableIndexBuilder().build(
        malformed,
        (unit,),
        (source,),
        canonical,
        project_id='demo',
        project_root=project,
        lineage='project:demo',
    )

    assert artifact.coverage.represented_callables == 1
    assert artifact.coverage.indexed_callables == 0
    assert artifact.coverage.unindexed_callables == 1
    assert artifact.coverage.methods == 1
    assert artifact.coverage.constructors == 0
    assert any(
        item.code == 'source_range_unavailable'
        and item.subject_id is not None
        for item in artifact.diagnostics
    )


def test_parse_failure_is_source_safe_and_call_graph_is_not_produced(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/Broken.java'
    source.parent.mkdir(parents=True)
    source.write_text('package demo; class', encoding='utf-8')
    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project),
        (source,),
        {},
    )
    artifact = document.require_artifact('java_callable_index')
    finding = next(
        item for item in artifact.diagnostics if item.code == 'parse_failure'
    )

    assert finding.source_path == 'src/main/java/demo/Broken.java'
    assert str(project.resolve()) not in repr(finding)
    assert document.get_artifact('call_graph') is None
    assert document.get_artifact('call_sites') is None
