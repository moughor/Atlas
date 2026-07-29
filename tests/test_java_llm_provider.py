from dataclasses import dataclass

from moughorai.java_llm_provider import (
    JavaLlmProviderService,
    LlmProviderConfig,
    LlmRunStatus,
    ScriptedLlmClient,
)


@dataclass(frozen=True)
class Request:
    system_prompt: str = "Use only evidence."
    user_prompt: str = "What depends on UserService?"


@dataclass(frozen=True)
class Validation:
    valid: bool


class Contract:
    def validate(self, request, answer):
        return Validation(valid="[E1]" in answer and "[E99]" not in answer)


def test_accepts_first_valid_answer():
    client = ScriptedLlmClient(["UserController depends on UserService. [E1]"])
    result = JavaLlmProviderService(client, Contract()).execute(Request())

    assert result.accepted
    assert result.status is LlmRunStatus.ACCEPTED
    assert result.attempt_count == 1
    assert result.answer.endswith("[E1]")


def test_retries_after_validation_failure():
    client = ScriptedLlmClient([
        "UserController depends on UserService.",
        "UserController depends on UserService. [E1]",
    ])
    result = JavaLlmProviderService(
        client,
        Contract(),
        LlmProviderConfig(maximum_attempts=2),
    ).execute(Request())

    assert result.accepted
    assert result.attempt_count == 2
    assert "previous answer failed" in client.calls[1]["user_prompt"]


def test_rejects_unknown_evidence_after_attempts_are_exhausted():
    client = ScriptedLlmClient(["Unsupported claim. [E99]"])
    result = JavaLlmProviderService(
        client,
        Contract(),
        LlmProviderConfig(maximum_attempts=1),
    ).execute(Request())

    assert not result.accepted
    assert result.status is LlmRunStatus.EXHAUSTED
    assert result.answer is None


def test_can_disable_validation_retry():
    client = ScriptedLlmClient([
        "Missing evidence.",
        "Would have been valid. [E1]",
    ])
    result = JavaLlmProviderService(
        client,
        Contract(),
        LlmProviderConfig(
            maximum_attempts=2,
            retry_on_validation_failure=False,
        ),
    ).execute(Request())

    assert result.status is LlmRunStatus.REJECTED
    assert result.attempt_count == 1
    assert len(client.calls) == 1


def test_retries_provider_errors():
    client = ScriptedLlmClient([
        TimeoutError("provider timed out"),
        "Recovered answer. [E1]",
    ])
    result = JavaLlmProviderService(
        client,
        Contract(),
        LlmProviderConfig(maximum_attempts=2),
    ).execute(Request())

    assert result.accepted
    assert result.attempts[0].status is LlmRunStatus.PROVIDER_ERROR
    assert result.attempts[1].status is LlmRunStatus.ACCEPTED


def test_reports_provider_failure_when_every_attempt_errors():
    client = ScriptedLlmClient([
        RuntimeError("offline"),
        RuntimeError("still offline"),
    ])
    result = JavaLlmProviderService(
        client,
        Contract(),
        LlmProviderConfig(
            provider_name="local",
            model="test-model",
            maximum_attempts=2,
        ),
    ).execute(Request())

    assert result.status is LlmRunStatus.PROVIDER_ERROR
    assert result.answer is None
    assert result.provider_name == "local"
    assert result.model == "test-model"
