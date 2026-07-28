"""Deterministic, content-addressed project file indexing."""
from __future__ import annotations

import hashlib
from pathlib import Path

from moughorai.project_index.models import IndexedFile, IndexChangeSet, ProjectIndexSnapshot
from moughorai.project_inventory.scanner import ProjectScanner


class ProjectFileIndexer:
    def __init__(self, scanner: ProjectScanner | None = None, *, chunk_size: int = 1024 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._scanner = scanner or ProjectScanner()
        self._chunk_size = chunk_size

    def build(self, root: Path) -> ProjectIndexSnapshot:
        scan = self._scanner.scan(root)
        entries = tuple(
            IndexedFile(
                relative_path=item.relative_path,
                size=item.size,
                modified_ns=item.path.stat().st_mtime_ns,
                sha256=self._hash(item.path),
            )
            for item in scan.files
        )
        return ProjectIndexSnapshot(root=scan.root, files=entries)

    def compare(self, previous: ProjectIndexSnapshot, current: ProjectIndexSnapshot) -> IndexChangeSet:
        old = previous.by_path()
        new = current.by_path()
        old_paths = set(old)
        new_paths = set(new)
        added = tuple(sorted(new_paths - old_paths, key=lambda p: p.as_posix().casefold()))
        removed = tuple(sorted(old_paths - new_paths, key=lambda p: p.as_posix().casefold()))
        modified = tuple(sorted(
            (path for path in old_paths & new_paths if old[path].sha256 != new[path].sha256),
            key=lambda p: p.as_posix().casefold(),
        ))
        unchanged = tuple(sorted(
            (path for path in old_paths & new_paths if old[path].sha256 == new[path].sha256),
            key=lambda p: p.as_posix().casefold(),
        ))
        return IndexChangeSet(added=added, modified=modified, removed=removed, unchanged=unchanged)

    def _hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(self._chunk_size):
                digest.update(chunk)
        return digest.hexdigest()
