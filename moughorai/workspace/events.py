from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FileEventKind(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class FileEvent:
    kind: FileEventKind
    path: Path
    project: str | None = None
    previous_path: Path | None = None
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path.resolve())
        if self.previous_path is not None:
            object.__setattr__(self, "previous_path", self.previous_path.resolve())
        if self.kind is FileEventKind.RENAMED and self.previous_path is None:
            raise ValueError("renamed events require previous_path")
        if self.kind is not FileEventKind.RENAMED and self.previous_path is not None:
            raise ValueError("previous_path is only valid for renamed events")

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        def display(path: Path | None) -> str | None:
            if path is None:
                return None
            if root is not None:
                try:
                    path = path.relative_to(root.resolve())
                except ValueError:
                    pass
            return path.as_posix()

        return {
            "kind": self.kind.value,
            "path": display(self.path),
            "previous_path": display(self.previous_path),
            "project": self.project,
            "timestamp_ns": self.timestamp_ns,
        }
