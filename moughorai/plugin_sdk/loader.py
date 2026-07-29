from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import ExtensionPoint, PluginExtension, PluginManifest, PluginManifestError

_ALLOWED_ROOT = {"id", "version", "api_version", "name", "description", "requires", "permissions", "metadata", "extensions"}
_ALLOWED_EXTENSION = {"name", "point", "factory", "capabilities", "config"}


class PluginManifestLoader:
    def load_path(self, path: str | Path) -> PluginManifest:
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginManifestError(f"cannot read plugin manifest {source}: {exc}") from exc
        suffix = source.suffix.lower()
        if suffix == ".json":
            return self.load_json(text)
        if suffix in {".yaml", ".yml"}:
            return self.load_yaml(text)
        raise PluginManifestError(f"unsupported plugin manifest format: {suffix or '<none>'}")

    def load_json(self, text: str) -> PluginManifest:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"invalid JSON plugin manifest: {exc}") from exc
        return self.load_mapping(data)

    def load_yaml(self, text: str) -> PluginManifest:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PluginManifestError(f"invalid YAML plugin manifest: {exc}") from exc
        return self.load_mapping(data)

    def load_mapping(self, data: Any) -> PluginManifest:
        if not isinstance(data, Mapping):
            raise PluginManifestError("plugin manifest root must be an object")
        unknown = sorted(set(data) - _ALLOWED_ROOT)
        if unknown:
            raise PluginManifestError(f"unknown plugin manifest fields: {', '.join(unknown)}")
        required = ("id", "version", "api_version", "name", "extensions")
        missing = [key for key in required if key not in data]
        if missing:
            raise PluginManifestError(f"missing plugin manifest fields: {', '.join(missing)}")
        raw_extensions = data["extensions"]
        if not isinstance(raw_extensions, list):
            raise PluginManifestError("extensions must be a list")
        extensions = tuple(self._extension(item) for item in raw_extensions)
        requires = data.get("requires", [])
        if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
            raise PluginManifestError("requires must be a list of plugin ids")
        permissions = data.get("permissions", [])
        if not isinstance(permissions, list) or not all(isinstance(item, str) and item.strip() for item in permissions):
            raise PluginManifestError("permissions must be a list of non-empty strings")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise PluginManifestError("metadata must be an object")
        return PluginManifest(
            plugin_id=self._string(data, "id"),
            version=self._string(data, "version"),
            api_version=self._string(data, "api_version"),
            name=self._string(data, "name"),
            description=str(data.get("description", "")),
            requires=tuple(requires),
            permissions=tuple(permissions),
            metadata=dict(metadata),
            extensions=extensions,
        )

    def _extension(self, data: Any) -> PluginExtension:
        if not isinstance(data, Mapping):
            raise PluginManifestError("each extension must be an object")
        unknown = sorted(set(data) - _ALLOWED_EXTENSION)
        if unknown:
            raise PluginManifestError(f"unknown extension fields: {', '.join(unknown)}")
        missing = [key for key in ("name", "point", "factory") if key not in data]
        if missing:
            raise PluginManifestError(f"missing extension fields: {', '.join(missing)}")
        try:
            point = ExtensionPoint(str(data["point"]))
        except ValueError as exc:
            raise PluginManifestError(f"unknown extension point: {data['point']}") from exc
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise PluginManifestError("extension capabilities must be a list of strings")
        config = data.get("config", {})
        if not isinstance(config, Mapping):
            raise PluginManifestError("extension config must be an object")
        return PluginExtension(
            name=self._string(data, "name"),
            point=point,
            factory=self._string(data, "factory"),
            capabilities=tuple(capabilities),
            config=dict(config),
        )

    @staticmethod
    def _string(data: Mapping[str, Any], key: str) -> str:
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise PluginManifestError(f"{key} must be a non-empty string")
        return value.strip()
