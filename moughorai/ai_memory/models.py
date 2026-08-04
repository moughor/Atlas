from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ConversationRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationTurnStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    id: int
    conversation_id: int
    position: int
    workspace_fingerprint: str
    snapshot_id: str
    intent: str
    resolved_subject_ids: tuple[str, ...]
    context_digest: str
    evidence_ids: tuple[str, ...]
    truncated: bool
    provider: str
    model: str
    status: ConversationTurnStatus
    limitations: tuple[str, ...]
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, ConversationTurnStatus)
            else ConversationTurnStatus(self.status)
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "resolved_subject_ids",
            tuple(sorted(set(self.resolved_subject_ids))),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sorted(set(self.evidence_ids))),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted(set(self.limitations))),
        )
