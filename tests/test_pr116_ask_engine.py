from pathlib import Path

from moughorai.ai_ask import AskEngine, AskRequest
from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


def _snapshot(tmp_path: Path):
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    return AtlasSemanticSnapshot.create(
        WorkspaceContextBuilder().build(workspace),
        workspace_fingerprint="abc",
        analyzer_version="2",
    )


def test_ask_uses_bounded_history_and_records_answer(tmp_path: Path) -> None:
    memory = ConversationMemoryStore(tmp_path)
    conversation = memory.create("abc")
    memory.append(conversation.id, ConversationRole.USER, "Old question")
    memory.append(conversation.id, ConversationRole.ASSISTANT, "Old answer")
    provider = ScriptedLlmProvider(["Verified answer"])
    result = AskEngine(LlmClient(provider), memory=memory).ask(
        _snapshot(tmp_path),
        AskRequest("Where is app?", conversation.id, history_limit=1),
    )
    assert result.answer == "Verified answer"
    prompt = provider.calls[0][0].messages[-1].content
    assert "assistant: Old answer" in prompt
    assert "Old question" not in prompt
    assert len(memory.messages(conversation.id)) == 4


def test_ask_rejects_empty_question(tmp_path: Path) -> None:
    try:
        AskEngine(LlmClient(ScriptedLlmProvider([]))).ask(_snapshot(tmp_path), AskRequest(" "))
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty question accepted")
