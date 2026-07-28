from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .models import (
    LlmAttempt,
    LlmExecutionResult,
    LlmProviderConfig,
    LlmProviderResponse,
    LlmRunStatus,
)
from .protocols import LlmClient, LlmContract, LlmRequest


class JavaLlmProviderService:
    """Execute an LLM request and accept only contract-valid answers.

    The service is provider-independent.  It intentionally delegates all
    network behaviour to ``LlmClient`` and all evidence checking to the
    Phase 18 contract implementation.
    """

    def __init__(
        self,
        client: LlmClient,
        contract: LlmContract,
        config: LlmProviderConfig | None = None,
    ) -> None:
        self._client = client
        self._contract = contract
        self._config = config or LlmProviderConfig()

    @property
    def config(self) -> LlmProviderConfig:
        return self._config

    def execute(
        self,
        request: LlmRequest,
        *,
        metadata: Mapping[str, Any] | None = None,
        config: LlmProviderConfig | None = None,
    ) -> LlmExecutionResult:
        selected = config or self._config
        attempts: list[LlmAttempt] = []

        for attempt_number in range(1, selected.maximum_attempts + 1):
            try:
                response = self._client.complete(
                    system_prompt=request.system_prompt,
                    user_prompt=self._prompt_for_attempt(
                        request.user_prompt,
                        attempts,
                    ),
                    model=selected.model,
                    timeout_seconds=selected.timeout_seconds,
                    temperature=selected.temperature,
                    maximum_output_tokens=selected.maximum_output_tokens,
                    metadata=metadata,
                )
            except Exception as exc:  # provider adapters normalize their own errors
                attempts.append(
                    LlmAttempt(
                        number=attempt_number,
                        status=LlmRunStatus.PROVIDER_ERROR,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            validation = self._contract.validate(request, response.text)
            if bool(getattr(validation, "valid", False)):
                attempts.append(
                    LlmAttempt(
                        number=attempt_number,
                        status=LlmRunStatus.ACCEPTED,
                        response=response,
                        validation=validation,
                    )
                )
                return LlmExecutionResult(
                    status=LlmRunStatus.ACCEPTED,
                    answer=response.text,
                    provider_name=response.provider_name,
                    model=response.model,
                    attempts=tuple(attempts),
                    validation=validation,
                )

            attempts.append(
                LlmAttempt(
                    number=attempt_number,
                    status=LlmRunStatus.REJECTED,
                    response=response,
                    validation=validation,
                )
            )
            if not selected.retry_on_validation_failure:
                return LlmExecutionResult(
                    status=LlmRunStatus.REJECTED,
                    answer=None,
                    provider_name=response.provider_name,
                    model=response.model,
                    attempts=tuple(attempts),
                    validation=validation,
                    error="The provider answer failed the evidence contract.",
                )

        last_response = next(
            (a.response for a in reversed(attempts) if a.response is not None),
            None,
        )
        last_validation = next(
            (a.validation for a in reversed(attempts) if a.validation is not None),
            None,
        )
        only_provider_errors = bool(attempts) and all(
            a.status is LlmRunStatus.PROVIDER_ERROR for a in attempts
        )
        final_status = (
            LlmRunStatus.PROVIDER_ERROR
            if only_provider_errors
            else LlmRunStatus.EXHAUSTED
        )
        return LlmExecutionResult(
            status=final_status,
            answer=None,
            provider_name=(
                last_response.provider_name
                if last_response is not None
                else selected.provider_name
            ),
            model=(
                last_response.model
                if last_response is not None
                else selected.model
            ),
            attempts=tuple(attempts),
            validation=last_validation,
            error=(
                "All provider attempts failed."
                if only_provider_errors
                else "No provider answer satisfied the evidence contract."
            ),
        )

    @staticmethod
    def _prompt_for_attempt(
        original_user_prompt: str,
        prior_attempts: list[LlmAttempt],
    ) -> str:
        if not prior_attempts:
            return original_user_prompt

        last = prior_attempts[-1]
        if last.status is LlmRunStatus.REJECTED:
            return (
                f"{original_user_prompt}\n\n"
                "Your previous answer failed deterministic evidence validation. "
                "Answer again using only the supplied evidence IDs, cite every "
                "substantive claim, and state 'Insufficient evidence' when the "
                "evidence does not support a claim."
            )
        return original_user_prompt
