from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfigurationSyncState:
    generation: int = 0
    overrides: tuple[tuple[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return dict(self.overrides)

    def update(self, settings: Mapping[str, Any]) -> "ConfigurationSyncState":
        normalized = flatten_settings(settings)
        return ConfigurationSyncState(self.generation + 1, tuple(sorted(normalized.items())))


def flatten_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(settings, Mapping):
        raise ValueError("configuration settings must be an object")
    source = settings.get("atlas", settings)
    if not isinstance(source, Mapping):
        raise ValueError("atlas configuration settings must be an object")
    result: dict[str, Any] = {}

    def visit(values: Mapping[str, Any], prefix: str = "") -> None:
        for key in sorted(values, key=str):
            name = str(key).strip()
            if not name:
                raise ValueError("configuration keys must not be empty")
            path = f"{prefix}.{name}" if prefix else name
            value = values[key]
            if isinstance(value, Mapping):
                visit(value, path)
            else:
                result[path] = value

    visit(source)
    return result
