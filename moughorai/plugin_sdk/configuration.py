from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .models import PluginExtension, PluginLoadError, PluginManifest, PluginManifestError
from .runtime import PluginRuntime


class PluginConfigurationError(PluginLoadError):
    """Raised when plugin configuration validation or application fails."""


class ReconfigurationStatus(str, Enum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginConfigurationProfile:
    name: str
    values: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PluginManifestError("configuration profile name must not be empty")
        normalized: dict[str, Mapping[str, Any]] = {}
        for extension_name, config in sorted(self.values.items()):
            if not extension_name.strip():
                raise PluginManifestError("configuration profile extension name must not be empty")
            if not isinstance(config, Mapping):
                raise PluginManifestError(f"configuration for {extension_name} must be a mapping")
            normalized[extension_name] = MappingProxyType(dict(config))
        object.__setattr__(self, "values", MappingProxyType(normalized))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "name": self.name,
            "values": {name: dict(config) for name, config in sorted(self.values.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PluginConfigurationProfile":
        unknown = set(payload) - {"schema_version", "name", "values"}
        if unknown:
            raise PluginManifestError(f"unknown configuration profile fields: {', '.join(sorted(unknown))}")
        if payload.get("schema_version", 1) != 1:
            raise PluginManifestError("unsupported configuration profile schema version")
        return cls(str(payload.get("name", "")), payload.get("values", {}))

    @classmethod
    def from_json(cls, text: str) -> "PluginConfigurationProfile":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"invalid configuration profile JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise PluginManifestError("configuration profile must be a JSON object")
        return cls.from_dict(payload)


@dataclass(frozen=True, slots=True)
class PluginReconfigurationEvent:
    sequence: int
    phase: str
    plugin_id: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class PluginReconfigurationReport:
    plugin_id: str
    profile: str
    status: ReconfigurationStatus
    changed_extensions: tuple[str, ...]
    restarted_plugins: tuple[str, ...]
    error: str = ""
    events: tuple[PluginReconfigurationEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plugin_id": self.plugin_id,
            "profile": self.profile,
            "status": self.status.value,
            "changed_extensions": list(self.changed_extensions),
            "restarted_plugins": list(self.restarted_plugins),
            "error": self.error,
            "events": [
                {"sequence": event.sequence, "phase": event.phase, "plugin_id": event.plugin_id, "message": event.message}
                for event in self.events
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class PluginConfigurationManager:
    def __init__(self, runtime: PluginRuntime) -> None:
        self.runtime = runtime
        self.registry = runtime.registry
        self._events: list[PluginReconfigurationEvent] = []
        self._sequence = 0

    def apply(self, plugin_id: str, profile: PluginConfigurationProfile) -> PluginReconfigurationReport:
        self._events = []
        self._sequence = 0
        old = self.registry.get(plugin_id)
        new, changed = self._configured_manifest(old, profile)
        if not changed:
            return PluginReconfigurationReport(plugin_id, profile.name, ReconfigurationStatus.NO_CHANGE, (), (), events=())
        loaded_before = {item.plugin_id for item in self.runtime.extensions()}
        dependents = self._loaded_dependents(plugin_id)
        restart_order = tuple(pid for pid in self._reverse_load_order() if pid in dependents)
        self._event("validated", plugin_id, profile.name)
        try:
            for dependent in restart_order:
                self.runtime.unload(dependent)
                self._event("unloaded-dependent", dependent)
            if plugin_id in loaded_before:
                self.runtime.unload(plugin_id)
                self._event("unloaded", plugin_id)
            self.registry.replace(new)
            self._event("manifest-replaced", plugin_id)
            if plugin_id in loaded_before:
                self.runtime.load(plugin_id)
                self._event("loaded", plugin_id)
            restarted: list[str] = []
            for dependent in reversed(restart_order):
                self.runtime.load(dependent)
                restarted.append(dependent)
                self._event("restarted-dependent", dependent)
            return PluginReconfigurationReport(
                plugin_id, profile.name, ReconfigurationStatus.APPLIED, changed,
                tuple(restarted), events=tuple(self._events),
            )
        except Exception as exc:
            self._event("reconfiguration-failed", plugin_id, str(exc))
            rollback_error = self._rollback(old, loaded_before, dependents)
            if rollback_error:
                return PluginReconfigurationReport(
                    plugin_id, profile.name, ReconfigurationStatus.FAILED, changed, (),
                    f"{exc}; rollback failed: {rollback_error}", tuple(self._events),
                )
            return PluginReconfigurationReport(
                plugin_id, profile.name, ReconfigurationStatus.ROLLED_BACK, changed,
                tuple(sorted(dependents)), str(exc), tuple(self._events),
            )

    def _configured_manifest(
        self, manifest: PluginManifest, profile: PluginConfigurationProfile
    ) -> tuple[PluginManifest, tuple[str, ...]]:
        known = {extension.name for extension in manifest.extensions}
        unknown = set(profile.values) - known
        if unknown:
            raise PluginConfigurationError(
                f"profile {profile.name} references unknown extensions: {', '.join(sorted(unknown))}"
            )
        changed: list[str] = []
        extensions: list[PluginExtension] = []
        for extension in manifest.extensions:
            override = profile.values.get(extension.name)
            if override is None:
                extensions.append(extension)
                continue
            merged = dict(extension.config)
            merged.update(dict(override))
            if merged != dict(extension.config):
                changed.append(extension.name)
            extensions.append(replace(extension, config=merged))
        return replace(manifest, extensions=tuple(extensions)), tuple(sorted(changed))

    def _loaded_dependents(self, plugin_id: str) -> tuple[str, ...]:
        loaded = {item.plugin_id for item in self.runtime.extensions()}
        result: set[str] = set()
        changed = True
        while changed:
            changed = False
            for manifest in self.registry.manifests():
                if manifest.plugin_id not in loaded or manifest.plugin_id in result:
                    continue
                if plugin_id in manifest.requires or any(dep in result for dep in manifest.requires):
                    result.add(manifest.plugin_id)
                    changed = True
        return tuple(sorted(result))

    def _reverse_load_order(self) -> tuple[str, ...]:
        return tuple(manifest.plugin_id for manifest in reversed(self.registry.resolve_order()))

    def _rollback(self, old: PluginManifest, loaded_before: set[str], dependents: tuple[str, ...]) -> str:
        try:
            loaded = {item.plugin_id for item in self.runtime.extensions()}
            for plugin_id in self._reverse_load_order():
                if plugin_id in dependents and plugin_id in loaded:
                    self.runtime.unload(plugin_id)
            loaded = {item.plugin_id for item in self.runtime.extensions()}
            if old.plugin_id in loaded:
                self.runtime.unload(old.plugin_id)
            self.registry.replace(old)
            self._event("rollback-manifest", old.plugin_id)
            if old.plugin_id in loaded_before:
                self.runtime.load(old.plugin_id)
            for manifest in self.registry.resolve_order():
                if manifest.plugin_id in dependents and manifest.plugin_id in loaded_before:
                    self.runtime.load(manifest.plugin_id)
            self._event("rollback-complete", old.plugin_id)
            return ""
        except Exception as exc:
            self._event("rollback-failed", old.plugin_id, str(exc))
            return str(exc)

    def _event(self, phase: str, plugin_id: str, message: str = "") -> None:
        self._sequence += 1
        self._events.append(PluginReconfigurationEvent(self._sequence, phase, plugin_id, message))
