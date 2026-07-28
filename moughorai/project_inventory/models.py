"""Immutable models used by project inventory analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FileKind(str, Enum):
    """High-level classification for project files."""

    SOURCE = "source"
    CONFIG = "config"
    BUILD = "build"
    ARCHIVE = "archive"
    BINARY = "binary"
    DOCUMENTATION = "documentation"
    GENERATED = "generated"
    ASSET = "asset"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScannedFile:
    """Raw filesystem information collected by the scanner."""

    path: Path
    relative_path: Path
    size: int
    extension: str


@dataclass(frozen=True)
class ProjectFile:
    """A scanned file enriched with deterministic classification."""

    path: Path
    relative_path: Path
    size: int
    extension: str
    language: str | None
    kind: FileKind


@dataclass(frozen=True)
class FileStatistic:
    """A named count and total size."""

    name: str
    files: int
    size: int


@dataclass(frozen=True)
class DirectoryStatistic:
    """Aggregated statistics for one project directory."""

    path: Path
    files: int
    size: int


@dataclass(frozen=True)
class ProjectInventory:
    """Complete deterministic inventory for one project root."""

    root: Path
    total_files: int
    total_directories: int
    total_size: int
    average_file_size: float
    largest_file: ProjectFile | None
    files: tuple[ProjectFile, ...]
    languages: tuple[FileStatistic, ...]
    extensions: tuple[FileStatistic, ...]
    kinds: tuple[FileStatistic, ...]
    largest_directories: tuple[DirectoryStatistic, ...]

    def files_of_kind(self, kind: FileKind) -> tuple[ProjectFile, ...]:
        """Return all files matching a high-level kind."""

        return tuple(file for file in self.files if file.kind is kind)

    def files_for_language(self, language: str) -> tuple[ProjectFile, ...]:
        """Return all files matching a language name, case-insensitively."""

        normalized = language.casefold()
        return tuple(
            file
            for file in self.files
            if file.language is not None
            and file.language.casefold() == normalized
        )
