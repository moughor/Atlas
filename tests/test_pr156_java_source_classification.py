from __future__ import annotations

from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.global_symbols import GlobalSymbolKind
from moughorai.java_code_intelligence import (
    SourceClassification,
    classify_source,
)
from moughorai.java_workspace import SourceRoot, SourceRootKind
from moughorai.workspace import Project


def _root(path: Path, kind: SourceRootKind) -> SourceRoot:
    return SourceRoot(path, kind, 'java')


def test_maven_and_gradle_authoritative_source_roots(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    maven_main = project / 'src/main/java/demo/App.java'
    maven_test = project / 'src/test/java/demo/AppTest.java'
    gradle_main = project / 'src/main/java/demo/Worker.java'
    gradle_test = project / 'src/test/java/demo/WorkerSpec.java'

    roots = (
        _root(project / 'src/main/java', SourceRootKind.MAIN),
        _root(project / 'src/test/java', SourceRootKind.TEST),
    )

    assert classify_source(maven_main, project, roots).classification is (
        SourceClassification.PRODUCTION
    )
    assert classify_source(maven_test, project, roots).classification is (
        SourceClassification.TEST
    )
    assert classify_source(gradle_main, project, roots).classification is (
        SourceClassification.PRODUCTION
    )
    assert classify_source(gradle_test, project, roots).classification is (
        SourceClassification.TEST
    )


def test_generated_unknown_and_ambiguous_classification(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    generated = project / 'target/generated-sources/annotations/demo/Gen.java'
    unknown = project / 'custom/demo/Unknown.java'
    conflict = project / 'src/shared/java/demo/Shared.java'

    assert classify_source(generated, project).classification is (
        SourceClassification.GENERATED
    )
    unknown_result = classify_source(unknown, project)
    assert unknown_result.classification is SourceClassification.UNKNOWN
    assert unknown_result.evidence == 'unclassified-source-root'

    conflicting_roots = (
        _root(project / 'src/shared/java', SourceRootKind.MAIN),
        _root(project / 'src/shared/java', SourceRootKind.TEST),
    )
    ambiguous = classify_source(conflict, project, conflicting_roots)
    assert ambiguous.classification is SourceClassification.UNKNOWN
    assert ambiguous.evidence == 'ambiguous-workspace-source-root'
    assert ambiguous.limitations


def test_authoritative_root_overrides_name_and_path_heuristics(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    misleading = project / 'custom/main/java/demo/ApplicationTest.java'
    result = classify_source(
        misleading,
        project,
        (_root(project / 'custom/main/java', SourceRootKind.TEST),),
    )

    assert result.classification is SourceClassification.TEST
    assert result.evidence == 'workspace-source-root'


def test_test_source_main_method_remains_explicitly_test(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    source = project / 'src/test/java/demo/Harness.java'
    source.parent.mkdir(parents=True)
    source.write_text(
        'package demo; public class Harness {'
        ' public static void main(String[] args) {} }',
        encoding='utf-8',
    )

    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project),
        (source,),
        {},
    )
    index = document.require_artifact('java_callable_index')
    main_entry = next(
        item for item in index.entries if item.identity.name == 'main'
    )
    main_symbol = next(
        item
        for item in document.require_artifact('global_symbols')
        if item.kind is GlobalSymbolKind.METHOD and item.name == 'main'
    )

    assert main_entry.source_classification is SourceClassification.TEST
    assert dict(main_symbol.metadata)['source_classification'] == 'test'
