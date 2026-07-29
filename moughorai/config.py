"""Application configuration for MoughorAI."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = WORKSPACE_ROOT / "config" / "config.yaml"


class OllamaSettings(BaseModel):
    host: str = "http://localhost:11434"
    timeout_seconds: float = Field(default=600, gt=0)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        host = value.strip().rstrip("/")

        if not host.startswith(("http://", "https://")):
            raise ValueError(
                "Ollama host must begin with http:// or https://"
            )

        return host


class GenerationSettings(BaseModel):
    context_tokens: int = Field(default=65536, gt=0)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)


class PathSettings(BaseModel):
    brain: Path = Path("brain")
    memory: Path = Path("memory")
    projects: Path = Path("projects")
    prompts: Path = Path("prompts")
    templates: Path = Path("templates")
    logs: Path = Path("logs")


class AppConfig(BaseModel):
    model: str = "my-coder"
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    generation: GenerationSettings = Field(
        default_factory=GenerationSettings
    )
    paths: PathSettings = Field(default_factory=PathSettings)
    workspace_root: Path = Field(
        default=WORKSPACE_ROOT,
        exclude=True,
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        model = value.strip()

        if not model:
            raise ValueError("Model name cannot be empty")

        return model

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path

        return self.workspace_root / path

    @property
    def brain_path(self) -> Path:
        return self.resolve_path(self.paths.brain)

    @property
    def memory_path(self) -> Path:
        return self.resolve_path(self.paths.memory)

    @property
    def projects_path(self) -> Path:
        return self.resolve_path(self.paths.projects)

    @property
    def prompts_path(self) -> Path:
        return self.resolve_path(self.paths.prompts)

    @property
    def templates_path(self) -> Path:
        return self.resolve_path(self.paths.templates)

    @property
    def logs_path(self) -> Path:
        return self.resolve_path(self.paths.logs)


def load_config(
    config_path: Path | str | None = None,
) -> AppConfig:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Configuration path is not a file: {path}"
        )

    try:
        with path.open("r", encoding="utf-8-sig") as config_file:
            raw_config: Any = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ValueError(
            f"Invalid YAML configuration in {path}: {error}"
        ) from error

    if raw_config is None:
        raw_config = {}

    if not isinstance(raw_config, dict):
        raise ValueError(
            f"Configuration root must be a YAML object: {path}"
        )

    return AppConfig(
        **raw_config,
        workspace_root=WORKSPACE_ROOT,
    )
