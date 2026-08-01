from __future__ import annotations

from dataclasses import replace
import json
from typing import Protocol

from moughorai.semantic_evidence import EvidenceIndex

from .models import (
    ReportSelection,
    RepositoryReport,
    RepositoryReportSection,
)


class ReportContextBudgetError(ValueError):
    """Raised when the mandatory report envelope cannot fit the token budget."""


class _TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class RepositoryReportContextSelector:
    """Select whole report items and their citations within a deterministic budget."""

    DEFAULT_TOKEN_BUDGET = 7_000
    # The envelope always retains every section capability state. Identity,
    # repository scale, and canonical graph scale are the only mandatory items;
    # detailed coverage measurements compete for the remaining budget.
    MANDATORY_PRIORITY = 6

    def __init__(self, estimator: _TokenEstimator | None = None) -> None:
        if estimator is None:
            # Lazy import preserves the existing ai_context -> collector import
            # direction while reusing PR109's single token estimator.
            from moughorai.prompts import TokenEstimator

            estimator = TokenEstimator()
        self.estimator = estimator

    def select(
        self,
        report: RepositoryReport,
        *,
        token_budget: int,
    ) -> RepositoryReport:
        if token_budget <= 0:
            raise ValueError("repository report token budget must be positive")
        ordered = tuple(sorted(
            report.items,
            key=lambda item: (item.priority, item.item_id),
        ))
        mandatory = tuple(item for item in ordered if item.priority <= self.MANDATORY_PRIORITY)
        optional = tuple(item for item in ordered if item.priority > self.MANDATORY_PRIORITY)
        mandatory_ids = tuple(item.item_id for item in mandatory)
        mandatory_set = set(mandatory_ids)
        candidate = self._finalize_estimate(
            self._materialize(report, mandatory_set, token_budget)
        )
        if self._estimate(candidate) > token_budget:
            raise ReportContextBudgetError(
                "repository report token budget is smaller than the mandatory identity and coverage envelope"
            )
        eligible: list[str] = []
        available_ids = set(mandatory_ids)
        for item in optional:
            if item.related_item_ids and not set(item.related_item_ids).issubset(available_ids):
                continue
            eligible.append(item.item_id)
            available_ids.add(item.item_id)

        # Priority is strict: select the longest fitting prefix. Binary search
        # avoids serializing the complete report once per optional item.
        low = 0
        high = len(eligible)
        result = candidate
        while low <= high:
            count = (low + high) // 2
            trial_ids = {*mandatory_ids, *eligible[:count]}
            trial = self._finalize_estimate(
                self._materialize(report, trial_ids, token_budget)
            )
            if self._estimate(trial) <= token_budget:
                result = trial
                low = count + 1
            else:
                high = count - 1
        if self._estimate(result) > token_budget:
            raise ReportContextBudgetError("repository report selector exceeded its token budget")
        return result

    def _finalize_estimate(self, report: RepositoryReport) -> RepositoryReport:
        result = report
        estimated = self._estimate(result)
        for _ in range(8):
            updated = replace(
                result,
                selection=replace(result.selection, estimated_tokens=estimated),
            )
            next_estimated = self._estimate(updated)
            result = updated
            if next_estimated == estimated:
                return result
            estimated = next_estimated
        raise ReportContextBudgetError(
            "repository report token estimator did not reach an exact fixed point"
        )

    def _materialize(
        self,
        report: RepositoryReport,
        selected_ids: set[str],
        token_budget: int,
    ) -> RepositoryReport:
        items = tuple(item for item in report.items if item.item_id in selected_ids)
        selected_evidence = {
            evidence_id for item in items for evidence_id in item.evidence_ids
        }
        evidence = EvidenceIndex(
            record for record in report.evidence_index.records
            if record.evidence_id in selected_evidence
        ).freeze()
        sections = tuple(
            RepositoryReportSection(
                section.kind,
                section.capability_state,
                section.observation_state,
                tuple(item_id for item_id in section.item_ids if item_id in selected_ids),
                section.total_item_count,
                section.total_item_count - sum(
                    1 for item_id in section.item_ids if item_id in selected_ids
                ),
                section.producer_ids,
                section.limitations,
            )
            for section in report.sections
        )
        return RepositoryReport(
            report.input_fingerprint,
            report.graph_digest,
            report.lineage,
            items,
            sections,
            evidence,
            report.limitations,
            ReportSelection(
                True,
                token_budget,
                0,
                len(items),
                len(report.items) - len(items),
            ),
            report.producer_version,
            report.schema_version,
        )

    def _estimate(self, report: RepositoryReport) -> int:
        text = json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return self.estimator.estimate(text)
