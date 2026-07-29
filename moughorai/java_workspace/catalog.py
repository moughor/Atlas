"""Deterministic builders for workspace catalog objects."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from moughorai.java_workspace.catalog_models import WorkspaceCatalog, WorkspaceModule


def stable_workspace_key(root: Path, module_root: Path) -> str:
    """Return a stable, portable key derived from a module's relative path."""
    root = root.expanduser().resolve()
    module_root = module_root.expanduser().resolve()
    try:
        relative = module_root.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("module root must be inside workspace root") from exc
    logical = relative if relative != "." else "root"
    digest = hashlib.sha256(logical.encode("utf-8")).hexdigest()[:12]
    return f"{logical}:{digest}"


class WorkspaceCatalogBuilder:
    """Validate and normalize a workspace catalog without scanning files."""

    def build(self, root: Path, modules: Iterable[WorkspaceModule]) -> WorkspaceCatalog:
        workspace_root = root.expanduser().resolve()
        if not workspace_root.exists():
            raise FileNotFoundError(workspace_root)
        if not workspace_root.is_dir():
            raise NotADirectoryError(workspace_root)

        normalized: list[WorkspaceModule] = []
        seen: set[str] = set()
        for module in modules:
            module_root = module.root.expanduser().resolve()
            try:
                module_root.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError(f"module outside workspace: {module_root}") from exc
            folded = module.key.casefold()
            if folded in seen:
                raise ValueError(f"duplicate module key: {module.key}")
            seen.add(folded)
            normalized.append(module)

        normalized.sort(key=lambda item: (item.root.as_posix().casefold(), item.key.casefold()))
        return WorkspaceCatalog(root=workspace_root, modules=tuple(normalized))
