from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.finding_baseline import (
    FINDING_BASELINE_SCHEMA_VERSION,
    FindingBaseline,
    FindingBaselineError,
    FindingBaselineService,
    FindingBaselineStore,
)
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_factory():
    previous = atlas_cli._analyzer_factory
    atlas_cli._analyzer_factory = None
    yield
    atlas_cli._analyzer_factory = previous


def finding(rule: str = "R1", message: str = "issue", path: str = "a.py", line: int = 1):
    return {"rule_id": rule, "message": message, "path": path, "line": line}


def report(*findings, project: str = "core") -> WorkspaceRunReport:
    run = ProjectRun(project, ProjectRunStatus.SUCCEEDED, value={"findings": list(findings)})
    return WorkspaceRunReport((run,), (project,), (project,))


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text("projects:\n  - name: core\n    path: core\n", encoding="utf-8")
    return tmp_path


def analyzer_with(findings):
    return lambda service: lambda project, dependencies: {"findings": list(findings)}


def test_capture_creates_sorted_unique_fingerprints() -> None:
    service = FindingBaselineService()
    baseline = service.capture(report(finding("B"), finding("A"), finding("B")), created_at="2026-01-01T00:00:00+00:00")
    assert baseline.schema_version == FINDING_BASELINE_SCHEMA_VERSION
    assert baseline.fingerprints == tuple(sorted(set(baseline.fingerprints)))
    assert len(baseline.fingerprints) == 2


def test_identical_finding_is_existing() -> None:
    service = FindingBaselineService()
    current = report(finding())
    comparison = service.compare(current, service.capture(current))
    assert comparison.new_count == 0
    assert comparison.existing_count == 1


def test_changed_finding_is_new() -> None:
    service = FindingBaselineService()
    baseline = service.capture(report(finding(message="old")))
    comparison = service.compare(report(finding(message="new")), baseline)
    assert comparison.new_count == 1
    assert comparison.existing_count == 0


def test_explicit_fingerprint_is_stable_across_message_changes() -> None:
    service = FindingBaselineService()
    old = {"fingerprint": "stable", "message": "old"}
    new = {"fingerprint": "stable", "message": "new"}
    baseline = service.capture(report(old))
    assert service.compare(report(new), baseline).existing_count == 1


def test_project_is_part_of_fingerprint() -> None:
    service = FindingBaselineService()
    baseline = service.capture(report(finding(), project="core"))
    assert service.compare(report(finding(), project="api"), baseline).new_count == 1


def test_filter_removes_existing_findings_only() -> None:
    service = FindingBaselineService()
    old = finding("OLD")
    new = finding("NEW")
    filtered, comparison = service.filter(report(old, new), service.capture(report(old)))
    assert filtered.runs[0].value["findings"] == [new]
    assert filtered.runs[0].value["baseline"] == {"new_count": 1, "existing_count": 1}
    assert comparison.new_count == comparison.existing_count == 1


def test_filter_preserves_non_finding_results() -> None:
    run = ProjectRun("core", ProjectRunStatus.SUCCEEDED, value={"files": 3})
    value = WorkspaceRunReport((run,), ("core",), ("core",))
    filtered, _ = FindingBaselineService().filter(value, FindingBaselineService().capture(value))
    assert filtered == value


def test_comparison_serialization() -> None:
    service = FindingBaselineService()
    comparison = service.compare(report(finding("N")), service.capture(report(finding("E"))))
    data = comparison.to_dict()
    assert data["new_count"] == 1 and data["existing_count"] == 0
    assert list(data) == ["new", "existing", "new_count", "existing_count"]


def test_store_round_trip(tmp_path: Path) -> None:
    baseline = FindingBaselineService().capture(report(finding()))
    store = FindingBaselineStore(tmp_path / "nested" / "baseline.json")
    assert store.save(baseline) == store.path
    assert store.load() == baseline


def test_store_shape_has_checksum(tmp_path: Path) -> None:
    store = FindingBaselineStore(tmp_path / "baseline.json")
    store.save(FindingBaselineService().capture(report(finding())))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert sorted(payload) == ["baseline", "checksum"]


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    store = FindingBaselineStore(tmp_path / "baseline.json")
    store.save(FindingBaselineService().capture(report(finding())))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["baseline"]["fingerprints"] = []
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FindingBaselineError, match="checksum"):
        store.load()


def test_invalid_schema_is_rejected() -> None:
    with pytest.raises(FindingBaselineError, match="unsupported"):
        FindingBaseline(99, (), "2026-01-01T00:00:00+00:00")


def test_unsorted_fingerprints_are_rejected() -> None:
    with pytest.raises(FindingBaselineError, match="unique and sorted"):
        FindingBaseline(1, ("z", "a"), "2026-01-01T00:00:00+00:00")


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(FindingBaselineError, match="timezone"):
        FindingBaseline.from_dict({"schema_version": 1, "fingerprints": [], "created_at": "2026-01-01T00:00:00"})


def test_missing_baseline_file_propagates(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FindingBaselineStore(tmp_path / "missing.json").load()


def test_cli_writes_baseline(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    path = tmp_path / "accepted.json"
    atlas_cli._analyzer_factory = analyzer_with([finding()])
    result = runner.invoke(app, ["analyze", str(root), "--no-recover", "--write-baseline", str(path), "--format", "json"])
    assert result.exit_code == 0
    assert path.exists()
    assert len(FindingBaselineStore(path).load().fingerprints) == 1


def test_cli_reports_only_new_findings(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    path = tmp_path / "accepted.json"
    FindingBaselineStore(path).save(FindingBaselineService().capture(report(finding("OLD"))))
    atlas_cli._analyzer_factory = analyzer_with([finding("OLD"), finding("NEW")])
    result = runner.invoke(app, ["analyze", str(root), "--no-recover", "--baseline", str(path), "--format", "json"])
    assert result.exit_code == 0
    value = json.loads(result.stdout)["runs"][0]["value"]
    assert [item["rule_id"] for item in value["findings"]] == ["NEW"]
    assert value["baseline"] == {"existing_count": 1, "new_count": 1}


def test_cli_sarif_excludes_existing_findings(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    path = tmp_path / "accepted.json"
    FindingBaselineStore(path).save(FindingBaselineService().capture(report(finding("OLD"))))
    atlas_cli._analyzer_factory = analyzer_with([finding("OLD"), finding("NEW")])
    result = runner.invoke(app, ["analyze", str(root), "--no-recover", "--baseline", str(path), "--format", "sarif"])
    rules = json.loads(result.stdout)["runs"][0]["results"]
    assert [item["ruleId"] for item in rules] == ["NEW"]


def test_cli_corrupt_baseline_returns_input_error(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    result = runner.invoke(app, ["analyze", str(root), "--no-recover", "--baseline", str(path)])
    assert result.exit_code == 2
    assert "finding baseline" in result.stderr


def test_cli_help_documents_baseline_options() -> None:
    for command in ("analyze", "check"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert "--baseline" in result.stdout
        assert "--write-baseline" in result.stdout


def test_baseline_does_not_mutate_original_report() -> None:
    service = FindingBaselineService()
    original = report(finding())
    baseline = service.capture(original)
    filtered, _ = service.filter(original, baseline)
    assert original.runs[0].value["findings"] == [finding()]
    assert filtered.runs[0].value["findings"] == []
