from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class PluginError(ValueError):
    """Base error raised by the plugin SDK."""


class PluginManifestError(PluginError):
    pass


class PluginCompatibilityError(PluginError):
    pass


class PluginLoadError(PluginError):
    pass


class ExtensionPoint(str, Enum):
    ANALYZER = "analyzer"
    POLICY_PACK = "policy_pack"
    REPORTER = "reporter"


@dataclass(frozen=True, slots=True)
class PluginExtension:
    name: str
    point: ExtensionPoint
    factory: str
    capabilities: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PluginManifestError("extension name must not be empty")
        if ":" not in self.factory:
            raise PluginManifestError("extension factory must use 'module:attribute' syntax")
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    version: str
    api_version: str
    name: str
    extensions: tuple[PluginExtension, ...]
    description: str = ""
    requires: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plugin_id.strip():
            raise PluginManifestError("plugin id must not be empty")
        if not self.version.strip() or not self.api_version.strip():
            raise PluginManifestError("plugin version and api_version are required")
        names = [extension.name for extension in self.extensions]
        if len(names) != len(set(names)):
            raise PluginManifestError(f"duplicate extension name in plugin {self.plugin_id}")
        object.__setattr__(self, "extensions", tuple(sorted(self.extensions, key=lambda item: (item.point.value, item.name))))
        object.__setattr__(self, "requires", tuple(sorted(set(self.requires))))
        object.__setattr__(self, "permissions", tuple(sorted(set(self.permissions))))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    level: str
    code: str
    message: str
    plugin_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoadedExtension:
    plugin_id: str
    plugin_version: str
    extension: PluginExtension
    instance: Any
