from __future__ import annotations

import os
from pathlib import Path


DEFAULT_IGNORED_DIRECTORIES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
})


def project_files(
    root: Path,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> tuple[Path, ...]:
    """Return matched files without entering hidden or inaccessible directories."""
    resolved_root = root.resolve()
    matched: list[Path] = []

    def ignore_error(error: OSError) -> None:
        return None

    for current, directory_names, file_names in os.walk(
        resolved_root,
        topdown=True,
        onerror=ignore_error,
        followlinks=False,
    ):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".") and name not in DEFAULT_IGNORED_DIRECTORIES
        )
        current_path = Path(current)
        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(resolved_root)
            if _matches(relative, include) and not _matches(relative, exclude):
                matched.append(path)
    return tuple(matched)


def _matches(path: Path, patterns: tuple[str, ...]) -> bool:
    path_text = path.as_posix()
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        if normalized.endswith("/**/*") and path_text.startswith(normalized[:-4]):
            return True
        if path.match(normalized):
            return True
        if normalized.startswith("**/") and path.match(normalized[3:]):
            return True
    return False
