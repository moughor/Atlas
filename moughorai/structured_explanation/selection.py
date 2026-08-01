from __future__ import annotations

from dataclasses import replace

from moughorai.semantic_evidence import EvidenceIndex

from .models import (
    ExplanationAvailability,
    ExplanationSelection,
    StructuredExplanation,
)


class ExplanationContextBudgetError(ValueError):
    """Raised when the mandatory subject envelope cannot fit the token budget."""


class StructuredExplanationSelector:
    """Select whole facts and their exact citation closure deterministically."""

    DEFAULT_TOKEN_BUDGET = 7_000
    MANDATORY_PRIORITY = 10

    def __init__(self, estimator=None) -> None:
        if estimator is None:
            from moughorai.prompts import TokenEstimator

            estimator = TokenEstimator()
        self.estimator = estimator

    def select(
        self,
        explanation: StructuredExplanation,
        *,
        token_budget: int,
        preselection_omitted_fact_count: int = 0,
        preselection_omitted_evidence_count: int = 0,
    ) -> StructuredExplanation:
        if isinstance(token_budget, bool) or not isinstance(token_budget, int):
            raise TypeError("structured explanation token budget must be an integer")
        if token_budget <= 0:
            raise ValueError("structured explanation token budget must be positive")
        for name, value in (
            ("preselection fact omission count", preselection_omitted_fact_count),
            ("preselection evidence omission count", preselection_omitted_evidence_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if preselection_omitted_fact_count < 0 or preselection_omitted_evidence_count < 0:
            raise ValueError("preselection omission counts must not be negative")
        ordered = tuple(sorted(
            explanation.facts,
            key=lambda item: (item.priority, item.fact_id),
        ))
        mandatory_ids = {
            item.fact_id for item in ordered
            if item.priority <= self.MANDATORY_PRIORITY
        }
        optional = tuple(
            item.fact_id for item in ordered
            if item.fact_id not in mandatory_ids
        )
        candidate = self._finalize_estimate(self._materialize(
            explanation,
            mandatory_ids,
            token_budget,
            preselection_omitted_fact_count,
            preselection_omitted_evidence_count,
        ))
        if candidate is None:
            raise ExplanationContextBudgetError(
                "structured explanation token budget is smaller than the mandatory subject envelope"
            )

        low = 0
        high = len(optional)
        result = candidate
        while low <= high:
            count = (low + high) // 2
            selected = {*mandatory_ids, *optional[:count]}
            trial = self._finalize_estimate(self._materialize(
                explanation,
                selected,
                token_budget,
                preselection_omitted_fact_count,
                preselection_omitted_evidence_count,
            ))
            if trial is not None:
                result = trial
                low = count + 1
            else:
                high = count - 1
        if self._estimate(result) > token_budget:
            raise ExplanationContextBudgetError(
                "structured explanation selector exceeded its token budget"
            )
        return result

    def _materialize(
        self,
        explanation: StructuredExplanation,
        selected_ids: set[str],
        token_budget: int,
        preselection_omitted_fact_count: int,
        preselection_omitted_evidence_count: int,
    ) -> StructuredExplanation:
        facts = tuple(
            item for item in explanation.facts
            if item.fact_id in selected_ids
        )
        selected_evidence_ids = {
            evidence_id for fact in facts for evidence_id in fact.evidence_ids
        }
        evidence = EvidenceIndex(
            record for record in explanation.evidence_index.records
            if record.evidence_id in selected_evidence_ids
        ).freeze()
        omitted_facts = (
            len(explanation.facts) - len(facts) + preselection_omitted_fact_count
        )
        omitted_evidence = (
            len(explanation.evidence_index) - len(evidence)
            + preselection_omitted_evidence_count
        )
        truncated = bool(omitted_facts or omitted_evidence)
        availability = explanation.availability
        if truncated and availability is ExplanationAvailability.AVAILABLE:
            availability = ExplanationAvailability.PARTIAL
        return StructuredExplanation(
            explanation.request,
            availability,
            explanation.snapshot_id,
            explanation.graph_digest,
            explanation.input_fingerprint,
            explanation.lineage,
            explanation.subject,
            explanation.candidates,
            facts,
            explanation.capabilities,
            evidence,
            explanation.limitations,
            ExplanationSelection(
                True,
                token_budget,
                0,
                len(explanation.facts) + preselection_omitted_fact_count,
                len(facts),
                omitted_facts,
                len(explanation.evidence_index) + preselection_omitted_evidence_count,
                len(evidence),
                omitted_evidence,
                truncated,
            ),
            "",
            explanation.producer_version,
            explanation.schema_version,
        )

    def _finalize_estimate(
        self,
        explanation: StructuredExplanation,
    ) -> StructuredExplanation | None:
        result = explanation
        estimate = self._estimate(result)
        for _ in range(8):
            if (
                result.selection.token_budget is not None
                and estimate > result.selection.token_budget
            ):
                return None
            selection = replace(result.selection, estimated_tokens=estimate)
            updated = StructuredExplanation(
                result.request,
                result.availability,
                result.snapshot_id,
                result.graph_digest,
                result.input_fingerprint,
                result.lineage,
                result.subject,
                result.candidates,
                result.facts,
                result.capabilities,
                result.evidence_index,
                result.limitations,
                selection,
                "",
                result.producer_version,
                result.schema_version,
            )
            next_estimate = self._estimate(updated)
            result = updated
            if next_estimate == estimate:
                return result
            estimate = next_estimate
        raise ExplanationContextBudgetError(
            "structured explanation token estimator did not reach an exact fixed point"
        )

    def _estimate(self, explanation: StructuredExplanation) -> int:
        return self.estimator.estimate(explanation.to_json())
