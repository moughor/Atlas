from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from moughorai.policy_packs import SemanticVersion

from .models import LoadedExtension, PluginLoadError, PluginManifest
from .registry import PluginRegistry
from .runtime import PluginRuntime


class PluginUpgradeError(PluginLoadError):
    """Raised when a transactional plugin upgrade cannot be completed."""


class UpgradeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginUpgradePolicy:
    allow_downgrade: bool = False
    require_state_restore: bool = False
    restart_dependents: bool = True


@dataclass(frozen=True, slots=True)
class PluginUpgradeEvent:
    sequence: int
    phase: str
    plugin_id: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class PluginUpgradeReport:
    plugin_id: str
    previous_version: str
    requested_version: str
    active_version: str
    status: UpgradeStatus
    restarted_plugins: tuple[str, ...]
    restored_state: bool
    error: str = ""
    events: tuple[PluginUpgradeEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plugin_id": self.plugin_id,
            "previous_version": self.previous_version,
            "requested_version": self.requested_version,
            "active_version": self.active_version,
            "status": self.status.value,
            "restarted_plugins": list(self.restarted_plugins),
            "restored_state": self.restored_state,
            "error": self.error,
            "events": [
                {
                    "sequence": event.sequence,
                    "phase": event.phase,
                    "plugin_id": event.plugin_id,
                    "message": event.message,
                }
                for event in self.events
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class PluginUpgradeManager:
    def __init__(
        self,
        runtime: PluginRuntime,
        *,
        policy: PluginUpgradePolicy | None = None,
    ) -> None:
        self.runtime = runtime
        self.registry = runtime.registry
        self.policy = policy or PluginUpgradePolicy()
        self._events: list[PluginUpgradeEvent] = []
        self._sequence = 0

    def upgrade(self, manifest: PluginManifest) -> PluginUpgradeReport:
        self._events = []
        self._sequence = 0
        old = self.registry.get(manifest.plugin_id)
        self._validate(old, manifest)
        loaded_before = {item.plugin_id for item in self.runtime.extensions()}
        dependents = self._loaded_dependents(manifest.plugin_id)
        if dependents and not self.policy.restart_dependents:
            raise PluginUpgradeError(
                f"loaded dependents prevent upgrade of {manifest.plugin_id}: {', '.join(dependents)}"
            )
        restart_order = tuple(plugin_id for plugin_id in self._reverse_load_order() if plugin_id in dependents)
        state = self._export_state(manifest.plugin_id)
        restored = False
        self._event("validated", manifest.plugin_id, f"{old.version} -> {manifest.version}")
        try:
            for plugin_id in restart_order:
                self._drain(plugin_id)
                self.runtime.unload(plugin_id)
                self._event("unloaded-dependent", plugin_id)
            if manifest.plugin_id in loaded_before:
                self._drain(manifest.plugin_id)
                self.runtime.unload(manifest.plugin_id)
                self._event("unloaded", manifest.plugin_id)
            self.registry.replace(manifest)
            self._event("manifest-replaced", manifest.plugin_id)
            if manifest.plugin_id in loaded_before:
                self.runtime.load(manifest.plugin_id)
                self._event("loaded", manifest.plugin_id)
                restored = self._import_state(manifest.plugin_id, state)
            for plugin_id in reversed(restart_order):
                self.runtime.load(plugin_id)
                self._event("restarted-dependent", plugin_id)
            return PluginUpgradeReport(
                manifest.plugin_id, old.version, manifest.version, manifest.version,
                UpgradeStatus.SUCCEEDED, tuple(reversed(restart_order)), restored,
                events=tuple(self._events),
            )
        except Exception as exc:
            self._event("upgrade-failed", manifest.plugin_id, str(exc))
            rollback_error = self._rollback(old, loaded_before, dependents, state)
            if rollback_error:
                message = f"{exc}; rollback failed: {rollback_error}"
                return PluginUpgradeReport(
                    manifest.plugin_id, old.version, manifest.version,
                    self.registry.get(manifest.plugin_id).version,
                    UpgradeStatus.FAILED, (), False, message, tuple(self._events),
                )
            return PluginUpgradeReport(
                manifest.plugin_id, old.version, manifest.version, old.version,
                UpgradeStatus.ROLLED_BACK, tuple(sorted(dependents)), bool(state), str(exc), tuple(self._events),
            )

    def _validate(self, old: PluginManifest, new: PluginManifest) -> None:
        if old.plugin_id != new.plugin_id:
            raise PluginUpgradeError("replacement manifest must keep the same plugin id")
        old_version = SemanticVersion.parse(old.version)
        new_version = SemanticVersion.parse(new.version)
        if new_version == old_version:
            raise PluginUpgradeError(f"plugin {old.plugin_id} is already at version {old.version}")
        if new_version < old_version and not self.policy.allow_downgrade:
            raise PluginUpgradeError(f"plugin downgrade is disabled: {old.version} -> {new.version}")
        probe = PluginRegistry(api_version=str(self.registry.api_version))
        probe.register(new)

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

    def _extensions(self, plugin_id: str) -> tuple[LoadedExtension, ...]:
        return tuple(item for item in self.runtime.extensions() if item.plugin_id == plugin_id)

    def _drain(self, plugin_id: str) -> None:
        for loaded in self._extensions(plugin_id):
            hook = getattr(loaded.instance, "begin_drain", None)
            if callable(hook):
                hook(self.runtime.context)
        self._event("drained", plugin_id)

    def _export_state(self, plugin_id: str) -> Mapping[str, Any]:
        state: dict[str, Any] = {}
        for loaded in self._extensions(plugin_id):
            hook = getattr(loaded.instance, "export_state", None)
            if callable(hook):
                state[loaded.extension.name] = hook()
        if state:
            self._event("state-exported", plugin_id)
        return state

    def _import_state(self, plugin_id: str, state: Mapping[str, Any]) -> bool:
        if not state:
            if self.policy.require_state_restore:
                raise PluginUpgradeError(f"plugin {plugin_id} did not export upgrade state")
            return False
        loaded_by_name = {item.extension.name: item for item in self._extensions(plugin_id)}
        for name, value in sorted(state.items()):
            loaded = loaded_by_name.get(name)
            hook = getattr(loaded.instance, "import_state", None) if loaded else None
            if not callable(hook):
                if self.policy.require_state_restore:
                    raise PluginUpgradeError(f"extension cannot restore state: {plugin_id}/{name}")
                continue
            hook(value)
        self._event("state-restored", plugin_id)
        return True

    def _import_state_for_rollback(self, plugin_id: str, state: Mapping[str, Any]) -> bool:
        if not state:
            return False
        loaded_by_name = {item.extension.name: item for item in self._extensions(plugin_id)}
        restored = False
        for name, value in sorted(state.items()):
            loaded = loaded_by_name.get(name)
            hook = getattr(loaded.instance, "import_state", None) if loaded else None
            if callable(hook):
                hook(value)
                restored = True
        if restored:
            self._event("state-restored", plugin_id)
        return restored

    def _rollback(
        self,
        old: PluginManifest,
        loaded_before: set[str],
        dependents: tuple[str, ...],
        state: Mapping[str, Any],
    ) -> str:
        try:
            for plugin_id in self._reverse_load_order():
                if plugin_id in dependents and plugin_id in {item.plugin_id for item in self.runtime.extensions()}:
                    self.runtime.unload(plugin_id)
            if old.plugin_id in {item.plugin_id for item in self.runtime.extensions()}:
                self.runtime.unload(old.plugin_id)
            self.registry.replace(old)
            self._event("rollback-manifest", old.plugin_id)
            if old.plugin_id in loaded_before:
                self.runtime.load(old.plugin_id)
                self._import_state_for_rollback(old.plugin_id, state)
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
        self._events.append(PluginUpgradeEvent(self._sequence, phase, plugin_id, message))
