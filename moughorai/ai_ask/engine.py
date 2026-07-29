from __future__ import annotations

from dataclasses import dataclass

from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


@dataclass(frozen=True, slots=True)
class AskRequest:
    question: str
    conversation_id: int | None = None
    history_limit: int = 12


@dataclass(frozen=True, slots=True)
class AskResult:
    answer: str
    snapshot_id: str
    conversation_id: int | None


class AskEngine:
    def __init__(self, client: LlmClient, *, memory: ConversationMemoryStore | None = None) -> None:
        self.client = client
        self.memory = memory
        self.prompts = SemanticPromptBuilder()

    def ask(self, snapshot: AtlasSemanticSnapshot, request: AskRequest) -> AskResult:
        question = request.question.strip()
        if not question:
            raise ValueError("question must not be empty")
        if request.history_limit < 0:
            raise ValueError("history_limit must be non-negative")
        conversation_id = request.conversation_id
        history = ()
        if self.memory:
            if conversation_id is None:
                conversation_id = self.memory.create(snapshot.workspace_fingerprint, title="Ask Atlas").id
            history = self.memory.messages(conversation_id)
            if request.history_limit:
                history = history[-request.history_limit:]
            else:
                history = ()
        transcript = "\n".join(f"{item.role.value}: {item.content}" for item in history)
        prompt_text = (
            "Answer using only verified Atlas semantic context. "
            "State when the facts are insufficient.\n"
            f"Conversation:\n{transcript or '(none)'}\nQuestion: {question}"
        )
        if self.memory and conversation_id is not None:
            self.memory.append(conversation_id, ConversationRole.USER, question, references={"snapshot": snapshot.snapshot_id})
        answer = self.client.complete(self.prompts.build(prompt_text, snapshot.to_context()).request).text.strip()
        if not answer:
            raise ValueError("ask provider returned empty output")
        if self.memory and conversation_id is not None:
            self.memory.append(conversation_id, ConversationRole.ASSISTANT, answer, references={"snapshot": snapshot.snapshot_id, "kind": "answer"})
        return AskResult(answer, snapshot.snapshot_id, conversation_id)
