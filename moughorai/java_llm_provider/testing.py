from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from .models import LlmProviderResponse


class ScriptedLlmClient:
    """Small deterministic client for tests and offline development."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        maximum_output_tokens: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LlmProviderResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "timeout_seconds": timeout_seconds,
                "temperature": temperature,
                "maximum_output_tokens": maximum_output_tokens,
                "metadata": dict(metadata or {}),
            }
        )
        if not self._responses:
            raise RuntimeError("No scripted response remains")
        value = self._responses.popleft()
        if isinstance(value, Exception):
            raise value
        return LlmProviderResponse(
            text=value,
            provider_name="scripted",
            model=model,
            finish_reason="stop",
        )
