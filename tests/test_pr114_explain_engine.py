from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceContextBuilder, WorkspaceSemanticContext
from moughorai.ai_explain import ExplainEngine, ExplainRequest
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.atlas_cli import app
from moughorai.llm import LlmClient, LlmResponse, ScriptedLlmProvider
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
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


def test_default_repository_explanation_prioritizes_compact_summary() -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {"root": "C:/demo", "projects": [{"name": "api"}]},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "api"}, {"name": "core"}],
            "module_hierarchy": [{"project": "api", "parent": "core"}],
            "languages": {"Java": 120, "Python": 30},
            "build_systems": ["Gradle"],
            "frameworks": ["Spring Framework"],
            "framework_evidence": [{
                "framework": "Spring Framework",
                "project": "documentation",
                "scope": "test-or-sample",
                "reference": "@springio/antora-extensions",
            }],
            "entry_points": ["api:Main.java"],
            "dependencies_by_ecosystem": {"gradle": 12},
        },
        "architecture": {
            "bounded_contexts": ["api", "core"],
            "findings": [{
                "architecture": "layered",
                "confidence": 0.84,
                "evidence": [{"kind": "semantic-name", "reference": "api", "detail": "api"}],
            }],
        },
        "dependencies": [{"name": "org.example:core", "ecosystem": "gradle"}],
        "semantic_graph": {
            "nodes": [{"id": str(index), "qualified_name": f"OMITTED_MARKER_{index}"} for index in range(500)],
            "edges": [],
        },
        "symbols": [{"qualified_name": f"OMITTED_MARKER_{index}"} for index in range(500)],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )
    provider = ScriptedLlmProvider(["Repository overview"])

    result = ExplainEngine(LlmClient(provider)).explain(snapshot)

    request = provider.calls[0][0]
    system, user = (message.content for message in request.messages)
    assert request.metadata["prompt_template"] == "atlas-repository-explanation-v1"
    assert "Prioritize repository_summary" in system
    assert "Present findings below 0.75 as possibilities" in system
    assert "Do not claim that cycles" in system
    assert '"repository_summary"' in user
    assert '"project_count":2' in user
    assert '"Gradle"' in user and '"Spring Framework"' in user
    assert '"display_name":"Spring-related documentation tooling"' in user
    assert "does not establish repository-wide Spring Framework adoption" in user
    assert '"scope":"test-or-sample"' in user
    assert '"architectural_areas":["api","core"]' in user
    assert '"bounded_contexts"' not in user
    assert "'Modules' or 'Architectural Areas'" in system
    assert '"layered"' in user
    assert '"total_declared_dependency_records":12' in user
    assert '"dependencies_by_ecosystem"' not in user
    assert "OMITTED_MARKER" not in user
    assert "source-free" in user
    assert result.estimated_input_tokens < 2_000


def test_specific_subject_preserves_detailed_context_path() -> None:
    context = WorkspaceSemanticContext({
        "repository_summary": {"projects": [{"name": "api"}]},
        "symbols": [{"qualified_name": "DETAIL_MARKER"}],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )
    provider = ScriptedLlmProvider(["Detail"])

    ExplainEngine(LlmClient(provider)).explain(
        snapshot,
        ExplainRequest(subject="demo.Service"),
    )

    request = provider.calls[0][0]
    assert request.metadata["prompt_template"] == "atlas-grounded-v1"
    assert "DETAIL_MARKER" in request.messages[1].content
