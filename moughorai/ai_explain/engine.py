from __future__ import annotations

from dataclasses import dataclass

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.structured_explanation import (
    ExplanationAvailability,
    ExplanationRequest as StructuredExplanationRequest,
    StructuredExplanation,
    StructuredExplanationRenderer,
    StructuredExplanationService,
)

from .repository_projection import RepositoryExplanationProjector
from .repository_report import RepositoryReportRenderer


@dataclass(frozen=True, slots=True)
class ExplainRequest:
    subject: str = "workspace"
    question: str = "Explain this workspace."
    conversation_id: int | None = None
    kind: str | None = None
    project: str | None = None
    language: str | None = None
    path_constraint: str | None = None
    target: str | None = None
    relation: str | None = None
    narrative: bool = True


@dataclass(frozen=True, slots=True)
class ExplainResult:
    markdown: str
    snapshot_id: str
    estimated_input_tokens: int
    conversation_id: int | None = None
    structured_explanation: StructuredExplanation | None = None
    context_digest: str = ""
    citations: tuple[str, ...] = ()
    truncated: bool = False


class ExplainEngine:
    """Explain semantic snapshots without allowing LLMs to mutate repository facts."""

    MAXIMUM_INPUT_TOKENS = 7_000
    _NON_NARRATIVE_AVAILABILITY = frozenset({
        ExplanationAvailability.AMBIGUOUS,
        ExplanationAvailability.NOT_FOUND,
        ExplanationAvailability.UNAVAILABLE,
        ExplanationAvailability.UNSUPPORTED,
    })

    def __init__(
        self,
        client: LlmClient | None = None,
        *,
        prompt_builder: SemanticPromptBuilder | None = None,
        memory: ConversationMemoryStore | None = None,
    ) -> None:
        self.client = client
        self.prompts = prompt_builder or SemanticPromptBuilder()
        self.memory = memory

    def explain(
        self,
        snapshot: AtlasSemanticSnapshot,
        request: ExplainRequest | None = None,
    ) -> ExplainResult:
        selected = request or ExplainRequest()
        subject = selected.subject.strip()
        question = selected.question.strip()
        if not subject or not question:
            raise ValueError("explanation subject and question are required")
        repository_default = self._is_repository_default(selected)
        client = self.client
        if not repository_default and selected.narrative and client is None:
            raise ValueError("targeted explanations require an LLM client")

        structured: StructuredExplanation | None = None
        use_provider = False
        prompt = None
        if repository_default:
            structured = StructuredExplanationService(snapshot).explain(
                self._structured_request(selected, subject),
                token_budget=self.MAXIMUM_INPUT_TOKENS,
            )
        else:
            targeted_question = self._targeted_question(selected, subject)
            token_budget = self._structured_context_budget(
                targeted_question,
                subject,
            )
            structured = StructuredExplanationService(snapshot).explain(
                self._structured_request(selected, subject),
                token_budget=token_budget,
            )
            use_provider = (
                selected.narrative
                and structured.availability not in self._NON_NARRATIVE_AVAILABILITY
            )
            if use_provider:
                prompt = self.prompts.build(
                    targeted_question,
                    WorkspaceSemanticContext({
                        "structured_explanation": structured.to_dict(),
                    }),
                    template="atlas-explain-anything-v1",
                    variables={"subject": subject},
                    model="",
                    maximum_input_tokens=self.MAXIMUM_INPUT_TOKENS,
                )

        conversation_id = selected.conversation_id
        if self.memory is not None:
            if conversation_id is None:
                conversation_id = self.memory.create(
                    snapshot.workspace_fingerprint,
                    title=f"Explain {subject}",
                ).id
            self.memory.append(
                conversation_id,
                ConversationRole.USER,
                question,
                references={"snapshot": snapshot.snapshot_id, "subject": subject},
            )

        if repository_default:
            context = self._repository_context(snapshot)
            markdown = RepositoryReportRenderer().render(context.to_dict())
            # No provider input is sent for the deterministic default report.
            estimated_input_tokens = 0
        elif use_provider:
            if client is None or prompt is None:
                raise RuntimeError("narrative explanation state is incomplete")
            response = client.complete(prompt.request)
            narrative = response.text.strip()
            if not narrative:
                raise ValueError("explanation provider returned empty output")
            if structured is None:
                raise RuntimeError("structured explanation state is incomplete")
            deterministic = StructuredExplanationRenderer().render(structured)
            markdown = (
                f"{deterministic}\n\n"
                "## Optional provider narrative\n\n"
                "This non-authoritative interpretation cannot add repository facts "
                "or change Atlas confidence; verify it against the structured facts "
                "and citations above.\n\n"
                f"{narrative}"
            )
            estimated_input_tokens = prompt.estimated_input_tokens
        else:
            if structured is None:
                raise RuntimeError("structured explanation state is incomplete")
            markdown = StructuredExplanationRenderer().render(structured)
            estimated_input_tokens = 0

        if self.memory is not None and conversation_id is not None:
            self.memory.append(
                conversation_id,
                ConversationRole.ASSISTANT,
                markdown,
                references={"snapshot": snapshot.snapshot_id, "kind": "explanation"},
            )
        return ExplainResult(
            markdown,
            snapshot.snapshot_id,
            estimated_input_tokens,
            conversation_id,
            structured,
            structured.context_digest if structured is not None else "",
            structured.citations if structured is not None else (),
            structured.selection.truncated if structured is not None else False,
        )

    @staticmethod
    def _is_repository_default(request: ExplainRequest) -> bool:
        return (
            request.narrative
            and request.kind is None
            and request.project is None
            and request.language is None
            and request.path_constraint is None
            and request.target is None
            and request.relation is None
            and request.subject.strip().casefold() in {"workspace", "repository"}
            and request.question.strip() == ExplainRequest().question
        )

    @staticmethod
    def _structured_request(
        request: ExplainRequest,
        subject: str,
    ) -> StructuredExplanationRequest:
        if (request.target is None) != (request.relation is None):
            raise ValueError(
                "relationship explanations require both target and relation"
            )
        return StructuredExplanationRequest(
            subject,
            request.kind,
            request.project,
            request.language,
            request.path_constraint,
            subject if request.target is not None else None,
            request.target,
            request.relation,
        )

    @staticmethod
    def _targeted_question(request: ExplainRequest, subject: str) -> str:
        question = request.question.strip()
        if question == ExplainRequest().question:
            return f"Explain the resolved Atlas subject {subject}."
        return question

    def _structured_context_budget(self, question: str, subject: str) -> int:
        empty = self.prompts.build(
            question,
            WorkspaceSemanticContext({"structured_explanation": {}}),
            template="atlas-explain-anything-v1",
            variables={"subject": subject},
            model="",
        )
        # The empty JSON object already accounts for the enclosing context key.
        # Reserve two additional tokens for estimator rounding at the boundary.
        available = self.MAXIMUM_INPUT_TOKENS - empty.estimated_input_tokens - 2
        if available <= 0:
            raise ValueError("explanation request exceeds the input token budget")
        return available

    @staticmethod
    def _repository_context(
        snapshot: AtlasSemanticSnapshot,
    ) -> WorkspaceSemanticContext:
        return RepositoryExplanationProjector().project(snapshot)
