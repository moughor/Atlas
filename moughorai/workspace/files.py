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
    include_patterns = _compile_patterns(include)
    exclude_patterns = _compile_patterns(exclude)
    matched: list[Path] = []

    def ignore_error(error: OSError) -> None:
        return None

    for current, directory_names, file_names in os.walk(
        resolved_root,
        topdown=True,
        onerror=ignore_error,
        followlinks=False,
    ):
        current_path = Path(current)
        current_relative = current_path.relative_to(resolved_root)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".")
            and name not in DEFAULT_IGNORED_DIRECTORIES
            and not _is_literal_excluded_tree(
                current_relative / name,
                exclude_patterns,
            )
        )
        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(resolved_root)
            if _matches(relative, include_patterns) and not _matches(
                relative,
                exclude_patterns,
            ):
                matched.append(path)
    return tuple(matched)


def _compile_patterns(
    patterns: tuple[str, ...],
) -> tuple[tuple[str, str | None], ...]:
    compiled: list[tuple[str, str | None]] = []
    for pattern in patterns:
        normalized = pattern.replace("\\", "/")
        compiled.append((normalized, _literal_subtree(normalized)))
    return tuple(compiled)


def _literal_subtree(normalized: str) -> str | None:
    suffix = "/**/*"
    if not normalized.endswith(suffix):
        return None
    tree = normalized[: -len(suffix)].rstrip("/")
    if not tree or any(character in tree for character in "*?["):
        return None
    return tree


def _is_literal_excluded_tree(
    path: Path,
    patterns: tuple[tuple[str, str | None], ...],
) -> bool:
    """Return whether *path* is covered by a literal full-subtree exclusion."""
    path_text = path.as_posix()
    for _normalized, tree in patterns:
        if tree is None:
            continue
        if path_text == tree or path_text.startswith(f"{tree}/"):
            return True
    return False


def _matches(
    path: Path,
    patterns: tuple[tuple[str, str | None], ...],
) -> bool:
    path_text = path.as_posix()
    for normalized, tree in patterns:
        if normalized == "**/*":
            return True
        if tree is not None:
            if path_text.startswith(f"{tree}/"):
                return True
            continue
        if path.match(normalized):
            return True
        if normalized.startswith("**/") and path.match(normalized[3:]):
            return True
    return False
