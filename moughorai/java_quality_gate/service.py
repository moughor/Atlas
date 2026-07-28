"""Public facade for deterministic Java quality gates."""
from __future__ import annotations

from collections.abc import Iterable

from moughorai.java_baseline.models import ArchitectureBaseline
from moughorai.java_policy import ArchitecturePolicy
from moughorai.java_workspace.graph import JavaWorkspaceGraph

from .evaluator import JavaQualityGateEvaluator
from .models import QualityGateConfig, QualityGateReport


class JavaQualityGateService:
    def __init__(self, evaluator: JavaQualityGateEvaluator | None = None) -> None:
        self._evaluator = evaluator or JavaQualityGateEvaluator()

    def evaluate(
        self,
        graph: JavaWorkspaceGraph,
        *,
        config: QualityGateConfig | None = None,
        policy: ArchitecturePolicy | None = None,
        baseline: ArchitectureBaseline | None = None,
        changed_symbols: Iterable[tuple[str, str]] = (),
    ) -> QualityGateReport:
        return self._evaluator.evaluate(
            graph,
            config=config,
            policy=policy,
            baseline=baseline,
            changed_symbols=changed_symbols,
        )
