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
    assert "# Repository explanation:" in result.stdout
    assert "An LLM did not create or alter" in result.stdout
    assert provider.calls == []


def test_empty_explanation_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    provider = ScriptedLlmProvider([LlmResponse(" ", "test", "model")], name="test")
    try:
        ExplainEngine(LlmClient(provider)).explain(
            snapshot,
            ExplainRequest(subject="app"),
        )
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

    projected = ExplainEngine._repository_context(snapshot).to_dict()
    summary = projected["repository_summary"]
    assert provider.calls == []
    assert result.estimated_input_tokens == 0
    assert projected["workspace"]["discovered_project_count"] == 2
    assert summary["language_distribution"]["total_classified_language_files"] == 150
    assert summary["language_distribution"]["percentage_total_basis_points"] == 10_000
    assert summary["build_systems"]["items"][0]["name"] == "Gradle"
    framework = summary["frameworks_and_related_technologies"]["items"][0]
    assert framework["name"] == "Spring Framework"
    assert framework["classification"] == "test-or-sample-evidence"
    assert framework["adoption_status"] == "insufficient"
    assert projected["architecture"]["findings"][0]["status"] == "insufficient"
    assert projected["design_patterns"]["status"] == "unavailable"
    assert projected["reachability"]["status"] == "unavailable"
    assert "OMITTED_MARKER" not in result.markdown
    assert "source-free" in result.markdown


def test_default_repository_explanation_compacts_pr130_patterns() -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {"root": "C:/demo", "projects": [{"name": "demo"}]},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "demo"}],
        },
        "design_patterns": {
            "schema_version": 1,
            "producer_version": "atlas-pr130/1",
            "findings": [{
                "pattern": "builder",
                "confidence": 0.72,
                "confidence_tier": "medium",
                "participants": [
                    {
                        "role": "builder",
                        "symbol_id": "SECRET_SYMBOL_ID",
                        "qualified_name": "demo.SourceMustStayOmitted",
                    },
                    {
                        "role": "product",
                        "symbol_id": "SECRET_PRODUCT_ID",
                        "qualified_name": "demo.ProductMustStayOmitted",
                    },
                ],
                "evidence_ids": ["evidence:one", "evidence:two"],
                "limitations": ["Behavioral construction is not proven."],
            }],
            "evidence_index": {
                "schema_version": 1,
                "records": [{"detail": "MUST_NOT_ENTER_DEFAULT_PROMPT"}],
            },
        },
        "semantic_graph": {"nodes": [], "edges": []},
        "symbols": [],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )
    provider = ScriptedLlmProvider(["Repository overview"])

    result = ExplainEngine(LlmClient(provider)).explain(snapshot)

    patterns = ExplainEngine._repository_context(snapshot).to_dict()["design_patterns"]
    builder = patterns["pattern_types"][0]
    assert provider.calls == []
    assert builder["pattern"] == "builder"
    assert builder["status_counts"] == {"medium": 1}
    assert builder["minimum_confidence"] == 0.72
    assert builder["participating_symbols_count"] == 2
    assert builder["evidence_count"] == 2
    assert builder["limitations"] == ["Behavioral construction is not proven."]
    assert "SECRET_SYMBOL_ID" not in result.markdown
    assert "SourceMustStayOmitted" not in result.markdown
    assert "evidence:one" in result.markdown
    assert "MUST_NOT_ENTER_DEFAULT_PROMPT" not in result.markdown


def test_default_repository_explanation_compacts_pr131_reachability() -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {"root": "C:/demo", "projects": [{"name": "demo"}]},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "demo"}],
        },
        "reachability": {
            "schema_version": 1,
            "producer_version": "atlas-pr131/1",
            "statistics": {
                "analyzed_symbols": 100,
                "states": {
                    "reachable": 20,
                    "reachable_test_only": 3,
                    "unused": 70,
                    "likely_dead": 1,
                },
            },
            "coverage": {
                "status": "partial",
                "projects": [{
                    "project": "demo",
                    "status": "partial",
                    "calls": "unavailable",
                    "closed_world": False,
                    "evidence_ids": ["coverage:evidence"],
                }],
                "limitations": ["Reliable call evidence is unavailable."],
            },
            "findings": [
                {
                    "subject_id": "method:representative",
                    "state": "likely_dead",
                    "confidence": 0.81,
                    "confidence_tier": "high",
                    "project": "demo",
                    "limitations": ["Closed test fixture only."],
                    "evidence_ids": ["finding:evidence"],
                },
                *(
                    {
                        "subject_id": f"method:omitted:{index}",
                        "state": "unused",
                        "confidence": 0.5,
                        "confidence_tier": "low",
                        "project": "demo",
                        "limitations": [],
                        "evidence_ids": [f"evidence:{index}"],
                    }
                    for index in range(50)
                ),
            ],
            "evidence_index": {
                "records": [{"detail": "MUST_NOT_ENTER_DEFAULT_PROMPT"}],
            },
        },
        "semantic_graph": {"nodes": [], "edges": []},
        "symbols": [],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )
    provider = ScriptedLlmProvider(["Repository overview"])

    result = ExplainEngine(LlmClient(provider)).explain(snapshot)

    reachability = ExplainEngine._repository_context(snapshot).to_dict()["reachability"]
    assert provider.calls == []
    assert reachability["status"] == "partial"
    assert reachability["statistics"]["analyzed_symbols"] == 100
    assert reachability["statistics"]["states"]["likely_dead"] == 1
    assert reachability["representative_findings"][0]["subject_id"] == "method:representative"
    assert "method:omitted:1" not in result.markdown
    assert "finding:evidence" in result.markdown
    assert "MUST_NOT_ENTER_DEFAULT_PROMPT" not in result.markdown


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
