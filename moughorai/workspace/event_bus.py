from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from threading import RLock
from typing import Any
from uuid import uuid4

from ..structured_logging import current_correlation_id, get_logger, log_event


_logger = get_logger("workspace.events")


class WorkspaceEventKind(str, Enum):
    FILES_CHANGED = "files_changed"
    PLAN_CREATED = "plan_created"
    ANALYSIS_STARTED = "analysis_started"
    PROJECT_STARTED = "project_started"
    PROJECT_COMPLETED = "project_completed"
    PROJECT_FAILED = "project_failed"
    PROJECT_BLOCKED = "project_blocked"
    ANALYSIS_COMPLETED = "analysis_completed"
    CACHE_INVALIDATED = "cache_invalidated"
    STATE_SAVED = "state_saved"
    STATE_RESTORED = "state_restored"
    CONFIGURATION_RESOLVED = "configuration_resolved"
    RECOVERY_STARTED = "recovery_started"
    RECOVERY_JOURNAL_SAVED = "recovery_journal_saved"
    RECOVERY_RESUMED = "recovery_resumed"
    RECOVERY_INVALIDATED = "recovery_invalidated"
    RECOVERY_COMPLETED = "recovery_completed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class WorkspaceEvent:
    kind: WorkspaceEventKind
    payload: Mapping[str, Any] = field(default_factory=dict)
    project: str | None = None
    source: str = "workspace"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "project": self.project,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class EventDeliveryFailure:
    subscription_id: str
    error: str


@dataclass(frozen=True, slots=True)
class EventDeliveryReport:
    event: WorkspaceEvent
    delivered: tuple[str, ...]
    failures: tuple[EventDeliveryFailure, ...]

    @property
    def succeeded(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            "delivered": list(self.delivered),
            "failures": [
                {"subscription_id": item.subscription_id, "error": item.error}
                for item in self.failures
            ],
        }


@dataclass(slots=True)
class _Subscription:
    subscription_id: str
    callback: Callable[[WorkspaceEvent], Any]
    kinds: frozenset[WorkspaceEventKind] | None
    project: str | None
    predicate: Callable[[WorkspaceEvent], bool] | None
    priority: int
    once: bool
    order: int

    def matches(self, event: WorkspaceEvent) -> bool:
        if self.kinds is not None and event.kind not in self.kinds:
            return False
        if self.project is not None and event.project != self.project:
            return False
        return self.predicate(event) if self.predicate is not None else True


class WorkspaceEventBus:
    """Thread-safe synchronous event bus with deterministic delivery order."""

    def __init__(self, *, history_limit: int = 100, correlation_id: str | None = None) -> None:
        if history_limit < 0:
            raise ValueError("history_limit must be non-negative")
        self._subscriptions: dict[str, _Subscription] = {}
        self._history: deque[WorkspaceEvent] = deque(maxlen=history_limit)
        self._lock = RLock()
        self._counter = 0
        self._correlation_id = correlation_id or current_correlation_id()

    @property
    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    @property
    def history(self) -> tuple[WorkspaceEvent, ...]:
        with self._lock:
            return tuple(self._history)

    def subscribe(
        self,
        callback: Callable[[WorkspaceEvent], Any],
        *,
        kinds: WorkspaceEventKind | Iterable[WorkspaceEventKind] | None = None,
        project: str | None = None,
        predicate: Callable[[WorkspaceEvent], bool] | None = None,
        priority: int = 0,
        once: bool = False,
        subscription_id: str | None = None,
    ) -> str:
        if not callable(callback):
            raise TypeError("callback must be callable")
        normalized: frozenset[WorkspaceEventKind] | None
        if kinds is None:
            normalized = None
        elif isinstance(kinds, WorkspaceEventKind):
            normalized = frozenset((kinds,))
        else:
            normalized = frozenset(WorkspaceEventKind(item) for item in kinds)
        identifier = subscription_id or uuid4().hex
        with self._lock:
            if identifier in self._subscriptions:
                raise ValueError(f"duplicate subscription id: {identifier}")
            self._counter += 1
            self._subscriptions[identifier] = _Subscription(
                identifier, callback, normalized, project, predicate, int(priority), bool(once), self._counter
            )
        return identifier

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def clear(self) -> int:
        with self._lock:
            count = len(self._subscriptions)
            self._subscriptions.clear()
            return count

    def clear_history(self) -> int:
        with self._lock:
            count = len(self._history)
            self._history.clear()
            return count

    def publish(self, event: WorkspaceEvent, *, raise_errors: bool = False) -> EventDeliveryReport:
        if not isinstance(event, WorkspaceEvent):
            raise TypeError("event must be a WorkspaceEvent")
        with self._lock:
            self._history.append(event)
            subscriptions = sorted(self._subscriptions.values(), key=lambda item: (-item.priority, item.order))
        level = logging.ERROR if event.kind is WorkspaceEventKind.ERROR else logging.INFO
        log_event(
            _logger,
            level,
            f"workspace.{event.kind.value}",
            correlation_id=self._correlation_id,
            event_id=event.event_id,
            project=event.project,
            source=event.source,
            payload=event.payload,
        )
        delivered: list[str] = []
        failures: list[EventDeliveryFailure] = []
        remove: list[str] = []
        for subscription in subscriptions:
            try:
                matches = subscription.matches(event)
            except Exception as exc:
                failures.append(EventDeliveryFailure(subscription.subscription_id, f"{type(exc).__name__}: {exc}"))
                if raise_errors:
                    raise
                continue
            if not matches:
                continue
            try:
                subscription.callback(event)
            except Exception as exc:
                failures.append(EventDeliveryFailure(subscription.subscription_id, f"{type(exc).__name__}: {exc}"))
                if raise_errors:
                    raise
            else:
                delivered.append(subscription.subscription_id)
                if subscription.once:
                    remove.append(subscription.subscription_id)
        for identifier in remove:
            self.unsubscribe(identifier)
        return EventDeliveryReport(event, tuple(delivered), tuple(failures))

    def emit(
        self,
        kind: WorkspaceEventKind,
        *,
        payload: Mapping[str, Any] | None = None,
        project: str | None = None,
        source: str = "workspace",
        raise_errors: bool = False,
    ) -> EventDeliveryReport:
        return self.publish(
            WorkspaceEvent(WorkspaceEventKind(kind), dict(payload or {}), project=project, source=source),
            raise_errors=raise_errors,
        )

    def publish_many(self, events: Iterable[WorkspaceEvent], *, raise_errors: bool = False) -> tuple[EventDeliveryReport, ...]:
        return tuple(self.publish(event, raise_errors=raise_errors) for event in events)
