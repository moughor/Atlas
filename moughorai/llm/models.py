from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _metadata(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(sorted((value or {}).items())))


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError(f"unsupported LLM message role: {self.role}")
        if not self.content:
            raise ValueError("LLM message content must not be empty")


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    model: str = ""
    temperature: float = 0.0
    maximum_output_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("LLM request must contain at least one message")
        if self.temperature < 0:
            raise ValueError("temperature must be non-negative")
        if self.maximum_output_tokens is not None and self.maximum_output_tokens < 1:
            raise ValueError("maximum_output_tokens must be positive")
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    provider: str
    model: str
    finish_reason: str = "stop"
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("LLM response provider and model are required")
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class LlmChunk:
    text: str
    index: int
    provider: str
    model: str
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("LLM chunk index must be non-negative")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    maximum_attempts: int = 3
    timeout_seconds: float = 30.0
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
