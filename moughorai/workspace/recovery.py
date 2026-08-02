from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any

from .configuration import ResolvedConfiguration
from .event_bus import WorkspaceEvent, WorkspaceEventKind
from .execution import ProjectRunStatus, WorkspaceAnalysisOrchestrator, WorkspaceRunReport
from .models import Project
from .persistence import (
    ANALYSIS_RESULT_PRODUCER_FINGERPRINT,
    WorkspaceStateError,
    WorkspaceStateStore,
)
from .service import WorkspaceService


RECOVERY_SCHEMA_VERSION = 1


class WorkspaceRecoveryError(ValueError):
    """Raised when a recovery journal cannot be read or represented."""


class RecoveryProjectStatus(str, Enum):
    COMPLETED = "completed"
    RUNNING = "running"
    FAILED = "failed"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class RecoveryProject:
    name: str
    status: RecoveryProjectStatus
    value: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status.value}
        if self.status is RecoveryProjectStatus.COMPLETED:
            data["value"] = self.value
        if self.error is not None:
            data["error"] = self.error
        return data


@dataclass(frozen=True, slots=True)
class WorkspaceRecoveryJournal:
    schema_version: int
    workspace_fingerprint: str
    configuration_fingerprint: str
    requested: tuple[str, ...]
    analysis_order: tuple[str, ...]
    projects: tuple[RecoveryProject, ...]
    started_at: str
    updated_at: str
    producer_fingerprint: str = ANALYSIS_RESULT_PRODUCER_FINGERPRINT

    def get(self, name: str) -> RecoveryProject:
        for project in self.projects:
            if project.name == name:
                return project
        raise KeyError(name)

    def with_project(
        self,
        name: str,
        status: RecoveryProjectStatus,
        *,
        value: Any = None,
        error: str | None = None,
        updated_at: str,
    ) -> "WorkspaceRecoveryJournal":
        projects = []
        found = False
        for project in self.projects:
            if project.name == name:
                projects.append(RecoveryProject(name, status, value, error))
                found = True
            else:
                projects.append(project)
        if not found:
            raise WorkspaceRecoveryError(f"journal contains no project {name!r}")
        return replace(self, projects=tuple(projects), updated_at=updated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace_fingerprint": self.workspace_fingerprint,
            "configuration_fingerprint": self.configuration_fingerprint,
            "requested": list(self.requested),
            "analysis_order": list(self.analysis_order),
            "projects": {project.name: project.to_dict() for project in self.projects},
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "producer_fingerprint": self.producer_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkspaceRecoveryJournal":
        try:
            schema = int(data["schema_version"])
            workspace_fingerprint = str(data["workspace_fingerprint"])
            configuration_fingerprint = str(data["configuration_fingerprint"])
            requested = _string_tuple(data["requested"], "requested")
            order = _string_tuple(data["analysis_order"], "analysis_order")
            raw_projects = data["projects"]
            started_at = str(data["started_at"])
            updated_at = str(data["updated_at"])
            producer_fingerprint = str(
                data.get(
                    "producer_fingerprint",
                    "atlas/legacy:unversioned-analysis-result",
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceRecoveryError("recovery journal is missing required fields") from exc
        if schema != RECOVERY_SCHEMA_VERSION:
            raise WorkspaceRecoveryError(f"unsupported recovery journal schema: {schema}")
        if not isinstance(raw_projects, Mapping):
            raise WorkspaceRecoveryError("recovery journal projects must be a mapping")
        if len(order) != len(set(order)) or set(raw_projects) != set(order):
            raise WorkspaceRecoveryError("recovery journal project set is inconsistent")
        projects: list[RecoveryProject] = []
        for name in order:
            raw = raw_projects[name]
            if not isinstance(raw, Mapping):
                raise WorkspaceRecoveryError(f"recovery project {name!r} must be an object")
            try:
                status = RecoveryProjectStatus(str(raw["status"]))
            except (KeyError, ValueError) as exc:
                raise WorkspaceRecoveryError(f"invalid recovery status for project {name!r}") from exc
            if status is RecoveryProjectStatus.COMPLETED and "value" not in raw:
                raise WorkspaceRecoveryError(f"completed recovery project {name!r} has no value")
            projects.append(RecoveryProject(name, status, raw.get("value"), _optional_string(raw.get("error"))))
        _parse_time(started_at)
        _parse_time(updated_at)
        return cls(
            schema,
            workspace_fingerprint,
            configuration_fingerprint,
            requested,
            order,
            tuple(projects),
            started_at,
            updated_at,
            producer_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceRecoveryReport:
    journal_found: bool
    resumed: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()
    running: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    invalidated: bool = False
    invalidation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_found": self.journal_found,
            "resumed": list(self.resumed),
            "completed": list(self.completed),
            "running": list(self.running),
            "failed": list(self.failed),
            "pending": list(self.pending),
            "invalidated": self.invalidated,
            "invalidation_reason": self.invalidation_reason,
        }


class WorkspaceRecoveryManager:
    """Durable, event-driven recovery for workspace analysis."""

    def __init__(
        self,
        service: WorkspaceService,
        path: str | Path | None = None,
        *,
        state_store: WorkspaceStateStore | None = None,
        configuration: ResolvedConfiguration | None = None,
        max_age_seconds: float | None = None,
        encoder: Callable[[Any], Any] | None = None,
        decoder: Callable[[Any], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        producer_fingerprint: str | None = None,
    ) -> None:
        self.service = service
        configured_path = configuration.get("recovery.path") if configuration is not None else None
        self.path = Path(path or configured_path or service.workspace.root / ".atlas" / "workspace-recovery.json")
        configured_age = configuration.get("recovery.max_age_seconds") if configuration is not None else None
        self.max_age_seconds = float(max_age_seconds if max_age_seconds is not None else configured_age) if (
            max_age_seconds is not None or configured_age is not None
        ) else None
        if self.max_age_seconds is not None and self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        self.configuration = configuration
        self.encoder = encoder or (lambda value: value)
        self.decoder = decoder or (lambda value: value)
        resolved_producer = (
            producer_fingerprint
            if producer_fingerprint is not None
            else getattr(
                state_store,
                "producer_fingerprint",
                ANALYSIS_RESULT_PRODUCER_FINGERPRINT,
            )
        )
        if not isinstance(resolved_producer, str) or not resolved_producer.strip():
            raise ValueError("producer_fingerprint must be a non-empty string")
        self.producer_fingerprint = resolved_producer.strip()
        if (
            state_store is not None
            and state_store.producer_fingerprint != self.producer_fingerprint
        ):
            raise ValueError("state_store producer fingerprint is inconsistent")
        self.state_store = state_store or WorkspaceStateStore(
            service,
            encoder=self.encoder,
            decoder=self.decoder,
            producer_fingerprint=self.producer_fingerprint,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._journal: WorkspaceRecoveryJournal | None = None
        self._orchestrator: WorkspaceAnalysisOrchestrator | None = None
        self._subscription: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.configuration.get("recovery.enabled", True)) if self.configuration is not None else True

    def inspect(self) -> WorkspaceRecoveryReport:
        journal, report = self._load_valid()
        return report if journal is None else self._report(journal, journal_found=True)

    def execute(
        self,
        orchestrator: WorkspaceAnalysisOrchestrator,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        projects: tuple[str, ...] | list[str] | None = None,
        include_dependencies: bool = True,
        force: bool = False,
        cancelled: Callable[[], bool] | None = None,
        max_workers: int = 1,
        fail_fast: bool = False,
    ) -> WorkspaceRunReport:
        if not self.enabled:
            return orchestrator.execute(
                analyzer, projects=projects, include_dependencies=include_dependencies, force=force,
                cancelled=cancelled, max_workers=max_workers, fail_fast=fail_fast,
            )
        requested = tuple(sorted(set(projects or self.service.workspace.names())))
        order = self.service.analysis_order(requested, include_dependencies=include_dependencies)
        now = self._now()
        self._journal = WorkspaceRecoveryJournal(
            RECOVERY_SCHEMA_VERSION,
            self._workspace_fingerprint(),
            self._configuration_fingerprint(),
            requested,
            tuple(project.name for project in order),
            tuple(RecoveryProject(project.name, RecoveryProjectStatus.PENDING) for project in order),
            now,
            now,
            self.producer_fingerprint,
        )
        self._save(self._journal)
        self.service.events.emit(WorkspaceEventKind.RECOVERY_STARTED, source="workspace.recovery", payload=self._report(self._journal, True).to_dict())
        return self._run(orchestrator, analyzer, requested, include_dependencies, force, cancelled, max_workers, fail_fast)

    def resume(
        self,
        orchestrator: WorkspaceAnalysisOrchestrator,
        analyzer: Callable[[Project, Mapping[str, Any]], Any],
        *,
        cancelled: Callable[[], bool] | None = None,
        max_workers: int = 1,
        fail_fast: bool = False,
    ) -> tuple[WorkspaceRunReport | None, WorkspaceRecoveryReport]:
        if not self.enabled:
            return None, WorkspaceRecoveryReport(False)
        journal, report = self._load_valid()
        if journal is None:
            return None, report
        completed = [project for project in journal.projects if project.status is RecoveryProjectStatus.COMPLETED]
        try:
            restored = {project.name: self.decoder(project.value) for project in completed}
        except Exception as exc:
            return None, self._invalidate(f"cannot decode recovery result: {type(exc).__name__}: {exc}")
        orchestrator._results.update(restored)
        for name in restored:
            orchestrator.planner.mark_valid(name)
        unfinished = tuple(project.name for project in journal.projects if project.status is not RecoveryProjectStatus.COMPLETED)
        self._journal = journal
        self.service.events.emit(
            WorkspaceEventKind.RECOVERY_RESUMED,
            source="workspace.recovery",
            payload={"resumed": list(unfinished), "completed": sorted(restored)},
        )
        if not unfinished:
            run_report = orchestrator.execute(
                analyzer, projects=journal.requested, include_dependencies=True, force=False,
                cancelled=cancelled, max_workers=max_workers, fail_fast=fail_fast,
            )
        else:
            run_report = self._run(
                orchestrator, analyzer, unfinished, True, False, cancelled, max_workers, fail_fast
            )
        return run_report, replace(self._report(self._journal or journal, True), resumed=unfinished)

    def delete(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True

    def _run(self, orchestrator, analyzer, projects, include_dependencies, force, cancelled, max_workers, fail_fast):
        self._orchestrator = orchestrator
        self._subscription = self.service.events.subscribe(
            self._on_event,
            kinds=[
                WorkspaceEventKind.PROJECT_STARTED,
                WorkspaceEventKind.PROJECT_COMPLETED,
                WorkspaceEventKind.PROJECT_FAILED,
                WorkspaceEventKind.PROJECT_BLOCKED,
            ],
        )
        try:
            report = orchestrator.execute(
                analyzer, projects=projects, include_dependencies=include_dependencies, force=force,
                cancelled=cancelled, max_workers=max_workers, fail_fast=fail_fast,
            )
            self._finalize(report)
            return report
        finally:
            if self._subscription is not None:
                self.service.events.unsubscribe(self._subscription)
            self._subscription = None
            self._orchestrator = None

    def _on_event(self, event: WorkspaceEvent) -> None:
        if event.project is None:
            return
        with self._lock:
            journal = self._journal
            if journal is None or event.project not in journal.analysis_order:
                return
            previous = journal.get(event.project)
            if event.kind is WorkspaceEventKind.PROJECT_STARTED:
                if previous.status is RecoveryProjectStatus.COMPLETED:
                    return
                status, value, error = RecoveryProjectStatus.RUNNING, None, None
            elif event.kind is WorkspaceEventKind.PROJECT_COMPLETED:
                try:
                    value = self.encoder(event.payload.get("value"))
                except Exception as exc:
                    raise WorkspaceRecoveryError(f"cannot encode result for project {event.project!r}: {exc}") from exc
                status, error = RecoveryProjectStatus.COMPLETED, None
            elif event.kind is WorkspaceEventKind.PROJECT_FAILED:
                status, value, error = RecoveryProjectStatus.FAILED, None, _optional_string(event.payload.get("error"))
            else:
                status, value, error = RecoveryProjectStatus.PENDING, None, _optional_string(event.payload.get("error"))
            self._journal = journal.with_project(event.project, status, value=value, error=error, updated_at=self._now())
            self._save(self._journal)
            if status is RecoveryProjectStatus.COMPLETED and self._orchestrator is not None:
                self.state_store.save(self.state_store.capture(self._orchestrator._results, self._orchestrator.planner.valid_projects))

    def _finalize(self, report: WorkspaceRunReport) -> None:
        with self._lock:
            journal = self._journal
            if journal is None:
                return
            for run in report.runs:
                if run.status in {ProjectRunStatus.SUCCEEDED, ProjectRunStatus.REUSED}:
                    value = self.encoder(run.value)
                    status, error = RecoveryProjectStatus.COMPLETED, None
                elif run.status is ProjectRunStatus.FAILED:
                    value, status, error = None, RecoveryProjectStatus.FAILED, run.error
                else:
                    value, status, error = None, RecoveryProjectStatus.PENDING, run.error
                journal = journal.with_project(run.project, status, value=value, error=error, updated_at=self._now())
            self._journal = journal
            self._save(journal)
            self.service.events.emit(WorkspaceEventKind.RECOVERY_COMPLETED, source="workspace.recovery", payload=self._report(journal, True).to_dict())

    def _load_valid(self) -> tuple[WorkspaceRecoveryJournal | None, WorkspaceRecoveryReport]:
        if not self.path.exists():
            return None, WorkspaceRecoveryReport(False)
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, Mapping) or not isinstance(envelope.get("journal"), Mapping):
                raise WorkspaceRecoveryError("recovery journal envelope is invalid")
            raw = envelope["journal"]
            canonical = _canonical(raw)
            if envelope.get("checksum") != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
                raise WorkspaceRecoveryError("recovery journal checksum mismatch")
            journal = WorkspaceRecoveryJournal.from_dict(raw)
        except (OSError, json.JSONDecodeError, WorkspaceRecoveryError) as exc:
            return None, self._invalidate(str(exc))
        if journal.workspace_fingerprint != self._workspace_fingerprint():
            return None, self._invalidate("workspace fingerprint changed")
        if journal.configuration_fingerprint != self._configuration_fingerprint():
            return None, self._invalidate("recovery configuration changed")
        if journal.producer_fingerprint != self.producer_fingerprint:
            return None, self._invalidate("analysis producer changed")
        current = set(self.service.workspace.names())
        if set(journal.analysis_order) != current.intersection(journal.analysis_order) or not set(journal.requested).issubset(current):
            return None, self._invalidate("workspace project set changed")
        if self.max_age_seconds is not None:
            age = (self.clock() - _parse_time(journal.updated_at)).total_seconds()
            if age > self.max_age_seconds:
                return None, self._invalidate(f"recovery journal is stale ({age:.3f}s old)")
        return journal, self._report(journal, True)

    def _invalidate(self, reason: str) -> WorkspaceRecoveryReport:
        try:
            self.delete()
        except OSError as exc:
            raise WorkspaceRecoveryError(f"cannot invalidate recovery journal: {exc}") from exc
        report = WorkspaceRecoveryReport(True, invalidated=True, invalidation_reason=reason)
        self.service.events.emit(WorkspaceEventKind.RECOVERY_INVALIDATED, source="workspace.recovery", payload=report.to_dict())
        return report

    def _save(self, journal: WorkspaceRecoveryJournal) -> Path:
        raw = journal.to_dict()
        envelope = {"checksum": hashlib.sha256(_canonical(raw).encode("utf-8")).hexdigest(), "journal": raw}
        text = json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        self.service.events.emit(
            WorkspaceEventKind.RECOVERY_JOURNAL_SAVED,
            source="workspace.recovery",
            payload={"path": str(self.path), "projects": list(journal.analysis_order)},
        )
        return self.path

    def _report(self, journal: WorkspaceRecoveryJournal, journal_found: bool) -> WorkspaceRecoveryReport:
        by_status = {
            status: tuple(project.name for project in journal.projects if project.status is status)
            for status in RecoveryProjectStatus
        }
        return WorkspaceRecoveryReport(
            journal_found,
            completed=by_status[RecoveryProjectStatus.COMPLETED],
            running=by_status[RecoveryProjectStatus.RUNNING],
            failed=by_status[RecoveryProjectStatus.FAILED],
            pending=by_status[RecoveryProjectStatus.PENDING],
        )

    def _workspace_fingerprint(self) -> str:
        return self.state_store.capture({}, ()).workspace_fingerprint

    def _configuration_fingerprint(self) -> str:
        values = self.configuration.to_dict() if self.configuration is not None else {}
        return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None:
            raise WorkspaceRecoveryError("recovery clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorkspaceRecoveryError(f"{field} must be a list of strings")
    return tuple(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WorkspaceRecoveryError(f"invalid recovery timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise WorkspaceRecoveryError("recovery timestamps must be timezone-aware")
    return parsed
