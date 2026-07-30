from __future__ import annotations

from pathlib import Path

from moughorai.project_locator import DEFAULT_PROJECT_MARKERS

from .loader import WorkspaceLoader
from .files import DEFAULT_IGNORED_DIRECTORIES
from .models import Project, Workspace


class WorkspaceDiscovery:
    DEFAULT_IGNORED = DEFAULT_IGNORED_DIRECTORIES

    def __init__(self, *, markers: tuple[str, ...] = DEFAULT_PROJECT_MARKERS, ignored: frozenset[str] = DEFAULT_IGNORED) -> None:
        self.markers = markers
        self.ignored = ignored
        self.loader = WorkspaceLoader()

    def discover(self, root: Path | str, *, max_depth: int = 4) -> Workspace:
        workspace_root = Path(root).expanduser().resolve()
        if not workspace_root.is_dir():
            raise FileNotFoundError(f"workspace root not found: {workspace_root}")
        config = self.loader.find_config(workspace_root)
        if config is not None:
            return self.loader.load(config)
        projects: list[Project] = []
        for directory in self._directories(workspace_root, max_depth=max_depth):
            if self._is_project(directory):
                relative = directory.relative_to(workspace_root)
                name = workspace_root.name if relative == Path(".") else "-".join(relative.parts)
                projects.append(Project(name=name, path=directory))
        return Workspace(root=workspace_root, projects=tuple(sorted(projects, key=lambda item: item.name)))

    def _directories(self, root: Path, *, max_depth: int):
        pending = [(root, 0)]
        while pending:
            directory, depth = pending.pop(0)
            yield directory
            if depth >= max_depth:
                continue
            try:
                children = sorted(
                    (
                        item
                        for item in directory.iterdir()
                        if item.is_dir()
                        and not item.name.startswith(".")
                        and item.name not in self.ignored
                    ),
                    key=lambda item: item.name,
                )
            except OSError:
                children = ()
            pending.extend((child, depth + 1) for child in children)

    def _is_project(self, directory: Path) -> bool:
        return any((directory / marker).exists() for marker in self.markers)
