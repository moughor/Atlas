from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import (
    ConversationMemoryStore,
    ConversationRole,
    ConversationTurnStatus,
)
from moughorai.llm import LlmClient
from moughorai.measurement import MeasurementSession
from moughorai.prompts import PromptTemplateError, SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from .context import (
    ChatContextBudgetError,
    EngineeringChatContextBuilder,
    MAXIMUM_ANSWER_TEXT,
    requested_chat_capabilities,
    sanitize_chat_text,
    strip_chat_citations,
    validate_citations,
)
from .models import ChatCapabilityState, ChatContext, CitationValidation
from .safety import contains_unsafe_chat_content, sanitize_chat_metadata


def _serialized_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _serialized_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _serialized_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _optional_serialized_string(value: object, label: str) -> str | None:
    return None if value is None else _serialized_string(value, label)


@dataclass(frozen=True, slots=True)
class AskRequest:
    question: str
    conversation_id: int | None = None
    history_limit: int = 12
    subject: str | None = None
    kind: str | None = None
    project: str | None = None
    language: str | None = None
    capabilities: tuple[str, ...] = ()
    maximum_input_tokens: int = 7_000
    result_limit: int = 8

    def __post_init__(self) -> None:
        question = _serialized_string(self.question, "question").strip()
        if not question:
            raise ValueError("question must not be empty")
        if self.conversation_id is not None:
            conversation_id = _serialized_integer(
                self.conversation_id, "conversation ID"
            )
            if conversation_id < 1:
                raise ValueError("conversation ID must be positive")
        _serialized_integer(self.history_limit, "history limit")
        _serialized_integer(self.maximum_input_tokens, "maximum input tokens")
        _serialized_integer(self.result_limit, "result limit")
        if self.history_limit < 0:
            raise ValueError("history_limit must be non-negative")
        if self.maximum_input_tokens < 1_024:
            raise ValueError("maximum_input_tokens must be at least 1024")
        if not 1 <= self.result_limit <= 20:
            raise ValueError("result_limit must be between 1 and 20")
        object.__setattr__(self, "question", question)
        for name in ("subject", "kind", "project", "language"):
            raw = getattr(self, name)
            if raw is not None:
                raw = _serialized_string(raw, name)
            object.__setattr__(self, name, raw.strip() if raw and raw.strip() else None)
        if not isinstance(self.capabilities, Sequence) or isinstance(
            self.capabilities, (str, bytes, bytearray)
        ) or any(not isinstance(item, str) for item in self.capabilities):
            raise TypeError("chat capabilities must be an array of strings")
        object.__setattr__(
            self,
            "capabilities",
            requested_chat_capabilities("", self.capabilities),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "conversation_id": self.conversation_id,
            "history_limit": self.history_limit,
            "subject": self.subject,
            "kind": self.kind,
            "project": self.project,
            "language": self.language,
            "capabilities": list(self.capabilities),
            "maximum_input_tokens": self.maximum_input_tokens,
            "result_limit": self.result_limit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AskRequest:
        raw_capabilities = value.get("capabilities", ())
        if not isinstance(raw_capabilities, Sequence) or isinstance(
            raw_capabilities, (str, bytes, bytearray)
        ) or any(not isinstance(item, str) for item in raw_capabilities):
            raise TypeError("chat capabilities must be an array of strings")
        conversation_id = value.get("conversation_id")
        return cls(
            _serialized_string(value.get("question", ""), "question"),
            _serialized_integer(conversation_id, "conversation ID")
            if conversation_id is not None else None,
            _serialized_integer(value.get("history_limit", 12), "history limit"),
            _optional_serialized_string(value.get("subject"), "subject"),
            _optional_serialized_string(value.get("kind"), "kind"),
            _optional_serialized_string(value.get("project"), "project"),
            _optional_serialized_string(value.get("language"), "language"),
            tuple(raw_capabilities),
            _serialized_integer(
                value.get("maximum_input_tokens", 7_000),
                "maximum input tokens",
            ),
            _serialized_integer(value.get("result_limit", 8), "result limit"),
        )


@dataclass(frozen=True, slots=True)
class AskResult:
    answer: str
    snapshot_id: str
    conversation_id: int | None
    context: ChatContext | None = None
    citations: CitationValidation = CitationValidation()
    provider: str = ""
    model: str = ""
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        answer = _serialized_string(self.answer, "ask result answer").strip()
        snapshot = _serialized_string(
            self.snapshot_id, "ask result snapshot ID"
        ).strip()
        if not answer or not snapshot:
            raise ValueError("ask result answer and snapshot ID are required")
        if self.context is not None and contains_unsafe_chat_content(answer):
            raise ValueError("context-bearing ask result answer must be source-free")
        if self.conversation_id is not None:
            conversation_id = _serialized_integer(
                self.conversation_id, "ask result conversation ID"
            )
            if conversation_id < 1:
                raise ValueError("ask result conversation ID must be positive")
        if self.context is not None and self.context.snapshot_id != snapshot:
            raise ValueError("ask result context belongs to another snapshot")
        if not isinstance(self.citations, CitationValidation):
            raise TypeError("ask result citations must use CitationValidation")
        if self.citations.accepted_evidence_ids:
            if self.context is None:
                raise ValueError(
                    "accepted citations require a selected chat context"
                )
            available_evidence = {
                item.evidence_id for item in self.context.evidence_index.records
            }
            if not set(self.citations.accepted_evidence_ids).issubset(
                available_evidence
            ):
                raise ValueError(
                    "accepted citations are not present in the selected context"
                )
        available_evidence = (
            tuple(
                item.evidence_id for item in self.context.evidence_index.records
            )
            if self.context is not None else ()
        )
        legacy_without_context = (
            self.context is None and self.citations == CitationValidation()
        )
        if (
            not legacy_without_context
            and validate_citations(answer, available_evidence) != self.citations
        ):
            raise ValueError(
                "citation validation does not match the delivered answer"
            )
        object.__setattr__(self, "answer", answer)
        object.__setattr__(self, "snapshot_id", snapshot)
        object.__setattr__(
            self,
            "provider",
            sanitize_chat_metadata(
                _serialized_string(self.provider, "provider")
            ),
        )
        object.__setattr__(
            self,
            "model",
            sanitize_chat_metadata(_serialized_string(self.model, "model")),
        )
        if not isinstance(self.limitations, Sequence) or isinstance(
            self.limitations, (str, bytes, bytearray)
        ) or any(not isinstance(item, str) for item in self.limitations):
            raise TypeError("ask result limitations must be an array of strings")
        limitations = tuple(sorted({
            item.strip() for item in self.limitations if item.strip()
        }))
        if self.context is not None and contains_unsafe_chat_content(limitations):
            raise ValueError(
                "context-bearing ask result limitations must be source-free"
            )
        object.__setattr__(self, "limitations", limitations)

    @property
    def grounded(self) -> bool:
        if (
            self.context is None
            or not self.citations.valid
            or not self.citations.accepted_evidence_ids
        ):
            return False
        capabilities = {item.name: item.state for item in self.context.capabilities}
        retained_capabilities = {
            section.capability for section in self.context.sections
        }
        searchable = {
            ChatCapabilityState.AVAILABLE,
            ChatCapabilityState.PARTIAL,
            ChatCapabilityState.AMBIGUOUS,
        }
        if (
            capabilities.get("semantic_search") not in searchable
            or "semantic_search" not in retained_capabilities
        ):
            return False
        explainable = {
            ChatCapabilityState.AVAILABLE,
            ChatCapabilityState.PARTIAL,
        }
        if self.context.subject_ids:
            if (
                capabilities.get("canonical_explanation") not in explainable
                or "canonical_explanation" not in retained_capabilities
            ):
                return False
        for name in (
            "impact_prediction",
            "refactoring_advisor",
            "security_intelligence",
        ):
            state = capabilities.get(name)
            if state is None or state is ChatCapabilityState.NOT_REQUESTED:
                continue
            if state not in explainable:
                return False
            selected_evidence = {
                evidence_id
                for section in self.context.sections
                if section.capability == name
                for evidence_id in section.evidence_ids
            }
            if not selected_evidence.intersection(
                self.citations.accepted_evidence_ids
            ):
                return False
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer,
            "snapshot_id": self.snapshot_id,
            "conversation_id": self.conversation_id,
            "context": self.context.to_dict() if self.context is not None else None,
            "citations": self.citations.to_dict(),
            "provider": self.provider,
            "model": self.model,
            "limitations": list(self.limitations),
            "grounded": self.grounded,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AskResult:
        raw_context = value.get("context")
        raw_citations = value.get("citations", {})
        if raw_context is not None and not isinstance(raw_context, Mapping):
            raise TypeError("ask result context must be an object or null")
        if not isinstance(raw_citations, Mapping):
            raise TypeError("ask result citations must be an object")
        raw_limitations = value.get("limitations", ())
        if not isinstance(raw_limitations, Sequence) or isinstance(
            raw_limitations, (str, bytes, bytearray)
        ) or any(not isinstance(item, str) for item in raw_limitations):
            raise TypeError("ask result limitations must be an array of strings")
        conversation_id = value.get("conversation_id")
        result = cls(
            _serialized_string(value.get("answer", ""), "ask result answer"),
            _serialized_string(
                value.get("snapshot_id", ""), "ask result snapshot ID"
            ),
            _serialized_integer(conversation_id, "ask result conversation ID")
            if conversation_id is not None else None,
            ChatContext.from_dict(raw_context) if isinstance(raw_context, Mapping) else None,
            CitationValidation.from_dict(raw_citations),
            _serialized_string(value.get("provider", ""), "provider"),
            _serialized_string(value.get("model", ""), "model"),
            tuple(raw_limitations),
        )
        raw_grounded = value.get("grounded")
        if raw_grounded is not None and _serialized_boolean(
            raw_grounded, "ask result grounded flag"
        ) != result.grounded:
            raise ValueError("serialized ask result grounding is inconsistent")
        return result


class AskEngine:
    """The single Atlas ask/chat engine, grounded in persisted semantic facts."""

    def __init__(
        self,
        client: LlmClient,
        *,
        memory: ConversationMemoryStore | None = None,
        context_builder: EngineeringChatContextBuilder | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.client = client
        self.memory = memory
        self.prompts = SemanticPromptBuilder()
        self.measurement = measurement or MeasurementSession()
        self.context_builder = context_builder or EngineeringChatContextBuilder(
            estimator=self.prompts.estimator
        )

    def ask(self, snapshot: AtlasSemanticSnapshot, request: AskRequest) -> AskResult:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("ask requires an Atlas semantic snapshot")
        if not isinstance(request, AskRequest):
            raise TypeError("ask requires an AskRequest")
        safe_question = sanitize_chat_text(request.question)
        conversation_id = request.conversation_id
        history = ()
        history_total_count = 0
        prior_subject_ids: tuple[str, ...] = ()
        if self.memory:
            if conversation_id is None:
                conversation_id = self.memory.create(
                    snapshot.workspace_fingerprint, title="Ask Atlas"
                ).id
            else:
                self.memory.require_workspace(
                    conversation_id, snapshot.workspace_fingerprint
                )
            all_history = self.memory.messages(conversation_id)
            history_total_count = len(all_history)
            effective_limit = min(request.history_limit, 100)
            history = all_history[-effective_limit:] if effective_limit else ()
            turns = self.memory.turns(conversation_id)
            for turn in reversed(turns):
                if (
                    turn.status is ConversationTurnStatus.COMPLETED
                    and turn.resolved_subject_ids
                ):
                    prior_subject_ids = turn.resolved_subject_ids
                    break

        requested = requested_chat_capabilities(
            safe_question, request.capabilities
        )
        context_budget = self._initial_context_budget(
            request.maximum_input_tokens, safe_question, history
        )
        context = None
        prompt = None
        for _ in range(5):
            with self.measurement.scope(
                "engineering_chat.context",
                consumer="engineering-chat",
                sample_key=snapshot.snapshot_id,
            ) as measured:
                context = self.context_builder.build(
                    snapshot,
                    question=safe_question,
                    subject=request.subject,
                    kind=request.kind,
                    project=request.project,
                    language=request.language,
                    capabilities=requested,
                    result_limit=request.result_limit,
                    token_budget=context_budget,
                    history=history,
                    history_total_count=history_total_count,
                    prior_subject_ids=prior_subject_ids,
                )
                measured.add_units(len(context.sections))
                measured.add_objects_produced(len(context.sections))
                measured.set_objects_retained(
                    len(context.sections) + len(context.evidence_index)
                )
            with self.measurement.scope(
                "engineering_chat.prompt",
                consumer="engineering-chat",
                sample_key=context.context_digest,
            ) as measured:
                prompt_text = self._prompt_text(context)
                prompt = self.prompts.build(
                    prompt_text,
                    WorkspaceSemanticContext(context.to_dict()),
                    template="atlas-engineering-chat-v1",
                )
                measured.add_bytes(sum(
                    len(item.content.encode("utf-8"))
                    for item in prompt.request.messages
                ))
            if prompt.estimated_input_tokens <= request.maximum_input_tokens:
                break
            overage = prompt.estimated_input_tokens - request.maximum_input_tokens
            context_budget -= overage + 32
            if context_budget < 256:
                raise ChatContextBudgetError(
                    "mandatory engineering-chat prompt exceeds its token budget"
                )
        else:
            raise ChatContextBudgetError(
                "engineering-chat prompt could not be bounded deterministically"
            )
        if context is None or prompt is None:
            raise RuntimeError("engineering-chat context construction did not complete")

        provider_name = sanitize_chat_metadata(
            str(getattr(self.client.provider, "name", "unknown"))
        ) or "unknown"
        provider_model = sanitize_chat_metadata(
            str(getattr(self.client.provider, "model", ""))
        )
        turn = None
        if self.memory and conversation_id is not None:
            turn = self.memory.begin_turn(
                conversation_id,
                workspace_fingerprint=snapshot.workspace_fingerprint,
                snapshot_id=snapshot.snapshot_id,
                intent=context.intent.value,
                resolved_subject_ids=context.subject_ids,
                context_digest=context.context_digest,
                evidence_ids=(
                    item.evidence_id for item in context.evidence_index.records
                ),
                truncated=context.selection.truncated,
                provider=provider_name,
                model=provider_model,
                limitations=context.limitations,
            )
            try:
                self.memory.append(
                    conversation_id,
                    ConversationRole.USER,
                    safe_question,
                    references={
                        "context": context.context_digest,
                        "snapshot": snapshot.snapshot_id,
                        "turn": str(turn.id),
                    },
                )
            except Exception:
                try:
                    self.memory.fail_turn(
                        turn.id,
                        limitations=(
                            "The user message could not be recorded for this turn.",
                        ),
                    )
                except Exception:
                    pass
                raise

        try:
            with self.measurement.scope(
                "engineering_chat.provider",
                consumer="engineering-chat-provider",
                sample_key=context.context_digest,
            ) as measured:
                response = self.client.complete(prompt.request)
                measured.add_bytes(len(response.text.encode("utf-8")))
            response_required_redaction = contains_unsafe_chat_content(
                response.text
            )
            answer = sanitize_chat_text(
                response.text, maximum=MAXIMUM_ANSWER_TEXT
            )
            if response_required_redaction:
                answer = strip_chat_citations(answer)
            if not answer or answer == "[content omitted]":
                raise ValueError("ask provider returned empty output")
            citations = validate_citations(
                answer,
                (item.evidence_id for item in context.evidence_index.records),
            )
            limitations = set(context.limitations)
            if response_required_redaction:
                limitations.add(
                    "Provider response required source-free redaction; "
                    "its citations were not accepted."
                )
            if citations.unknown_citation_ids:
                limitations.add(
                    f"Provider response cited {len(citations.unknown_citation_ids)} unknown evidence ID(s)."
                )
            if citations.missing_required:
                limitations.add(
                    "Provider response did not cite the selected Atlas evidence."
                )
            if not context.evidence_index.records:
                limitations.add(
                    "No Atlas evidence was selected; provider prose is not grounded."
                )
            response_provider = sanitize_chat_metadata(response.provider)
            response_model = sanitize_chat_metadata(response.model)
            result = AskResult(
                answer,
                snapshot.snapshot_id,
                conversation_id,
                context,
                citations,
                response_provider,
                response_model,
                tuple(limitations),
            )
            if self.memory and conversation_id is not None and turn is not None:
                self.memory.complete_turn(
                    turn.id,
                    provider=response_provider,
                    model=response_model,
                    limitations=limitations,
                    message_content=answer,
                    message_references={
                        "citation_status": "valid" if result.grounded else "invalid",
                        "context": context.context_digest,
                        "kind": "answer",
                        "snapshot": snapshot.snapshot_id,
                        "turn": str(turn.id),
                    },
                )
            return result
        except Exception:
            if self.memory and turn is not None:
                try:
                    self.memory.fail_turn(
                        turn.id,
                        limitations=(
                            "The turn failed before a grounded answer was recorded.",
                        ),
                    )
                except Exception:
                    pass
            raise

    def _initial_context_budget(
        self,
        maximum_input_tokens: int,
        question: str,
        history,
    ) -> int:
        history_chars = sum(min(len(item.content), 1_024) for item in history)
        reserved = 600 + self.prompts.estimator.estimate(question) + (
            history_chars + 3
        ) // 4
        return max(256, maximum_input_tokens - reserved)

    @staticmethod
    def _prompt_text(context: ChatContext) -> str:
        history = next(
            (
                section.content.get("messages", ())
                for section in context.sections
                if section.section_id == "conversation_history"
            ),
            (),
        )
        transcript = []
        if isinstance(history, Sequence):
            for item in history:
                if not isinstance(item, Mapping):
                    continue
                suffix = " [stale snapshot]" if item.get("stale") is True else ""
                transcript.append(
                    f"{item.get('role', 'unknown')}: {item.get('content', '')}{suffix}"
                )
        return (
            "Conversation (untrusted):\n"
            + ("\n".join(transcript) if transcript else "(none)")
            + f"\nQuestion: {context.question}"
        )


# Additive PR139 names; the implementation remains the existing AskEngine path.
ChatEngine = AskEngine
ChatRequest = AskRequest
ChatResult = AskResult
