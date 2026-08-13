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
from moughorai.llm import LlmClient, LlmProviderError
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
from .models import (
    CapabilityGroundingStatus,
    ChatCapabilityState,
    ChatContext,
    CitationValidation,
    GroundingSummary,
)
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
    grounding_summary: GroundingSummary | None = None

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
        if self.grounding_summary is not None:
            if not isinstance(self.grounding_summary, GroundingSummary):
                raise TypeError(
                    "ask result grounding summary must use GroundingSummary"
                )
            if self.grounding_summary.request_complete != self.grounded:
                raise ValueError(
                    "ask result grounding summary conflicts with legacy grounding"
                )
            if (
                self.grounding_summary.delivered_answer_grounded
                and (
                    not self.citations.valid
                    or not self.citations.accepted_evidence_ids
                )
            ):
                raise ValueError(
                    "answer-grounded summary requires accepted valid citations"
                )

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
        explicit_subject = any(
            section.section_id == "canonical_explanation"
            and section.content.get("resolution_origin") == "explicit"
            for section in self.context.sections
        )
        code_subject = any(
            section.section_id == 'code_impact'
            and section.capability == 'code_impact'
            and isinstance(section.content.get('report'), Mapping)
            and isinstance(section.content['report'].get('subject'), Mapping)
            and section.content['report']['subject'].get('canonical_id')
            in self.context.subject_ids
            for section in self.context.sections
        )
        explicit_subject = explicit_subject or code_subject
        searchable = {
            ChatCapabilityState.AVAILABLE,
            ChatCapabilityState.PARTIAL,
            ChatCapabilityState.AMBIGUOUS,
        }
        if (
            not explicit_subject
            and (
                capabilities.get("semantic_search") not in searchable
                or "semantic_search" not in retained_capabilities
            )
        ):
            return False
        explainable = {
            ChatCapabilityState.AVAILABLE,
            ChatCapabilityState.PARTIAL,
        }
        if self.context.subject_ids:
            if (
                not code_subject
                and (
                    capabilities.get("canonical_explanation") not in explainable
                    or "canonical_explanation" not in retained_capabilities
                )
            ):
                return False
        for name in (
            'code_impact',
            "impact_prediction",
            "refactoring_advisor",
            "security_intelligence",
        ):
            state = capabilities.get(name)
            if state is None or state is ChatCapabilityState.NOT_REQUESTED:
                continue
            if state not in explainable:
                return False
            qualifying_sections = tuple(
                section
                for section in self.context.sections
                if section.capability == name
                and (
                    name != "impact_prediction"
                    or section.section_id == "impact_aggregate"
                )
            )
            if not qualifying_sections:
                return False
            selected_evidence = {
                evidence_id
                for section in qualifying_sections
                for evidence_id in section.evidence_ids
            }
            if not selected_evidence.intersection(
                self.citations.accepted_evidence_ids
            ):
                return False
        return True

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        if self.grounding_summary is not None:
            result["grounding_summary"] = self.grounding_summary.to_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AskResult:
        raw_context = value.get("context")
        raw_citations = value.get("citations", {})
        raw_grounding_summary = value.get("grounding_summary")
        if raw_context is not None and not isinstance(raw_context, Mapping):
            raise TypeError("ask result context must be an object or null")
        if not isinstance(raw_citations, Mapping):
            raise TypeError("ask result citations must be an object")
        if raw_grounding_summary is not None and not isinstance(
            raw_grounding_summary, Mapping
        ):
            raise TypeError("ask result grounding summary must be an object")
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
            GroundingSummary.from_dict(raw_grounding_summary)
            if isinstance(raw_grounding_summary, Mapping)
            else None,
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
                try:
                    response = self.client.complete(prompt.request)
                except LlmProviderError as provider_error:
                    if not _eligible_for_deterministic_code_impact_fallback(
                        context
                    ):
                        raise
                    code_fallback = _deterministic_code_impact_fallback(context)
                    impact_fallback = _deterministic_impact_fallback(context)
                    fallback_parts = tuple(
                        item for item in (code_fallback, impact_fallback) if item
                    )
                    if not fallback_parts:
                        raise
                    fallback_answer = '\n\n'.join(fallback_parts)
                    fallback_citations = validate_citations(
                        fallback_answer,
                        (
                            item.evidence_id
                            for item in context.evidence_index.records
                        ),
                    )
                    fallback_limitations = {
                        *context.limitations,
                        'The provider failed before returning a grounded answer; '
                        'Atlas returned authoritative deterministic code-impact '
                        f'evidence ({type(provider_error).__name__}).',
                    }
                    fallback_result = _code_provider_failure_result(
                        context=context,
                        snapshot=snapshot,
                        conversation_id=conversation_id,
                        answer=fallback_answer,
                        citations=fallback_citations,
                        provider=provider_name,
                        model=provider_model,
                        limitations=tuple(fallback_limitations),
                    )
                    if self.memory and turn is not None:
                        summary = fallback_result.grounding_summary
                        references = {
                            'citation_status': (
                                'valid' if fallback_result.grounded else 'invalid'
                            ),
                            'context': context.context_digest,
                            'kind': 'answer',
                            'snapshot': snapshot.snapshot_id,
                            'turn': str(turn.id),
                        }
                        if summary is not None:
                            references.update(
                                _grounding_summary_references(summary)
                            )
                        self.memory.complete_turn(
                            turn.id,
                            provider=provider_name,
                            model=provider_model,
                            limitations=fallback_limitations,
                            message_content=fallback_answer,
                            message_references=references,
                        )
                    return fallback_result
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
            provider_result = AskResult(
                answer,
                snapshot.snapshot_id,
                conversation_id,
                context,
                citations,
                response_provider,
                response_model,
                tuple(limitations),
            )
            provider_grounded = provider_result.grounded
            fallback_used = False
            if (
                not provider_grounded
                and _eligible_for_deterministic_code_impact_fallback(context)
            ):
                code_fallback = _deterministic_code_impact_fallback(context)
                impact_fallback = _deterministic_impact_fallback(context)
                fallback_parts = tuple(
                    item for item in (code_fallback, impact_fallback) if item
                )
                if fallback_parts:
                    answer = '\n\n'.join(fallback_parts)
                    citations = validate_citations(
                        answer,
                        (
                            item.evidence_id
                            for item in context.evidence_index.records
                        ),
                    )
                    limitations.add(
                        'Provider grounding failed; Atlas discarded the provider '
                        'interpretation and returned authoritative deterministic '
                        'code-impact evidence.'
                    )
                    fallback_used = True
            if (
                not provider_grounded
                and _eligible_for_deterministic_impact_fallback(context)
            ):
                fallback = _deterministic_impact_fallback(context)
                if fallback is not None:
                    answer = fallback
                    citations = validate_citations(
                        answer,
                        (
                            item.evidence_id
                            for item in context.evidence_index.records
                        ),
                    )
                    limitations.add(
                        "Provider grounding failed; Atlas discarded the provider interpretation and returned a deterministic impact fallback."
                    )
                    fallback_used = True
            result_without_summary = AskResult(
                answer,
                snapshot.snapshot_id,
                conversation_id,
                context,
                citations,
                response_provider,
                response_model,
                tuple(limitations),
            )
            grounding_summary = _derive_grounding_summary(
                context,
                provider_grounded=provider_grounded,
                delivered_result=result_without_summary,
                fallback_used=fallback_used,
            )
            result = AskResult(
                answer,
                snapshot.snapshot_id,
                conversation_id,
                context,
                citations,
                response_provider,
                response_model,
                tuple(limitations),
                grounding_summary,
            )
            if self.memory and conversation_id is not None and turn is not None:
                message_references = {
                    "citation_status": "valid" if result.grounded else "invalid",
                    "context": context.context_digest,
                    "kind": "answer",
                    "snapshot": snapshot.snapshot_id,
                    "turn": str(turn.id),
                }
                message_references.update(
                    _grounding_summary_references(grounding_summary)
                )
                self.memory.complete_turn(
                    turn.id,
                    provider=response_provider,
                    model=response_model,
                    limitations=limitations,
                    message_content=answer,
                    message_references=message_references,
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


def _code_provider_failure_result(
    *,
    context: ChatContext,
    snapshot: AtlasSemanticSnapshot,
    conversation_id: int | None,
    answer: str,
    citations: CitationValidation,
    provider: str,
    model: str,
    limitations: tuple[str, ...],
) -> AskResult:
    without_summary = AskResult(
        answer,
        snapshot.snapshot_id,
        conversation_id,
        context,
        citations,
        provider,
        model,
        limitations,
    )
    summary = _derive_grounding_summary(
        context,
        provider_grounded=False,
        delivered_result=without_summary,
        fallback_used=True,
    )
    return AskResult(
        answer,
        snapshot.snapshot_id,
        conversation_id,
        context,
        citations,
        provider,
        model,
        limitations,
        summary,
    )


_OPTIONAL_ANSWER_CAPABILITIES = (
    'code_impact',
    "impact_prediction",
    "refactoring_advisor",
    "security_intelligence",
)


def _derive_grounding_summary(
    context: ChatContext,
    *,
    provider_grounded: bool,
    delivered_result: AskResult,
    fallback_used: bool,
) -> GroundingSummary:
    delivered_answer_grounded = provider_grounded
    if fallback_used and _eligible_for_deterministic_code_impact_fallback(context):
        fallback_evidence = {
            evidence_id
            for section in context.sections
            if section.section_id in {'code_impact', 'impact_aggregate'}
            for evidence_id in section.evidence_ids
        }
        delivered_answer_grounded = (
            delivered_result.citations.valid
            and bool(fallback_evidence.intersection(
                delivered_result.citations.accepted_evidence_ids
            ))
        )
    elif fallback_used:
        aggregate_evidence = {
            evidence_id
            for section in context.sections
            if section.section_id == "impact_aggregate"
            and section.capability == "impact_prediction"
            for evidence_id in section.evidence_ids
        }
        delivered_answer_grounded = (
            delivered_result.citations.valid
            and bool(aggregate_evidence.intersection(
                delivered_result.citations.accepted_evidence_ids
            ))
        )

    statuses = []
    for capability in context.capabilities:
        if (
            capability.name not in _OPTIONAL_ANSWER_CAPABILITIES
            or capability.state is ChatCapabilityState.NOT_REQUESTED
        ):
            continue
        computed = capability.state in {
            ChatCapabilityState.AVAILABLE,
            ChatCapabilityState.PARTIAL,
        }
        delivered = (
            provider_grounded
            or (
                fallback_used
                and delivered_answer_grounded
                and capability.name == "impact_prediction"
            )
        )
        if fallback_used:
            delivered = _fallback_capability_delivered(
                context,
                capability.name,
                delivered_result.citations.accepted_evidence_ids,
            )
        statuses.append(CapabilityGroundingStatus(
            capability.name,
            requested=True,
            computed=computed,
            delivered=delivered,
            grounded=delivered,
        ))
    statuses = sorted(statuses)
    delivered_capabilities = tuple(
        item.capability for item in statuses if item.delivered
    )
    omitted_capabilities = tuple(
        item.capability for item in statuses if not item.delivered
    )
    return GroundingSummary(
        provider_grounded,
        delivered_answer_grounded,
        delivered_result.grounded,
        fallback_used,
        delivered_capabilities,
        omitted_capabilities,
        tuple(statuses),
    )


def _fallback_capability_delivered(
    context: ChatContext,
    capability: str,
    accepted_evidence_ids,
) -> bool:
    section_ids = {
        'code_impact': frozenset({'code_impact'}),
        'impact_prediction': frozenset({'impact_aggregate'}),
    }.get(capability, frozenset())
    if not section_ids:
        return False
    evidence = {
        evidence_id
        for section in context.sections
        if section.section_id in section_ids
        and section.capability == capability
        for evidence_id in section.evidence_ids
    }
    return bool(evidence.intersection(accepted_evidence_ids))


def _grounding_summary_references(
    summary: GroundingSummary,
) -> dict[str, str]:
    return {
        "delivered_answer_grounded": str(
            summary.delivered_answer_grounded
        ).lower(),
        "request_complete": str(summary.request_complete).lower(),
        "fallback_used": str(summary.fallback_used).lower(),
        "delivered_capabilities": (
            ",".join(summary.delivered_capabilities) or "none"
        ),
        "omitted_requested_capabilities": (
            ",".join(summary.omitted_requested_capabilities) or "none"
        ),
    }


def _eligible_for_deterministic_code_impact_fallback(
    context: ChatContext,
) -> bool:
    capability = next((
        item for item in context.capabilities if item.name == 'code_impact'
    ), None)
    if (
        capability is None
        or capability.state
        not in {ChatCapabilityState.AVAILABLE, ChatCapabilityState.PARTIAL}
    ):
        return False
    section = next((
        item for item in context.sections
        if item.section_id == 'code_impact'
        and item.capability == 'code_impact'
    ), None)
    if section is None or not section.evidence_ids:
        return False
    available = {
        record.evidence_id for record in context.evidence_index.records
    }
    if not set(section.evidence_ids).issubset(available):
        return False
    return isinstance(section.content.get('report'), Mapping)


def _deterministic_code_impact_fallback(context: ChatContext) -> str | None:
    section = next((
        item for item in context.sections
        if item.section_id == 'code_impact'
    ), None)
    if section is None or not section.evidence_ids:
        return None
    report = section.content.get('report')
    if not isinstance(report, Mapping):
        return None
    subject = report.get('subject')
    upstream = report.get('upstream_change_impact')
    tests = report.get('represented_test_intelligence')
    if not isinstance(subject, Mapping) or not isinstance(upstream, Mapping):
        return None
    canonical_id = str(subject.get('canonical_id', 'unavailable'))
    display_name = str(subject.get('display_name', canonical_id))
    direct_upstream = upstream.get('direct')
    transitive_upstream = upstream.get('transitive')
    traversal = upstream.get('traversal')
    direct_count = _bounded_code_total(direct_upstream)
    transitive_count = _bounded_code_total(transitive_upstream)
    callers = report.get('direct_callers')
    callees = report.get('direct_callees')
    caller_count = _code_relationship_group_total(callers)
    callee_count = _code_relationship_group_total(callees)
    lines = [
        'Atlas deterministic Java code-impact answer',
        '',
        'Provider grounding failed, so the provider interpretation was discarded.',
        '',
        f'Subject: {display_name}',
        f'Canonical ID: {canonical_id}',
        'Direction contract: canonical CALLER -> CALLEE; impact traversal is reverse upstream from the changed callee.',
        '',
        f'Direct represented callers: {caller_count}.',
        f'Direct represented callees: {callee_count}.',
        f'Upstream impact: {direct_count} direct and {transitive_count} transitive.',
    ]
    _append_code_relationships(lines, 'caller', callers)
    _append_code_relationships(lines, 'callee', callees)
    _append_code_paths(lines, 'direct upstream', direct_upstream)
    _append_code_paths(lines, 'transitive upstream', transitive_upstream)
    if isinstance(traversal, Mapping):
        visited_nodes = traversal.get('visited_node_count', 0)
        visited_edges = traversal.get('visited_edge_count', 0)
        truncated = str(traversal.get('truncated') is True).lower()
        lines.append(
            f'Traversal metrics: visited nodes={visited_nodes}, '
            f'visited edges={visited_edges}, truncated={truncated}.'
        )
    lines.extend(('', 'Represented TEST reachability:'))
    if isinstance(tests, Mapping):
        direct_tests = _bounded_code_total(tests.get('direct_test_callers'))
        high_tests = _bounded_code_total(tests.get('high_confidence_paths'))
        possible_tests = _bounded_code_total(tests.get('possible_paths'))
        lines.extend((
            f'- Direct represented TEST callers: {direct_tests}.',
            f'- High-confidence TEST-root paths: {high_tests}.',
            f'- Possible TEST-root paths: {possible_tests}.',
        ))
        _append_code_paths(
            lines,
            'high-confidence represented TEST path',
            tests.get('high_confidence_paths'),
        )
        _append_code_paths(
            lines,
            'possible represented TEST path',
            tests.get('possible_paths'),
        )
        negative = tests.get('negative_statement')
        if negative:
            lines.append(f'- {negative}')
    lines.extend((
        '- This is represented TEST reachability, not runtime test coverage.',
        '',
        'What Atlas cannot prove:',
        '- Runtime invocation, complete runtime dispatch, reflection, dependency-injection wiring, or framework dispatch.',
        '- Runtime test execution or behavioral coverage from represented source reachability alone.',
    ))
    raw_limitations = report.get('limitations', ())
    if isinstance(raw_limitations, Sequence) and not isinstance(
        raw_limitations, (str, bytes, bytearray)
    ):
        for item in raw_limitations[:8]:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {item.get('category', 'limitation')}: "
                f"total={item.get('total_count', 0)}, "
                f"included={item.get('included_count', 0)}, "
                f"omitted={item.get('omitted_count', 0)}."
            )
    limitations = report.get('general_limitations', ())
    if isinstance(limitations, Sequence) and not isinstance(
        limitations, (str, bytes, bytearray)
    ):
        lines.extend(f'- {item}' for item in limitations[:6])
    lines.extend(('', 'Grounding evidence: ' + ' '.join(section.evidence_ids)))
    return '\n'.join(lines)


