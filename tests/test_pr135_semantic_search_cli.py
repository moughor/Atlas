from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.semantic_search import SemanticSearchResponse
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import Workspace


runner = CliRunner()


def _snapshot() -> AtlasSemanticSnapshot:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": "semantic-search-fixture",
            "projects": [{"name": "app", "path": "app"}],
        },
        "semantic_graph": {
            "schema_version": 1,
            "nodes": [
                {
                    "id": "project:app",
                    "kind": "project",
                    "qualified_name": "app",
                    "project_id": None,
                    "language": "unknown",
                    "metadata": {"path": "app"},
                },
                {
                    "id": "type:app:demo.Api",
                    "kind": "type",
                    "qualified_name": "demo.Api",
                    "project_id": "app",
                    "language": "java",
                },
                {
                    "id": "module:app",
                    "kind": "module",
                    "qualified_name": "app",
                    "project_id": "app",
                    "language": "unknown",
                },
                {
                    "id": "method:app:demo.Api#get()",
                    "kind": "method",
                    "qualified_name": "demo.Api#get()",
                    "project_id": "app",
                    "language": "java",
                },
                {
                    "id": "type:app:demo.Worker",
                    "kind": "type",
                    "qualified_name": "demo.Worker",
                    "project_id": "app",
                    "language": "java",
                },
            ],
            "edges": [
                {
                    "source": "project:app",
                    "target": "module:app",
                    "kind": "ownership",
                    "evidence": ["semantic_graph.module"],
                },
                {
                    "source": "module:app",
                    "target": "type:app:demo.Api",
                    "kind": "ownership",
                    "evidence": ["semantic_graph.module_membership"],
                },
                {
                    "source": "project:app",
                    "target": "type:app:demo.Api",
                    "kind": "ownership",
                    "evidence": ["semantic_graph.project_id"],
                },
                {
                    "source": "type:app:demo.Api",
                    "target": "method:app:demo.Api#get()",
                    "kind": "ownership",
                    "evidence": ["global_symbol.owner_id"],
                },
                {
                    "source": "method:app:demo.Api#get()",
                    "target": "type:app:demo.Worker",
                    "kind": "calls",
                    "evidence": ["calls"],
                },
            ],
        },
        "symbols": [
            {
                "id": "type:app:demo.Api",
                "kind": "type",
                "name": "Api",
                "qualified_name": "demo.Api",
                "project_id": "app",
                "source": "app/src/main/java/demo/Api.java",
                "metadata": {"annotations": "@RestController", "language": "java"},
            },
            {
                "id": "method:app:demo.Api#get()",
                "kind": "method",
                "name": "get",
                "qualified_name": "demo.Api#get()",
                "owner_id": "type:app:demo.Api",
                "project_id": "app",
                "source": "app/src/main/java/demo/Api.java",
                "metadata": {"annotations": "@GetMapping", "language": "java"},
            },
            {
                "id": "type:app:demo.Worker",
                "kind": "type",
                "name": "Worker",
                "qualified_name": "demo.Worker",
                "project_id": "app",
                "source": "app/src/main/java/demo/Worker.java",
                "metadata": {"language": "java"},
            },
        ],
    })
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="semantic-search-workspace",
        analyzer_version="test",
    )


def _save_snapshot(root: Path) -> AtlasSemanticSnapshot:
    root.mkdir(parents=True)
    snapshot = _snapshot()
    SemanticSnapshotStore(Workspace(root, ())).save(snapshot)
    return snapshot


def test_search_help_exposes_snapshot_filters_and_output_controls() -> None:
    root_help = runner.invoke(app, ["--help"])
    search_help = runner.invoke(app, ["search", "--help"])

    assert root_help.exit_code == 0
    assert "search" in root_help.stdout
    assert search_help.exit_code == 0
    for option in (
        "--snapshot",
        "--kind",
        "--project",
        "--module",
        "--package",
        "--language",
        "--relation",
        "--min-confidence",
        "--limit",
        "--json",
        "--explain-score",
        "--profile-output",
    ):
        assert option in search_help.stdout


def test_search_json_is_deterministic_canonical_and_exactly_round_trippable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)
    arguments = ["search", "rest endpoint", str(root), "--json"]

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    restored = SemanticSearchResponse.from_dict(payload)
    assert restored.to_dict() == payload
    assert first.stdout == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    assert [hit["canonical_subject_id"] for hit in payload["hits"]] == [
        "method:app:demo.Api#get()"
    ]
    assert "app/src/main/java" not in first.stdout
    assert "@GetMapping" not in first.stdout


