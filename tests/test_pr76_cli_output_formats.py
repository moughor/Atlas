from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.cli_output import OutputFormat, render_report, report_payload
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_factory():
    previous = atlas_cli._analyzer_factory
    atlas_cli._analyzer_factory = None
    yield
    atlas_cli._analyzer_factory = previous


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "main.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: core\n    path: core\n",
        encoding="utf-8",
    )
    return tmp_path


def report(*runs: ProjectRun) -> WorkspaceRunReport:
    names = tuple(run.project for run in runs)
    return WorkspaceRunReport(tuple(runs), names, names)


def test_output_format_values() -> None:
    assert [item.value for item in OutputFormat] == ["text", "json", "jsonl", "sarif"]


def test_text_preserves_pr75_output() -> None:
    value = report(ProjectRun("core", ProjectRunStatus.SUCCEEDED, value={"x": 1}))
    assert render_report(value, OutputFormat.TEXT) == "core: succeeded\nprojects: 1\nsucceeded: yes"


def test_json_is_valid_and_stably_indented() -> None:
    value = report(ProjectRun("core", ProjectRunStatus.SUCCEEDED, value={"z": 1, "a": 2}))
    text = render_report(value, "json")
    assert json.loads(text)["runs"][0]["value"] == {"a": 2, "z": 1}
    assert text.startswith("{\n  \"analysis_order\"")


def test_json_omits_nondeterministic_duration() -> None:
    value = report(ProjectRun("core", ProjectRunStatus.SUCCEEDED, duration_ms=123.456))
    assert "duration" not in render_report(value, "json")


def test_json_includes_errors_and_blockers() -> None:
    value = report(
        ProjectRun("core", ProjectRunStatus.FAILED, error="bad"),
        ProjectRun("api", ProjectRunStatus.BLOCKED, blocked_by=("core",)),
    )
    payload = json.loads(render_report(value, "json"))
    assert payload["runs"][0]["error"] == "bad"
    assert payload["runs"][1]["blocked_by"] == ["core"]


def test_jsonl_has_one_project_record_and_summary() -> None:
    value = report(ProjectRun("core", ProjectRunStatus.SUCCEEDED))
    records = [json.loads(line) for line in render_report(value, "jsonl").splitlines()]
    assert records[0] == {"project": "core", "status": "succeeded", "type": "project"}
    assert records[1]["type"] == "summary"
    assert records[1]["projects"] == 1


def test_jsonl_follows_report_order() -> None:
    value = report(
        ProjectRun("core", ProjectRunStatus.SUCCEEDED),
        ProjectRun("api", ProjectRunStatus.SUCCEEDED),
    )
    records = [json.loads(line) for line in render_report(value, "jsonl").splitlines()]
    assert [item.get("project") for item in records[:-1]] == ["core", "api"]


def test_sarif_has_required_version_and_schema() -> None:
    payload = json.loads(render_report(report(ProjectRun("core", ProjectRunStatus.SUCCEEDED)), "sarif"))
    assert payload["version"] == "2.1.0"
    assert payload["$schema"].endswith("sarif-2.1.0.json")
    assert payload["runs"][0]["tool"]["driver"]["name"] == "Atlas"


def test_sarif_converts_findings() -> None:
    finding = {"rule_id": "SEC001", "message": "unsafe", "level": "error", "path": "src/A.java", "line": 7, "column": 3}
    value = report(ProjectRun("core", ProjectRunStatus.SUCCEEDED, value={"findings": [finding]}))
    result = json.loads(render_report(value, "sarif"))["runs"][0]["results"][0]
    assert result["ruleId"] == "SEC001"
    assert result["level"] == "error"
    assert result["locations"][0]["physicalLocation"]["region"] == {"startColumn": 3, "startLine": 7}


@pytest.mark.parametrize(
    ("severity", "expected"),
    [("critical", "error"), ("high", "error"), ("medium", "warning"), ("info", "note"), ("off", "none")],
)
def test_sarif_maps_severity(severity: str, expected: str) -> None:
    finding = {"ruleId": "R", "message": "m", "severity": severity}
    value = report(ProjectRun("p", ProjectRunStatus.SUCCEEDED, value={"findings": [finding]}))
    result = json.loads(render_report(value, "sarif"))["runs"][0]["results"][0]
    assert result["level"] == expected


def test_sarif_sorts_results_deterministically() -> None:
    findings = [
        {"rule_id": "Z", "message": "z", "path": "b.py", "line": 2},
        {"rule_id": "A", "message": "a", "path": "a.py", "line": 9},
    ]
    value = report(ProjectRun("p", ProjectRunStatus.SUCCEEDED, value={"findings": findings}))
    results = json.loads(render_report(value, "sarif"))["runs"][0]["results"]
    assert [item["ruleId"] for item in results] == ["A", "Z"]


def test_sarif_deduplicates_rule_metadata() -> None:
    findings = [{"rule_id": "R", "message": "one"}, {"rule_id": "R", "message": "two"}]
    value = report(ProjectRun("p", ProjectRunStatus.SUCCEEDED, value={"findings": findings}))
    driver = json.loads(render_report(value, "sarif"))["runs"][0]["tool"]["driver"]
    assert driver["rules"] == [{"id": "R", "shortDescription": {"text": "R"}}]


def test_report_payload_normalizes_unknown_values() -> None:
    class Value:
        def __str__(self):
            return "stable"
    value = report(ProjectRun("p", ProjectRunStatus.SUCCEEDED, value={"item": Value()}))
    assert report_payload(value)["runs"][0]["value"] == {"item": "stable"}


def test_invalid_format_is_rejected() -> None:
    with pytest.raises(ValueError):
        render_report(report(), "xml")


@pytest.mark.parametrize("output_format", ["json", "jsonl", "sarif"])
def test_analyze_cli_supports_structured_format(tmp_path: Path, output_format: str) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "--no-recover", "--format", output_format])
    assert result.exit_code == 0
    if output_format == "jsonl":
        assert all(json.loads(line) for line in result.stdout.splitlines())
    else:
        assert json.loads(result.stdout)


def test_analyze_json_is_repeatable(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    first = runner.invoke(app, ["analyze", str(root), "--no-recover", "--format", "json"])
    second = runner.invoke(app, ["analyze", str(root), "--no-recover", "--format", "json"])
    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout


def test_check_json_preserves_failure_exit_code(tmp_path: Path) -> None:
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: (_ for _ in ()).throw(RuntimeError("bad"))
    result = runner.invoke(app, ["check", str(workspace(tmp_path)), "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["succeeded"] is False


def test_check_sarif_contains_analyzer_findings(tmp_path: Path) -> None:
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: {
        "findings": [{"rule_id": "T1", "message": "test", "path": "main.py"}]
    }
    result = runner.invoke(app, ["check", str(workspace(tmp_path)), "--format", "sarif"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["runs"][0]["results"][0]["ruleId"] == "T1"


def test_help_documents_all_formats() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--format" in result.stdout
    assert "text" in result.stdout and "jsonl" in result.stdout and "sarif" in result.stdout
