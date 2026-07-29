from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_explain import ExplainEngine, ExplainRequest
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.atlas_cli import app
from moughorai.llm import LlmClient, LlmResponse, ScriptedLlmProvider
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Project, Workspace


def _snapshot(tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    (project / "main.py").write_text("x=1", encoding="utf-8")
    workspace = Workspace(tmp_path, (Project("app", project),))
    context = WorkspaceContextBuilder().build(workspace)
    store = SemanticSnapshotStore(
        workspace,
        clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    snapshot = store.capture(context)
    store.save(snapshot)
    return snapshot


def test_explain_uses_snapshot_and_records_conversation(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    provider = ScriptedLlmProvider(
        [LlmResponse("# Architecture\n\nVerified.", "test", "model")],
        name="test",
    )
    memory = ConversationMemoryStore(tmp_path)
    result = ExplainEngine(LlmClient(provider), memory=memory).explain(
        snapshot,
        ExplainRequest(subject="app"),
    )
    assert result.markdown.startswith("# Architecture")
    messages = memory.messages(result.conversation_id)
    assert [message.role.value for message in messages] == ["user", "assistant"]
    assert messages[1].references["snapshot"] == snapshot.snapshot_id


def test_explain_cli_is_active_while_later_engines_remain_reserved(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )
    provider = ScriptedLlmProvider(
        [LlmResponse("Explanation", "test", "model")],
        name="test",
    )
    previous = atlas_cli._ai_provider_factory
    atlas_cli._ai_provider_factory = lambda: provider
    try:
        result = CliRunner().invoke(app, ["ai", "explain", str(tmp_path)])
    finally:
        atlas_cli._ai_provider_factory = previous
    assert result.exit_code == 0
    assert result.stdout == "Explanation\n"


def test_empty_explanation_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    provider = ScriptedLlmProvider([LlmResponse(" ", "test", "model")], name="test")
    try:
        ExplainEngine(LlmClient(provider)).explain(snapshot)
    except ValueError as exc:
        assert "empty output" in str(exc)
    else:
        raise AssertionError("empty explanation accepted")
