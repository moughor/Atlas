from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.history import HISTORY_SCHEMA_VERSION, HistoryDatabase, HistoryDatabaseError
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


runner = CliRunner()


def report(name: str = "core", *, failed: bool = False) -> WorkspaceRunReport:
    status = ProjectRunStatus.FAILED if failed else ProjectRunStatus.SUCCEEDED
    run = ProjectRun(name, status, {"findings": [{"rule_id": "A", "line": 2}]}, "bad" if failed else None)
    return WorkspaceRunReport((run,), (name,), (name,))


def workspace(root: Path) -> Path:
    (root / "core").mkdir()
    (root / "core" / "main.py").write_text("# core\n", encoding="utf-8")
    (root / "atlas.yaml").write_text("projects:\n  - name: core\n    path: core\n", encoding="utf-8")
    return root


def test_missing_database_lists_empty_without_creating_file(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    assert database.list() == ()
    assert not database.path.exists()


def test_record_and_get_round_trip(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    run_id = database.record(report(), created_at="2026-01-02T03:04:05+00:00")
    item = database.get(run_id)
    assert item.created_at == "2026-01-02T03:04:05+00:00"
    assert item.to_report().to_dict() == report().to_dict()


def test_list_is_newest_first_and_paginated(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    ids = [database.record(report(str(index))) for index in range(3)]
    assert [item.run_id for item in database.list(limit=2)] == ids[::-1][:2]
    assert [item.run_id for item in database.list(limit=1, offset=1)] == [ids[1]]


def test_failed_report_is_preserved(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    item = database.get(database.record(report(failed=True)))
    assert not item.succeeded
    assert item.runs[0].error == "bad"


def test_prune_retains_newest_runs(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    ids = [database.record(report(str(index))) for index in range(4)]
    assert database.prune(keep=2) == 2
    assert [item.run_id for item in database.list()] == ids[-2:][::-1]


@pytest.mark.parametrize(("limit", "offset"), [(-1, 0), (1, -1)])
def test_invalid_pagination_is_rejected(tmp_path: Path, limit: int, offset: int) -> None:
    with pytest.raises(HistoryDatabaseError):
        HistoryDatabase(tmp_path).list(limit=limit, offset=offset)


def test_schema_version_mismatch_is_rejected(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    database.initialize()
    import sqlite3
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE atlas_metadata SET value = '999' WHERE key = 'schema_version'")
    with pytest.raises(HistoryDatabaseError, match="unsupported history schema"):
        database.initialize()


def test_schema_constant_is_stable() -> None:
    assert HISTORY_SCHEMA_VERSION == 1


def test_cli_analyze_records_history(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    result = runner.invoke(app, ["analyze", str(root), "--no-recover"])
    assert result.exit_code == 0
    stored = HistoryDatabase(root).list()
    assert len(stored) == 1
    assert stored[0].runs[0].project == "core"


def test_cli_history_is_deterministic(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    database = HistoryDatabase(root)
    database.record(report(), created_at="2026-01-02T03:04:05+00:00")
    result = runner.invoke(app, ["history", str(root)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "1 2026-01-02T03:04:05+00:00 succeeded projects=1",
        "runs: 1",
    ]
