from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import Project, Workspace


class WorkspaceConfigError(ValueError):
    pass


class WorkspaceLoader:
    CONFIG_NAMES = ("atlas.yaml", "atlas.yml")

    def find_config(self, root: Path | str) -> Path | None:
        directory = Path(root).expanduser().resolve()
        for name in self.CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return None

    def load(self, path: Path | str) -> Workspace:
        config_path = Path(path).expanduser().resolve()
        if config_path.is_dir():
            found = self.find_config(config_path)
            if found is None:
                raise FileNotFoundError(f"workspace configuration not found in {config_path}")
            config_path = found
        if not config_path.is_file():
            raise FileNotFoundError(f"workspace configuration not found: {config_path}")
        try:
            value = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
        except yaml.YAMLError as error:
            raise WorkspaceConfigError(f"invalid workspace YAML: {error}") from error
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise WorkspaceConfigError("workspace configuration root must be an object")
        return self.load_mapping(value, root=config_path.parent, config_path=config_path)

    def load_mapping(self, value: Mapping[str, Any], *, root: Path | str, config_path: Path | None = None) -> Workspace:
        workspace_root = Path(root).expanduser().resolve()
        raw_projects = value.get("projects", ())
        if isinstance(raw_projects, (str, bytes)) or not isinstance(raw_projects, list):
            raise WorkspaceConfigError("projects must be an array")
        projects = tuple(self._parse_project(item, workspace_root) for item in raw_projects)
        options = self._string_options(value.get("options", {}), "workspace options")
        return Workspace(root=workspace_root, projects=projects, config_path=config_path, options=options)

    def _parse_project(self, value: Any, root: Path) -> Project:
        if isinstance(value, str):
            raw: Mapping[str, Any] = {"path": value}
        elif isinstance(value, Mapping):
            raw = value
        else:
            raise WorkspaceConfigError("each project must be a path string or object")
        raw_path = str(raw.get("path", "")).strip()
        if not raw_path:
            raise WorkspaceConfigError("project path must not be empty")
        path = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise WorkspaceConfigError(f"project path escapes workspace: {raw_path}") from error
        name = str(raw.get("name", path.name)).strip()
        dependencies = self._strings(raw.get("dependencies", ()), "dependencies")
        include = self._strings(raw.get("include", ("**/*",)), "include")
        exclude = self._strings(raw.get("exclude", ()), "exclude")
        options = self._string_options(raw.get("options", {}), "project options")
        return Project(name=name, path=path, dependencies=dependencies, include=include, exclude=exclude, options=options)

    @staticmethod
    def _strings(value: Any, field: str) -> tuple[str, ...]:
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise WorkspaceConfigError(f"{field} must be an array")
        result = tuple(str(item).strip() for item in value)
        if any(not item for item in result):
            raise WorkspaceConfigError(f"{field} must not contain empty values")
        return result

    @staticmethod
    def _string_options(value: Any, field: str) -> tuple[tuple[str, str], ...]:
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise WorkspaceConfigError(f"{field} must be an object")
        return tuple(sorted((str(key), str(item)) for key, item in value.items()))
