from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Project:
    name: str
    path: Path
    dependencies: tuple[str, ...] = ()
    include: tuple[str, ...] = ("**/*",)
    exclude: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("project name must not be empty")
        if any(not value.strip() for value in self.dependencies):
            raise ValueError("project dependencies must not contain empty values")
        if self.name in self.dependencies:
            raise ValueError(f"project {self.name!r} cannot depend on itself")

    @property
    def option_map(self) -> dict[str, str]:
        return dict(self.options)

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        path = self.path
        if root is not None:
            try:
                path = path.relative_to(root)
            except ValueError:
                pass
        return {
            "name": self.name,
            "path": path.as_posix(),
            "dependencies": list(self.dependencies),
            "include": list(self.include),
            "exclude": list(self.exclude),
            "options": dict(self.options),
        }


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    projects: tuple[Project, ...]
    config_path: Path | None = None
    options: tuple[tuple[str, str], ...] = ()
    _by_name: Mapping[str, Project] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        object.__setattr__(self, "root", root)
        by_name: dict[str, Project] = {}
        for project in self.projects:
            if project.name in by_name:
                raise ValueError(f"duplicate project name: {project.name}")
            by_name[project.name] = project
        object.__setattr__(self, "_by_name", by_name)

    def get(self, name: str) -> Project:
        try:
            return self._by_name[name]
        except KeyError as error:
            raise KeyError(f"unknown project: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root.as_posix(),
            "config_path": self.config_path.as_posix() if self.config_path else None,
            "options": dict(self.options),
            "projects": [project.to_dict(root=self.root) for project in sorted(self.projects, key=lambda item: item.name)],
        }
