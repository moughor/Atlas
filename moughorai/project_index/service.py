"""High-level persistent project index service."""
from __future__ import annotations

from pathlib import Path

from moughorai.project_index.indexer import ProjectFileIndexer
from moughorai.project_index.models import IndexChangeSet, ProjectIndexSnapshot
from moughorai.project_index.store import ProjectIndexStore


class PersistentProjectIndex:
    def __init__(self, indexer: ProjectFileIndexer | None = None, store: ProjectIndexStore | None = None) -> None:
        self._indexer = indexer or ProjectFileIndexer()
        self._store = store or ProjectIndexStore()

    def refresh(self, root: Path, cache_path: Path) -> tuple[ProjectIndexSnapshot, IndexChangeSet]:
        current = self._indexer.build(root)
        resolved_root = root.expanduser().resolve()
        resolved_cache = cache_path.expanduser().resolve()
        try:
            cache_relative = resolved_cache.relative_to(resolved_root)
        except ValueError:
            cache_relative = None
        if cache_relative is not None:
            current = ProjectIndexSnapshot(
                root=current.root,
                files=tuple(item for item in current.files if item.relative_path != cache_relative),
                schema_version=current.schema_version,
            )
        if cache_path.exists():
            previous = self._store.load(cache_path)
            changes = self._indexer.compare(previous, current)
        else:
            changes = IndexChangeSet(added=tuple(item.relative_path for item in current.files))
        self._store.save(current, cache_path)
        return current, changes
