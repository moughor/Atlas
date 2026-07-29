from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ProgressTask:
    token: str
    title: str
    total: int
    _emit: Callable[[dict[str, Any]], None]
    completed: int = 0
    ended: bool = False
    cancelled: bool = False

    def advance(self, message: str = "", *, amount: int = 1) -> None:
        if self.ended:
            raise ValueError("progress task has ended")
        if amount < 0:
            raise ValueError("progress amount must be non-negative")
        self.completed = min(self.total, self.completed + amount)
        value: dict[str, Any] = {"kind": "report"}
        if message:
            value["message"] = message
        if self.total:
            value["percentage"] = int(self.completed * 100 / self.total)
        self._emit(_notification(self.token, value))

    def cancel(self) -> None:
        if not self.ended:
            self.cancelled = True

    def end(self, message: str = "") -> None:
        if self.ended:
            return
        value: dict[str, Any] = {"kind": "end"}
        if message:
            value["message"] = message
        self._emit(_notification(self.token, value))
        self.ended = True


class WorkDoneProgressReporter:
    """Create deterministic LSP work-done progress streams."""

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit
        self._counter = 0
        self._tasks: dict[str, ProgressTask] = {}

    @property
    def active_tokens(self) -> tuple[str, ...]:
        return tuple(sorted(token for token, task in self._tasks.items() if not task.ended))

    def begin(self, title: str, *, total: int, cancellable: bool = True) -> ProgressTask:
        if not title.strip():
            raise ValueError("progress title must not be empty")
        if total < 0:
            raise ValueError("progress total must be non-negative")
        self._counter += 1
        token = f"atlas-{self._counter}"
        task = ProgressTask(token, title, total, self._emit)
        self._tasks[token] = task
        self._emit({
            "jsonrpc": "2.0",
            "method": "window/workDoneProgress/create",
            "params": {"token": token},
        })
        self._emit(_notification(token, {
            "kind": "begin",
            "title": title,
            "cancellable": cancellable,
            "percentage": 0,
        }))
        return task

    def cancel(self, token: str) -> bool:
        task = self._tasks.get(token)
        if task is None or task.ended:
            return False
        task.cancel()
        return True

    def task(self, token: str) -> ProgressTask | None:
        return self._tasks.get(token)


def _notification(token: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "$/progress",
        "params": {"token": token, "value": value},
    }
