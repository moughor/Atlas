"""HTTP service for communicating with the local Ollama server."""

from collections.abc import Iterator
import json
from typing import Any

import httpx
from pydantic import ValidationError

from moughorai.config import AppConfig
from moughorai.models.ollama import (
    GenerateRequest,
    GenerateResponse,
    StreamChunk,
)


class OllamaServiceError(RuntimeError):
    """Base error raised by the Ollama service."""


class OllamaConnectionError(OllamaServiceError):
    """Raised when the Ollama server cannot be reached."""


class OllamaResponseError(OllamaServiceError):
    """Raised when Ollama returns an invalid or unsuccessful response."""


class OllamaService:
    """Synchronous client for Ollama's local HTTP API."""

    def __init__(
        self,
        config: AppConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._base_url = config.ollama.host.rstrip("/")
        self._owns_client = client is None

        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.ollama.timeout_seconds),
            headers={"Accept": "application/json"},
        )

    def __enter__(self) -> "OllamaService":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the internally managed HTTP client."""
        if self._owns_client:
            self._client.close()

    def _generation_options(
        self,
        additional_options: dict[str, object] | None = None,
    ) -> dict[str, object]:
        options: dict[str, object] = {
            "num_ctx": self._config.generation.context_tokens,
            "temperature": self._config.generation.temperature,
            "top_p": self._config.generation.top_p,
        }

        if additional_options:
            options.update(additional_options)

        return options

    def _create_request(
        self,
        prompt: str,
        *,
        system: str | None,
        stream: bool,
        options: dict[str, object] | None,
    ) -> GenerateRequest:
        return GenerateRequest(
            model=self._config.model,
            prompt=prompt,
            system=system,
            stream=stream,
            options=self._generation_options(options),
        )

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, object] | None = None,
    ) -> GenerateResponse:
        """Generate and return one complete Ollama response."""

        request = self._create_request(
            prompt,
            system=system,
            stream=False,
            options=options,
        )

        try:
            response = self._client.post(
                "/api/generate",
                json=request.to_payload(),
            )
            response.raise_for_status()
        except httpx.ConnectError as error:
            raise OllamaConnectionError(
                f"Could not connect to Ollama at {self._base_url}. "
                "Make sure Ollama is running."
            ) from error
        except httpx.TimeoutException as error:
            raise OllamaConnectionError(
                "The Ollama request timed out after "
                f"{self._config.ollama.timeout_seconds} seconds."
            ) from error
        except httpx.HTTPStatusError as error:
            detail = self._extract_error_detail(error.response)
            raise OllamaResponseError(
                f"Ollama returned HTTP {error.response.status_code}: {detail}"
            ) from error
        except httpx.HTTPError as error:
            raise OllamaConnectionError(
                f"Ollama communication failed: {error}"
            ) from error

        try:
            return GenerateResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            raise OllamaResponseError(
                "Ollama returned an invalid JSON response."
            ) from error

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, object] | None = None,
    ) -> Iterator[StreamChunk]:
        """Yield validated newline-delimited streaming chunks from Ollama."""

        request = self._create_request(
            prompt,
            system=system,
            stream=True,
            options=options,
        )

        try:
            with self._client.stream(
                "POST",
                "/api/generate",
                json=request.to_payload(),
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines():
                    if not line.strip():
                        continue

                    try:
                        raw_chunk: Any = json.loads(line)
                        yield StreamChunk.model_validate(raw_chunk)
                    except (json.JSONDecodeError, ValidationError) as error:
                        raise OllamaResponseError(
                            "Ollama returned an invalid streaming chunk."
                        ) from error

        except httpx.ConnectError as error:
            raise OllamaConnectionError(
                f"Could not connect to Ollama at {self._base_url}. "
                "Make sure Ollama is running."
            ) from error
        except httpx.TimeoutException as error:
            raise OllamaConnectionError(
                "The Ollama streaming request timed out after "
                f"{self._config.ollama.timeout_seconds} seconds."
            ) from error
        except httpx.HTTPStatusError as error:
            detail = self._extract_error_detail(error.response)
            raise OllamaResponseError(
                f"Ollama returned HTTP {error.response.status_code}: {detail}"
            ) from error
        except httpx.HTTPError as error:
            raise OllamaConnectionError(
                f"Ollama streaming failed: {error}"
            ) from error

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return response.text.strip() or "Unknown Ollama error"

        if isinstance(payload, dict):
            error = payload.get("error")

            if isinstance(error, str):
                return error

        return response.text.strip() or "Unknown Ollama error"