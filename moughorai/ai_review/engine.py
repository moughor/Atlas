from __future__ import annotations

from dataclasses import dataclass

from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


DEFAULT_CATEGORIES = (
    "architecture", "design", "layering", "dependencies",
    "complexity", "maintainability", "naming", "code smells",
)


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    categories: tuple[str, ...] = DEFAULT_CATEGORIES
    conversation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    markdown: str
    snapshot_id: str
    categories: tuple[str, ...]
    conversation_id: int | None


class ReviewEngine:
    def __init__(self, client: LlmClient, *, memory: ConversationMemoryStore | None = None) -> None:
        self.client = client
        self.memory = memory
        self.prompts = SemanticPromptBuilder()

    def review(self, snapshot: AtlasSemanticSnapshot, request: ReviewRequest | None = None) -> ReviewResult:
        selected = request or ReviewRequest()
        categories = tuple(sorted({item.strip().lower() for item in selected.categories if item.strip()}))
        if not categories:
            raise ValueError("at least one review category is required")
        instruction = (
            "Review the verified Atlas semantic context. Produce Markdown with "
            "evidence, severity, and actionable recommendations for: "
            + ", ".join(categories)
            + ". Do not invent source facts."
        )
        prompt = self.prompts.build(instruction, snapshot.to_context())
        conversation_id = selected.conversation_id
        if self.memory:
            if conversation_id is None:
                conversation_id = self.memory.create(snapshot.workspace_fingerprint, title="Architecture review").id
            self.memory.append(conversation_id, ConversationRole.USER, instruction, references={"snapshot": snapshot.snapshot_id})
        markdown = self.client.complete(prompt.request).text.strip()
        if not markdown:
            raise ValueError("review provider returned empty output")
        if self.memory and conversation_id is not None:
            self.memory.append(conversation_id, ConversationRole.ASSISTANT, markdown, references={"snapshot": snapshot.snapshot_id, "kind": "review"})
        return ReviewResult(markdown, snapshot.snapshot_id, categories, conversation_id)
