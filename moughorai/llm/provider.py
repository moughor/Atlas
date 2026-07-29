from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .models import LlmChunk, LlmRequest, LlmResponse


class LlmProviderError(RuntimeError):
    """Normalized provider failure eligible for retry."""


@runtime_checkable
class LlmProvider(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, request: LlmRequest, *, timeout_seconds: float) -> LlmResponse: ...

    def stream(self, request: LlmRequest, *, timeout_seconds: float) -> Iterable[LlmChunk]: ...
