from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import time

from .events import FileEvent, FileEventKind
from .event_bus import WorkspaceEventBus, WorkspaceEventKind
from .models import Project, Workspace
from .files import project_files


@dataclass(frozen=True, slots=True)
class FileState:
    size: int
    modified_ns: int
    digest_hint: int


@dataclass(frozen=True, slots=True)
class WatchSnapshot:
    files: tuple[tuple[Path, FileState], ...]

    def as_dict(self) -> dict[Path, FileState]:
        return dict(self.files)


class WorkspaceWatcher:
    """Portable polling watcher with deterministic event ordering."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
        debounce_ms: int = 100,
        event_bus: WorkspaceEventBus | None = None,
    ) -> None:
        if debounce_ms < 0:
            raise ValueError("debounce_ms must be non-negative")
        self.workspace = workspace
        self.clock_ns = clock_ns
        self.debounce_ns = debounce_ms * 1_000_000
        self.event_bus = event_bus
        self._snapshot: WatchSnapshot | None = None
        self._pending: dict[tuple[str, Path], FileEvent] = {}
        self._last_seen_ns: dict[tuple[str, Path], int] = {}

    def snapshot(self) -> WatchSnapshot:
        files: dict[Path, FileState] = {}
        for project in sorted(self.workspace.projects, key=lambda item: item.name):
            for path in self._project_files(project):
                stat = path.stat()
                files[path.resolve()] = FileState(
                    size=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    digest_hint=self._digest_hint(path),
                )
        return WatchSnapshot(tuple(sorted(files.items(), key=lambda item: item[0].as_posix())))

    def start(self) -> WatchSnapshot:
        self._snapshot = self.snapshot()
        self._pending.clear()
        self._last_seen_ns.clear()
        return self._snapshot

    def poll(self, *, now_ns: int | None = None, flush: bool = False) -> tuple[FileEvent, ...]:
        timestamp = self.clock_ns() if now_ns is None else now_ns
        current = self.snapshot()
        if self._snapshot is None:
            self._snapshot = current
            return ()
        detected = self.diff(self._snapshot, current, timestamp_ns=timestamp)
        self._snapshot = current
        self._enqueue(detected, timestamp)
        events = self.flush(now_ns=timestamp, force=flush)
        if events and self.event_bus is not None:
            self.event_bus.emit(
                WorkspaceEventKind.FILES_CHANGED,
                source="workspace.watcher",
                payload={"events": [event.to_dict(root=self.workspace.root) for event in events]},
            )
        return events

    def flush(self, *, now_ns: int | None = None, force: bool = False) -> tuple[FileEvent, ...]:
        timestamp = self.clock_ns() if now_ns is None else now_ns
        ready: list[FileEvent] = []
        for key, event in list(self._pending.items()):
            if force or timestamp - self._last_seen_ns[key] >= self.debounce_ns:
                ready.append(event)
                del self._pending[key]
                del self._last_seen_ns[key]
        return tuple(sorted(ready, key=self._event_key))

    def diff(self, before: WatchSnapshot, after: WatchSnapshot, *, timestamp_ns: int = 0) -> tuple[FileEvent, ...]:
        old = before.as_dict()
        new = after.as_dict()
        created = [path for path in new.keys() - old.keys()]
        deleted = [path for path in old.keys() - new.keys()]
        modified = [path for path in new.keys() & old.keys() if new[path] != old[path]]

        events: list[FileEvent] = []
        deleted_by_state: dict[FileState, list[Path]] = {}
        for path in deleted:
            deleted_by_state.setdefault(old[path], []).append(path)
        consumed_deleted: set[Path] = set()
        consumed_created: set[Path] = set()
        for path in sorted(created, key=Path.as_posix):
            matches = sorted(deleted_by_state.get(new[path], ()), key=Path.as_posix)
            match = next((candidate for candidate in matches if candidate not in consumed_deleted), None)
            if match is not None:
                consumed_deleted.add(match)
                consumed_created.add(path)
                events.append(self._event(FileEventKind.RENAMED, path, timestamp_ns, previous_path=match))

        for path in created:
            if path not in consumed_created:
                events.append(self._event(FileEventKind.CREATED, path, timestamp_ns))
        for path in modified:
            events.append(self._event(FileEventKind.MODIFIED, path, timestamp_ns))
        for path in deleted:
            if path not in consumed_deleted:
                events.append(self._event(FileEventKind.DELETED, path, timestamp_ns))
        return tuple(sorted(events, key=self._event_key))

    def _enqueue(self, events: Iterable[FileEvent], timestamp: int) -> None:
        for event in events:
            key = (event.project or "", event.path)
            previous = self._pending.get(key)
            merged = self._merge(previous, event)
            if merged is None:
                self._pending.pop(key, None)
                self._last_seen_ns.pop(key, None)
                continue
            self._pending[key] = merged
            self._last_seen_ns[key] = timestamp

    def _merge(self, previous: FileEvent | None, current: FileEvent) -> FileEvent | None:
        if previous is None:
            return current
        if previous.kind is FileEventKind.CREATED and current.kind is FileEventKind.MODIFIED:
            return FileEvent(FileEventKind.CREATED, current.path, current.project, timestamp_ns=current.timestamp_ns)
        if previous.kind is FileEventKind.CREATED and current.kind is FileEventKind.DELETED:
            return None
        if previous.kind is FileEventKind.MODIFIED and current.kind is FileEventKind.DELETED:
            return current
        return current

    def _event(self, kind: FileEventKind, path: Path, timestamp_ns: int, *, previous_path: Path | None = None) -> FileEvent:
        return FileEvent(kind, path, self._project_for(path), previous_path, timestamp_ns)

    def _project_for(self, path: Path) -> str | None:
        resolved = path.resolve()
        matches: list[tuple[int, str]] = []
        for project in self.workspace.projects:
            try:
                resolved.relative_to(project.path.resolve())
            except ValueError:
                continue
            matches.append((len(project.path.resolve().parts), project.name))
        return max(matches)[1] if matches else None

    def _project_files(self, project: Project) -> tuple[Path, ...]:
        return project_files(project.path, project.include, project.exclude)

    @staticmethod
    def _digest_hint(path: Path) -> int:
        data = path.read_bytes()
        return hash(data)

    @staticmethod
    def _event_key(event: FileEvent) -> tuple[str, str, str]:
        return (event.project or "", event.path.as_posix(), event.kind.value)
