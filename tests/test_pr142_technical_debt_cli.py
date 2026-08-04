from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import moughorai.technical_debt as technical_debt_api
from moughorai.atlas_cli import app
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.knowledge_graph import KnowledgeKind
from moughorai.subject_resolution import SubjectQuery
from moughorai.technical_debt import TechnicalDebtResponse
from moughorai.workspace import Workspace

from test_pr142_technical_debt import _snapshot


runner = CliRunner()


def _save(root: Path) -> Path:
    root.mkdir(parents=True)
    SemanticSnapshotStore(Workspace(root, ())).save(_snapshot())
    return root / ".atlas" / "ass" / "latest.ass"


def _arguments(root: Path, *extra: str) -> list[str]:
    return [
        "debt",
        str(root),
        "--subject",
        "project:alpha",
        "--kind",
        "project",
        *extra,
    ]


def test_debt_help_exposes_bounded_snapshot_and_profile_controls() -> None:
    root_help = runner.invoke(app, ["--help"])
    command_help = runner.invoke(app, ["debt", "--help"])

    assert root_help.exit_code == command_help.exit_code == 0
    assert "debt" in root_help.stdout
    for option in (
        "--snapshot",
        "--subject",
        "--kind",
        "--project",
        "--language",
        "--path",
        "--limit",
        "--candidate-limit",
        "--impact-depth",
        "--json",
        "--profile-output",
    ):
        assert option in command_help.stdout


def test_debt_json_is_deterministic_canonical_and_round_trippable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    arguments = _arguments(root, "--json")

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    response = TechnicalDebtResponse.from_dict(payload)
    assert response.to_dict() == payload
    assert response.total_candidate_count == 3
    assert response.returned_count == response.ranked_count == 3


def test_debt_human_output_is_compact_honest_and_source_free(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    result = runner.invoke(app, _arguments(root))

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Atlas Technical Debt Observations\n")
    assert "ordinal-only=yes" in result.stdout
    assert "dependency_cycle" in result.stdout or "Dependency-Cycle" in result.stdout
    assert "not by itself proof" in result.stdout
    assert "developer intent" in result.stdout
    assert not contains_absolute_path(result.stdout)
    assert "```" not in result.stdout


def test_debt_missing_and_corrupt_snapshot_errors_are_sanitized(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "private-missing"
    missing = runner.invoke(app, _arguments(missing_root, "--json"))

    assert missing.exit_code == 2
    assert "semantic snapshot not found; run analysis snapshot creation first" in missing.stderr
    assert str(missing_root) not in missing.stderr
    assert "Traceback" not in missing.stderr

    root = tmp_path / "workspace"
    root.mkdir()
    corrupt = root / "private-corrupt.ass"
    corrupt.write_text("{not-json", encoding="utf-8")
    invalid = runner.invoke(app, _arguments(
        root,
        "--snapshot",
        str(corrupt),
        "--json",
    ))

    assert invalid.exit_code == 2
    assert "semantic snapshot could not be loaded or verified" in invalid.stderr
    assert str(corrupt) not in invalid.stderr
    assert "Traceback" not in invalid.stderr


@pytest.mark.parametrize(
    ("option", "value"),
    (
        ("--kind", "not-a-kind"),
        ("--limit", "0"),
        ("--candidate-limit", "257"),
        ("--impact-depth", "0"),
    ),
)
def test_debt_invalid_options_follow_cli_error_convention(
    option: str,
    value: str,
) -> None:
    result = runner.invoke(app, ["debt", option, value])

    assert result.exit_code == 2
    assert "Traceback" not in result.stderr


def test_debt_profile_is_opt_in_semantically_inert_and_snapshot_read_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    snapshot_path = _save(root)
    before = snapshot_path.read_bytes()
    sidecar = root / ".atlas" / "measurements" / "debt-test.json"

    baseline = runner.invoke(app, _arguments(root, "--json"))
    profiled = runner.invoke(app, _arguments(
        root,
        "--json",
        "--profile-output",
        str(sidecar),
    ))

    assert baseline.exit_code == profiled.exit_code == 0
    assert baseline.stdout == profiled.stdout
    assert snapshot_path.read_bytes() == before
    assert sidecar.is_file()
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {
        "technical_debt.prepare",
        "technical_debt.query",
        "technical_debt.cycle_candidates",
        "technical_debt.impact",
        "technical_debt.render",
    }.issubset(report["phase_ids"])
    assert "profile:" in profiled.stderr


def test_public_package_exports_are_provisional_and_renderer_is_source_free() -> None:
    response = technical_debt_api.TechnicalDebtService.from_snapshot(
        _snapshot()
    ).analyze(technical_debt_api.TechnicalDebtRequest(
        SubjectQuery("project:alpha", KnowledgeKind.PROJECT)
    ))
    rendered = technical_debt_api.render_technical_debt(response)

    for public_name in (
        "TechnicalDebtService",
        "TechnicalDebtRequest",
        "TechnicalDebtResponse",
        "TechnicalDebtItem",
        "TechnicalDebtState",
        "render_technical_debt",
    ):
        assert public_name in technical_debt_api.__all__
        assert getattr(technical_debt_api, public_name) is not None
    assert rendered.startswith("Atlas Technical Debt Observations\n")
    assert not contains_absolute_path(rendered)
