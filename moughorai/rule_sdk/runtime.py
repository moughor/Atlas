from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .models import RuleContext, RuleFinding, RuleLocation, RuleSeverity


class Rule(Protocol):
    rule_id: str
    default_severity: RuleSeverity

    def analyze(self, context: RuleContext, reporter: "RuleReporter") -> None: ...


class RuleAuthoringError(ValueError):
    pass


class RuleExecutionError(RuntimeError):
    pass


class RuleReporter:
    def __init__(self, rule_id: str, default_severity: RuleSeverity, context: RuleContext) -> None:
        if not rule_id.strip():
            raise RuleAuthoringError("rule_id must not be empty")
        self.rule_id = rule_id
        self.default_severity = RuleSeverity(default_severity)
        self.context = context
        self._findings: list[RuleFinding] = []

    @property
    def findings(self) -> tuple[RuleFinding, ...]:
        return tuple(self._findings)

    def report(
        self,
        message: str,
        *,
        line: int = 1,
        column: int = 1,
        end_line: int | None = None,
        end_column: int | None = None,
        severity: RuleSeverity | str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> RuleFinding:
        finding = RuleFinding(
            self.rule_id,
            message,
            self.default_severity if severity is None else RuleSeverity(severity),
            RuleLocation(self.context.path, line, column, end_line, end_column),
            tuple(sorted((str(key), value) for key, value in (data or {}).items())),
        )
        self._findings.append(finding)
        return finding


class RuleRunner:
    def run(self, rules: Iterable[Rule], context: RuleContext) -> tuple[RuleFinding, ...]:
        findings: list[RuleFinding] = []
        seen_rules: set[str] = set()
        for rule in sorted(tuple(rules), key=lambda item: item.rule_id):
            rule_id = str(rule.rule_id).strip()
            if not rule_id:
                raise RuleAuthoringError("rule_id must not be empty")
            if rule_id in seen_rules:
                raise RuleAuthoringError(f"duplicate rule_id: {rule_id}")
            seen_rules.add(rule_id)
            reporter = RuleReporter(rule_id, rule.default_severity, context)
            try:
                result = rule.analyze(context, reporter)
            except Exception as exc:
                raise RuleExecutionError(f"{rule_id}: {type(exc).__name__}: {exc}") from exc
            if result is not None:
                raise RuleAuthoringError(f"{rule_id}: analyze must return None")
            findings.extend(reporter.findings)
        unique = {_finding_key(finding): finding for finding in findings}
        return tuple(sorted(unique.values(), key=_finding_key))


class RuleRegistry:
    def __init__(self, rules: Iterable[Rule] = ()) -> None:
        self._rules: dict[str, Rule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: Rule) -> None:
        rule_id = str(rule.rule_id).strip()
        if not rule_id:
            raise RuleAuthoringError("rule_id must not be empty")
        if rule_id in self._rules:
            raise RuleAuthoringError(f"duplicate rule_id: {rule_id}")
        self._rules[rule_id] = rule

    def get(self, rule_id: str) -> Rule:
        try:
            return self._rules[rule_id]
        except KeyError as exc:
            raise KeyError(f"unknown rule: {rule_id}") from exc

    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))

    def run(self, context: RuleContext) -> tuple[RuleFinding, ...]:
        return RuleRunner().run(self.rules(), context)


def _finding_key(finding: RuleFinding) -> tuple[str, str, int, int, str, str]:
    return (
        finding.location.path.as_posix(),
        finding.rule_id,
        finding.location.line,
        finding.location.column,
        finding.message,
        finding.severity.value,
    )
