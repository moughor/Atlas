from __future__ import annotations

from collections.abc import Iterable

from .models import LlmChunk, LlmRequest, LlmResponse


class ScriptedLlmProvider:
    def __init__(self, outcomes: Iterable[object], *, name: str = "scripted", model: str = "test") -> None:
        self._outcomes = list(outcomes)
        self.name = name
        self.model = model
        self.calls: list[tuple[LlmRequest, float, bool]] = []

    def _next(self) -> object:
        if not self._outcomes:
            raise RuntimeError("scripted provider has no outcome")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def complete(self, request: LlmRequest, *, timeout_seconds: float) -> LlmResponse:
        self.calls.append((request, timeout_seconds, False))
        outcome = self._next()
        return outcome if isinstance(outcome, LlmResponse) else LlmResponse(str(outcome), self.name, request.model or self.model)

    def stream(self, request: LlmRequest, *, timeout_seconds: float) -> Iterable[LlmChunk]:
        self.calls.append((request, timeout_seconds, True))
        outcome = self._next()
        if isinstance(outcome, str):
            return (LlmChunk(outcome, 0, self.name, request.model or self.model, "stop"),)
        return outcome  # type: ignore[return-value]
