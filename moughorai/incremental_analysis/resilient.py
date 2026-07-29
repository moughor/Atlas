"""Retryable, checkpointed execution for parallel incremental analysis."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable, Iterable, Mapping

from .engine import ChangeSummary, IncrementalAnalysisEngine, _path_key
from .fingerprints import FileFingerprint
from .scheduler import DependencyCycleError, ExecutionFailure, ParallelIncrementalScheduler


class CheckpointFormatError(ValueError):
    """Raised when a scheduler checkpoint cannot be trusted."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    retryable: tuple[type[BaseException], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        if not self.retryable:
            raise ValueError("retryable must not be empty")
        if not all(isinstance(item, type) and issubclass(item, BaseException) for item in self.retryable):
            raise TypeError("retryable entries must be exception types")

    def permits(self, error: BaseException, attempt: int) -> bool:
        return attempt < self.max_attempts and isinstance(error, self.retryable)


@dataclass(frozen=True, order=True)
class AttemptRecord:
    path: Path
    attempt: int
    succeeded: bool
    error_type: str = ""
    message: str = ""


@dataclass(frozen=True)
class CheckpointEntry:
    path: Path
    fingerprint: str
    result: Any


class ExecutionCheckpoint:
    SCHEMA_VERSION = 1

    def __init__(self, entries: Iterable[CheckpointEntry] = ()) -> None:
        self._entries = {entry.path: entry for entry in entries}
        self._lock = RLock()

    @property
    def entries(self) -> tuple[CheckpointEntry, ...]:
        with self._lock:
            return tuple(sorted(self._entries.values(), key=lambda item: _path_key(item.path)))

    def get(self, path: Path, fingerprint: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(path)
            return entry.result if entry is not None and entry.fingerprint == fingerprint else None

    def put(self, path: Path, fingerprint: str, result: Any) -> None:
        if len(fingerprint) != 64:
            raise ValueError("checkpoint fingerprint must be a SHA-256 digest")
        with self._lock:
            self._entries[path] = CheckpointEntry(path, fingerprint, result)

    def remove_missing(self, paths: Iterable[Path]) -> tuple[Path, ...]:
        allowed = set(paths)
        with self._lock:
            removed = tuple(sorted((path for path in self._entries if path not in allowed), key=_path_key))
            for path in removed:
                del self._entries[path]
            return removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "entries": [
                {"path": entry.path.as_posix(), "fingerprint": entry.fingerprint, "result": entry.result}
                for entry in self.entries
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(self.to_json(), encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionCheckpoint":
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise CheckpointFormatError("unsupported checkpoint schema version")
        raw = value.get("entries")
        if not isinstance(raw, list):
            raise CheckpointFormatError("checkpoint entries must be a list")
        entries: list[CheckpointEntry] = []
        try:
            for item in raw:
                path = Path(str(item["path"]))
                fingerprint = str(item["fingerprint"])
                if not path.as_posix() or len(fingerprint) != 64:
                    raise ValueError("invalid checkpoint entry")
                entries.append(CheckpointEntry(path, fingerprint, item.get("result")))
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointFormatError(f"invalid checkpoint entry: {exc}") from exc
        if len({entry.path for entry in entries}) != len(entries):
            raise CheckpointFormatError("duplicate checkpoint path")
        return cls(entries)

    @classmethod
    def load(cls, path: Path, *, recover: bool = False) -> "ExecutionCheckpoint":
        if not path.exists():
            return cls()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise CheckpointFormatError("checkpoint root must be an object")
            return cls.from_dict(value)
        except (OSError, json.JSONDecodeError, CheckpointFormatError) as exc:
            if recover:
                return cls()
            if isinstance(exc, CheckpointFormatError):
                raise
            raise CheckpointFormatError(f"unable to load checkpoint: {exc}") from exc


@dataclass(frozen=True)
class ResilientIncrementalRun:
    changes: ChangeSummary
    analyzed: tuple[Path, ...]
    reused: tuple[Path, ...]
    resumed: tuple[Path, ...]
    results: tuple[tuple[Path, Any], ...]
    failures: tuple[ExecutionFailure, ...] = ()
    cancelled: tuple[Path, ...] = ()
    waves: tuple[tuple[Path, ...], ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failures

    @property
    def retry_count(self) -> int:
        return sum(1 for record in self.attempts if record.attempt > 1)

    def result_map(self) -> dict[Path, Any]:
        return dict(self.results)


class ResilientParallelScheduler:
    """Runs dependency waves with retries and durable successful checkpoints."""

    def __init__(
        self,
        engine: IncrementalAnalysisEngine | None = None,
        *,
        max_workers: int = 4,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.engine = engine or IncrementalAnalysisEngine()
        self.parallel = ParallelIncrementalScheduler(self.engine, max_workers=max_workers)
        self.retry_policy = retry_policy or RetryPolicy()

    def run(
        self,
        fingerprints: Iterable[FileFingerprint],
        analyzer: Callable[[Path], Any],
        *,
        previous: Iterable[FileFingerprint] = (),
        dependencies: Mapping[Path, Iterable[Path]] | None = None,
        full_rebuild: bool = False,
        fail_fast: bool = False,
        checkpoint_path: Path | None = None,
        resume: bool = True,
        recover_checkpoint: bool = False,
    ) -> ResilientIncrementalRun:
        current = tuple(sorted(fingerprints, key=lambda item: _path_key(item.path)))
        current_by_path = {item.path: item for item in current}
        dependency_map = {path: tuple(sorted(set(required), key=_path_key)) for path, required in (dependencies or {}).items()}
        changes = self.engine.compare(previous, current, dependency_map)
        dirty = set(current_by_path) if full_rebuild else set(changes.dirty)
        if full_rebuild:
            extra = set(current_by_path) - set(changes.added) - set(changes.modified)
            changes = ChangeSummary(changes.added, changes.modified, changes.removed, changes.unchanged, tuple(sorted(extra, key=_path_key)))
        if changes.removed:
            self.engine.cache.invalidate(path.as_posix() for path in changes.removed)

        checkpoint = ExecutionCheckpoint.load(checkpoint_path, recover=recover_checkpoint) if checkpoint_path else ExecutionCheckpoint()
        checkpoint.remove_missing(current_by_path)
        results: dict[Path, Any] = {}
        reused: list[Path] = []
        resumed: list[Path] = []
        to_analyze: set[Path] = set()
        for path, fingerprint in current_by_path.items():
            value = None
            if resume and not full_rebuild:
                value = checkpoint.get(path, fingerprint.sha256)
                if value is not None:
                    results[path] = value
                    resumed.append(path)
                    continue
            cached = None if path in dirty else self.engine.cache.get(path.as_posix(), fingerprint.sha256)
            if cached is not None:
                results[path] = cached
                reused.append(path)
            else:
                to_analyze.add(path)

        waves = self.parallel.plan_waves(to_analyze, dependency_map)
        analyzed: list[Path] = []
        failures: list[ExecutionFailure] = []
        cancelled: set[Path] = set()
        blocked: set[Path] = set()
        attempts: list[AttemptRecord] = []

        for wave_index, wave in enumerate(waves):
            runnable = tuple(path for path in wave if not (set(dependency_map.get(path, ())) & blocked))
            blocked_now = set(wave) - set(runnable)
            cancelled.update(blocked_now)
            blocked.update(blocked_now)
            if fail_fast and failures:
                for rest in waves[wave_index:]:
                    cancelled.update(rest)
                break
            if not runnable:
                continue
            outcomes = self.parallel._execute_wave(runnable, lambda path: self._analyze_with_retry(path, analyzer, attempts))
            for path in sorted(outcomes, key=_path_key):
                value, error = outcomes[path]
                if error is not None:
                    failures.append(ExecutionFailure(path, type(error).__name__, str(error)))
                    blocked.add(path)
                    continue
                fingerprint = current_by_path[path]
                deps = tuple(dep.as_posix() for dep in dependency_map.get(path, ()))
                self.engine.cache.put(path.as_posix(), fingerprint.sha256, value, deps)
                checkpoint.put(path, fingerprint.sha256, value)
                if checkpoint_path:
                    checkpoint.save(checkpoint_path)
                results[path] = value
                analyzed.append(path)
            if fail_fast and failures:
                for rest in waves[wave_index + 1:]:
                    cancelled.update(rest)
                break

        if checkpoint_path:
            checkpoint.save(checkpoint_path)
        return ResilientIncrementalRun(
            changes,
            tuple(sorted(analyzed, key=_path_key)),
            tuple(sorted(reused, key=_path_key)),
            tuple(sorted(resumed, key=_path_key)),
            tuple(sorted(results.items(), key=lambda item: _path_key(item[0]))),
            tuple(sorted(failures, key=lambda item: _path_key(item.path))),
            tuple(sorted(cancelled, key=_path_key)),
            waves,
            tuple(sorted(attempts, key=lambda item: (_path_key(item.path), item.attempt))),
        )

    def _analyze_with_retry(self, path: Path, analyzer: Callable[[Path], Any], attempts: list[AttemptRecord]) -> Any:
        attempt = 1
        while True:
            try:
                value = analyzer(path)
                attempts.append(AttemptRecord(path, attempt, True))
                return value
            except BaseException as error:
                attempts.append(AttemptRecord(path, attempt, False, type(error).__name__, str(error)))
                if not self.retry_policy.permits(error, attempt):
                    raise
                if self.retry_policy.backoff_seconds:
                    time.sleep(self.retry_policy.backoff_seconds)
                attempt += 1
