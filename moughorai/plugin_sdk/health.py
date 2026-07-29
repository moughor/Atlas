from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .models import LoadedExtension, PluginLoadError
from .runtime import PluginRuntime


class PluginHealthError(PluginLoadError):
    """Raised when a plugin extension is blocked by health policy."""


class PluginHealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class PluginHealthPolicy:
    failure_threshold: int = 3
    recovery_threshold: int = 2
    block_unhealthy: bool = True

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.recovery_threshold < 1:
            raise ValueError("recovery_threshold must be at least 1")


@dataclass(frozen=True, slots=True)
class PluginHealthRecord:
    plugin_id: str
    extension_name: str
    status: PluginHealthStatus = PluginHealthStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_probes: int = 0
    total_failures: int = 0
    last_message: str = ""
    quarantined_reason: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.plugin_id, self.extension_name


@dataclass(frozen=True, slots=True)
class PluginHealthEvent:
    sequence: int
    plugin_id: str
    extension_name: str
    previous_status: PluginHealthStatus
    status: PluginHealthStatus
    success: bool
    message: str = ""
    source: str = "probe"


@dataclass(frozen=True, slots=True)
class PluginHealthSnapshot:
    records: tuple[PluginHealthRecord, ...]
    events: tuple[PluginHealthEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "records": [
                {
                    "plugin_id": item.plugin_id,
                    "extension_name": item.extension_name,
                    "status": item.status.value,
                    "consecutive_failures": item.consecutive_failures,
                    "consecutive_successes": item.consecutive_successes,
                    "total_probes": item.total_probes,
                    "total_failures": item.total_failures,
                    "last_message": item.last_message,
                    "quarantined_reason": item.quarantined_reason,
                }
                for item in self.records
            ],
            "events": [
                {
                    "sequence": item.sequence,
                    "plugin_id": item.plugin_id,
                    "extension_name": item.extension_name,
                    "previous_status": item.previous_status.value,
                    "status": item.status.value,
                    "success": item.success,
                    "message": item.message,
                    "source": item.source,
                }
                for item in self.events
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class PluginHealthSupervisor:
    def __init__(
        self,
        runtime: PluginRuntime,
        *,
        policy: PluginHealthPolicy | None = None,
    ) -> None:
        self.runtime = runtime
        self.policy = policy or PluginHealthPolicy()
        self._records: dict[tuple[str, str], PluginHealthRecord] = {}
        self._events: list[PluginHealthEvent] = []
        self._sequence = 0

    def records(self) -> tuple[PluginHealthRecord, ...]:
        self._synchronize_loaded()
        return tuple(self._records[key] for key in sorted(self._records))

    def events(self) -> tuple[PluginHealthEvent, ...]:
        return tuple(self._events)

    def record(self, plugin_id: str, extension_name: str) -> PluginHealthRecord:
        self._synchronize_loaded()
        key = (plugin_id, extension_name)
        try:
            return self._records[key]
        except KeyError as exc:
            raise PluginHealthError(f"plugin extension is not loaded: {plugin_id}/{extension_name}") from exc

    def probe_all(self) -> tuple[PluginHealthRecord, ...]:
        self._synchronize_loaded()
        for loaded in self.runtime.extensions():
            self.probe(loaded.plugin_id, loaded.extension.name)
        return self.records()

    def probe(self, plugin_id: str, extension_name: str) -> PluginHealthRecord:
        loaded = self._find_loaded(plugin_id, extension_name)
        current = self.record(plugin_id, extension_name)
        if current.status is PluginHealthStatus.QUARANTINED:
            return current
        try:
            result = self._call_probe(loaded)
            success, message = self._normalize_probe_result(result)
        except Exception as exc:
            success, message = False, str(exc)
        return self._apply_observation(current, success=success, message=message, source="probe")

    def invoke(
        self,
        plugin_id: str,
        extension_name: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        loaded = self._find_loaded(plugin_id, extension_name)
        current = self.record(plugin_id, extension_name)
        if current.status is PluginHealthStatus.QUARANTINED:
            raise PluginHealthError(
                f"plugin extension is quarantined: {plugin_id}/{extension_name}: {current.quarantined_reason}"
            )
        if self.policy.block_unhealthy and current.status is PluginHealthStatus.UNHEALTHY:
            raise PluginHealthError(f"plugin extension is unhealthy: {plugin_id}/{extension_name}")
        target = getattr(loaded.instance, method, None)
        if not callable(target):
            raise PluginHealthError(f"plugin extension method is unavailable: {plugin_id}/{extension_name}.{method}")
        try:
            result = target(*args, **kwargs)
        except Exception as exc:
            self._apply_observation(current, success=False, message=str(exc), source="invoke")
            raise
        self._apply_observation(current, success=True, message="", source="invoke")
        return result

    def quarantine(self, plugin_id: str, extension_name: str, reason: str) -> PluginHealthRecord:
        if not reason.strip():
            raise ValueError("quarantine reason must not be empty")
        current = self.record(plugin_id, extension_name)
        updated = replace(
            current,
            status=PluginHealthStatus.QUARANTINED,
            quarantined_reason=reason.strip(),
            last_message=reason.strip(),
        )
        self._store_event(current, updated, success=False, message=reason.strip(), source="quarantine")
        return updated

    def release(self, plugin_id: str, extension_name: str) -> PluginHealthRecord:
        current = self.record(plugin_id, extension_name)
        updated = replace(
            current,
            status=PluginHealthStatus.UNKNOWN,
            consecutive_failures=0,
            consecutive_successes=0,
            quarantined_reason="",
            last_message="",
        )
        self._store_event(current, updated, success=True, message="", source="release")
        return updated

    def snapshot(self) -> PluginHealthSnapshot:
        return PluginHealthSnapshot(self.records(), self.events())

    def status_counts(self) -> Mapping[str, int]:
        counts = {status.value: 0 for status in PluginHealthStatus}
        for record in self.records():
            counts[record.status.value] += 1
        return MappingProxyType(counts)

    def _synchronize_loaded(self) -> None:
        loaded_keys = {(item.plugin_id, item.extension.name) for item in self.runtime.extensions()}
        for key in sorted(loaded_keys):
            if key not in self._records:
                self._records[key] = PluginHealthRecord(*key)
        for key in tuple(self._records):
            if key not in loaded_keys:
                del self._records[key]

    def _find_loaded(self, plugin_id: str, extension_name: str) -> LoadedExtension:
        for loaded in self.runtime.extensions():
            if loaded.plugin_id == plugin_id and loaded.extension.name == extension_name:
                return loaded
        raise PluginHealthError(f"plugin extension is not loaded: {plugin_id}/{extension_name}")

    def _call_probe(self, loaded: LoadedExtension) -> Any:
        probe = getattr(loaded.instance, "health_check", None)
        if not callable(probe):
            return True
        try:
            return probe(self.runtime.context)
        except TypeError:
            return probe()

    @staticmethod
    def _normalize_probe_result(result: Any) -> tuple[bool, str]:
        if isinstance(result, bool):
            return result, "" if result else "health check returned false"
        if isinstance(result, tuple) and len(result) == 2:
            return bool(result[0]), str(result[1])
        if isinstance(result, Mapping):
            return bool(result.get("healthy", False)), str(result.get("message", ""))
        if result is None:
            return True, ""
        raise PluginHealthError("health check must return bool, (bool, message), mapping, or None")

    def _apply_observation(
        self,
        current: PluginHealthRecord,
        *,
        success: bool,
        message: str,
        source: str,
    ) -> PluginHealthRecord:
        if current.status is PluginHealthStatus.QUARANTINED:
            return current
        if success:
            successes = current.consecutive_successes + 1
            if current.status in (PluginHealthStatus.UNHEALTHY, PluginHealthStatus.DEGRADED):
                status = (
                    PluginHealthStatus.HEALTHY
                    if successes >= self.policy.recovery_threshold
                    else PluginHealthStatus.DEGRADED
                )
            else:
                status = PluginHealthStatus.HEALTHY
            updated = replace(
                current,
                status=status,
                consecutive_failures=0,
                consecutive_successes=successes,
                total_probes=current.total_probes + 1,
                last_message=message,
            )
        else:
            failures = current.consecutive_failures + 1
            status = (
                PluginHealthStatus.UNHEALTHY
                if failures >= self.policy.failure_threshold
                else PluginHealthStatus.DEGRADED
            )
            updated = replace(
                current,
                status=status,
                consecutive_failures=failures,
                consecutive_successes=0,
                total_probes=current.total_probes + 1,
                total_failures=current.total_failures + 1,
                last_message=message,
            )
        self._store_event(current, updated, success=success, message=message, source=source)
        return updated

    def _store_event(
        self,
        previous: PluginHealthRecord,
        updated: PluginHealthRecord,
        *,
        success: bool,
        message: str,
        source: str,
    ) -> None:
        self._records[updated.key] = updated
        self._sequence += 1
        self._events.append(
            PluginHealthEvent(
                sequence=self._sequence,
                plugin_id=updated.plugin_id,
                extension_name=updated.extension_name,
                previous_status=previous.status,
                status=updated.status,
                success=success,
                message=message,
                source=source,
            )
        )
