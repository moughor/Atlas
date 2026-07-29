from __future__ import annotations

from dataclasses import asdict, dataclass
import json


ATLAS_AI_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class AtlasAiCapabilities:
    semantic_snapshot: bool = True
    ai_cli: bool = True
    conversation_memory: bool = True
    explain: bool = True
    review: bool = True
    ask: bool = True
    patch: bool = True
    git_context: bool = True
    ide_protocol: bool = True
    providers: tuple[str, ...] = ("ollama",)

    @property
    def ready(self) -> bool:
        values = asdict(self)
        return all(value for key, value in values.items() if key != "providers") and bool(self.providers)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def atlas_ai_capabilities() -> AtlasAiCapabilities:
    return AtlasAiCapabilities()
