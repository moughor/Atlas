"""Deterministic architecture and change-risk quality-gate evaluation."""
from __future__ import annotations

from collections.abc import Iterable

from moughorai.java_baseline.models import ArchitectureBaseline, RegressionSeverity
from moughorai.java_baseline.service import JavaArchitectureBaselineService
from moughorai.java_impact.models import RiskLevel
from moughorai.java_impact.service import JavaChangeImpactService
from moughorai.java_policy import ArchitecturePolicy, PolicySeverity
from moughorai.java_policy.service import JavaArchitecturePolicyService
from moughorai.java_workspace.graph import JavaWorkspaceGraph

from .models import GateFinding, GateSeverity, GateStatus, QualityGateConfig, QualityGateReport


_SEVERITY_MAP = {
    "info": GateSeverity.INFO,
    "warning": GateSeverity.WARNING,
    "error": GateSeverity.ERROR,
    "critical": GateSeverity.CRITICAL,
}


class JavaQualityGateEvaluator:
    def __init__(
        self,
        policy_service: JavaArchitecturePolicyService | None = None,
        baseline_service: JavaArchitectureBaselineService | None = None,
        impact_service: JavaChangeImpactService | None = None,
    ) -> None:
        self._policy = policy_service or JavaArchitecturePolicyService()
        self._baseline = baseline_service or JavaArchitectureBaselineService()
        self._impact = impact_service or JavaChangeImpactService()

    def evaluate(
        self,
        graph: JavaWorkspaceGraph,
        *,
        config: QualityGateConfig | None = None,
        policy: ArchitecturePolicy | None = None,
        baseline: ArchitectureBaseline | None = None,
        changed_symbols: Iterable[tuple[str, str]] = (),
    ) -> QualityGateReport:
        config = config or QualityGateConfig()
        findings: list[GateFinding] = []
        checked: list[str] = []

        policy_report = self._policy.evaluate(graph, policy)
        for violation in policy_report.violations:
            severity = _SEVERITY_MAP[violation.severity.value]
            points = {
                PolicySeverity.INFO: 2,
                PolicySeverity.WARNING: 8,
                PolicySeverity.ERROR: 20,
                PolicySeverity.CRITICAL: 35,
            }[violation.severity]
            findings.append(GateFinding(
                severity,
                "policy",
                violation.message,
                violation.evidence or tuple(filter(None, (violation.source, violation.target))),
                points,
            ))

        if baseline is not None:
            regression_report = self._baseline.compare(baseline, graph, policy)
            for regression in regression_report.regressions:
                severity = _SEVERITY_MAP[regression.severity.value]
                points = {
                    RegressionSeverity.INFO: 2,
                    RegressionSeverity.WARNING: 10,
                    RegressionSeverity.ERROR: 25,
                    RegressionSeverity.CRITICAL: 40,
                }[regression.severity]
                findings.append(GateFinding(
                    severity,
                    f"regression:{regression.category}",
                    regression.message,
                    regression.evidence,
                    points,
                ))

        impact_levels: list[RiskLevel] = []
        for project_key, key in sorted(set(changed_symbols)):
            checked.append(f"{project_key}:{key}")
            report = self._impact.analyze(graph, project_key, key)
            impact_levels.append(report.level)
            if report.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                severity = GateSeverity.CRITICAL if report.level is RiskLevel.CRITICAL else GateSeverity.WARNING
                findings.append(GateFinding(
                    severity,
                    "change-impact",
                    f"{key} has {report.level.value} change risk with blast radius {report.blast_radius}",
                    tuple(report.affected_projects),
                    min(30, max(10, report.score // 3)),
                ))

        score = min(100, sum(item.score for item in findings))
        critical_impacts = impact_levels.count(RiskLevel.CRITICAL)
        high_impacts = impact_levels.count(RiskLevel.HIGH)

        blocking_policy = config.fail_on_policy_error and any(
            item.category == "policy" and item.severity in (GateSeverity.ERROR, GateSeverity.CRITICAL)
            for item in findings
        )
        blocking_regression = config.fail_on_regression_error and any(
            item.category.startswith("regression:")
            and item.severity in (GateSeverity.ERROR, GateSeverity.CRITICAL)
            for item in findings
        )
        unresolved_growth = config.fail_on_unresolved_growth and any(
            item.category == "regression:unresolved" for item in findings
        )
        blocking_impact = (
            critical_impacts > config.maximum_critical_impacts
            or high_impacts > config.maximum_high_impacts
        )

        if (
            blocking_policy
            or blocking_regression
            or unresolved_growth
            or blocking_impact
            or score >= config.failure_score_threshold
        ):
            status = GateStatus.FAIL
        elif findings or score >= config.warning_score_threshold:
            status = GateStatus.WARN
        else:
            status = GateStatus.PASS

        return QualityGateReport(
            status=status,
            score=score,
            findings=tuple(sorted(findings)),
            checked_symbols=tuple(checked),
        )
