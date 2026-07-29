from __future__ import annotations

from threading import RLock

from .provider import LlmProvider


class LlmProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LlmProvider] = {}
        self._lock = RLock()

    def register(self, provider: LlmProvider, *, replace: bool = False) -> None:
        if not isinstance(provider, LlmProvider):
            raise TypeError("provider must implement LlmProvider")
        name = provider.name.strip()
        if not name:
            raise ValueError("provider name must not be empty")
        with self._lock:
            if name in self._providers and not replace:
                raise ValueError(f"LLM provider already registered: {name}")
            self._providers[name] = provider

    def get(self, name: str) -> LlmProvider:
        with self._lock:
            try:
                return self._providers[name]
            except KeyError as exc:
                raise KeyError(f"unknown LLM provider: {name}") from exc

    def remove(self, name: str) -> LlmProvider:
        with self._lock:
            try:
                return self._providers.pop(name)
            except KeyError as exc:
                raise KeyError(f"unknown LLM provider: {name}") from exc

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._providers))
