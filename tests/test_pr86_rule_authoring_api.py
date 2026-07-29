from pathlib import Path

import pytest

from moughorai.rule_sdk import (
    RuleAuthoringError,
    RuleContext,
    RuleExecutionError,
    RuleRegistry,
    RuleReporter,
    RuleRunner,
    RuleSeverity,
)


class TodoRule:
    rule_id = "ATLAS-TODO"
    default_severity = RuleSeverity.LOW

    def analyze(self, context, reporter):
        for line, text in enumerate(context.source.splitlines(), 1):
            if "TODO" in text:
                reporter.report("TODO marker", line=line, column=text.index("TODO") + 1)


def context(source="TODO") -> RuleContext:
    return RuleContext(Path("src/app.py"), source, "python", {"mode": "strict"})


def test_author_can_report_findings() -> None:
    findings = RuleRunner().run((TodoRule(),), context("ok\n# TODO"))
    assert len(findings) == 1
    assert findings[0].rule_id == "ATLAS-TODO"
    assert findings[0].location.line == 2
    assert findings[0].severity is RuleSeverity.LOW


def test_reporter_supports_severity_and_sorted_data() -> None:
    reporter = RuleReporter("R", RuleSeverity.MEDIUM, context())
    finding = reporter.report("bad", severity="high", data={"z": 2, "a": 1})
    assert finding.severity is RuleSeverity.HIGH
    assert finding.data == (("a", 1), ("z", 2))


def test_finding_serializes_for_workspace_reports() -> None:
    finding = RuleRunner().run((TodoRule(),), context())[0].to_dict()
    assert finding == {
        "rule_id": "ATLAS-TODO",
        "message": "TODO marker",
        "severity": "low",
        "path": "src/app.py",
        "line": 1,
        "column": 1,
    }


def test_runner_is_rule_and_finding_deterministic() -> None:
    class Z(TodoRule):
        rule_id = "Z"
    class A(TodoRule):
        rule_id = "A"
    assert [item.rule_id for item in RuleRunner().run((Z(), A()), context())] == ["A", "Z"]


def test_duplicate_findings_are_deduplicated() -> None:
    class Duplicate(TodoRule):
        def analyze(self, context, reporter):
            reporter.report("same")
            reporter.report("same")
    assert len(RuleRunner().run((Duplicate(),), context())) == 1


def test_duplicate_rule_ids_are_rejected() -> None:
    with pytest.raises(RuleAuthoringError, match="duplicate"):
        RuleRunner().run((TodoRule(), TodoRule()), context())


def test_rule_must_return_none() -> None:
    class Returning(TodoRule):
        def analyze(self, context, reporter):
            return []
    with pytest.raises(RuleAuthoringError, match="return None"):
        RuleRunner().run((Returning(),), context())


def test_rule_exception_has_rule_identity() -> None:
    class Broken(TodoRule):
        def analyze(self, context, reporter):
            raise RuntimeError("boom")
    with pytest.raises(RuleExecutionError, match="ATLAS-TODO: RuntimeError: boom"):
        RuleRunner().run((Broken(),), context())


def test_registry_registers_and_runs_rules() -> None:
    registry = RuleRegistry()
    registry.register(TodoRule())
    assert registry.get("ATLAS-TODO").rule_id == "ATLAS-TODO"
    assert len(registry.run(context())) == 1


def test_registry_is_sorted_and_conflict_safe() -> None:
    class Z(TodoRule):
        rule_id = "Z"
    registry = RuleRegistry((Z(), TodoRule()))
    assert [rule.rule_id for rule in registry.rules()] == ["ATLAS-TODO", "Z"]
    with pytest.raises(RuleAuthoringError, match="duplicate"):
        registry.register(TodoRule())


def test_registry_unknown_rule_error() -> None:
    with pytest.raises(KeyError, match="unknown rule"):
        RuleRegistry().get("missing")


def test_context_validation_and_configuration_copy() -> None:
    values = {"x": 1}
    item = RuleContext(Path("a"), "x", "python", values)
    values["x"] = 2
    assert item.configuration == {"x": 1}
    with pytest.raises(ValueError, match="language"):
        RuleContext(Path("a"), "x", "", {})


def test_locations_are_one_based() -> None:
    reporter = RuleReporter("R", RuleSeverity.LOW, context())
    with pytest.raises(ValueError, match="one-based"):
        reporter.report("bad", line=0)


def test_empty_rule_and_message_are_rejected() -> None:
    with pytest.raises(RuleAuthoringError, match="rule_id"):
        RuleReporter("", RuleSeverity.LOW, context())
    with pytest.raises(ValueError, match="message"):
        RuleReporter("R", RuleSeverity.LOW, context()).report("")
