"""Immutable persistent file-index models."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class IndexedFile:
    relative_path: Path
    size: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True)
class ProjectIndexSnapshot:
    root: Path
    files: tuple[IndexedFile, ...]
    schema_version: int = 1

    def by_path(self) -> dict[Path, IndexedFile]:
        return {item.relative_path: item for item in self.files}


@dataclass(frozen=True)
class IndexChangeSet:
    added: tuple[Path, ...] = ()
    modified: tuple[Path, ...] = ()
    removed: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.removed)
