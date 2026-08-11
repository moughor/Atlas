from __future__ import annotations

from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence import SourcePosition, SourceRange
from moughorai.workspace import Project


SOURCE = '''package demo;
class Ranges {
    @Deprecated
    public void work(
        int value
    ) {
        value++;
    }
}
interface Contract {
    void missing(String value);
}
'''


def _position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    return SourcePosition(prefix.count('\n') + 1, len(prefix.rsplit('\n', 1)[-1]) + 1)


def _artifact(tmp_path: Path):
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/Ranges.java'
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE, encoding='utf-8')
    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project),
        (source,),
        {},
    )
    return document.require_artifact('java_callable_index')


def test_exact_workspace_relative_declaration_and_body_ranges(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    entry = next(item for item in artifact.entries if item.identity.name == 'work')

    declaration_start = SOURCE.index('@Deprecated')
    body_start = SOURCE.index('{', SOURCE.index('public void work'))
    body_end = SOURCE.index('}', body_start) + 1

    assert entry.source.path == 'src/main/java/demo/Ranges.java'
    assert entry.source.declaration == SourceRange(
        _position(SOURCE, declaration_start),
        _position(SOURCE, body_end),
    )
    assert entry.source.body == SourceRange(
        _position(SOURCE, body_start),
        _position(SOURCE, body_end),
    )


def test_missing_executable_body_is_explicit(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    entry = next(
        item for item in artifact.entries if item.identity.name == 'missing'
    )
    semicolon_end = SOURCE.index(';', SOURCE.index('void missing')) + 1

    assert entry.source.declaration.end == _position(SOURCE, semicolon_end)
    assert entry.source.body is None
    assert any(
        item.code == 'body_unavailable'
        and item.subject_id == entry.canonical_subject_id
        for item in artifact.diagnostics
    )
