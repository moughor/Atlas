import json

import pytest

from moughorai.rule_sdk import RuleCatalog, RuleMetadata, RuleSeverity, rule_metadata
from moughorai.sarif import (
    SARIF_SCHEMA,
    SARIF_VERSION,
    SarifExporter,
    SarifValidationError,
    validate_sarif,
)
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


def report(*findings, succeeded=True):
    status = ProjectRunStatus.SUCCEEDED if succeeded else ProjectRunStatus.FAILED
    run = ProjectRun("app", status, value={"findings": list(findings)} if succeeded else None, error=None if succeeded else "bad")
    return WorkspaceRunReport((run,), ("app",), ("app",))


def finding(**values):
    return {
        "rule_id": "SEC-1",
        "message": "unsafe",
        "severity": "high",
        "path": "src/app.py",
        "line": 2,
        "column": 3,
        **values,
    }


def test_export_has_sarif_schema_tool_and_invocation() -> None:
    value = SarifExporter().to_dict(report(finding()))
    assert value["version"] == SARIF_VERSION
    assert value["$schema"] == SARIF_SCHEMA
    run = value["runs"][0]
    assert run["tool"]["driver"]["name"] == "Atlas"
    assert run["tool"]["driver"]["version"] == "2.0.0"
    assert run["columnKind"] == "unicodeCodePoints"
    assert run["invocations"] == [{"executionSuccessful": True}]


def test_result_has_location_project_and_fingerprint() -> None:
    result = SarifExporter().to_dict(report(finding()))["runs"][0]["results"][0]
    assert result["properties"]["project"] == "app"
    assert len(result["partialFingerprints"]["atlasFinding/v1"]) == 64
    region = result["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 2, "startColumn": 3}


def test_explicit_fingerprint_is_preserved() -> None:
    result = SarifExporter().to_dict(report(finding(fingerprint="stable")))["runs"][0]["results"][0]
    assert result["partialFingerprints"]["atlasFinding/v1"] == "stable"


def test_nested_location_is_supported() -> None:
    item = {"rule_id": "R", "message": "m", "location": {"file": "a.py", "start_line": 7, "start_column": 2}}
    result = SarifExporter().to_dict(report(item))["runs"][0]["results"][0]
    assert result["locations"][0]["physicalLocation"]["region"]["startLine"] == 7


def test_properties_are_normalized() -> None:
    result = SarifExporter().to_dict(report(finding(properties={"z": object(), "a": [2, 1]})))["runs"][0]["results"][0]
    assert list(result["properties"]) == ["project", "a", "z"]
    assert result["properties"]["a"] == [2, 1]


def test_optional_fix_is_emitted() -> None:
    item = finding(fixes=[{
        "description": "replace",
        "path": "src/app.py",
        "start_line": 2,
        "start_column": 3,
        "end_line": 2,
        "end_column": 9,
        "replacement": "safe",
    }])
    fix = SarifExporter().to_dict(report(item))["runs"][0]["results"][0]["fixes"][0]
    assert fix["description"]["text"] == "replace"
    assert fix["artifactChanges"][0]["replacements"][0]["insertedContent"]["text"] == "safe"


@rule_metadata(RuleMetadata(
    "SEC-1", "Secure API", "Avoid unsafe APIs.", RuleSeverity.HIGH,
    category="security", tags=("security",), languages=("python",),
    documentation_url="https://example.test/sec-1",
))
class Rule:
    rule_id = "SEC-1"
    default_severity = RuleSeverity.HIGH
    def analyze(self, context, reporter): pass


def test_rule_catalog_enriches_sarif_descriptor() -> None:
    driver = SarifExporter().to_dict(report(finding()), catalog=RuleCatalog((Rule(),)))["runs"][0]["tool"]["driver"]
    descriptor = driver["rules"][0]
    assert descriptor["name"] == "Secure API"
    assert descriptor["helpUri"] == "https://example.test/sec-1"
    assert descriptor["properties"]["tags"] == ["security"]


def test_catalog_can_include_rule_without_findings() -> None:
    driver = SarifExporter().to_dict(report(), catalog=RuleCatalog((Rule(),)))["runs"][0]["tool"]["driver"]
    assert [item["id"] for item in driver["rules"]] == ["SEC-1"]


def test_automation_id_and_run_properties() -> None:
    run = SarifExporter().to_dict(report(), automation_id="ci/main")["runs"][0]
    assert run["automationDetails"] == {"id": "ci/main"}
    assert run["properties"]["analysisOrder"] == ["app"]
    assert run["properties"]["requested"] == ["app"]


def test_failed_report_marks_invocation_unsuccessful() -> None:
    run = SarifExporter().to_dict(report(succeeded=False))["runs"][0]
    assert run["invocations"][0]["executionSuccessful"] is False


def test_json_is_deterministic_compact_or_pretty() -> None:
    exporter = SarifExporter()
    pretty = exporter.to_json(report(finding()))
    compact = exporter.to_json(report(finding()), pretty=False)
    assert json.loads(pretty) == json.loads(compact)
    assert "\n" in pretty and "\n" not in compact
    assert pretty == exporter.to_json(report(finding()))


def test_results_sort_by_location_then_rule() -> None:
    values = (
        finding(rule_id="Z", path="b.py"),
        finding(rule_id="A", path="a.py"),
    )
    results = SarifExporter().to_dict(report(*values))["runs"][0]["results"]
    assert [item["ruleId"] for item in results] == ["A", "Z"]


def test_validation_accepts_export_and_rejects_bad_values() -> None:
    value = SarifExporter().to_dict(report())
    assert validate_sarif(value) is None
    with pytest.raises(SarifValidationError, match="version"):
        validate_sarif({"version": "1", "$schema": SARIF_SCHEMA, "runs": [{}]})
    with pytest.raises(SarifValidationError, match="runs"):
        validate_sarif({"version": SARIF_VERSION, "$schema": SARIF_SCHEMA, "runs": []})


def test_validation_requires_result_identity_and_message() -> None:
    base = {
        "version": SARIF_VERSION,
        "$schema": SARIF_SCHEMA,
        "runs": [{"tool": {"driver": {"name": "Atlas"}}, "results": [{"message": {"text": "m"}}]}],
    }
    with pytest.raises(SarifValidationError, match="ruleId"):
        validate_sarif(base)
    base["runs"][0]["results"][0]["ruleId"] = "R"
    base["runs"][0]["results"][0]["message"] = {}
    with pytest.raises(SarifValidationError, match="message"):
        validate_sarif(base)
