"""Immutable models for deterministic Java CI quality gates."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class GateSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class QualityGateConfig:
    """Thresholds used to decide whether a workspace is releasable."""

    fail_on_policy_error: bool = True
    fail_on_regression_error: bool = True
    fail_on_unresolved_growth: bool = True
    maximum_critical_impacts: int = 0
    maximum_high_impacts: int = 0
    warning_score_threshold: int = 40
    failure_score_threshold: int = 70


@dataclass(frozen=True, order=True)
class GateFinding:
    severity: GateSeverity
    category: str
    message: str
    evidence: tuple[str, ...] = ()
    score: int = 0


@dataclass(frozen=True)
class QualityGateReport:
    status: GateStatus
    score: int
    findings: tuple[GateFinding, ...] = ()
    checked_symbols: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status is GateStatus.FAIL

    def by_category(self, category: str) -> tuple[GateFinding, ...]:
        return tuple(item for item in self.findings if item.category == category)

    def to_markdown(self) -> str:
        lines = [
            "# Java Quality Gate",
            "",
            f"**Status:** {self.status.value.upper()}",
            f"**Score:** {self.score}/100",
        ]
        if self.checked_symbols:
            lines.extend(("", "## Checked symbols"))
            lines.extend(f"- `{symbol}`" for symbol in self.checked_symbols)
        if self.findings:
            lines.extend(("", "## Findings"))
            for finding in self.findings:
                lines.append(
                    f"- **{finding.severity.value.upper()}** "
                    f"[{finding.category}] {finding.message} (+{finding.score})"
                )
                lines.extend(f"  - `{item}`" for item in finding.evidence)
        else:
            lines.extend(("", "No blocking findings."))
        return "\n".join(lines) + "\n"