def test_search_human_output_is_compact_and_source_free(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    result = runner.invoke(app, ["search", "rest endpoint", str(root)])

    assert result.exit_code == 0, result.stderr
    assert "query: rest endpoint" in result.stdout
    assert "intent: concept" in result.stdout
    assert "1. get [app]" in result.stdout
    assert "method | score=" in result.stdout
    assert "confidence=" in result.stdout
    assert "concepts: rest_endpoint" in result.stdout
    assert "app/src/main" not in result.stdout


def test_search_applies_kind_and_scope_filters(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    result = runner.invoke(app, [
        "search",
        "rest endpoint",
        str(root),
        "--kind",
        "method",
        "--project",
        "app",
        "--module",
        "app",
        "--package",
        "demo",
        "--language",
        "java",
        "--min-confidence",
        "0.1",
        "--limit",
        "1",
        "--json",
    ])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["returned_count"] == 1
    assert payload["hits"][0]["kind"] == "method"
    assert payload["hits"][0]["project"] == "app"
    assert payload["hits"][0]["module"] == "app"
    assert payload["hits"][0]["package"] == "demo"
    assert payload["hits"][0]["language"] == "java"


def test_search_zero_results_is_success_and_reports_uncertainty(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    result = runner.invoke(app, [
        "search", "authentication", str(root), "--json",
    ])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hits"] == []
    assert payload["returned_count"] == 0
    assert any(
        "does not prove" in limitation
        for limitation in payload["limitations"]
    )


def test_search_cli_reports_unqualified_used_by_as_ambiguous(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    result = runner.invoke(app, [
        "search", "used by demo.Api", str(root), "--json",
    ])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hits"] == []
    assert payload["interpretation"]["ambiguous"] is True
    assert "calls (outgoing)" in payload["interpretation"]["alternatives"]
    assert any("'used by' is ambiguous" in item for item in payload["limitations"])


def test_search_rejects_an_empty_query_and_missing_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)
    empty = runner.invoke(app, ["search", "", str(root), "--json"])

    missing_root = tmp_path / "missing-snapshot"
    missing_root.mkdir()
    missing = runner.invoke(app, [
        "search", "rest endpoint", str(missing_root), "--json",
    ])

    assert empty.exit_code == 2
    assert "query must not be empty" in empty.stderr
    assert missing.exit_code == 2
    assert "semantic snapshot not found" in missing.stderr
    assert str(missing_root.resolve()) not in missing.stderr
    assert ".atlas" not in missing.stderr


def test_search_snapshot_failure_never_discloses_local_paths(tmp_path: Path) -> None:
    root = tmp_path / "corrupt-snapshot"
    target = root / ".atlas" / "ass" / "latest.ass"
    target.parent.mkdir(parents=True)
    target.write_text("not-json", encoding="utf-8")

    result = runner.invoke(app, ["search", "controller", str(root), "--json"])

    assert result.exit_code == 2
    assert "could not be loaded or verified" in result.stderr
    assert str(root.resolve()) not in result.stderr
    assert str(target.resolve()) not in result.stderr


def test_search_never_constructs_an_llm_or_rediscovers_the_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    def forbidden_provider():
        raise AssertionError("semantic search must not construct an LLM provider")

    def forbidden_context(*_args, **_kwargs):
        raise AssertionError("semantic search must not rediscover the workspace")

    monkeypatch.setattr(atlas_cli, "_ai_provider_factory", forbidden_provider)
    monkeypatch.setattr(atlas_cli, "_context", forbidden_context)

    result = runner.invoke(app, [
        "search", "demo.Api#get()", str(root), "--json",
    ])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["returned_count"] == 1


def test_search_explain_score_renders_every_deterministic_component(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)

    result = runner.invoke(app, [
        "search", "rest endpoint", str(root), "--explain-score",
    ])

    assert result.exit_code == 0, result.stderr
    assert "score components:" in result.stdout
    assert "intent_fit: value=" in result.stdout
    assert "lexical: value=" in result.stdout
    assert "evidence_quality: value=" in result.stdout
    assert "weight=" in result.stdout
    assert "contribution=" in result.stdout


def test_search_profile_sidecar_records_all_search_phases(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save_snapshot(root)
    target = tmp_path / "search-profile.json"

    result = runner.invoke(app, [
        "search",
        "rest endpoint",
        str(root),
        "--json",
        "--profile-output",
        str(target),
    ])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(target.read_text(encoding="utf-8"))
    phases = {
        "semantic_search.index",
        "semantic_search.interpret",
        "semantic_search.retrieve",
        "semantic_search.score",
        "semantic_search.sort",
        "semantic_search.evidence",
        "semantic_search.render",
    }
    assert phases <= set(payload["phase_ids"])
    assert phases <= {sample["phase_id"] for sample in payload["samples"]}
    assert str(root.resolve()).replace("\\", "/") not in target.read_text(
        encoding="utf-8",
    ).replace("\\", "/")
    assert "profile: samples=" in result.stderr
