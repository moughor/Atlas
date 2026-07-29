from __future__ import annotations

import pytest

from moughorai.llm import (
    LlmChunk,
    LlmClient,
    LlmMessage,
    LlmProviderError,
    LlmProviderRegistry,
    LlmRequest,
    RetryPolicy,
    ScriptedLlmProvider,
)


def request() -> LlmRequest:
    return LlmRequest((LlmMessage("user", "Explain Atlas."),), model="qwen")


def test_registry_is_sorted_and_conflict_safe() -> None:
    registry = LlmProviderRegistry()
    registry.register(ScriptedLlmProvider((), name="z"))
    registry.register(ScriptedLlmProvider((), name="a"))
    assert registry.names() == ("a", "z")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ScriptedLlmProvider((), name="a"))


def test_complete_retries_timeout_and_propagates_timeout() -> None:
    provider = ScriptedLlmProvider((TimeoutError("slow"), "done"))
    client = LlmClient(provider, RetryPolicy(maximum_attempts=2, timeout_seconds=4.5))
    assert client.complete(request()).text == "done"
    assert [call[1] for call in provider.calls] == [4.5, 4.5]


def test_complete_reports_exhaustion() -> None:
    provider = ScriptedLlmProvider((LlmProviderError("offline"),))
    with pytest.raises(LlmProviderError, match="after 1 attempt"):
        LlmClient(provider, RetryPolicy(maximum_attempts=1)).complete(request())


def test_stream_retries_before_first_chunk() -> None:
    chunks = (LlmChunk("A", 0, "scripted", "qwen"), LlmChunk("B", 1, "scripted", "qwen", "stop"))
    provider = ScriptedLlmProvider((TimeoutError("slow"), chunks))
    assert tuple(LlmClient(provider, RetryPolicy(maximum_attempts=2)).stream(request())) == chunks


def test_stream_does_not_retry_after_emitting_output() -> None:
    def broken():
        yield LlmChunk("partial", 0, "scripted", "qwen")
        raise TimeoutError("late")

    provider = ScriptedLlmProvider((broken(), "must-not-run"))
    with pytest.raises(LlmProviderError, match="after output"):
        tuple(LlmClient(provider).stream(request()))
    assert len(provider.calls) == 1
