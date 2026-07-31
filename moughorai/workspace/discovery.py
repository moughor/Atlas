from __future__ import annotations

from pathlib import Path
import re

from moughorai.project_inventory.maven_parser import MavenParseError, MavenParser
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
        self.maven_parser = MavenParser()

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
        projects.extend(self._gradle_projects(workspace_root, projects))
        projects.extend(self._maven_projects(workspace_root, projects))
        projects = self._exclude_nested_projects(projects)
        return Workspace(root=workspace_root, projects=tuple(sorted(projects, key=lambda item: item.name)))

    def _maven_projects(self, root: Path, existing: list[Project]) -> list[Project]:
        """Discover explicit Maven reactor modules beyond the generic depth limit."""

        workspace_root = root.resolve()
        known_paths = {project.path.resolve() for project in existing}
        pending = sorted(
            (path for path in known_paths if (path / "pom.xml").is_file()),
            key=lambda path: path.as_posix().casefold(),
        )
        parsed_paths: set[Path] = set()
        discovered: list[Project] = []

        while pending:
            project_path = pending.pop(0)
            if project_path in parsed_paths:
                continue
            parsed_paths.add(project_path)
            try:
                model = self.maven_parser.parse(project_path / "pom.xml")
            except MavenParseError:
                continue

            for module in sorted(model.modules, key=lambda item: item.path.casefold()):
                declared = project_path / module.path
                pom = declared if declared.name == "pom.xml" else declared / "pom.xml"
                if not pom.is_file():
                    continue
                module_path = pom.parent.resolve()
                try:
                    relative = module_path.relative_to(workspace_root)
                except ValueError:
                    continue
                if module_path not in known_paths:
                    known_paths.add(module_path)
                    discovered.append(Project("-".join(relative.parts), module_path))
                if module_path not in parsed_paths:
                    pending.append(module_path)
            pending.sort(key=lambda path: path.as_posix().casefold())

        return discovered

    @staticmethod
    def _gradle_projects(root: Path, existing: list[Project]) -> list[Project]:
        """Discover modules declared by Gradle settings without executing Gradle."""
        known_paths = {project.path.resolve() for project in existing}
        discovered: list[Project] = []
        for filename in ("settings.gradle", "settings.gradle.kts"):
            settings = root / filename
            if not settings.is_file():
                continue
            try:
                source = settings.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            for match in re.finditer(r"""(?m)^\s*include\s*\(([^)]*)\)""", source):
                for token in re.findall(r"""["']([^"']+)["']""", match.group(1)):
                    parts = tuple(part for part in token.lstrip(":").split(":") if part)
                    if not parts:
                        continue
                    path = root.joinpath(*parts).resolve()
                    if not path.is_dir() or path in known_paths:
                        continue
                    known_paths.add(path)
                    discovered.append(Project("-".join(parts), path))
        return discovered

    @staticmethod
    def _exclude_nested_projects(projects: list[Project]) -> list[Project]:
        """Assign nested source trees to their most specific discovered project."""
        result: list[Project] = []
        for project in projects:
            nested: list[str] = []
            for candidate in projects:
                if candidate is project:
                    continue
                try:
                    relative = candidate.path.resolve().relative_to(project.path.resolve())
                except ValueError:
                    continue
                nested.append(f"{relative.as_posix()}/**/*")
            result.append(
                Project(
                    project.name,
                    project.path,
                    project.dependencies,
                    project.include,
                    tuple(sorted(set(project.exclude).union(nested))),
                    project.options,
                )
            )
        return result

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
