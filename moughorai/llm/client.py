from __future__ import annotations

from collections.abc import Callable, Iterator
from time import sleep

from .models import LlmChunk, LlmRequest, LlmResponse, RetryPolicy
from .provider import LlmProvider, LlmProviderError


class LlmClient:
    def __init__(
        self,
        provider: LlmProvider,
        policy: RetryPolicy | None = None,
        *,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.provider = provider
        self.policy = policy or RetryPolicy()
        self._sleeper = sleeper

    def complete(self, request: LlmRequest) -> LlmResponse:
        errors: list[str] = []
        for attempt in range(1, self.policy.maximum_attempts + 1):
            try:
                return self.provider.complete(request, timeout_seconds=self.policy.timeout_seconds)
            except (LlmProviderError, TimeoutError) as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                if attempt < self.policy.maximum_attempts and self.policy.backoff_seconds:
                    self._sleeper(self.policy.backoff_seconds)
        raise LlmProviderError(
            f"LLM provider {self.provider.name} failed after {len(errors)} attempt(s): {errors[-1]}"
        )

    def stream(self, request: LlmRequest) -> Iterator[LlmChunk]:
        errors: list[str] = []
        for attempt in range(1, self.policy.maximum_attempts + 1):
            emitted = False
            try:
                for chunk in self.provider.stream(request, timeout_seconds=self.policy.timeout_seconds):
                    emitted = True
                    yield chunk
                return
            except (LlmProviderError, TimeoutError) as exc:
                if emitted:
                    raise LlmProviderError("LLM stream failed after output was emitted") from exc
                errors.append(f"{type(exc).__name__}: {exc}")
                if attempt < self.policy.maximum_attempts and self.policy.backoff_seconds:
                    self._sleeper(self.policy.backoff_seconds)
        raise LlmProviderError(
            f"LLM provider {self.provider.name} failed after {len(errors)} attempt(s): {errors[-1]}"
        )
