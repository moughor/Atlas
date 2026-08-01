from __future__ import annotations

from dataclasses import dataclass

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from .repository_projection import RepositoryExplanationProjector
from .repository_report import RepositoryReportRenderer


@dataclass(frozen=True, slots=True)
class ExplainRequest:
    subject: str = "workspace"
    question: str = "Explain this workspace."
    conversation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExplainResult:
    markdown: str
    snapshot_id: str
    estimated_input_tokens: int
    conversation_id: int | None = None


class ExplainEngine:
    """Explain semantic snapshots without allowing LLMs to mutate repository facts."""

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
        if not repository_default and client is None:
            raise ValueError("targeted explanations require an LLM client")

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
        else:
            prompt = self.prompts.build(
                question,
                snapshot.to_context(),
                template="atlas-grounded-v1",
                variables={"subject": subject},
                model="",
            )
            response = client.complete(prompt.request)
            markdown = response.text.strip()
            if not markdown:
                raise ValueError("explanation provider returned empty output")
            estimated_input_tokens = prompt.estimated_input_tokens

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
        )

    @staticmethod
    def _is_repository_default(request: ExplainRequest) -> bool:
        return (
            request.subject.strip().casefold() in {"workspace", "repository"}
            and request.question.strip() == ExplainRequest().question
        )

    @staticmethod
    def _repository_context(
        snapshot: AtlasSemanticSnapshot,
    ) -> WorkspaceSemanticContext:
        return RepositoryExplanationProjector().project(snapshot)
