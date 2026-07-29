from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class LlmRunStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROVIDER_ERROR = "provider_error"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    provider_name: str = "default"
    model: str = "default"
    timeout_seconds: float = 60.0
    maximum_attempts: int = 2
    retry_on_validation_failure: bool = True
    temperature: float = 0.0
    maximum_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be at least one")
        if self.temperature < 0:
            raise ValueError("temperature must not be negative")
        if self.maximum_output_tokens is not None and self.maximum_output_tokens < 1:
            raise ValueError("maximum_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class LlmProviderResponse:
    text: str
    provider_name: str
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")


@dataclass(frozen=True, slots=True)
class LlmAttempt:
    number: int
    status: LlmRunStatus
    response: LlmProviderResponse | None = None
    validation: Any | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LlmExecutionResult:
    status: LlmRunStatus
    answer: str | None
    provider_name: str
    model: str
    attempts: tuple[LlmAttempt, ...]
    validation: Any | None = None
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is LlmRunStatus.ACCEPTED

    @property
    def rejected(self) -> bool:
        return self.status in {LlmRunStatus.REJECTED, LlmRunStatus.EXHAUSTED}

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)
