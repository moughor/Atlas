"""Deterministic dependency-aware parallel scheduling for incremental analysis."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .engine import ChangeSummary, IncrementalAnalysisEngine, _path_key
from .fingerprints import FileFingerprint


class DependencyCycleError(ValueError):
    """Raised when dirty files contain a dependency cycle."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self.paths = tuple(sorted(set(paths), key=_path_key))
        joined = ", ".join(path.as_posix() for path in self.paths)
        super().__init__(f"incremental dependency cycle: {joined}")


@dataclass(frozen=True, order=True)
class ExecutionFailure:
    path: Path
    error_type: str
    message: str


@dataclass(frozen=True)
class ParallelIncrementalRun:
    changes: ChangeSummary
    analyzed: tuple[Path, ...]
    reused: tuple[Path, ...]
    results: tuple[tuple[Path, Any], ...]
    failures: tuple[ExecutionFailure, ...] = ()
    cancelled: tuple[Path, ...] = ()
    waves: tuple[tuple[Path, ...], ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failures

    @property
    def completed(self) -> tuple[Path, ...]:
        return tuple(path for path, _ in self.results)

    def result_map(self) -> dict[Path, Any]:
        return dict(self.results)


class ParallelIncrementalScheduler:
    """Executes dirty files concurrently while respecting file dependencies."""

    def __init__(self, engine: IncrementalAnalysisEngine | None = None, *, max_workers: int = 4) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least one")
        self.engine = engine or IncrementalAnalysisEngine()
        self.max_workers = max_workers

    def plan_waves(
        self,
        paths: Iterable[Path],
        dependencies: Mapping[Path, Iterable[Path]] | None = None,
    ) -> tuple[tuple[Path, ...], ...]:
        pending = set(paths)
        dependency_map = {
            path: set(required) & pending
            for path, required in (dependencies or {}).items()
            if path in pending
        }
        waves: list[tuple[Path, ...]] = []
        completed: set[Path] = set()
        while pending:
            ready = tuple(sorted(
                (path for path in pending if dependency_map.get(path, set()) <= completed),
                key=_path_key,
            ))
            if not ready:
                raise DependencyCycleError(pending)
            waves.append(ready)
            completed.update(ready)
            pending.difference_update(ready)
        return tuple(waves)

    def run(
        self,
        fingerprints: Iterable[FileFingerprint],
        analyzer: Callable[[Path], Any],
        *,
        previous: Iterable[FileFingerprint] = (),
        dependencies: Mapping[Path, Iterable[Path]] | None = None,
        full_rebuild: bool = False,
        fail_fast: bool = False,
    ) -> ParallelIncrementalRun:
        current = tuple(sorted(fingerprints, key=lambda item: _path_key(item.path)))
        current_by_path = {item.path: item for item in current}
        dependency_map = {
            path: tuple(sorted(set(required), key=_path_key))
            for path, required in (dependencies or {}).items()
        }
        changes = self.engine.compare(previous, current, dependency_map)
        dirty = set(current_by_path) if full_rebuild else set(changes.dirty)
        if full_rebuild:
            additional = set(current_by_path) - set(changes.added) - set(changes.modified)
            changes = ChangeSummary(
                changes.added,
                changes.modified,
                changes.removed,
                changes.unchanged,
                tuple(sorted(additional, key=_path_key)),
            )

        if changes.removed:
            self.engine.cache.invalidate(path.as_posix() for path in changes.removed)

        results: dict[Path, Any] = {}
        reused: list[Path] = []
        to_analyze: set[Path] = set()
        for path, fingerprint in current_by_path.items():
            cached = None if path in dirty else self.engine.cache.get(path.as_posix(), fingerprint.sha256)
            if cached is None:
                to_analyze.add(path)
            else:
                results[path] = cached
                reused.append(path)

        waves = self.plan_waves(to_analyze, dependency_map)
        analyzed: list[Path] = []
        failures: list[ExecutionFailure] = []
        cancelled: set[Path] = set()
        failed_or_blocked: set[Path] = set()

        for wave_index, wave in enumerate(waves):
            runnable: list[Path] = []
            for path in wave:
                required = set(dependency_map.get(path, ()))
                if required & failed_or_blocked:
                    cancelled.add(path)
                    failed_or_blocked.add(path)
                else:
                    runnable.append(path)

            if fail_fast and failures:
                for remaining_wave in waves[wave_index:]:
                    cancelled.update(remaining_wave)
                break
            if not runnable:
                continue

            outcomes = self._execute_wave(tuple(runnable), analyzer)
            for path in sorted(outcomes, key=_path_key):
                value, error = outcomes[path]
                if error is not None:
                    failures.append(ExecutionFailure(path, type(error).__name__, str(error)))
                    failed_or_blocked.add(path)
                    continue
                fingerprint = current_by_path[path]
                deps = tuple(dep.as_posix() for dep in dependency_map.get(path, ()))
                self.engine.cache.put(path.as_posix(), fingerprint.sha256, value, deps)
                results[path] = value
                analyzed.append(path)

            if fail_fast and failures:
                for remaining_wave in waves[wave_index + 1:]:
                    cancelled.update(remaining_wave)
                break

        return ParallelIncrementalRun(
            changes=changes,
            analyzed=tuple(sorted(analyzed, key=_path_key)),
            reused=tuple(sorted(reused, key=_path_key)),
            results=tuple(sorted(results.items(), key=lambda item: _path_key(item[0]))),
            failures=tuple(sorted(failures, key=lambda item: _path_key(item.path))),
            cancelled=tuple(sorted(cancelled, key=_path_key)),
            waves=waves,
        )

    def _execute_wave(
        self,
        wave: tuple[Path, ...],
        analyzer: Callable[[Path], Any],
    ) -> dict[Path, tuple[Any | None, BaseException | None]]:
        outcomes: dict[Path, tuple[Any | None, BaseException | None]] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(wave))) as executor:
            futures: dict[Future[Any], Path] = {executor.submit(analyzer, path): path for path in wave}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    outcomes[path] = (future.result(), None)
                except BaseException as exc:  # analyzer failures are reported, not leaked
                    outcomes[path] = (None, exc)
        return outcomes
