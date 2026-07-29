"""Filesystem scanner for deterministic project inventories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from moughorai.project_inventory.models import ScannedFile

_DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)


@dataclass(frozen=True)
class ScanResult:
    """Raw output produced by a project scan."""

    root: Path
    files: tuple[ScannedFile, ...]
    total_directories: int


class ProjectScanner:
    """Walk a project tree and return raw file metadata."""

    def __init__(
        self,
        ignored_directories: Iterable[str] | None = None,
        *,
        follow_symlinks: bool = False,
    ) -> None:
        ignored = (
            _DEFAULT_IGNORED_DIRECTORIES
            if ignored_directories is None
            else frozenset(ignored_directories)
        )
        self._ignored_directories = ignored
        self._follow_symlinks = follow_symlinks

    def scan(self, root: Path) -> ScanResult:
        """Scan a project directory.

        Raises:
            FileNotFoundError: if the root does not exist.
            NotADirectoryError: if the root is not a directory.
        """

        root = root.expanduser().resolve()

        if not root.exists():
            raise FileNotFoundError(root)

        if not root.is_dir():
            raise NotADirectoryError(root)

        files: list[ScannedFile] = []
        total_directories = 1

        for current_root, directory_names, file_names in os.walk(
            root,
            followlinks=self._follow_symlinks,
        ):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in self._ignored_directories
            )
            file_names.sort()

            current_path = Path(current_root)

            if current_path != root:
                total_directories += 1

            for file_name in file_names:
                path = current_path / file_name

                if path.is_symlink() and not self._follow_symlinks:
                    continue

                try:
                    size = path.stat().st_size
                except OSError:
                    continue

                files.append(
                    ScannedFile(
                        path=path,
                        relative_path=path.relative_to(root),
                        size=size,
                        extension=path.suffix.casefold(),
                    )
                )

        files.sort(key=lambda file: file.relative_path.as_posix().casefold())

        return ScanResult(
            root=root,
            files=tuple(files),
            total_directories=total_directories,
        )
