from types import SimpleNamespace

from moughorai.java_baseline.models import ArchitectureRegressionReport
from moughorai.java_impact.models import RiskLevel
from moughorai.java_policy import ArchitecturePolicyReport, PolicySeverity, PolicyViolation
from moughorai.java_quality_gate import (
    GateFinding,
    GateSeverity,
    GateStatus,
    JavaQualityGateEvaluator,
    JavaQualityGateJson,
    QualityGateConfig,
    QualityGateReport,
)


class PolicyStub:
    def __init__(self, violations=()):
        self.report = ArchitecturePolicyReport(tuple(violations))

    def evaluate(self, graph, policy):
        return self.report


class BaselineStub:
    def __init__(self, report=None):
        self.report = report or ArchitectureRegressionReport()

    def compare(self, baseline, graph, policy):
        return self.report


class ImpactStub:
    def __init__(self, level=RiskLevel.LOW, score=10):
        self.level = level
        self.score = score

    def analyze(self, graph, project, key):
        return SimpleNamespace(
            level=self.level,
            score=self.score,
            blast_radius=3,
            affected_projects=(project,),
        )


def evaluator(policy=(), level=RiskLevel.LOW, score=10):
    return JavaQualityGateEvaluator(
        PolicyStub(policy), BaselineStub(), ImpactStub(level, score)
    )


def test_clean_workspace_passes():
    report = evaluator().evaluate(object())
    assert report.status is GateStatus.PASS
    assert report.score == 0


def test_policy_error_fails_gate():
    violation = PolicyViolation(
        "forbidden", PolicySeverity.ERROR, "Forbidden dependency", "api", "Controller"
    )
    report = evaluator((violation,)).evaluate(object())
    assert report.failed
    assert report.by_category("policy")


def test_warning_can_remain_non_blocking():
    violation = PolicyViolation(
        "layer", PolicySeverity.WARNING, "Layer warning", "api", "Controller"
    )
    report = evaluator((violation,)).evaluate(object())
    assert report.status is GateStatus.WARN


def test_high_change_impact_is_checked_and_blocked_by_default():
    report = evaluator(level=RiskLevel.HIGH, score=72).evaluate(
        object(), changed_symbols=(("core", "com.acme.User"),)
    )
    assert report.status is GateStatus.FAIL
    assert report.checked_symbols == ("core:com.acme.User",)


def test_thresholds_are_configurable():
    report = evaluator(level=RiskLevel.HIGH, score=45).evaluate(
        object(),
        config=QualityGateConfig(maximum_high_impacts=1, failure_score_threshold=90),
        changed_symbols=(("core", "com.acme.User"),),
    )
    assert report.status is GateStatus.WARN


def test_markdown_and_json_are_deterministic():
    report = QualityGateReport(
        GateStatus.WARN,
        8,
        (GateFinding(GateSeverity.WARNING, "policy", "Layer warning", ("A -> B",), 8),),
        ("api:A",),
    )
    assert "**Status:** WARN" in report.to_markdown()
    payload = JavaQualityGateJson().dumps(report)
    assert '"status": "warn"' in payload
    assert payload == JavaQualityGateJson().dumps(report)
