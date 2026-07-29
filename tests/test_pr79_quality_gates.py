from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.quality_gate import FindingSeverity, QualityGatePolicy, WorkspaceQualityGate
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


def report(*findings, succeeded: bool = True) -> WorkspaceRunReport:
    status = ProjectRunStatus.SUCCEEDED if succeeded else ProjectRunStatus.FAILED
    run = ProjectRun("app", status, value={"findings": list(findings)} if succeeded else None, error=None if succeeded else "bad")
    return WorkspaceRunReport((run,), ("app",), ("app",))


def test_gate_is_disabled_by_default() -> None:
    result = WorkspaceQualityGate().evaluate(report({"severity": "critical"}), QualityGatePolicy())
    assert result.passed
    assert result.exit_code == 0


def test_gate_applies_severity_threshold() -> None:
    result = WorkspaceQualityGate().evaluate(
        report({"severity": "low"}, {"severity": "high"}),
        QualityGatePolicy(minimum_severity=FindingSeverity.HIGH, finding_exit_code=7),
    )
    assert not result.passed
    assert result.threshold_count == 1
    assert result.exit_code == 7


def test_gate_applies_max_findings() -> None:
    result = WorkspaceQualityGate().evaluate(report({"severity": "info"}), QualityGatePolicy(max_findings=0))
    assert result.reasons == ("1 finding(s) exceed maximum 0",)


def test_policy_reads_pr71_workspace_options_and_cli_overrides() -> None:
    policy = QualityGatePolicy.from_options({
        "quality_gate.minimum_severity": "high",
        "quality_gate.max_findings": "3",
        "quality_gate.finding_exit_code": "8",
        "quality_gate.analysis_exit_code": "9",
    }, minimum_severity="critical", finding_exit_code=6)
    assert policy == QualityGatePolicy(FindingSeverity.CRITICAL, 3, 6, 9)


@pytest.mark.parametrize("code", [0, 256])
def test_policy_rejects_invalid_exit_codes(code: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 255"):
        QualityGatePolicy(finding_exit_code=code)


def workspace(tmp_path: Path, options: str = "") -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x")
    (tmp_path / "atlas.yaml").write_text(
        f"options:\n{options}"
        "projects:\n- name: app\n  path: app\n  include: ['**/*.py']\n"
    )
    return tmp_path


def test_cli_uses_configured_finding_exit_code(tmp_path: Path) -> None:
    root = workspace(tmp_path, "  quality_gate.minimum_severity: high\n  quality_gate.finding_exit_code: '7'\n")
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: {
        "findings": [{"severity": "critical", "message": "bad"}]
    }
    try:
        result = CliRunner().invoke(app, ["check", str(root)])
    finally:
        atlas_cli._analyzer_factory = None
    assert result.exit_code == 7
    assert "quality-gate:" in result.stderr


def test_cli_override_wins_and_baseline_filter_runs_before_gate(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: {
        "findings": [{"severity": "high", "fingerprint": "known"}]
    }
    baseline = tmp_path / "baseline.json"
    try:
        created = CliRunner().invoke(app, ["analyze", str(root), "--write-baseline", str(baseline)])
        checked = CliRunner().invoke(
            app, ["check", str(root), "--baseline", str(baseline), "--fail-on", "low", "--finding-exit-code", "12"]
        )
    finally:
        atlas_cli._analyzer_factory = None
    assert created.exit_code == 0
    assert checked.exit_code == 0, checked.stderr


def test_cli_uses_configured_analysis_failure_code(tmp_path: Path) -> None:
    root = workspace(tmp_path, "  quality_gate.analysis_exit_code: '13'\n")
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: (_ for _ in ()).throw(RuntimeError("bad"))
    try:
        result = CliRunner().invoke(app, ["check", str(root)])
    finally:
        atlas_cli._analyzer_factory = None
    assert result.exit_code == 13
