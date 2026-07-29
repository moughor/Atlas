from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import LlmChunk, LlmRequest, LlmResponse
from .provider import LlmProviderError


@dataclass(frozen=True, slots=True)
class OllamaProviderConfig:
    endpoint: str = "http://localhost:11434"
    model: str = "qwen3:32b"

    def __post_init__(self) -> None:
        endpoint = self.endpoint.strip().rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ollama endpoint must be an absolute HTTP(S) URL")
        if not self.model.strip():
            raise ValueError("Ollama model must not be empty")
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "model", self.model.strip())

    @classmethod
    def from_configuration(cls, configuration: object) -> OllamaProviderConfig:
        defaults = cls()
        getter = getattr(configuration, "get", None)
        if callable(getter):
            provider = getter("llm.provider", "ollama")
            endpoint = getter("llm.endpoint", defaults.endpoint)
            model = getter("llm.model", defaults.model)
        elif isinstance(configuration, Mapping):
            llm = configuration.get("llm", configuration)
            if not isinstance(llm, Mapping):
                raise ValueError("llm configuration must be an object")
            provider = llm.get("provider", "ollama")
            endpoint = llm.get("endpoint", defaults.endpoint)
            model = llm.get("model", defaults.model)
        else:
            raise TypeError("configuration must be a mapping or resolved configuration")
        if provider != "ollama":
            raise ValueError(f"expected llm.provider 'ollama', got {provider!r}")
        if not isinstance(endpoint, str) or not isinstance(model, str):
            raise ValueError("llm.endpoint and llm.model must be strings")
        return cls(endpoint, model)


class OllamaProvider:
    """PR107 provider backed by Ollama's local `/api/chat` endpoint."""

    def __init__(
        self,
        config: OllamaProviderConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or OllamaProviderConfig()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.config.endpoint,
            headers={"Accept": "application/json"},
        )

    @property
    def name(self) -> str:
        return "ollama"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, request: LlmRequest, *, timeout_seconds: float) -> LlmResponse:
        payload = self._payload(request, stream=False)
        try:
            response = self._client.post("/api/chat", json=payload, timeout=timeout_seconds)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise self._error(exc) from exc
        if not isinstance(data, Mapping) or not isinstance(data.get("message"), Mapping):
            raise LlmProviderError("Ollama returned an invalid chat response")
        text = data["message"].get("content")
        if not isinstance(text, str):
            raise LlmProviderError("Ollama response message content must be a string")
        return LlmResponse(
            text=text,
            provider=self.name,
            model=str(data.get("model") or request.model or self.config.model),
            finish_reason=str(data.get("done_reason") or "stop"),
            input_tokens=self._integer(data.get("prompt_eval_count")),
            output_tokens=self._integer(data.get("eval_count")),
        )

    def stream(self, request: LlmRequest, *, timeout_seconds: float) -> Iterator[LlmChunk]:
        try:
            with self._client.stream(
                "POST",
                "/api/chat",
                json=self._payload(request, stream=True),
                timeout=timeout_seconds,
            ) as response:
                response.raise_for_status()
                index = 0
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if not isinstance(data, Mapping) or not isinstance(data.get("message"), Mapping):
                        raise ValueError("missing message")
                    text = data["message"].get("content")
                    if not isinstance(text, str):
                        raise ValueError("message content must be a string")
                    yield LlmChunk(
                        text,
                        index,
                        self.name,
                        str(data.get("model") or request.model or self.config.model),
                        str(data.get("done_reason") or "stop") if data.get("done") else None,
                    )
                    index += 1
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise self._error(exc) from exc

    def _payload(self, request: LlmRequest, *, stream: bool) -> dict[str, Any]:
        model = request.model.strip() or self.config.model
        options: dict[str, Any] = {"temperature": request.temperature}
        if request.maximum_output_tokens is not None:
            options["num_predict"] = request.maximum_output_tokens
        return {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "stream": stream,
            "options": options,
        }

    def _error(self, exc: Exception) -> LlmProviderError:
        if isinstance(exc, httpx.HTTPStatusError):
            detail = self._detail(exc.response)
            return LlmProviderError(
                f"Ollama returned HTTP {exc.response.status_code}: {detail}"
            )
        if isinstance(exc, httpx.TimeoutException):
            return LlmProviderError("Ollama request timed out")
        if isinstance(exc, httpx.HTTPError):
            return LlmProviderError(f"Ollama communication failed: {exc}")
        return LlmProviderError(f"Ollama returned invalid JSON: {exc}")

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text.strip() or "unknown error"
        return str(data.get("error", response.text)) if isinstance(data, Mapping) else response.text

    @staticmethod
    def _integer(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None
