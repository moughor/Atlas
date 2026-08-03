from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.impact_analysis import ImpactPredictionResponse
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import Workspace


runner = CliRunner()


def _snapshot() -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                "type:base", KnowledgeKind.TYPE, "Base",
                metadata=(("visibility", "public"),),
                qualified_name="demo.Base", project_id="core", language="java",
            ),
            KnowledgeNode(
                "type:child", KnowledgeKind.TYPE, "Child",
                qualified_name="demo.Child", project_id="api", language="java",
            ),
            KnowledgeNode(
                "type:duplicate:a", KnowledgeKind.TYPE, "Duplicate",
                qualified_name="alpha.Duplicate", project_id="alpha", language="java",
            ),
            KnowledgeNode(
                "type:duplicate:b", KnowledgeKind.TYPE, "Duplicate",
                qualified_name="beta.Duplicate", project_id="beta", language="java",
            ),
        ),
        (
            KnowledgeEdge(
                "type:child", "type:base", KnowledgeRelation.INHERITS,
                ("global_symbol.metadata:inherits:demo.Base",),
            ),
        ),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr136-cli-fixture",
        analyzer_version="test/1",
    )


def _save(root: Path) -> AtlasSemanticSnapshot:
    root.mkdir(parents=True)
    snapshot = _snapshot()
    SemanticSnapshotStore(Workspace(root, ())).save(snapshot)
    return snapshot


def test_impact_help_exposes_bounded_snapshot_controls() -> None:
    root_help = runner.invoke(app, ["--help"])
    command_help = runner.invoke(app, ["impact", "--help"])

    assert root_help.exit_code == command_help.exit_code == 0
    assert "impact" in root_help.stdout
    for option in (
        "--snapshot", "--additional-sub", "--kind", "--project", "--module",
        "--package",
        "--change", "--relation", "--tests", "--depth", "--limit",
        "--json", "--explain-score", "--profile-output",
    ):
        assert option in command_help.stdout


def test_impact_json_is_deterministic_and_round_trippable(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save(root)
    arguments = [
        "impact", "demo.Base", str(root), "--change", "signature", "--json",
    ]

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    response = ImpactPredictionResponse.from_dict(payload)
    assert response.to_dict() == payload
    assert [item.subject.qualified_name for item in response.findings] == [
        "demo.Child"
    ]
    assert response.breaking_change.state.value == "potentially_breaking"


def test_impact_human_ambiguity_and_not_found_are_valid_results(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    ambiguous = runner.invoke(app, ["impact", "Duplicate", str(root)])
    missing = runner.invoke(app, ["impact", "DoesNotExist", str(root)])

    assert ambiguous.exit_code == missing.exit_code == 0
    assert "resolution: ambiguous" in ambiguous.stdout
    assert "alpha.Duplicate" in ambiguous.stdout
    assert "beta.Duplicate" in ambiguous.stdout
    assert "resolution: not_found" in missing.stdout
    assert "subject: unavailable" in missing.stdout


def test_impact_human_keeps_additional_source_status_when_primary_is_ambiguous(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    result = runner.invoke(app, [
        "impact",
        "Duplicate",
        str(root),
        "--additional-subject",
        "demo.Base",
    ])

    assert result.exit_code == 0, result.stderr
    assert "resolution: ambiguous" in result.stdout
    assert "additional-sources: 1" in result.stdout
    assert "demo.Base status=resolved" in result.stdout
    assert "External consumers may still exist." in result.stdout


def test_impact_human_zero_result_preserves_external_uncertainty(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    result = runner.invoke(
        app,
        ["impact", "demo.Child", str(root), "--change", "signature"],
    )

    assert result.exit_code == 0, result.stderr
    assert "No affected in-repository subject was proven" in result.stdout
    assert "External consumers may still exist." in result.stdout
    assert "Call-based impact was not evaluated" in result.stdout


def test_impact_missing_snapshot_error_is_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "missing"

    result = runner.invoke(app, ["impact", "demo.Base", str(root), "--json"])

    assert result.exit_code == 2
    assert (
        "error: semantic snapshot not found; run analysis snapshot creation first"
        in result.stderr
    )
    assert str(root) not in result.stderr


@pytest.mark.parametrize(
    ("option", "value"),
    (
        ("--kind", "not-a-kind"),
        ("--relation", "not-a-relation"),
        ("--change", "not-a-change"),
    ),
)
def test_impact_malformed_enum_options_follow_cli_error_convention(
    option: str,
    value: str,
) -> None:
    result = runner.invoke(app, ["impact", "demo.Base", option, value])

    assert result.exit_code == 2
    assert "Traceback" not in result.stderr


def test_impact_filters_are_applied_without_guessing(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _save(root)
    constrained = runner.invoke(app, [
        "impact", "demo.Base", str(root),
        "--kind", "type",
        "--project", "core",
        "--language", "java",
        "--module", "core",
        "--package", "demo",
        "--relation", "inheritance",
        "--no-dependencies",
        "--json",
    ])
    unavailable_scope = runner.invoke(app, [
        "impact", "demo.Base", str(root), "--package", "other", "--json",
    ])

    assert constrained.exit_code == unavailable_scope.exit_code == 0
    response = ImpactPredictionResponse.from_dict(json.loads(constrained.stdout))
    assert [item.subject.qualified_name for item in response.findings] == [
        "demo.Child"
    ]
    assert response.request.include_dependencies is False
    assert [item.value for item in response.request.relations] == ["inheritance"]
    assert json.loads(unavailable_scope.stdout)["resolution"]["status"] == "not_found"


def test_impact_corrupt_explicit_snapshot_error_is_sanitized(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    corrupt = root / "private-invalid.ass"
    corrupt.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(app, [
        "impact", "demo.Base", str(root), "--snapshot", str(corrupt), "--json",
    ])

    assert result.exit_code == 2
    assert "error: semantic snapshot could not be loaded or verified" in result.stderr
    assert str(corrupt) not in result.stderr
    assert "Traceback" not in result.stderr


def test_impact_profile_sidecar_is_opt_in_and_does_not_change_json(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    sidecar = root / ".atlas" / "measurements" / "impact-test.json"

    baseline = runner.invoke(
        app, ["impact", "demo.Base", str(root), "--json"],
    )
    profiled = runner.invoke(app, [
        "impact", "demo.Base", str(root), "--json",
        "--profile-output", str(sidecar),
    ])

    assert baseline.exit_code == profiled.exit_code == 0
    assert baseline.stdout == profiled.stdout
    assert sidecar.is_file()
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {
        "impact_prediction.resolver_index",
        "impact_prediction.index",
        "impact_prediction.query",
        "impact_prediction.resolve",
        "impact_prediction.sort",
        "impact_prediction.render",
    }.issubset(report["phase_ids"])
    assert "profile:" in profiled.stderr
