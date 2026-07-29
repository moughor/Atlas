from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import Enum
import json
from types import MappingProxyType
from typing import Any

from moughorai.semantic_snapshot import AtlasSemanticSnapshot


class SupportedIde(str, Enum):
    VSCODE = "vscode"
    INTELLIJ = "intellij"
    VISUAL_STUDIO = "visual-studio"
    ECLIPSE = "eclipse"
    NEOVIM = "neovim"


class IdeAction(str, Enum):
    EXPLAIN = "explain"
    REVIEW = "review"
    ASK = "ask"
    FIX = "fix"
    NAVIGATE = "navigate"


class IdeAssistantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IdeRequest:
    ide: SupportedIde
    action: IdeAction
    snapshot_id: str
    query: str = ""
    parameters: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        values = dict(sorted((self.parameters or {}).items()))
        forbidden = {"source", "source_code", "content"}
        if forbidden.intersection(values):
            raise IdeAssistantError("IDE requests must not include raw source code")
        object.__setattr__(self, "parameters", MappingProxyType(values))


@dataclass(frozen=True, slots=True)
class IdeResponse:
    action: IdeAction
    snapshot_id: str
    payload: Mapping[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"action": self.action.value, "snapshot_id": self.snapshot_id, "payload": dict(self.payload)},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )


class IdeAssistant:
    """Editor-neutral ASS request router shared by all supported IDEs."""

    def __init__(
        self,
        snapshot_loader: Callable[[str], AtlasSemanticSnapshot | None],
        handlers: Mapping[IdeAction, Callable[[AtlasSemanticSnapshot, IdeRequest], Mapping[str, Any]]],
    ) -> None:
        self.snapshot_loader = snapshot_loader
        self.handlers = dict(handlers)

    def handle(self, request: IdeRequest) -> IdeResponse:
        snapshot = self.snapshot_loader(request.snapshot_id)
        if snapshot is None or snapshot.snapshot_id != request.snapshot_id:
            raise IdeAssistantError(f"unknown semantic snapshot: {request.snapshot_id}")
        if request.action is IdeAction.NAVIGATE:
            payload = self._navigate(snapshot, request.query)
        else:
            try:
                handler = self.handlers[request.action]
            except KeyError as exc:
                raise IdeAssistantError(f"IDE action is not configured: {request.action.value}") from exc
            payload = handler(snapshot, request)
        return IdeResponse(request.action, snapshot.snapshot_id, MappingProxyType(dict(payload)))

    @staticmethod
    def _navigate(snapshot: AtlasSemanticSnapshot, query: str) -> Mapping[str, Any]:
        target = query.strip().lower()
        if not target:
            raise IdeAssistantError("navigation query must not be empty")
        symbols = snapshot.semantic_context.get("symbols", [])
        if not isinstance(symbols, list):
            raise IdeAssistantError("snapshot symbols are invalid")
        matches = [
            symbol for symbol in symbols
            if isinstance(symbol, dict)
            and target in str(symbol.get("qualified_name", symbol.get("name", ""))).lower()
        ]
        return {"matches": sorted(matches, key=lambda item: str(item.get("qualified_name", "")))}
