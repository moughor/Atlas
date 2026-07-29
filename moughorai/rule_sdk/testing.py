from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import RuleContext, RuleFinding, RuleSeverity
from .runtime import Rule, RuleRunner


@dataclass(frozen=True, slots=True)
class RuleTestCase:
    name: str
    source: str
    path: Path = Path("test.txt")
    language: str = "text"
    configuration: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("rule test case name must not be empty")
        object.__setattr__(self, "path", Path(self.path))
        if self.configuration != tuple(sorted(self.configuration, key=lambda item: item[0])):
            raise ValueError("rule test configuration must be sorted")

    def context(self) -> RuleContext:
        return RuleContext(self.path, self.source, self.language, dict(self.configuration))


@dataclass(frozen=True, slots=True)
class ExpectedFinding:
    rule_id: str
    line: int
    column: int | None = None
    message: str | None = None
    severity: RuleSeverity | None = None

    def matches(self, finding: RuleFinding) -> bool:
        return (
            finding.rule_id == self.rule_id
            and finding.location.line == self.line
            and (self.column is None or finding.location.column == self.column)
            and (self.message is None or finding.message == self.message)
            and (self.severity is None or finding.severity is self.severity)
        )


@dataclass(frozen=True, slots=True)
class RuleTestResult:
    case: RuleTestCase
    findings: tuple[RuleFinding, ...]

    def assert_clean(self) -> "RuleTestResult":
        if self.findings:
            raise AssertionError(f"{self.case.name}: expected no findings, got {self.describe()}")
        return self

    def assert_count(self, expected: int) -> "RuleTestResult":
        if len(self.findings) != expected:
            raise AssertionError(
                f"{self.case.name}: expected {expected} finding(s), got {len(self.findings)}: {self.describe()}"
            )
        return self

    def assert_findings(
        self,
        expected: Iterable[ExpectedFinding],
        *,
        exact: bool = True,
    ) -> "RuleTestResult":
        remaining = list(self.findings)
        missing: list[ExpectedFinding] = []
        for expectation in expected:
            match = next((finding for finding in remaining if expectation.matches(finding)), None)
            if match is None:
                missing.append(expectation)
            else:
                remaining.remove(match)
        if missing or (exact and remaining):
            raise AssertionError(
                f"{self.case.name}: finding mismatch; missing={missing!r}; "
                f"unexpected={[_short(item) for item in remaining]!r}"
            )
        return self

    def describe(self) -> str:
        return ", ".join(_short(finding) for finding in self.findings) or "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.case.name,
            "findings": [finding.to_dict() for finding in self.findings],
        }


class RuleTestHarness:
    def __init__(
        self,
        rules: Rule | Iterable[Rule],
        *,
        language: str = "text",
        path: str | Path = "test.txt",
        configuration: Mapping[str, Any] | None = None,
    ) -> None:
        self.rules = (rules,) if hasattr(rules, "analyze") else tuple(rules)
        self.language = language
        self.path = Path(path)
        self.configuration = tuple(sorted((str(key), value) for key, value in (configuration or {}).items()))

    def run(self, source: str, *, name: str = "rule test") -> RuleTestResult:
        return self.run_case(RuleTestCase(name, source, self.path, self.language, self.configuration))

    def run_case(self, case: RuleTestCase) -> RuleTestResult:
        return RuleTestResult(case, RuleRunner().run(self.rules, case.context()))

    def run_cases(self, cases: Iterable[RuleTestCase]) -> tuple[RuleTestResult, ...]:
        ordered = tuple(sorted(cases, key=lambda item: item.name))
        names = [case.name for case in ordered]
        if len(names) != len(set(names)):
            raise ValueError("rule test case names must be unique")
        return tuple(self.run_case(case) for case in ordered)


def _short(finding: RuleFinding) -> str:
    return (
        f"{finding.rule_id}@{finding.location.path.as_posix()}:"
        f"{finding.location.line}:{finding.location.column} {finding.message}"
    )
