from pathlib import Path
import json

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import (
    SemanticContextCollector,
    SemanticProjectAnalyzer,
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.atlas_cli import app
from moughorai.semantic import Diagnostic, DiagnosticBag, SemanticDocument
from moughorai.semantic.types import TypeRegistry, TypeTable
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    Workspace,
    WorkspaceRunReport,
    WorkspaceService,
)


runner = CliRunner()


def _workspace(tmp_path: Path, source: str = "package demo; public class App {}") -> Path:
    project = tmp_path / "app"
    project.mkdir()
    (project / "App.java").write_text(source, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )
    return tmp_path


def test_collector_aggregates_java_symbols_and_semantic_artifacts(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = WorkspaceService(root)
    document = SemanticDocument(
        "java",
        "",
        object(),
        artifacts={"types": TypeTable({"node": TypeRegistry().primitive("int")})},
        diagnostics=DiagnosticBag(),
    )
    document = document.with_diagnostic(Diagnostic("A1", "verified"))
    report = WorkspaceRunReport(
        (ProjectRun("app", ProjectRunStatus.SUCCEEDED, document),),
        ("app",),
        ("app",),
    )
    collected = SemanticContextCollector(service).collect(report)
    payload = collected.context.to_dict()
    assert any(symbol["qualified_name"] == "demo.App" for symbol in payload["symbols"])
    assert payload["diagnostics"][0]["code"] == "A1"
    assert payload["types"]["app"][0]["type"]["name"] == "int"


def test_default_project_analyzer_returns_real_semantic_document(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = WorkspaceService(root)
    document = SemanticProjectAnalyzer()(service.project("app"), {})
    assert isinstance(document, SemanticDocument)
    assert document.source == ""
    assert document.language == "java"
    assert len(document.syntax_tree) == 1
    assert document.metadata["files"] == 1
    assert any(
        symbol.qualified_name == "demo.App"
        for symbol in document.require_artifact("global_symbols")
    )


def test_project_analyzer_reports_invalid_java_without_raw_source(tmp_path: Path) -> None:
    source = "package demo; public class"
    root = _workspace(tmp_path, source)
    service = WorkspaceService(root)
    document = SemanticProjectAnalyzer()(service.project("app"), {})
    assert document.source == ""
    assert len(document.diagnostics) == 1
    assert document.diagnostics.items[0].code == "ATLAS-JAVA-PARSE"
    assert source not in repr(document.metadata)


def test_project_analyzer_ignores_hidden_tool_trees(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    hidden = root / "app" / ".pytest_runtime"
    hidden.mkdir()
    (hidden / "Broken.java").write_text("public class", encoding="utf-8")
    service = WorkspaceService(root)
    document = SemanticProjectAnalyzer()(service.project("app"), {})
    assert len(document.diagnostics) == 0
    assert document.metadata["files"] == 1


def test_semantic_document_persistence_round_trip_preserves_context(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    service = WorkspaceService(root)
    original = SemanticProjectAnalyzer()(service.project("app"), {})
    restored = decode_analysis_result(encode_analysis_result(original))
    assert isinstance(restored, SemanticDocument)
    assert restored.metadata == original.metadata
    assert restored.source == ""
    assert restored.syntax_tree == ()
    assert restored.get_artifact("global_symbols") == original.get_artifact("global_symbols")


def test_analyze_publishes_latest_ass_consumable_by_ai_context(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    analyzed = runner.invoke(app, ["analyze", str(root), "--no-recover"])
    assert analyzed.exit_code == 0
    store = SemanticSnapshotStore(WorkspaceService(root).workspace)
    snapshot = store.load()
    assert snapshot is not None
    assert snapshot.history_reference == 1
    assert any(
        symbol["qualified_name"] == "demo.App"
        for symbol in snapshot.semantic_context["symbols"]
    )
    context = runner.invoke(app, ["ai", "context", str(root)])
    assert context.exit_code == 0
    assert "demo.App" in context.stdout


def test_analyze_json_uses_stable_semantic_summary(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(
        app,
        ["analyze", str(root), "--no-recover", "--format", "json"],
    )
    assert result.exit_code == 0
    value = json.loads(result.stdout)["runs"][0]["value"]
    assert value == {
        "dependencies": [],
        "files": 1,
        "project": "app",
        "semantic_pipeline": "atlas",
    }


def test_recovery_restores_semantic_results_and_republishes_context(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first = runner.invoke(app, ["analyze", str(root)])
    second = runner.invoke(app, ["analyze", str(root)])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "app: reused" in second.stdout
    snapshot = SemanticSnapshotStore(WorkspaceService(root).workspace).load()
    assert snapshot is not None
    assert any(
        symbol["qualified_name"] == "demo.App"
        for symbol in snapshot.semantic_context["symbols"]
    )


def test_failed_analysis_does_not_publish_snapshot(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    previous = atlas_cli._analyzer_factory
    atlas_cli._analyzer_factory = lambda service: (
        lambda project, dependencies: (_ for _ in ()).throw(RuntimeError("broken"))
    )
    try:
        result = runner.invoke(app, ["analyze", str(root), "--no-recover"])
    finally:
        atlas_cli._analyzer_factory = previous
    assert result.exit_code == 0
    assert "succeeded: no" in result.stdout
    assert not (root / ".atlas" / "ass" / "latest.ass").exists()
