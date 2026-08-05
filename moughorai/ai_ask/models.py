from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

from moughorai.prompts import TokenEstimator
from moughorai.platform.safety import contains_absolute_path
from moughorai.semantic_evidence import EvidenceIndex

from .safety import contains_unsafe_chat_content


CHAT_PRODUCER_VERSION = "atlas-pr139/1"
CHAT_SCHEMA_VERSION = 1
CHAT_SELECTION_POLICY = "engineering-chat-context.v1"
_EVIDENCE_ID = re.compile(r"evidence:[0-9a-f]{64}")


class _FrozenDict(dict[str, Any]):
    """JSON-serializable mapping that rejects mutation at every nesting level."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("chat context content is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class ChatIntent(str, Enum):
    REPOSITORY = "repository"
    EXPLAIN = "explain"
    SEARCH = "search"
    IMPACT = "impact"
    REFACTORING = "refactoring"
    SECURITY = "security"
    UNKNOWN = "unknown"


class ChatCapabilityState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    AMBIGUOUS = "ambiguous"
    NOT_REQUESTED = "not_requested"
    UNSUPPORTED = "unsupported"


def _strings(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be a sequence")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{label} must contain strings")
    return tuple(sorted({item.strip() for item in value if item.strip()}))


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _json_mapping(value: Mapping[str, object], label: str) -> Mapping[str, Any]:
    try:
        encoded = json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must contain deterministic JSON data") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{label} must be an object")
    if contains_absolute_path(decoded):
        raise ValueError(f"{label} must be source-free")
    if contains_unsafe_chat_content(decoded):
        raise ValueError(f"{label} contains unsafe source or private data")
    return _freeze_json(decoded)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({
            str(key): _freeze_json(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        })
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _thaw_json(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, order=True, slots=True)
class ChatCapability:
    name: str
    state: ChatCapabilityState
    producer_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("chat capability name must not be empty")
        state = self.state if isinstance(self.state, ChatCapabilityState) else ChatCapabilityState(self.state)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "producer_ids", _strings(self.producer_ids, "capability producers"))
        object.__setattr__(self, "limitations", _strings(self.limitations, "capability limitations"))
        if contains_absolute_path(self.to_dict()) or contains_unsafe_chat_content(
            self.to_dict()
        ):
            raise ValueError("chat capabilities must be source-free")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "producer_ids": list(self.producer_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChatCapability:
        return cls(
            str(value.get("name", "")),
            ChatCapabilityState(str(value.get("state", "unavailable"))),
            _strings(value.get("producer_ids"), "capability producers"),
            _strings(value.get("limitations"), "capability limitations"),
        )


@dataclass(frozen=True, slots=True)
class ChatContextSection:
    section_id: str
    capability: str
    heading: str
    content: Mapping[str, object]
    evidence_ids: tuple[str, ...] = ()
    priority: int = 100
    total_item_count: int = 0
    included_item_count: int = 0
    omitted_item_count: int = 0

    def __post_init__(self) -> None:
        for name in ("section_id", "capability", "heading"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"chat context section {name} must not be empty")
            object.__setattr__(self, name, normalized)
        priority = _integer(self.priority, "chat section priority")
        if priority < 0:
            raise ValueError("chat section priority must not be negative")
        object.__setattr__(self, "content", _json_mapping(self.content, "chat section content"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "chat section evidence"))
        for name in ("total_item_count", "included_item_count", "omitted_item_count"):
            count = _integer(getattr(self, name), f"chat section {name}")
            if count < 0:
                raise ValueError(f"chat section {name} must not be negative")
        if self.total_item_count != self.included_item_count + self.omitted_item_count:
            raise ValueError("chat section item counts are inconsistent")

    @property
    def truncated(self) -> bool:
        return self.omitted_item_count > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "capability": self.capability,
            "heading": self.heading,
            "content": _thaw_json(self.content),
            "evidence_ids": list(self.evidence_ids),
            "priority": self.priority,
            "total_item_count": self.total_item_count,
            "included_item_count": self.included_item_count,
            "omitted_item_count": self.omitted_item_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChatContextSection:
        content = value.get("content")
        if not isinstance(content, Mapping):
            raise TypeError("chat section content must be an object")
        return cls(
            str(value.get("section_id", "")),
            str(value.get("capability", "")),
            str(value.get("heading", "")),
            content,
            _strings(value.get("evidence_ids"), "chat section evidence"),
            _integer(value.get("priority", 100), "chat section priority"),
            _integer(value.get("total_item_count", 0), "chat section total count"),
            _integer(value.get("included_item_count", 0), "chat section included count"),
            _integer(value.get("omitted_item_count", 0), "chat section omitted count"),
        )


@dataclass(frozen=True, slots=True)
class ChatSelection:
    token_budget: int
    estimated_tokens: int
    included_section_ids: tuple[str, ...] = ()
    omitted_section_count: int = 0
    truncated: bool = False
    policy: str = CHAT_SELECTION_POLICY

    def __post_init__(self) -> None:
        budget = _integer(self.token_budget, "chat token budget")
        estimated = _integer(self.estimated_tokens, "chat estimated tokens")
        omitted = _integer(self.omitted_section_count, "chat omitted section count")
        if budget < 1 or estimated < 0 or omitted < 0:
            raise ValueError("chat selection counts must not be negative and budget must be positive")
        if estimated > budget:
            raise ValueError("chat context exceeds its token budget")
        truncated = _boolean(self.truncated, "chat truncation")
        if omitted and not truncated:
            raise ValueError("chat selection omissions require truncation")
        policy = self.policy.strip()
        if not policy:
            raise ValueError("chat selection policy must not be empty")
        object.__setattr__(self, "included_section_ids", _strings(self.included_section_ids, "included chat sections"))
        object.__setattr__(self, "policy", policy)

    def to_dict(self) -> dict[str, object]:
        return {
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "included_section_ids": list(self.included_section_ids),
            "omitted_section_count": self.omitted_section_count,
            "truncated": self.truncated,
            "policy": self.policy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChatSelection:
        return cls(
            _integer(value.get("token_budget", 0), "chat token budget"),
            _integer(value.get("estimated_tokens", 0), "chat estimated tokens"),
            _strings(value.get("included_section_ids"), "included chat sections"),
            _integer(value.get("omitted_section_count", 0), "chat omitted section count"),
            _boolean(value.get("truncated", False), "chat truncation"),
            str(value.get("policy", CHAT_SELECTION_POLICY)),
        )


@dataclass(frozen=True, slots=True)
class CitationValidation:
    cited_evidence_ids: tuple[str, ...] = ()
    accepted_evidence_ids: tuple[str, ...] = ()
    unknown_citation_ids: tuple[str, ...] = ()
    missing_required: bool = False

    def __post_init__(self) -> None:
        cited = _strings(self.cited_evidence_ids, "cited evidence")
        accepted = _strings(self.accepted_evidence_ids, "accepted evidence")
        unknown = _strings(self.unknown_citation_ids, "unknown citations")
        if any(
            _EVIDENCE_ID.fullmatch(item) is None
            for item in (*cited, *accepted, *unknown)
        ):
            raise ValueError("citation validation contains an invalid evidence ID")
        if not set(accepted).issubset(cited) or not set(unknown).issubset(cited):
            raise ValueError("citation validation references citations that were not supplied")
        if set(accepted).intersection(unknown) or set(accepted).union(unknown) != set(cited):
            raise ValueError("citation validation partition is inconsistent")
        object.__setattr__(self, "cited_evidence_ids", cited)
        object.__setattr__(self, "accepted_evidence_ids", accepted)
        object.__setattr__(self, "unknown_citation_ids", unknown)
        object.__setattr__(self, "missing_required", _boolean(self.missing_required, "missing citation flag"))

    @property
    def valid(self) -> bool:
        return not self.unknown_citation_ids and not self.missing_required

    def to_dict(self) -> dict[str, object]:
        return {
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "accepted_evidence_ids": list(self.accepted_evidence_ids),
            "unknown_citation_ids": list(self.unknown_citation_ids),
            "missing_required": self.missing_required,
            "valid": self.valid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CitationValidation:
        result = cls(
            _strings(value.get("cited_evidence_ids"), "cited evidence"),
            _strings(value.get("accepted_evidence_ids"), "accepted evidence"),
            _strings(value.get("unknown_citation_ids"), "unknown citations"),
            _boolean(value.get("missing_required", False), "missing citation flag"),
        )
        raw_valid = value.get("valid")
        if raw_valid is not None and _boolean(raw_valid, "citation validity") != result.valid:
            raise ValueError("serialized citation validity is inconsistent")
        return result


@dataclass(frozen=True, slots=True, eq=False)
class ChatContext:
    snapshot_id: str
    workspace_fingerprint: str
    intent: ChatIntent
    question: str
    subject_ids: tuple[str, ...]
    capabilities: tuple[ChatCapability, ...]
    sections: tuple[ChatContextSection, ...]
    evidence_index: EvidenceIndex
    selection: ChatSelection
    limitations: tuple[str, ...] = ()
    stale_history_count: int = 0
    history_message_count: int = 0
    context_digest: str = ""
    producer_version: str = CHAT_PRODUCER_VERSION
    schema_version: int = CHAT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "workspace_fingerprint", "question", "producer_version"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"chat context {name} must not be empty")
            object.__setattr__(self, name, normalized)
        intent = self.intent if isinstance(self.intent, ChatIntent) else ChatIntent(self.intent)
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "subject_ids", _strings(self.subject_ids, "chat subject IDs"))
        capabilities = tuple(sorted(self.capabilities, key=lambda item: item.name))
        if any(not isinstance(item, ChatCapability) for item in capabilities):
            raise TypeError("chat capabilities must use ChatCapability")
        if len({item.name for item in capabilities}) != len(capabilities):
            raise ValueError("chat capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        sections = tuple(sorted(self.sections, key=lambda item: (item.priority, item.section_id)))
        if any(not isinstance(item, ChatContextSection) for item in sections):
            raise TypeError("chat sections must use ChatContextSection")
        if len({item.section_id for item in sections}) != len(sections):
            raise ValueError("chat section IDs must be unique")
        if tuple(sorted(item.section_id for item in sections)) != self.selection.included_section_ids:
            raise ValueError("chat selection does not identify the retained sections")
        object.__setattr__(self, "sections", sections)
        if not isinstance(self.evidence_index, EvidenceIndex):
            raise TypeError("chat context requires an EvidenceIndex")
        evidence = self.evidence_index.freeze()
        available = {item.evidence_id for item in evidence.records}
        cited = {evidence_id for section in sections for evidence_id in section.evidence_ids}
        if cited != available:
            raise ValueError("chat context evidence index is not an exact section closure")
        object.__setattr__(self, "evidence_index", evidence)
        object.__setattr__(self, "limitations", _strings(self.limitations, "chat limitations"))
        for name in ("stale_history_count", "history_message_count"):
            count = _integer(getattr(self, name), f"chat {name}")
            if count < 0:
                raise ValueError(f"chat {name} must not be negative")
        if self.stale_history_count > self.history_message_count:
            raise ValueError("stale history count exceeds selected history")
        if self.producer_version != CHAT_PRODUCER_VERSION or self.schema_version != CHAT_SCHEMA_VERSION:
            raise ValueError("unsupported chat context producer or schema")
        if contains_absolute_path(self._payload(include_digest=False)):
            raise ValueError("chat context must be source-free")
        if contains_unsafe_chat_content(self._payload(include_digest=False)):
            raise ValueError("chat context contains unsafe source or private data")
        expected = self._digest()
        if self.context_digest and self.context_digest != expected:
            raise ValueError("chat context digest is inconsistent")
        object.__setattr__(self, "context_digest", expected)

    def _payload(self, *, include_digest: bool) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "snapshot_id": self.snapshot_id,
            "workspace_fingerprint": self.workspace_fingerprint,
            "intent": self.intent.value,
            "question": self.question,
            "subject_ids": list(self.subject_ids),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "sections": [item.to_dict() for item in self.sections],
            "evidence_index": self.evidence_index.to_dict(),
            "selection": self.selection.to_dict(),
            "limitations": list(self.limitations),
            "stale_history_count": self.stale_history_count,
            "history_message_count": self.history_message_count,
        }
        if include_digest:
            result["context_digest"] = self.context_digest
        return result

    def _digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self._payload(include_digest=False),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ChatContext) and self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(self.to_json())

    def to_dict(self) -> dict[str, object]:
        return self._payload(include_digest=True)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def estimated_tokens(self) -> int:
        return TokenEstimator().estimate(self.to_json())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChatContext:
        capabilities = value.get("capabilities")
        sections = value.get("sections")
        evidence = value.get("evidence_index")
        selection = value.get("selection")
        if not isinstance(capabilities, Sequence) or isinstance(capabilities, (str, bytes, bytearray)):
            raise TypeError("chat capabilities must be an array")
        if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes, bytearray)):
            raise TypeError("chat sections must be an array")
        if any(not isinstance(item, Mapping) for item in capabilities):
            raise TypeError("chat capabilities must contain objects")
        if any(not isinstance(item, Mapping) for item in sections):
            raise TypeError("chat sections must contain objects")
        if not isinstance(evidence, Mapping) or not isinstance(selection, Mapping):
            raise TypeError("chat evidence and selection must be objects")
        return cls(
            str(value.get("snapshot_id", "")),
            str(value.get("workspace_fingerprint", "")),
            ChatIntent(str(value.get("intent", "unknown"))),
            str(value.get("question", "")),
            _strings(value.get("subject_ids"), "chat subject IDs"),
            tuple(ChatCapability.from_dict(item) for item in capabilities),
            tuple(ChatContextSection.from_dict(item) for item in sections),
            EvidenceIndex.from_dict(evidence),
            ChatSelection.from_dict(selection),
            _strings(value.get("limitations"), "chat limitations"),
            _integer(value.get("stale_history_count", 0), "stale history count"),
            _integer(value.get("history_message_count", 0), "history message count"),
            str(value.get("context_digest", "")),
            str(value.get("producer_version", CHAT_PRODUCER_VERSION)),
            _integer(value.get("schema_version", CHAT_SCHEMA_VERSION), "chat schema version"),
        )
