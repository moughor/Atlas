"""Typed models used by the Ollama service."""

from pydantic import BaseModel, ConfigDict, Field


class GenerateRequest(BaseModel):
    """A text-generation request sent to Ollama."""

    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    system: str | None = None
    stream: bool = False
    keep_alive: str | int | None = None
    options: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-compatible payload without unset optional values."""
        return self.model_dump(exclude_none=True)


class GenerateResponse(BaseModel):
    """A complete response returned by Ollama."""

    model: str
    created_at: str | None = None
    response: str = ""
    thinking: str | None = None
    done: bool = False
    done_reason: str | None = None

    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None

    model_config = ConfigDict(extra="allow")


class StreamChunk(BaseModel):
    """One newline-delimited JSON chunk from Ollama."""

    model: str
    created_at: str | None = None
    response: str = ""
    thinking: str | None = None
    done: bool = False
    done_reason: str | None = None

    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None

    model_config = ConfigDict(extra="allow")