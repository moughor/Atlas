"""Incremental execution coordinator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .cache import IncrementalCache
from .fingerprints import FileFingerprint, FingerprintService


@dataclass(frozen=True)
class ChangeSummary:
    added: tuple[Path, ...] = ()
    modified: tuple[Path, ...] = ()
    removed: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()
    invalidated: tuple[Path, ...] = ()

    @property
    def dirty(self) -> tuple[Path, ...]:
        return tuple(sorted(set(self.added + self.modified + self.invalidated), key=_path_key))

    @property
    def is_noop(self) -> bool:
        return not self.added and not self.modified and not self.removed and not self.invalidated


@dataclass(frozen=True)
class IncrementalRun:
    changes: ChangeSummary
    analyzed: tuple[Path, ...]
    reused: tuple[Path, ...]
    results: tuple[tuple[Path, Any], ...]

    def result_map(self) -> dict[Path, Any]:
        return dict(self.results)


class IncrementalAnalysisEngine:
    """Runs an analyzer only for changed or transitively affected files."""

    def __init__(self, cache: IncrementalCache | None = None, fingerprints: FingerprintService | None = None) -> None:
        self.cache = cache or IncrementalCache()
        self.fingerprints = fingerprints or FingerprintService()

    def compare(
        self,
        previous: Iterable[FileFingerprint],
        current: Iterable[FileFingerprint],
        dependencies: Mapping[Path, Iterable[Path]] | None = None,
    ) -> ChangeSummary:
        old = {item.path: item for item in previous}
        new = {item.path: item for item in current}
        added = set(new) - set(old)
        removed = set(old) - set(new)
        modified = {path for path in set(old) & set(new) if old[path].sha256 != new[path].sha256}
        unchanged = set(old) & set(new) - modified
        invalidated = self._propagate(added | modified | removed, dependencies or {}) - added - modified - removed
        return ChangeSummary(
            tuple(sorted(added, key=_path_key)),
            tuple(sorted(modified, key=_path_key)),
            tuple(sorted(removed, key=_path_key)),
            tuple(sorted(unchanged, key=_path_key)),
            tuple(sorted(invalidated, key=_path_key)),
        )

    def run(
        self,
        fingerprints: Iterable[FileFingerprint],
        analyzer: Callable[[Path], Any],
        *,
        previous: Iterable[FileFingerprint] = (),
        dependencies: Mapping[Path, Iterable[Path]] | None = None,
        full_rebuild: bool = False,
    ) -> IncrementalRun:
        current = tuple(sorted(fingerprints, key=lambda item: _path_key(item.path)))
        changes = self.compare(previous, current, dependencies)
        current_by_path = {item.path: item for item in current}
        dirty = set(current_by_path) if full_rebuild else set(changes.dirty)
        if full_rebuild:
            changes = ChangeSummary(changes.added, changes.modified, changes.removed, changes.unchanged, tuple(sorted(set(current_by_path) - set(changes.added) - set(changes.modified), key=_path_key)))

        removed_keys = [path.as_posix() for path in changes.removed]
        if removed_keys:
            self.cache.invalidate(removed_keys)

        results: list[tuple[Path, Any]] = []
        analyzed: list[Path] = []
        reused: list[Path] = []
        dependency_map = dependencies or {}
        for path, fingerprint in sorted(current_by_path.items(), key=lambda item: _path_key(item[0])):
            key = path.as_posix()
            cached = None if path in dirty else self.cache.get(key, fingerprint.sha256)
            if cached is None:
                value = analyzer(path)
                deps = tuple(dep.as_posix() for dep in dependency_map.get(path, ()))
                self.cache.put(key, fingerprint.sha256, value, deps)
                analyzed.append(path)
            else:
                value = cached
                reused.append(path)
            results.append((path, value))
        return IncrementalRun(changes, tuple(analyzed), tuple(reused), tuple(results))

    @staticmethod
    def _propagate(changed: set[Path], dependencies: Mapping[Path, Iterable[Path]]) -> set[Path]:
        reverse: dict[Path, set[Path]] = {}
        for dependent, required in dependencies.items():
            for dependency in required:
                reverse.setdefault(dependency, set()).add(dependent)
        dirty = set(changed)
        queue = list(changed)
        while queue:
            current = queue.pop()
            for dependent in reverse.get(current, ()):
                if dependent not in dirty:
                    dirty.add(dependent)
                    queue.append(dependent)
        return dirty


def _path_key(path: Path) -> str:
    return path.as_posix().casefold()
