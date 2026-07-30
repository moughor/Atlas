import json

import httpx
import pytest

from moughorai.llm import (
    LlmMessage,
    LlmProviderError,
    LlmRequest,
    OllamaProvider,
    OllamaProviderConfig,
)
from moughorai.workspace.configuration import (
    ConfigurationLayer,
    WorkspaceConfigurationResolver,
)


def _request() -> LlmRequest:
    return LlmRequest(
        (LlmMessage("system", "Ground facts."), LlmMessage("user", "Explain.")),
        temperature=0.1,
        maximum_output_tokens=32,
    )


def test_configuration_integrates_with_pr71_layers() -> None:
    resolved = WorkspaceConfigurationResolver().resolve(
        ConfigurationLayer(
            "workspace",
            {
                "llm": {
                    "provider": "ollama",
                    "endpoint": "http://localhost:11434/",
                    "model": "my-coder:latest",
                }
            },
        )
    )
    config = OllamaProviderConfig.from_configuration(resolved)
    assert config.endpoint == "http://localhost:11434"
    assert config.model == "my-coder:latest"


def test_complete_uses_chat_api_and_normalizes_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["model"] == "my-coder:latest"
        assert payload["stream"] is False
        assert payload["options"] == {"temperature": 0.1, "num_predict": 32}
        return httpx.Response(
            200,
            json={
                "model": "my-coder:latest",
                "message": {"role": "assistant", "content": "grounded"},
                "done": True,
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    response = OllamaProvider(client=client).complete(_request(), timeout_seconds=2)
    assert (response.text, response.provider, response.input_tokens, response.output_tokens) == (
        "grounded",
        "ollama",
        7,
        3,
    )


def test_stream_yields_ordered_chunks() -> None:
    lines = [
        {"model": "my-coder:latest", "message": {"content": "one"}, "done": False},
        {
            "model": "my-coder:latest",
            "message": {"content": " two"},
            "done": True,
            "done_reason": "stop",
        },
    ]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content="\n".join(json.dumps(line) for line in lines),
        )
    )
    client = httpx.Client(transport=transport, base_url="http://test")
    chunks = tuple(OllamaProvider(client=client).stream(_request(), timeout_seconds=2))
    assert [chunk.text for chunk in chunks] == ["one", " two"]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert chunks[-1].finish_reason == "stop"


def test_http_and_invalid_response_errors_are_normalized() -> None:
    error_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": "not ready"})
        ),
        base_url="http://test",
    )
    with pytest.raises(LlmProviderError, match="HTTP 503: not ready"):
        OllamaProvider(client=error_client).complete(_request(), timeout_seconds=2)

    invalid_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        base_url="http://test",
    )
    with pytest.raises(LlmProviderError, match="invalid chat response"):
        OllamaProvider(client=invalid_client).complete(_request(), timeout_seconds=2)


@pytest.mark.parametrize("endpoint", ["localhost:11434", "file:///tmp/ollama"])
def test_invalid_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTP"):
        OllamaProviderConfig(endpoint=endpoint)
