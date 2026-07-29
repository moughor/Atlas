"""Locate the project associated with a filesystem location."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


DEFAULT_PROJECT_MARKERS: tuple[str, ...] = (
    ".git",
    ".moughorai",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "pnpm-workspace.yaml",
    "yarn.lock",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "composer.json",
    "Gemfile",
    "Makefile",
    "CMakeLists.txt",
)


class ProjectLocatorError(ValueError):
    """Raised when an explicitly supplied project path is invalid."""


class ProjectLocator:
    """Find a project by inspecting a directory and its parents."""

    def __init__(
        self,
        *,
        markers: Iterable[str] = DEFAULT_PROJECT_MARKERS,
    ) -> None:
        normalized_markers = tuple(
            marker.strip()
            for marker in markers
            if marker.strip()
        )

        if not normalized_markers:
            raise ValueError(
                "ProjectLocator requires at least one project marker."
            )

        self.markers = normalized_markers

    def locate(
        self,
        explicit: Path | None = None,
        *,
        start: Path | None = None,
    ) -> Path | None:
        """Return an explicit project or discover one from a starting path.

        Explicit paths always take priority and must reference an existing
        directory.

        Without an explicit path, discovery starts from ``start`` or the
        current working directory and walks upward until a project marker is
        found.
        """
        if explicit is not None:
            return self._validate_explicit(explicit)

        starting_path = start if start is not None else Path.cwd()
        current = starting_path.expanduser()

        if not current.exists():
            return None

        if current.is_file():
            current = current.parent

        current = current.resolve()

        for candidate in (current, *current.parents):
            if self.is_project_directory(candidate):
                return candidate

        return None

    def is_project_directory(self, path: Path) -> bool:
        """Return whether a directory contains a known project marker."""
        if not path.is_dir():
            return False

        return any(
            (path / marker).exists()
            for marker in self.markers
        )

    @staticmethod
    def _validate_explicit(path: Path) -> Path:
        resolved = path.expanduser().resolve()

        if not resolved.exists():
            raise ProjectLocatorError(
                f"Project directory does not exist: {resolved}"
            )

        if not resolved.is_dir():
            raise ProjectLocatorError(
                f"Project path is not a directory: {resolved}"
            )

        return resolved
