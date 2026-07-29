from pathlib import Path

from moughorai.ai import (
    ATLAS_AI_VERSION,
    ExplainEngine,
    ExplainRequest,
    IdeAction,
    IdeAssistant,
    IdeRequest,
    SupportedIde,
    atlas_ai_capabilities,
)
from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


def test_release_capabilities_are_complete_and_honest() -> None:
    capabilities = atlas_ai_capabilities()
    assert ATLAS_AI_VERSION == "1.0.0"
    assert capabilities.ready
    assert capabilities.providers == ("ollama",)
    assert "openai" not in capabilities.to_json()
    assert "anthropic" not in capabilities.to_json()


def test_end_to_end_snapshot_reasoning_memory_and_ide(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    context = WorkspaceContextBuilder().build(
        workspace,
        symbols=(GlobalSymbol.create(GlobalSymbolKind.TYPE, "App", "demo.App"),),
    )
    snapshot = AtlasSemanticSnapshot.create(
        context, workspace_fingerprint="workspace", analyzer_version="2"
    )
    result = ExplainEngine(
        LlmClient(ScriptedLlmProvider(["# Verified explanation"])),
        memory=ConversationMemoryStore(tmp_path),
    ).explain(snapshot, ExplainRequest(subject="demo.App"))
    assert result.conversation_id is not None
    assistant = IdeAssistant(lambda identifier: snapshot, {})
    navigation = assistant.handle(
        IdeRequest(SupportedIde.INTELLIJ, IdeAction.NAVIGATE, snapshot.snapshot_id, "demo.App")
    )
    assert navigation.payload["matches"][0]["qualified_name"] == "demo.App"
