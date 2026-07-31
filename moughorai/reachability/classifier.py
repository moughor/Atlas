from __future__ import annotations

from collections.abc import Mapping

from moughorai.knowledge_graph import KnowledgeKind, KnowledgeNode
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceRole,
)

from .models import (
    CoverageStatus,
    ProjectEvidence,
    ReachabilityProtection,
    ReachabilityState,
    SourceClassification,
)
from .traversal import ReachabilityTrace


class ReachabilityClassifier:
    """Apply conservative PR131 states and shared PR130 confidence."""

    def __init__(self, confidence: ConfidenceCalculator) -> None:
        self._confidence = confidence

    def classify(
        self,
        node: KnowledgeNode,
        metadata: Mapping[str, object],
        source_classification: SourceClassification,
        project: ProjectEvidence,
        protection: ReachabilityProtection | None,
        production: ReachabilityTrace | None,
        test: ReachabilityTrace | None,
        traversal_truncated: bool,
    ) -> tuple[ReachabilityState, tuple[str, ...]]:
        limitations: set[str] = set()
        if traversal_truncated:
            limitations.add("Reachability traversal reached its configured node bound.")
        if protection is not None:
            limitations.update(protection.limitations)
            return protection.state, tuple(limitations)
        if production is not None:
            special = {
                "public_api": ReachabilityState.EXTERNALLY_REACHABLE,
                "framework": ReachabilityState.FRAMEWORK_MANAGED,
                "reflection": ReachabilityState.REFLECTION_DISCOVERED,
                "service_loader": ReachabilityState.SERVICE_LOADER_DISCOVERED,
                "generated": ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED,
            }.get(production.category.value)
            return special or ReachabilityState.REACHABLE, tuple(limitations)
        if test is not None:
            return ReachabilityState.REACHABLE_TEST_ONLY, tuple(limitations)
        visibility = str(metadata.get("visibility", "unknown"))
        if project.reflection is CoverageStatus.PARTIAL:
            limitations.add("Unresolved reflection may reach additional symbols in this project.")
            return ReachabilityState.UNKNOWN, tuple(limitations)
        if project.calls in {CoverageStatus.UNAVAILABLE, CoverageStatus.INSUFFICIENT}:
            return ReachabilityState.UNKNOWN, tuple(limitations)
        if node.kind is KnowledgeKind.FIELD:
            limitations.add("Field read/write reachability is unavailable.")
            return ReachabilityState.UNKNOWN, tuple(limitations)
        if visibility in {"public", "protected"}:
            limitations.add("External API exposure is not proven; visibility prevents a dead-code claim.")
            return ReachabilityState.UNUSED, tuple(limitations)
        if source_classification in {
            SourceClassification.GENERATED,
            SourceClassification.EXTERNAL,
            SourceClassification.VENDORED,
        }:
            limitations.add("Non-production source classification prevents a dead-code claim.")
            return ReachabilityState.UNKNOWN, tuple(limitations)
        if (
            project.calls is CoverageStatus.COMPLETE
            and project.roots is CoverageStatus.COMPLETE
            and project.closed_world
            and project.frameworks is not CoverageStatus.PARTIAL
            and project.reflection is not CoverageStatus.PARTIAL
            and project.service_loader is not CoverageStatus.PARTIAL
            and project.generated is not CoverageStatus.PARTIAL
            and not traversal_truncated
        ):
            return ReachabilityState.LIKELY_DEAD, tuple(limitations)
        limitations.add("The symbol has no known path, but analyzed scope is not complete enough to prove it dead.")
        return ReachabilityState.UNUSED, tuple(limitations)

    def confidence_for(
        self,
        state: ReachabilityState,
        evidence: EvidenceIndex,
        *,
        node_id: str,
        coverage_id: str,
        root_ids: tuple[str, ...],
        relationship_ids: tuple[str, ...],
        protection_ids: tuple[str, ...],
        project: ProjectEvidence,
    ) -> tuple[float, ConfidenceTier]:
        if state in {ReachabilityState.REACHABLE, ReachabilityState.REACHABLE_TEST_ONLY}:
            roles = (
                EvidenceRole("root", root_ids),
                EvidenceRole("relationships", relationship_ids, required=False),
                EvidenceRole("canonical-subject", (node_id,), required=False),
            )
            result = self._confidence.calculate(roles, evidence)
        elif state in {
            ReachabilityState.EXTERNALLY_REACHABLE,
            ReachabilityState.FRAMEWORK_MANAGED,
            ReachabilityState.REFLECTION_DISCOVERED,
            ReachabilityState.SERVICE_LOADER_DISCOVERED,
            ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED,
            ReachabilityState.CONDITIONALLY_REACHABLE,
            ReachabilityState.UNREACHABLE,
        }:
            support = tuple(sorted(set((*protection_ids, *root_ids))))
            result = self._confidence.calculate(
                (EvidenceRole("structured-protection", support),), evidence,
            )
        elif state is ReachabilityState.LIKELY_DEAD:
            result = self._confidence.calculate(
                (
                    EvidenceRole("canonical-subject", (node_id,)),
                    EvidenceRole("complete-call-and-root-coverage", (coverage_id,)),
                    EvidenceRole("closed-scope-check", (coverage_id,)),
                ),
                evidence,
                coverage=1.0 if project.closed_world else 0.0,
            )
        elif state is ReachabilityState.UNUSED:
            result = self._confidence.calculate(
                (
                    EvidenceRole("canonical-subject", (node_id,)),
                    EvidenceRole("partial-usage-check", (coverage_id,), required=False),
                ),
                evidence,
                coverage=0.7,
            )
        else:
            result = self._confidence.calculate(
                (
                    EvidenceRole("canonical-subject", (node_id,), required=False),
                    EvidenceRole("required-reachability-evidence", ()),
                ),
                evidence,
                coverage=0.0,
            )
        return result.score, result.tier
