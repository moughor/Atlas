from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import moughorai.refactoring_advisor as refactoring_api
from moughorai.atlas_cli import app
from moughorai.refactoring_advisor import (
    RefactoringCapabilityState,
    RefactoringFamily,
    RefactoringResponse,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Workspace

from test_pr137_refactoring_advisor import _advise, _snapshot


runner = CliRunner()


def _save(root: Path) -> None:
    root.mkdir(parents=True)
    SemanticSnapshotStore(Workspace(root, ())).save(_snapshot())


def _cycle_arguments(root: Path, *extra: str) -> list[str]:
    return [
        "refactor",
        str(root),
        "--subject",
        "project:alpha",
        "--kind",
        "project",
        "--family",
        "cycle-breaking",
        "--no-impact",
        *extra,
    ]


def test_refactor_help_exposes_bounded_snapshot_and_profile_controls() -> None:
    root_help = runner.invoke(app, ["--help"])
    command_help = runner.invoke(app, ["refactor", "--help"])

    assert root_help.exit_code == command_help.exit_code == 0
    assert "refactor" in root_help.stdout
    for option in (
        "--snapshot",
        "--subject",
        "--kind",
        "--project",
        "--language",
        "--path",
        "--family",
        "--limit",
        "--impact",
        "--impact-depth",
        "--json",
        "--explain-score",
        "--profile-output",
    ):
        assert option in command_help.stdout


def test_refactor_json_is_deterministic_canonical_and_round_trippable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    arguments = _cycle_arguments(root, "--json")

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    response = RefactoringResponse.from_dict(payload)
    assert response.to_dict() == payload
    assert response.request.families == (RefactoringFamily.CYCLE_BREAKING,)
    assert response.total_candidate_count == 3
    assert len(response.advice) == 3


def test_refactor_human_output_is_directed_compact_and_source_free(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    result = runner.invoke(app, _cycle_arguments(root, "--explain-score"))

    assert result.exit_code == 0, result.stderr
    assert "Atlas refactoring advisor" in result.stdout
    assert "resolution: resolved" in result.stdout
    assert "review_dependency_cycle_seam:" in result.stdout
    assert "alpha -> beta" in result.stdout
    assert "confidence:" in result.stdout
    assert "expected-gain:" in result.stdout
    assert "effort:" in result.stdout
    assert "precondition:" in result.stdout
    assert "verify:" in result.stdout
    assert not contains_absolute_path(result.stdout)
    assert "```" not in result.stdout


def test_refactor_explicit_unavailable_family_does_not_infer_advice(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    result = runner.invoke(app, [
        "refactor",
        str(root),
        "--subject",
        "project:alpha",
        "--kind",
        "project",
        "--family",
        "extraction",
        "--no-impact",
        "--json",
    ])

    assert result.exit_code == 0, result.stderr
    response = RefactoringResponse.from_dict(json.loads(result.stdout))
    capability = next(
        item
        for item in response.capabilities
        if item.family is RefactoringFamily.EXTRACTION
    )
    assert response.request.families == (RefactoringFamily.EXTRACTION,)
    assert response.advice == ()
    assert response.total_candidate_count == 0
    assert capability.state is RefactoringCapabilityState.INSUFFICIENT
    assert capability.limitations
    cycle_capability = next(
        item
        for item in response.capabilities
        if item.family is RefactoringFamily.CYCLE_BREAKING
    )
    assert cycle_capability.state is RefactoringCapabilityState.UNAVAILABLE
    assert cycle_capability.coverage is None


def test_refactor_missing_snapshot_error_is_sanitized(tmp_path: Path) -> None:
    root = tmp_path / "private-missing-workspace"

    result = runner.invoke(app, _cycle_arguments(root, "--json"))

    assert result.exit_code == 2
    assert (
        "error: semantic snapshot not found; run analysis snapshot creation first"
        in result.stderr
    )
    assert str(root) not in result.stderr
    assert "Traceback" not in result.stderr


def test_refactor_corrupt_explicit_snapshot_error_is_sanitized(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    corrupt = root / "private-invalid.ass"
    corrupt.write_text("{not-json", encoding="utf-8")

    result = runner.invoke(app, [
        "refactor",
        str(root),
        "--snapshot",
        str(corrupt),
        "--subject",
        "project:alpha",
        "--json",
    ])

    assert result.exit_code == 2
    assert "error: semantic snapshot could not be loaded or verified" in result.stderr
    assert str(corrupt) not in result.stderr
    assert "Traceback" not in result.stderr


def test_refactor_profile_sidecar_is_opt_in_and_semantically_inert(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    sidecar = root / ".atlas" / "measurements" / "refactor-test.json"

    baseline = runner.invoke(app, _cycle_arguments(root, "--json"))
    profiled = runner.invoke(app, _cycle_arguments(
        root,
        "--json",
        "--profile-output",
        str(sidecar),
    ))

    assert baseline.exit_code == profiled.exit_code == 0
    assert baseline.stdout == profiled.stdout
    assert sidecar.is_file()
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {
        "refactoring_advisor.resolver_index",
        "refactoring_advisor.query",
        "refactoring_advisor.resolve",
        "refactoring_advisor.cycle_validate",
        "refactoring_advisor.impact",
        "refactoring_advisor.materialize",
        "refactoring_advisor.render",
    }.issubset(report["phase_ids"])
    assert "profile:" in profiled.stderr


@pytest.mark.parametrize(
    ("option", "value"),
    (
        ("--kind", "not-a-kind"),
        ("--family", "not-a-family"),
    ),
)
def test_refactor_malformed_enum_options_follow_cli_error_convention(
    option: str,
    value: str,
) -> None:
    result = runner.invoke(app, ["refactor", option, value])

    assert result.exit_code == 2
    assert "Traceback" not in result.stderr


def test_public_package_exports_and_renderer_remain_source_free() -> None:
    response = _advise()
    rendered = refactoring_api.render_refactoring_advice(
        response,
        explain_score=True,
    )

    for public_name in (
        "RefactoringAdvisorService",
        "RefactoringRequest",
        "RefactoringResponse",
        "RefactoringAdvice",
        "RefactoringFamily",
        "RefactoringCapabilityState",
        "render_refactoring_advice",
    ):
        assert public_name in refactoring_api.__all__
        assert getattr(refactoring_api, public_name) is not None
    assert rendered.startswith("Atlas refactoring advisor\n")
    assert not contains_absolute_path(rendered)
    assert "```" not in rendered
