from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class WorkspaceSemanticContext:
    """Immutable, JSON-serializable snapshot of deterministic Atlas facts."""

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)

    def to_json(self) -> str:
        return json.dumps(
            dict(self.data),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
