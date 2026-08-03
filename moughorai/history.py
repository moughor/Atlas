"""Transactional historical analysis storage for Atlas."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


HISTORY_SCHEMA_VERSION = 1


class HistoryDatabaseError(ValueError):
    """Raised when the historical database is invalid or unavailable."""


@dataclass(frozen=True, slots=True)
class HistoricalRun:
    run_id: int
    created_at: str
    succeeded: bool
    requested: tuple[str, ...]
    analysis_order: tuple[str, ...]
    runs: tuple[ProjectRun, ...]

    def to_report(self) -> WorkspaceRunReport:
        return WorkspaceRunReport(self.runs, self.requested, self.analysis_order)


class HistoryDatabase:
    """Versioned SQLite store for completed workspace reports."""

    def __init__(self, root: Path, path: Path | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.path = (path or self.root / ".atlas" / "history.sqlite3").expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS atlas_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS analysis_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1)),
                        requested_json TEXT NOT NULL,
                        analysis_order_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS project_runs (
                        analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        project TEXT NOT NULL,
                        status TEXT NOT NULL,
                        value_json TEXT,
                        error TEXT,
                        blocked_by_json TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        PRIMARY KEY (analysis_run_id, position)
                    );
                    CREATE INDEX IF NOT EXISTS project_runs_project
                        ON project_runs(project, analysis_run_id);
                    CREATE TABLE IF NOT EXISTS adaptive_history_exclusions (
                        analysis_run_id INTEGER PRIMARY KEY
                            REFERENCES analysis_runs(id) ON DELETE CASCADE,
                        reason TEXT NOT NULL
                            CHECK (reason = 'performance-measurement')
                    );
                    """
                )
                row = connection.execute(
                    "SELECT value FROM atlas_metadata WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO atlas_metadata(key, value) VALUES ('schema_version', ?)",
                        (str(HISTORY_SCHEMA_VERSION),),
                    )
                elif row[0] != str(HISTORY_SCHEMA_VERSION):
                    raise HistoryDatabaseError(f"unsupported history schema: {row[0]}")
        except sqlite3.Error as exc:
            raise HistoryDatabaseError(f"cannot initialize history database: {exc}") from exc

    def record(
        self,
        report: WorkspaceRunReport,
        *,
        created_at: str | None = None,
        adaptive_eligible: bool = True,
    ) -> int:
        if not isinstance(adaptive_eligible, bool):
            raise HistoryDatabaseError("adaptive eligibility must be a boolean")
        self.initialize()
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO analysis_runs(created_at, succeeded, requested_json, analysis_order_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        int(report.succeeded),
                        self._json(list(report.requested)),
                        self._json(list(report.analysis_order)),
                    ),
                )
                run_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO project_runs(
                        analysis_run_id, position, project, status, value_json,
                        error, blocked_by_json, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            position,
                            run.project,
                            run.status.value,
                            None if run.value is None else self._json(run.to_dict()["value"]),
                            run.error,
                            self._json(list(run.blocked_by)),
                            run.duration_ms,
                        )
                        for position, run in enumerate(report.runs)
                    ],
                )
                if not adaptive_eligible:
                    connection.execute(
                        """
                        INSERT INTO adaptive_history_exclusions(
                            analysis_run_id, reason
                        ) VALUES (?, 'performance-measurement')
                        """,
                        (run_id,),
                    )
                return run_id
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise HistoryDatabaseError(f"cannot record analysis history: {exc}") from exc

    def list(self, *, limit: int = 20, offset: int = 0) -> tuple[HistoricalRun, ...]:
        return self._list(limit=limit, offset=offset, adaptive_eligible_only=False)

    def list_adaptive_eligible(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[HistoricalRun, ...]:
        """Return runs whose timings were not collected under M2 profiling."""

        return self._list(limit=limit, offset=offset, adaptive_eligible_only=True)

    def _list(
        self,
        *,
        limit: int,
        offset: int,
        adaptive_eligible_only: bool,
    ) -> tuple[HistoricalRun, ...]:
        if limit < 0 or offset < 0:
            raise HistoryDatabaseError("history limit and offset must be non-negative")
        if not self.path.exists():
            return ()
        self.initialize()
        try:
            with self._connect() as connection:
                query = (
                    "SELECT id FROM analysis_runs "
                    "WHERE id NOT IN ("
                    "SELECT analysis_run_id FROM adaptive_history_exclusions"
                    ") ORDER BY id DESC LIMIT ? OFFSET ?"
                    if adaptive_eligible_only
                    else "SELECT id FROM analysis_runs "
                    "ORDER BY id DESC LIMIT ? OFFSET ?"
                )
                ids = [
                    int(row[0])
                    for row in connection.execute(query, (limit, offset))
                ]
                return tuple(self._load(connection, run_id) for run_id in ids)
        except sqlite3.Error as exc:
            raise HistoryDatabaseError(f"cannot read analysis history: {exc}") from exc

    def get(self, run_id: int) -> HistoricalRun:
        if not self.path.exists():
            raise KeyError(run_id)
        self.initialize()
        try:
            with self._connect() as connection:
                return self._load(connection, run_id)
        except sqlite3.Error as exc:
            raise HistoryDatabaseError(f"cannot read analysis history: {exc}") from exc

    def prune(self, *, keep: int) -> int:
        if keep < 0:
            raise HistoryDatabaseError("history retention must be non-negative")
        if not self.path.exists():
            return 0
        self.initialize()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM analysis_runs
                    WHERE id NOT IN (SELECT id FROM analysis_runs ORDER BY id DESC LIMIT ?)
                    """,
                    (keep,),
                )
                return max(0, cursor.rowcount)
        except sqlite3.Error as exc:
            raise HistoryDatabaseError(f"cannot prune analysis history: {exc}") from exc

    def _load(self, connection: sqlite3.Connection, run_id: int) -> HistoricalRun:
        row = connection.execute(
            """
            SELECT id, created_at, succeeded, requested_json, analysis_order_json
            FROM analysis_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        projects = connection.execute(
            """
            SELECT project, status, value_json, error, blocked_by_json, duration_ms
            FROM project_runs WHERE analysis_run_id = ? ORDER BY position
            """,
            (run_id,),
        )
        runs = tuple(
            ProjectRun(
                project=item[0],
                status=ProjectRunStatus(item[1]),
                value=None if item[2] is None else json.loads(item[2]),
                error=item[3],
                blocked_by=tuple(json.loads(item[4])),
                duration_ms=float(item[5]),
            )
            for item in projects
        )
        return HistoricalRun(
            int(row[0]),
            str(row[1]),
            bool(row[2]),
            tuple(json.loads(row[3])),
            tuple(json.loads(row[4])),
            runs,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
