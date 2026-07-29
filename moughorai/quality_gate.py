"""Deterministic quality gates for workspace analysis reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .workspace import WorkspaceRunReport


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_RANK = {severity: index for index, severity in enumerate(FindingSeverity)}


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    minimum_severity: FindingSeverity | None = None
    max_findings: int | None = None
    finding_exit_code: int = 1
    analysis_exit_code: int = 1

    def __post_init__(self) -> None:
        if self.max_findings is not None and self.max_findings < 0:
            raise ValueError("max_findings must be non-negative")
        for name, value in (
            ("finding_exit_code", self.finding_exit_code),
            ("analysis_exit_code", self.analysis_exit_code),
        ):
            if not 1 <= value <= 255:
                raise ValueError(f"{name} must be between 1 and 255")

    @classmethod
    def from_options(
        cls,
        options: Mapping[str, str],
        *,
        minimum_severity: str | FindingSeverity | None = None,
        max_findings: int | None = None,
        finding_exit_code: int | None = None,
        analysis_exit_code: int | None = None,
    ) -> "QualityGatePolicy":
        prefix = "quality_gate."
        raw_severity = minimum_severity
        if raw_severity is None:
            raw_severity = options.get(prefix + "minimum_severity")
        severity = (
            raw_severity
            if isinstance(raw_severity, FindingSeverity)
            else FindingSeverity(str(raw_severity).lower())
            if raw_severity is not None
            else None
        )
        return cls(
            severity,
            max_findings if max_findings is not None else _optional_int(options.get(prefix + "max_findings")),
            finding_exit_code if finding_exit_code is not None else _int(options.get(prefix + "finding_exit_code"), 1),
            analysis_exit_code if analysis_exit_code is not None else _int(options.get(prefix + "analysis_exit_code"), 1),
        )


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    passed: bool
    finding_count: int
    threshold_count: int
    exit_code: int
    reasons: tuple[str, ...]


class WorkspaceQualityGate:
    def evaluate(self, report: WorkspaceRunReport, policy: QualityGatePolicy) -> QualityGateResult:
        findings = tuple(_findings(report))
        threshold = (
            tuple(item for item in findings if _RANK[_severity(item)] >= _RANK[policy.minimum_severity])
            if policy.minimum_severity is not None
            else ()
        )
        reasons: list[str] = []
        if policy.minimum_severity is not None and threshold:
            reasons.append(f"{len(threshold)} finding(s) at or above {policy.minimum_severity.value}")
        if policy.max_findings is not None and len(findings) > policy.max_findings:
            reasons.append(f"{len(findings)} finding(s) exceed maximum {policy.max_findings}")
        passed = not reasons
        return QualityGateResult(passed, len(findings), len(threshold), 0 if passed else policy.finding_exit_code, tuple(reasons))


def _findings(report: WorkspaceRunReport) -> Iterable[Mapping[str, Any]]:
    for run in report.runs:
        if not isinstance(run.value, Mapping):
            continue
        value = run.value.get("findings", ())
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            yield from (item for item in value if isinstance(item, Mapping))


def _severity(finding: Mapping[str, Any]) -> FindingSeverity:
    raw = str(finding.get("severity", finding.get("level", "medium"))).lower()
    aliases = {"error": "high", "warning": "medium", "note": "info", "information": "info"}
    try:
        return FindingSeverity(aliases.get(raw, raw))
    except ValueError:
        return FindingSeverity.MEDIUM


def _optional_int(value: str | None) -> int | None:
    return None if value is None else int(value)


def _int(value: str | None, default: int) -> int:
    return default if value is None else int(value)
