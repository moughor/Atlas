from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ConversationRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: int
    workspace_fingerprint: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: int
    conversation_id: int
    position: int
    role: ConversationRole
    content: str
    references: Mapping[str, str]
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", MappingProxyType(dict(sorted(self.references.items()))))
