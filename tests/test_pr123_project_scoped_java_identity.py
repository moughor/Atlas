from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.ai_context import SemanticProjectAnalyzer
from moughorai.atlas_cli import app
from moughorai.global_symbols import (
    DuplicateSymbolError,
    GlobalSymbol,
    GlobalSymbolDatabase,
    GlobalSymbolDatabaseBuilder,
    GlobalSymbolKind,
)
from moughorai.java_ast import JavaParser
from moughorai.java_symbols import (
    DuplicateTypeError,
    JavaSymbolIndex,
    JavaSymbolIndexBuilder,
    JavaSymbolService,
)
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Project, WorkspaceDiscovery, WorkspaceService
from moughorai.workspace.files import project_files


runner = CliRunner()


def _java_project(root: Path, name: str, source: str) -> None:
    project = root / name
    project.mkdir()
    (project / "DefaultPackageTestCase.java").write_text(source, encoding="utf-8")


def test_scoped_global_symbols_with_same_qualified_name_coexist() -> None:
    first = GlobalSymbol.create(
        GlobalSymbolKind.TYPE, "Shared", "demo.Shared", project_id="one",
    )
    second = GlobalSymbol.create(
        GlobalSymbolKind.TYPE, "Shared", "demo.Shared", project_id="two",
    )
    database = GlobalSymbolDatabase((first, second))
    assert first.id != second.id
    assert database.by_qualified_name("demo.Shared", "one") == first
    assert database.by_qualified_name("demo.Shared", "two") == second
    assert database.find_qualified("demo.Shared") == (first, second)


def test_duplicate_symbol_inside_same_project_is_rejected() -> None:
    symbol = GlobalSymbol.create(
        GlobalSymbolKind.TYPE, "Shared", "demo.Shared", project_id="one",
    )
    with pytest.raises(DuplicateSymbolError, match="one:demo.Shared"):
        GlobalSymbolDatabase((symbol, symbol))


def test_junit_style_default_package_types_coexist_in_snapshot(tmp_path: Path) -> None:
    source = "public class DefaultPackageTestCase {}"
    _java_project(tmp_path, "jupiter-tests", source)
    _java_project(tmp_path, "platform-tests", source)
    (tmp_path / "atlas.yaml").write_text(
        """projects:
  - name: jupiter-tests
    path: jupiter-tests
  - name: platform-tests
    path: platform-tests
""",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    assert "succeeded: yes" in result.stdout
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    matches = [
        item for item in snapshot.semantic_context["symbols"]
        if item["qualified_name"] == "DefaultPackageTestCase"
    ]
    assert [item["project_id"] for item in matches] == [
        "jupiter-tests",
        "platform-tests",
    ]
    assert len({item["id"] for item in matches}) == 2


def test_same_fully_qualified_type_coexists_across_projects(tmp_path: Path) -> None:
    source = "package demo; public class Shared {}"
    _java_project(tmp_path, "one", source)
    _java_project(tmp_path, "two", source)
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: one\n    path: one\n  - name: two\n    path: two\n",
        encoding="utf-8",
    )
    report = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert report.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    matches = [
        item for item in snapshot.semantic_context["symbols"]
        if item["qualified_name"] == "demo.Shared"
    ]
    assert {item["project_id"] for item in matches} == {"one", "two"}


def test_duplicate_java_type_in_one_project_reports_sources_and_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    first = project / "One.java"
    second = project / "Two.java"
    first.write_text("package demo; class Shared {}", encoding="utf-8")
    second.write_text("package demo; class Shared {}", encoding="utf-8")
    target = Project("junit-module", project)
    with pytest.raises(DuplicateTypeError) as raised:
        SemanticProjectAnalyzer()(target, {})
    message = str(raised.value)
    assert target.name in message
    assert str(first.resolve()) in message
    assert str(second.resolve()) in message


def test_java_symbol_service_legacy_identity_remains_unscoped() -> None:
    index = JavaSymbolService().index_sources({
        Path("Shared.java"): "package demo; class Shared {}",
    })
    assert index.type_by_name("demo.Shared") is not None


def test_gradle_settings_modules_are_independent_projects(tmp_path: Path) -> None:
    (tmp_path / "settings.gradle.kts").write_text(
        'rootProject.name = "demo"\ninclude("jupiter-tests")\ninclude(":platform-tests")\n',
        encoding="utf-8",
    )
    for name in ("jupiter-tests", "platform-tests"):
        source = tmp_path / name / "src" / "test" / "java"
        source.mkdir(parents=True)
        (source / "DefaultPackageTestCase.java").write_text(
            "class DefaultPackageTestCase {}",
            encoding="utf-8",
        )

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert workspace.names() == (
        "jupiter-tests",
        "platform-tests",
        tmp_path.name,
    )
    root = workspace.get(tmp_path.name)
    assert root.exclude == ("jupiter-tests/**/*", "platform-tests/**/*")
    assert project_files(root.path, root.include, root.exclude) == (
        tmp_path / "settings.gradle.kts",
    )


def test_duplicate_member_emissions_from_one_ast_are_normalized(tmp_path: Path) -> None:
    source = tmp_path / "Repeated.java"
    source.write_text(
        "class Repeated { void run() {} void run(int value) {} }",
        encoding="utf-8",
    )
    parser = JavaParser()
    unit = parser.parse_source(source.read_text(encoding="utf-8"))
    index = JavaSymbolIndexBuilder().build((unit,), (source,))
    repeated = tuple(index.symbols) + (index.symbols[-1],)

    database = GlobalSymbolDatabaseBuilder().build(JavaSymbolIndex(repeated))

    assert len(database.snapshot().symbols) == len(index.symbols)
