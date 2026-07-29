from __future__ import annotations

from io import StringIO
import json
import logging
from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.structured_logging import (
    LogFormat,
    LogLevel,
    configure_logging,
    get_logger,
    log_event,
)
from moughorai.workspace import WorkspaceEventBus, WorkspaceEventKind


runner = CliRunner()


def workspace(root: Path) -> Path:
    (root / "core").mkdir()
    (root / "core" / "main.py").write_text("", encoding="utf-8")
    (root / "atlas.yaml").write_text("projects:\n  - name: core\n    path: core\n", encoding="utf-8")
    return root


def test_json_logging_has_stable_schema_and_correlation() -> None:
    output = StringIO()
    configure_logging(
        level=LogLevel.INFO,
        output_format=LogFormat.JSON,
        stream=output,
        correlation_id="request-123",
    )
    log_event(get_logger("test"), logging.INFO, "analysis.started", project="core", workers=2)
    payload = json.loads(output.getvalue())
    assert set(payload) == {
        "correlation_id", "event", "fields", "level", "logger",
        "message", "thread", "timestamp",
    }
    assert payload["correlation_id"] == "request-123"
    assert payload["event"] == "analysis.started"
    assert payload["fields"] == {"project": "core", "workers": 2}


def test_sensitive_fields_are_redacted_recursively() -> None:
    output = StringIO()
    configure_logging(level="info", stream=output, correlation_id="safe")
    log_event(
        get_logger("test"),
        logging.INFO,
        "configuration.loaded",
        token="visible-no",
        nested={"api_key": "visible-no", "name": "Atlas"},
    )
    fields = json.loads(output.getvalue())["fields"]
    assert fields == {
        "nested": {"api_key": "[REDACTED]", "name": "Atlas"},
        "token": "[REDACTED]",
    }


def test_text_logging_is_single_line() -> None:
    output = StringIO()
    configure_logging(level="warning", output_format="text", stream=output, correlation_id="text-1")
    log_event(get_logger("test"), logging.WARNING, "worker.retry", attempt=2)
    assert output.getvalue().splitlines() == [
        'warning correlation_id=text-1 event=worker.retry logger=moughorai.test fields={"attempt":2}'
    ]


def test_off_level_is_silent() -> None:
    output = StringIO()
    configure_logging(level="off", stream=output)
    log_event(get_logger("test"), logging.ERROR, "not-written")
    assert output.getvalue() == ""


def test_log_file_is_created(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "atlas.jsonl"
    configure_logging(level="info", path=target, correlation_id="file-1")
    log_event(get_logger("test"), logging.INFO, "file.event", path=Path("src/Main.java"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["fields"]["path"] == "src/Main.java"


def test_workspace_event_bus_emits_structured_event() -> None:
    output = StringIO()
    configure_logging(level="info", stream=output, correlation_id="workspace-1")
    bus = WorkspaceEventBus()
    bus.emit(WorkspaceEventKind.ANALYSIS_STARTED, project="core", payload={"workers": 2})
    payload = json.loads(output.getvalue())
    assert payload["event"] == "workspace.analysis_started"
    assert payload["correlation_id"] == "workspace-1"
    assert payload["fields"]["project"] == "core"
    assert payload["fields"]["payload"] == {"workers": 2}


def test_cli_default_remains_log_silent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "--no-recover"])
    assert result.exit_code == 0
    assert result.stderr == ""


def test_cli_json_logs_cover_concurrent_workspace_lifecycle(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--log-level", "info",
            "--log-format", "json",
            "--correlation-id", "cli-123",
            "analyze", str(root), "--workers", "2", "--no-recover",
        ],
    )
    assert result.exit_code == 0
    records = [json.loads(line) for line in result.stderr.splitlines()]
    events = [record["event"] for record in records]
    assert events[0] == "cli.started"
    assert "workspace.analysis_started" in events
    assert "workspace.project_started" in events
    assert "workspace.analysis_completed" in events
    assert {record["correlation_id"] for record in records} == {"cli-123"}


def test_cli_errors_are_logged_without_traceback(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--log-level", "error",
            "--correlation-id", "failure-1",
            "analyze", str(tmp_path / "missing"),
        ],
    )
    assert result.exit_code == 2
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert records[-1]["event"] == "cli.command_failed"
    assert records[-1]["fields"]["error_type"] == "FileNotFoundError"
    assert "Traceback" not in result.stderr
