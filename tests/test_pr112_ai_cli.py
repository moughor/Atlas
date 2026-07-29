from datetime import datetime, timezone
import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.atlas_cli import app
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _workspace(tmp_path: Path) -> Path:
    project = tmp_path / "app"
    project.mkdir()
    (project / "main.py").write_text("print('atlas')\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )
    return tmp_path


def _snapshot(root: Path) -> Path:
    workspace = WorkspaceService(root).workspace
    context = WorkspaceContextBuilder().build(workspace)
    store = SemanticSnapshotStore(
        workspace,
        clock=lambda: datetime(2026, 8, 1, 13, 20, 14, tzinfo=timezone.utc),
    )
    return store.save(store.capture(context, history_reference=3))


def test_root_and_ai_help_expose_namespace_and_commands() -> None:
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    assert "ai" in root_help.stdout
    ai_help = runner.invoke(app, ["ai", "--help"])
    assert ai_help.exit_code == 0
    for command in ("explain", "ask", "review", "fix", "context"):
        assert command in ai_help.stdout


def test_ai_context_reads_latest_snapshot_as_deterministic_json(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _snapshot(root)
    result = runner.invoke(app, ["ai", "context", str(root)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["workspace"]["projects"][0]["name"] == "app"
    assert "snapshot_id" not in payload


def test_ai_context_supports_explicit_snapshot_and_metadata(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot(root)
    result = runner.invoke(
        app,
        ["ai", "context", str(root), "--snapshot", str(snapshot), "--metadata"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["snapshot_id"]
    assert payload["history_reference"] == 3


def test_ai_context_reports_missing_snapshot(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(app, ["ai", "context", str(root)])
    assert result.exit_code == 2
    assert "semantic snapshot not found" in result.stderr


def test_future_engine_commands_are_explicit_and_do_not_call_provider(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _snapshot(root)
    invocations = {
        "ask": ["ai", "ask", "Why?", str(root)],
        "fix": ["ai", "fix", str(root)],
    }
    for command, arguments in invocations.items():
        result = runner.invoke(app, arguments)
        assert result.exit_code == 2
        assert f"atlas ai {command} requires its roadmap engine" in result.stderr


def test_future_engine_validates_snapshot_before_reporting_unavailable(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(app, ["ai", "explain", str(root)])
    assert result.exit_code == 2
    assert "semantic snapshot not found" in result.stderr
