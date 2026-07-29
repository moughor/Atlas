from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .models import LlmProviderResponse


@runtime_checkable
class LlmRequest(Protocol):
    system_prompt: str
    user_prompt: str


@runtime_checkable
class ValidationReport(Protocol):
    valid: bool


@runtime_checkable
class LlmContract(Protocol):
    def validate(self, request: LlmRequest, answer: str) -> ValidationReport:
        ...


@runtime_checkable
class LlmClient(Protocol):
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
        ...
