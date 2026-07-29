from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import SemanticContextCollector
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