def _bounded_code_total(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    total = value.get('total_count', 0)
    return total if isinstance(total, int) and not isinstance(total, bool) else 0


def _code_relationship_group_total(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    return sum(
        _bounded_code_total(value.get(name))
        for name in ('high_confidence', 'conservative')
    )


def _append_code_relationships(
    lines: list[str],
    label: str,
    value: object,
) -> None:
    if not isinstance(value, Mapping):
        return
    for group in ('high_confidence', 'conservative', 'method_references'):
        section = value.get(group)
        if not isinstance(section, Mapping):
            continue
        raw_items = section.get('items', ())
        if not isinstance(raw_items, Sequence) or isinstance(
            raw_items, (str, bytes, bytearray)
        ):
            continue
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            source = item.get('canonical_source', 'unavailable')
            target = item.get('canonical_target', 'unavailable')
            confidence = item.get('confidence', 'unknown')
            evidence = item.get('producer_evidence_id', 'unavailable')
            source_ref = item.get('source_ref', 'unavailable')
            lines.append(
                f'- {label} {group}: {source} -> {target}; '
                f'confidence={confidence}; producer evidence={evidence}; '
                f'source={source_ref}.'
            )


def _append_code_paths(lines: list[str], label: str, value: object) -> None:
    if not isinstance(value, Mapping):
        return
    raw_items = value.get('items', ())
    if not isinstance(raw_items, Sequence) or isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        return
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        consumer = item.get('consumer_subject_id', 'unavailable')
        depth = item.get('depth', 0)
        confidence = item.get('confidence', 'unknown')
        traversal = item.get('traversal_direction', 'unknown')
        evidence = item.get('producer_evidence_ids', ())
        evidence_text = ','.join(map(str, evidence)) if isinstance(
            evidence, Sequence
        ) and not isinstance(evidence, (str, bytes, bytearray)) else 'unavailable'
        lines.append(
            f'- {label}: consumer={consumer}; depth={depth}; '
            f'confidence={confidence}; traversal={traversal}; '
            f'producer evidence={evidence_text}.'
        )


def _eligible_for_deterministic_impact_fallback(context: ChatContext) -> bool:
    if _eligible_for_deterministic_code_impact_fallback(context):
        return False
    impact_capability = next(
        (
            capability
            for capability in context.capabilities
            if capability.name == "impact_prediction"
        ),
        None,
    )
    if (
        impact_capability is None
        or impact_capability.state
        not in {ChatCapabilityState.AVAILABLE, ChatCapabilityState.PARTIAL}
    ):
        return False
    aggregate_section = next(
        (
            section
            for section in context.sections
            if section.section_id == "impact_aggregate"
            and section.capability == "impact_prediction"
        ),
        None,
    )
    if aggregate_section is None or not aggregate_section.evidence_ids:
        return False
    available_evidence = {
        record.evidence_id for record in context.evidence_index.records
    }
    if not set(aggregate_section.evidence_ids).issubset(available_evidence):
        return False
    return isinstance(aggregate_section.content.get("aggregate"), Mapping)


def _deterministic_impact_fallback(context: ChatContext) -> str | None:
    aggregate_section = next(
        (
            section
            for section in context.sections
            if section.section_id == "impact_aggregate"
        ),
        None,
    )
    if aggregate_section is None or not aggregate_section.evidence_ids:
        return None
    raw_aggregate = aggregate_section.content.get("aggregate")
    if not isinstance(raw_aggregate, Mapping):
        return None

    def count(name: str) -> int:
        value = raw_aggregate.get(name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    total = count("total_impact_count")
    projects = count("unique_affected_project_count")
    direct = count("direct_affected_project_count")
    transitive = count("transitive_affected_project_count")
    evidence_id = aggregate_section.evidence_ids[0]
    depth_histogram = raw_aggregate.get("depth_histogram", {})
    depth_text = "none"
    if isinstance(depth_histogram, Mapping):
        depth_text = ", ".join(
            f"depth {depth}: {value}"
            for depth, value in sorted(
                depth_histogram.items(), key=lambda item: int(str(item[0]))
            )
        ) or "none"

    representative_section = next(
        (
            section
            for section in context.sections
            if section.section_id == "impact_prediction"
        ),
        None,
    )
    raw_findings = ()
    if representative_section is not None:
        candidate = representative_section.content.get("findings", ())
        if isinstance(candidate, Sequence) and not isinstance(
            candidate, (str, bytes, bytearray)
        ):
            raw_findings = tuple(
                item for item in candidate if isinstance(item, Mapping)
            )
    displayed_direct = sum(item.get("direct") is True for item in raw_findings)
    displayed_transitive = len(raw_findings) - displayed_direct
    displayed = len(raw_findings)
    omitted = max(0, total - displayed)

    lines = [
        "Atlas deterministic impact answer",
        "",
        "Provider grounding failed, so the provider interpretation was discarded.",
        "",
        (
            f"Deterministic aggregate: {total} impact classifications across "
            f"{projects} affected projects; {direct} direct and {transitive} "
            f"transitive. {evidence_id}"
        ),
        f"Depth distribution: {depth_text}.",
        (
            f"Traversal coverage: maximum configured depth "
            f"{count('configured_max_depth')}, maximum observed depth "
            f"{count('maximum_observed_depth')}, {count('visited_node_count')} "
            f"visited nodes, and {count('visited_edge_count')} visited edges; "
            f"complete: {str(raw_aggregate.get('traversal_complete') is True).lower()}."
        ),
        "",
        (
            f"Representative display: included {displayed} of {total}, omitted "
            f"{omitted}, complete: {str(omitted == 0).lower()}."
        ),
        (
            f"Direct representatives: included {displayed_direct} of {direct}, "
            f"omitted {max(0, direct - displayed_direct)}, complete: "
            f"{str(displayed_direct == direct).lower()}."
        ),
        (
            f"Transitive representatives: included {displayed_transitive} of "
            f"{transitive}, omitted {max(0, transitive - displayed_transitive)}, "
            f"complete: {str(displayed_transitive == transitive).lower()}."
        ),
    ]
    other_requested_capabilities = tuple(
        capability.name
        for capability in context.capabilities
        if capability.name in {"refactoring_advisor", "security_intelligence"}
        and capability.state is not ChatCapabilityState.NOT_REQUESTED
    )
    if other_requested_capabilities:
        lines[3:3] = [
            "",
            "Fallback scope: Atlas is returning the authoritative deterministic impact dimension.",
            "Other requested dimensions were not deterministically synthesized by this fallback: "
            + ", ".join(other_requested_capabilities)
            + ".",
        ]
    for item in raw_findings:
        subject = item.get("subject")
        canonical_id = (
            subject.get("canonical_id")
            if isinstance(subject, Mapping)
            else "unavailable"
        )
        category = item.get("category", "unknown")
        relation = "direct" if item.get("direct") is True else "transitive"
        item_evidence = item.get("evidence_ids", ())
        item_citation = next(
            (
                value
                for value in item_evidence
                if isinstance(value, str)
                and value in representative_section.evidence_ids
            ),
            evidence_id,
        ) if representative_section is not None else evidence_id
        lines.append(
            f"- Representative {relation} {category}: {canonical_id}. {item_citation}"
        )

    capabilities = raw_aggregate.get("capabilities", {})
    if isinstance(capabilities, Mapping):
        capability_text = ", ".join(
            f"{name}={value.get('state', 'unknown')}"
            for name, value in sorted(capabilities.items())
            if isinstance(value, Mapping)
        )
        if capability_text:
            lines.extend(("", f"Impact capability availability: {capability_text}."))

    architecture_state = "not retained"
    explanation_section = next(
        (
            section
            for section in context.sections
            if section.section_id == "canonical_explanation"
        ),
        None,
    )
    if explanation_section is not None:
        explanation_capabilities = explanation_section.content.get(
            "capabilities", ()
        )
        if isinstance(explanation_capabilities, Sequence):
            architecture = next(
                (
                    item
                    for item in explanation_capabilities
                    if isinstance(item, Mapping)
                    and "architecture" in str(item.get("name", ""))
                ),
                None,
            )
            if architecture is not None:
                architecture_state = str(
                    architecture.get("availability", "unknown")
                )
    lines.append(f"Architecture evidence availability: {architecture_state}.")
    lines.append(
        "These static declared or observed dependency relationships do not prove runtime usage."
    )

    aggregate_limitations = raw_aggregate.get("limitations", ())
    if isinstance(aggregate_limitations, Sequence) and not isinstance(
        aggregate_limitations, (str, bytes, bytearray)
    ):
        selected_limitations = tuple(
            str(item) for item in aggregate_limitations[:8] if str(item).strip()
        )
        if selected_limitations:
            lines.extend(("", "Limitations:"))
            lines.extend(f"- {item}" for item in selected_limitations)
        remaining = max(0, len(aggregate_limitations) - len(selected_limitations))
        if remaining:
            lines.append(
                f"- {remaining} additional deterministic limitation records were omitted from this display."
            )
    return "\n".join(lines)


# Additive PR139 names; the implementation remains the existing AskEngine path.
ChatEngine = AskEngine
ChatRequest = AskRequest
ChatResult = AskResult
