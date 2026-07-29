from pathlib import Path

import pytest

from moughorai.rule_sdk import (
    ExpectedFinding,
    RuleSeverity,
    RuleTestCase,
    RuleTestHarness,
)


class TodoRule:
    rule_id = "TODO"
    default_severity = RuleSeverity.LOW

    def analyze(self, context, reporter):
        for line, text in enumerate(context.source.splitlines(), 1):
            if "TODO" in text:
                reporter.report("TODO marker", line=line, column=text.index("TODO") + 1)


def test_harness_runs_single_rule() -> None:
    result = RuleTestHarness(TodoRule(), language="python", path="app.py").run("# TODO")
    result.assert_count(1).assert_findings((ExpectedFinding("TODO", 1, 3),))


def test_clean_assertion() -> None:
    assert RuleTestHarness(TodoRule()).run("clean").assert_clean().findings == ()


def test_assertion_failures_are_descriptive() -> None:
    with pytest.raises(AssertionError, match=r"expected 2 finding\(s\), got 1"):
        RuleTestHarness(TodoRule()).run("TODO", name="count case").assert_count(2)
    with pytest.raises(AssertionError, match="expected no findings"):
        RuleTestHarness(TodoRule()).run("TODO", name="clean case").assert_clean()


def test_expected_finding_matches_optional_fields() -> None:
    result = RuleTestHarness(TodoRule()).run("TODO")
    result.assert_findings((
        ExpectedFinding("TODO", 1, column=1, message="TODO marker", severity=RuleSeverity.LOW),
    ))


def test_non_exact_matching_allows_additional_findings() -> None:
    result = RuleTestHarness(TodoRule()).run("TODO\nTODO")
    result.assert_findings((ExpectedFinding("TODO", 1),), exact=False)


def test_exact_matching_rejects_additional_findings() -> None:
    result = RuleTestHarness(TodoRule()).run("TODO\nTODO")
    with pytest.raises(AssertionError, match="unexpected"):
        result.assert_findings((ExpectedFinding("TODO", 1),))


def test_missing_finding_is_reported() -> None:
    with pytest.raises(AssertionError, match="missing"):
        RuleTestHarness(TodoRule()).run("clean").assert_findings((ExpectedFinding("TODO", 1),))


def test_cases_are_run_in_name_order() -> None:
    harness = RuleTestHarness(TodoRule())
    results = harness.run_cases((RuleTestCase("z", "TODO"), RuleTestCase("a", "clean")))
    assert [result.case.name for result in results] == ["a", "z"]


def test_duplicate_case_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        RuleTestHarness(TodoRule()).run_cases((RuleTestCase("same", ""), RuleTestCase("same", "")))


def test_case_context_carries_configuration() -> None:
    seen = []

    class ConfigRule(TodoRule):
        def analyze(self, context, reporter):
            seen.append(context.configuration["mode"])

    case = RuleTestCase("config", "", Path("a.py"), "python", (("mode", "strict"),))
    RuleTestHarness(ConfigRule()).run_case(case)
    assert seen == ["strict"]


def test_harness_defaults_are_applied() -> None:
    seen = []

    class ContextRule(TodoRule):
        def analyze(self, context, reporter):
            seen.append((context.path, context.language, context.configuration["x"]))

    RuleTestHarness(ContextRule(), path="x.py", language="python", configuration={"x": 1}).run("")
    assert seen == [(Path("x.py"), "python", 1)]


def test_case_validation() -> None:
    with pytest.raises(ValueError, match="name"):
        RuleTestCase("", "")
    with pytest.raises(ValueError, match="sorted"):
        RuleTestCase("x", "", configuration=(("z", 1), ("a", 2)))


def test_result_serialization_is_deterministic() -> None:
    value = RuleTestHarness(TodoRule(), path="a.py").run("TODO", name="case").to_dict()
    assert value["name"] == "case"
    assert value["findings"][0]["rule_id"] == "TODO"


def test_result_description_contains_identity_and_location() -> None:
    description = RuleTestHarness(TodoRule(), path="a.py").run("TODO").describe()
    assert description == "TODO@a.py:1:1 TODO marker"


def test_harness_supports_multiple_rules() -> None:
    class Other(TodoRule):
        rule_id = "OTHER"
    result = RuleTestHarness((TodoRule(), Other())).run("TODO")
    assert [finding.rule_id for finding in result.findings] == ["OTHER", "TODO"]
