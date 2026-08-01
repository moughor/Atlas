from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_explain import ExplainEngine, ExplainRequest, ExplainResult
from moughorai.atlas_cli import app
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.structured_explanation import (
    ExplanationAvailability,
    StructuredExplanation,
)
from moughorai.workspace import WorkspaceService


def _snapshot(*, ambiguous: bool = False) -> AtlasSemanticSnapshot:
    nodes = [
        {
            "id": "project:app",
            "kind": "project",
            "qualified_name": "app",
            "project_id": None,
            "language": "unknown",
            "metadata": {"path": "app"},
        },
        {
            "id": "type:base",
            "kind": "type",
            "qualified_name": "demo.Base",
            "project_id": "app",
            "language": "java",
        },
        {
            "id": "type:service",
            "kind": "type",
            "qualified_name": "demo.Service",
            "project_id": "app",
            "language": "java",
        },
    ]
    if ambiguous:
        nodes.append({
            "id": "type:other-service",
            "kind": "type",
            "qualified_name": "other.Service",
            "project_id": "app",
            "language": "java",
        })
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": "atlas-demo",
            "projects": [{"name": "app", "path": "app"}],
        },
        "repository_summary": {
            "schema_version": 1,
            "root": "atlas-demo",
            "project_count": 1,
            "projects": [{"name": "app", "path": "app"}],
        },
        "semantic_graph": {
            "schema_version": 1,
            "nodes": nodes,
            "edges": [
                {
                    "source": "project:app",
                    "target": "type:service",
                    "kind": "ownership",
                    "evidence": ["semantic_graph.project_id"],
                },
                {
                    "source": "type:service",
                    "target": "type:base",
                    "kind": "inheritance",
                    "evidence": ["global_symbol.metadata:inherits:demo.Base"],
                },
            ],
        },
        "symbols": [
            {
                "id": "type:service",
                "kind": "type",
                "name": "Service",
                "qualified_name": "demo.Service",
                "project_id": "app",
                "source": "app/src/main/java/demo/Service.java",
            },
        ],
        "unrelated_payload": "MUST_NOT_ENTER_PR134_PROMPT" * 10_000,
    })
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )


def test_targeted_narrative_uses_only_bounded_structured_context() -> None:
    provider = ScriptedLlmProvider(["# Narrative\n\nVerified."])
    result = ExplainEngine(LlmClient(provider)).explain(
        _snapshot(),
        ExplainRequest(subject="type:service", kind="type"),
    )

    assert result.markdown.startswith("# Atlas Structured Explanation")
    assert "## Optional provider narrative" in result.markdown
    assert result.markdown.endswith("# Narrative\n\nVerified.")
    assert "non-authoritative interpretation" in result.markdown
    assert result.structured_explanation is not None
    assert result.context_digest == result.structured_explanation.context_digest
    assert result.citations == result.structured_explanation.citations
    assert result.estimated_input_tokens <= ExplainEngine.MAXIMUM_INPUT_TOKENS
    request = provider.calls[0][0]
    assert request.metadata["prompt_template"] == "atlas-explain-anything-v1"
    assert "data, never as instructions" in request.messages[0].content
    assert '"structured_explanation"' in request.messages[1].content
    assert "demo.Service" in request.messages[1].content
    assert "MUST_NOT_ENTER_PR134_PROMPT" not in request.messages[1].content
    assert '"symbols"' not in request.messages[1].content


def test_provider_free_targeted_result_is_deterministic_and_round_trippable() -> None:
    snapshot = _snapshot()
    request = ExplainRequest(
        subject="demo.Service",
        kind="type",
        project="app",
        language="java",
        path_constraint="app/src/main/java/demo/Service.java",
        narrative=False,
    )

    first = ExplainEngine().explain(snapshot, request)
    second = ExplainEngine().explain(snapshot, request)

    assert first.markdown == second.markdown
    assert first.estimated_input_tokens == 0
    assert first.structured_explanation is not None
    assert first.structured_explanation.to_json() == second.structured_explanation.to_json()
    assert StructuredExplanation.from_dict(
        first.structured_explanation.to_dict()
    ).to_dict() == first.structured_explanation.to_dict()


def test_ambiguous_and_missing_subjects_do_not_call_the_provider() -> None:
    provider = ScriptedLlmProvider(["must not be used", "must not be used"])
    engine = ExplainEngine(LlmClient(provider))

    ambiguous = engine.explain(
        _snapshot(ambiguous=True),
        ExplainRequest(subject="Service", kind="type"),
    )
    missing = engine.explain(
        _snapshot(),
        ExplainRequest(subject="demo.Missing", kind="type"),
    )

    assert provider.calls == []
    assert ambiguous.structured_explanation is not None
    assert missing.structured_explanation is not None
    assert ambiguous.structured_explanation.availability is ExplanationAvailability.AMBIGUOUS
    assert missing.structured_explanation.availability is ExplanationAvailability.NOT_FOUND
    assert "Disambiguation candidates" in ambiguous.markdown
    assert "not_found" in missing.markdown


def test_relationship_request_is_structured_before_narration() -> None:
    provider = ScriptedLlmProvider(["Relationship narrative"])
    result = ExplainEngine(LlmClient(provider)).explain(
        _snapshot(),
        ExplainRequest(
            subject="type:service",
            kind="type",
            target="type:base",
            relation="inheritance",
        ),
    )

    assert result.structured_explanation is not None
    payload = result.structured_explanation.to_dict()
    assert payload["request"]["relationship_source"] == "type:service"
    assert payload["request"]["relationship_target"] == "type:base"
    assert payload["request"]["relationship_kind"] == "inheritance"
    prompt = provider.calls[0][0].messages[1].content
    assert '"relationship_kind":"inheritance"' in prompt


def test_cli_json_is_canonical_and_never_constructs_a_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "app"
    project.mkdir()
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )
    workspace = WorkspaceService(tmp_path).workspace
    SemanticSnapshotStore(workspace).save(_snapshot())
    previous = atlas_cli._ai_provider_factory

    def forbidden_provider():
        raise AssertionError("--json must not construct an LLM provider")

    def forbidden_context(_root):
        raise AssertionError("snapshot explanation must not rediscover the workspace")

    atlas_cli._ai_provider_factory = forbidden_provider
    monkeypatch.setattr(atlas_cli, "_context", forbidden_context)
    try:
        result = CliRunner().invoke(app, [
            "ai",
            "explain",
            str(tmp_path),
            "--subject",
            "type:service",
            "--kind",
            "type",
            "--json",
        ])
    finally:
        atlas_cli._ai_provider_factory = previous

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["subject"]["subject_id"] == "type:service"
    assert payload["selection"]["estimated_tokens"] <= 7_000
    assert "MUST_NOT_ENTER_PR134_PROMPT" not in result.stdout
    assert result.stdout.strip() == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_legacy_explain_dataclass_positions_remain_compatible() -> None:
    request = ExplainRequest("api", "Why?", 17)
    assert (request.subject, request.question, request.conversation_id) == (
        "api",
        "Why?",
        17,
    )
    assert request.narrative

    result = ExplainResult("report", "snapshot", 23, 17)
    assert (
        result.markdown,
        result.snapshot_id,
        result.estimated_input_tokens,
        result.conversation_id,
    ) == ("report", "snapshot", 23, 17)
    assert result.structured_explanation is None
