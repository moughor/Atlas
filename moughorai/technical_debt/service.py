"""PR142 orchestration over the authoritative PR137 and PR136 services."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.impact_analysis import (
    ImpactCapabilityState,
    ImpactChangeKind,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
    ImpactPredictionService,
    ImpactRiskContext,
)
from moughorai.knowledge_graph import KnowledgeRelation
from moughorai.knowledge_graph.evidence import safe_edge_evidence_refs
from moughorai.measurement import MeasurementSession
from moughorai.refactoring_advisor import (
    RefactoringAdvice,
    RefactoringAdvisorService,
    RefactoringCapabilityState,
    RefactoringFamily,
    RefactoringOperation,
    RefactoringRequest,
)
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver, SubjectCandidate, SubjectQuery

from .models import (
    DEPENDENCY_CYCLE_OBSERVATION,
    TECHNICAL_DEBT_ITEM_LIMITATIONS,
    TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER,
    TECHNICAL_DEBT_PRODUCER,
    TechnicalDebtCapability,
    TechnicalDebtCapabilityKind,
    TechnicalDebtCategory,
    TechnicalDebtImpact,
    TechnicalDebtItem,
    TechnicalDebtRequest,
    TechnicalDebtResponse,
    TechnicalDebtState,
    technical_debt_advice_set_digest,
    technical_debt_fingerprint,
    technical_debt_item_id,
)


_IMPACT_RESULT_LIMIT = 50
_MAX_GROUPED_ADVICE_EVIDENCE = 6
_IMPACT_LIMITATION = (
    "PR136 impact is bounded and repository-local; absent static relations, "
    "external consumers, and runtime behavior remain unknown."
)


@dataclass(frozen=True, slots=True)
class _DebtPlan:
    advice: RefactoringAdvice
    advice_ids: tuple[str, ...]
    evidence_backed_advice_ids: tuple[str, ...]
    omitted_advice_evidence_count: int
    advice_limitations: tuple[str, ...]
    source: SubjectCandidate
    target: SubjectCandidate
    item_id: str
    impact_fingerprint: str | None
    impact: TechnicalDebtImpact
    risk_context: ImpactRiskContext | None
    risk_subject_id: str | None
    complexity_subject_ids: tuple[str, ...]
    complexity_evidence_ids: tuple[str, ...]
    risk_state: ImpactCapabilityState
    risk_limitations: tuple[str, ...]
    records: tuple[EvidenceRecord, ...]


class TechnicalDebtService:
    """Rank observed dependency-cycle seams without creating another analyzer."""

    def __init__(
        self,
        advisor: RefactoringAdvisorService,
        impact: ImpactPredictionService,
        *,
        snapshot_id: str,
        graph_digest: str,
        measurement: MeasurementSession | None = None,
    ) -> None:
        if not isinstance(advisor, RefactoringAdvisorService):
            raise TypeError("technical debt requires RefactoringAdvisorService")
        if not isinstance(impact, ImpactPredictionService):
            raise TypeError("technical debt requires ImpactPredictionService")
        if not snapshot_id.strip() or not graph_digest.strip():
            raise ValueError("technical debt requires snapshot and graph lineage")
        self._advisor = advisor
        self._impact = impact
        self._snapshot_id = snapshot_id
        self._graph_digest = graph_digest
        self._measurement = measurement or MeasurementSession()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> TechnicalDebtService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("technical debt snapshot is invalid")
        session = measurement or MeasurementSession()
        with session.scope(
            "technical_debt.prepare",
            consumer="technical-debt",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
            graph = resolver.graph
            scope.add_units(len(graph.nodes) + len(graph.edges) if graph is not None else 0)
            scope.set_objects_retained(len(graph.nodes) if graph is not None else 0)
        advisor = RefactoringAdvisorService(
            resolver,
            snapshot_id=snapshot.snapshot_id,
            analyzer_version=snapshot.analyzer_version,
            semantic_context=snapshot.semantic_context,
            measurement=session,
        )
        impact = ImpactPredictionService(
            resolver,
            snapshot_id=snapshot.snapshot_id,
            analyzer_version=snapshot.analyzer_version,
            semantic_context=snapshot.semantic_context,
            measurement=session,
        )
        return cls(
            advisor,
            impact,
            snapshot_id=snapshot.snapshot_id,
            graph_digest=resolver.graph_digest,
            measurement=session,
        )

    def analyze(
        self,
        request: TechnicalDebtRequest | None = None,
    ) -> TechnicalDebtResponse:
        selected = request or TechnicalDebtRequest()
        if not isinstance(selected, TechnicalDebtRequest):
            raise TypeError("technical debt request is invalid")
        with self._measurement.scope(
            "technical_debt.query",
            consumer="technical-debt",
            sample_key=technical_debt_fingerprint(
                self._snapshot_id, self._graph_digest, selected
            ),
        ) as scope:
            response = self._analyze(selected)
            scope.add_units(response.evaluated_count)
            scope.add_objects_produced(response.returned_count)
            scope.set_objects_retained(response.returned_count)
            return response

    def _analyze(self, request: TechnicalDebtRequest) -> TechnicalDebtResponse:
        with self._measurement.scope(
            "technical_debt.cycle_candidates",
            consumer="technical-debt",
            sample_key=self._graph_digest,
        ) as scope:
            upstream = self._advisor.advise(RefactoringRequest(
                subject=request.subject,
                families=(RefactoringFamily.CYCLE_BREAKING,),
                limit=request.candidate_limit,
                include_impact=False,
                impact_depth=request.impact_depth,
            ))
            advice = tuple(
                item for item in upstream.advice
                if item.family is RefactoringFamily.CYCLE_BREAKING
                and item.operation is RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM
            )
            scope.add_units(upstream.total_candidate_count)
            scope.add_objects_produced(len(advice))
            scope.set_objects_retained(len(advice))

        advice_groups = self._group_equivalent_advice(advice)

        advice_records = {
            record.evidence_id: record for record in upstream.evidence_index.records
        }
        with self._measurement.scope(
            "technical_debt.impact",
            consumer="technical-debt",
            sample_key=upstream.input_fingerprint,
        ) as scope:
            plans = tuple(
                self._plan(group, advice_records, request)
                for group in advice_groups
            )
            scope.add_units(len(advice))
            scope.add_objects_produced(sum(plan.impact.affected_count for plan in plans))
            scope.set_objects_retained(len(plans))

        ordered = tuple(sorted(plans, key=self._plan_sort_key))
        selected_plans = ordered[:request.limit]
        evidence = EvidenceIndex()
        items: list[TechnicalDebtItem] = []
        rank = 0
        for plan in selected_plans:
            if plan.impact.represented:
                rank += 1
                ordinal: int | None = rank
            else:
                ordinal = None
            adapter = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                plan.item_id,
                TECHNICAL_DEBT_PRODUCER,
                self._snapshot_id,
                source_refs=tuple(record.evidence_id for record in plan.records),
                scope=plan.source.project or "repository",
                language=plan.source.language,
                detail={
                    "category": TechnicalDebtCategory.DEPENDENCY_CYCLE.value,
                    "refactoring_advice_count": len(plan.advice_ids),
                    "evidence_backed_refactoring_advice_count": len(
                        plan.evidence_backed_advice_ids
                    ),
                    "omitted_refactoring_advice_evidence_count": (
                        plan.omitted_advice_evidence_count
                    ),
                    "representative_refactoring_advice_id": plan.advice.advice_id,
                    "advice_set_digest": technical_debt_advice_set_digest(
                        plan.advice_ids,
                        plan.evidence_backed_advice_ids,
                    ),
                    "impact_fingerprint": (
                        plan.impact_fingerprint or "unavailable"
                    ),
                    "impact_state": plan.impact.state.value,
                    "affected_count": plan.impact.affected_count,
                },
                limitations=TECHNICAL_DEBT_ITEM_LIMITATIONS,
                reliability=plan.advice.confidence.score,
                specificity=1.0,
            )
            for record in (*plan.records, adapter):
                evidence.add(record)
            item_evidence = tuple(sorted({
                *(record.evidence_id for record in plan.records),
                adapter.evidence_id,
            }))
            items.append(TechnicalDebtItem(
                plan.item_id,
                ordinal,
                TechnicalDebtCategory.DEPENDENCY_CYCLE,
                plan.advice.subjects,
                plan.source,
                plan.target,
                plan.advice_ids,
                plan.evidence_backed_advice_ids,
                plan.advice.advice_id,
                plan.omitted_advice_evidence_count,
                plan.impact_fingerprint,
                DEPENDENCY_CYCLE_OBSERVATION,
                plan.advice.confidence,
                item_evidence,
                plan.impact,
                plan.risk_context,
                plan.risk_subject_id,
                plan.complexity_subject_ids,
                plan.complexity_evidence_ids,
                bool(plan.complexity_subject_ids),
                tuple(sorted({
                    *TECHNICAL_DEBT_ITEM_LIMITATIONS,
                    *plan.advice_limitations,
                    *(
                        (
                            "Equivalent PR137 advice evidence reached the deterministic per-item bound; omitted advice IDs remain explicit.",
                        )
                        if plan.omitted_advice_evidence_count
                        else ()
                    ),
                })),
            ))

        total = upstream.total_candidate_count
        evaluated = len(advice)
        unique = len(plans)
        equivalent = evaluated - unique
        unevaluated = total - evaluated
        output_omitted = unique - len(items)
        omitted = equivalent + unevaluated + output_omitted
        limitations = {
            "PR142 ranks only fully revalidated dependency-cycle seam observations from PR137.",
            "Ranking is ordinal and uses represented PR136 impact counts; no composite debt score exists.",
            "Returning no candidate does not prove that the repository has no technical debt.",
        }
        if equivalent:
            limitations.add(
                "Equivalent PR137 observations for the same directed seam were collapsed into one debt item."
            )
        if unevaluated or output_omitted:
            limitations.add(
                "Candidate and result bounds omitted dependency-cycle seam observations from this response."
            )
        if upstream.truncated:
            limitations.update(upstream.limitations)
        capabilities = self._capabilities(
            upstream, plans, coverage_denominator=total,
        )
        return TechnicalDebtResponse(
            request,
            tuple(items),
            capabilities,
            evidence.freeze(),
            technical_debt_fingerprint(
                self._snapshot_id, self._graph_digest, request
            ),
            self._graph_digest,
            self._snapshot_id,
            total,
            evaluated,
            unique,
            equivalent,
            unevaluated,
            output_omitted,
            omitted,
            bool(unevaluated or output_omitted),
            tuple(sorted(limitations)),
        )

    @staticmethod
    def _group_equivalent_advice(
        advice: tuple[RefactoringAdvice, ...],
    ) -> tuple[tuple[RefactoringAdvice, ...], ...]:
        grouped: dict[tuple[str, str], list[RefactoringAdvice]] = {}
        for item in advice:
            roles = dict(item.attributes)
            key = (roles["source"], roles["target"])
            grouped.setdefault(key, []).append(item)
        return tuple(
            tuple(sorted(grouped[key], key=lambda item: item.advice_id))
            for key in sorted(grouped)
        )

    def _plan(
        self,
        advice_group: tuple[RefactoringAdvice, ...],
        advice_records: dict[str, EvidenceRecord],
        request: TechnicalDebtRequest,
    ) -> _DebtPlan:
        if not advice_group:
            raise ValueError("technical debt advice groups must not be empty")
        advice = min(
            advice_group,
            key=lambda item: (item.confidence.score, item.advice_id),
        )
        ordered_advice = tuple(sorted(
            advice_group, key=lambda item: item.advice_id
        ))
        evidence_advice = list(
            ordered_advice[:_MAX_GROUPED_ADVICE_EVIDENCE]
        )
        if advice not in evidence_advice:
            evidence_advice[-1] = advice
            evidence_advice.sort(key=lambda item: item.advice_id)
        roles = dict(advice.attributes)
        source = next(
            item for item in advice.subjects
            if item.canonical_id == roles["source"]
        )
        target = next(
            item for item in advice.subjects
            if item.canonical_id == roles["target"]
        )
        advice_ids = tuple(sorted(item.advice_id for item in advice_group))
        evidence_backed_advice_ids = tuple(
            item.advice_id for item in evidence_advice
        )
        omitted_advice_evidence_count = (
            len(advice_ids) - len(evidence_backed_advice_ids)
        )
        retained_advice = tuple(sorted({
            advice_records[evidence_id]
            for item in evidence_advice
            for evidence_id in item.evidence_ids
        }))
        advice_limitations = tuple(sorted({
            limitation
            for item in advice_group
            for limitation in item.limitations
        }))
        response: ImpactPredictionResponse | None = None
        impact_rejected = False
        try:
            response = self._impact.predict(ImpactPredictionRequest(
                SubjectQuery(source.canonical_id, source.kind),
                ImpactChangeKind.DEPENDENCY,
                relations=(KnowledgeRelation.DEPENDS_ON, KnowledgeRelation.IMPORTS),
                max_depth=request.impact_depth,
                limit=_IMPACT_RESULT_LIMIT,
                include_tests=False,
                include_dependencies=True,
                include_risk=False,
                additional_subjects=(SubjectQuery(target.canonical_id, target.kind),),
            ))
        except (TypeError, ValueError):
            impact_rejected = True

        impact, impact_records = self._compact_impact(
            response, source, rejected=impact_rejected,
        )
        risk_candidates: list[
            tuple[float, int, str, ImpactRiskContext, tuple[EvidenceRecord, ...]]
        ] = []
        risk_capabilities = []
        for participant in sorted(
            (source, target), key=lambda item: item.canonical_id
        ):
            context, risk_evidence, capability = (
                self._impact.risk_context_for_subject(participant)
            )
            risk_capabilities.append(capability)
            if context is not None:
                risk_candidates.append((
                    -context.score,
                    context.rank,
                    participant.canonical_id,
                    context,
                    risk_evidence.records,
                ))
        selected_risk = min(risk_candidates) if risk_candidates else None
        risk = selected_risk[3] if selected_risk is not None else None
        risk_records = selected_risk[4] if selected_risk is not None else ()
        risk_subject_id = selected_risk[2] if selected_risk is not None else None
        complexity_candidates = tuple(
            item for item in risk_candidates if "complexity" in item[3].signals
        )
        complexity_subject_ids = tuple(sorted({
            item[2] for item in complexity_candidates
        }))
        complexity_evidence_ids = tuple(sorted({
            evidence_id
            for item in complexity_candidates
            for evidence_id in item[3].evidence_ids
        }))
        complexity_records = tuple(sorted({
            record
            for item in complexity_candidates
            for record in item[4]
        }))
        risk_state, risk_limitations = self._risk_capability(
            risk_capabilities, risk
        )
        impact_fingerprint = response.input_fingerprint if response is not None else None
        item_id = technical_debt_item_id(
            source.canonical_id,
            target.canonical_id,
        )
        return _DebtPlan(
            advice,
            advice_ids,
            evidence_backed_advice_ids,
            omitted_advice_evidence_count,
            advice_limitations,
            source,
            target,
            item_id,
            impact_fingerprint,
            impact,
            risk,
            risk_subject_id,
            complexity_subject_ids,
            complexity_evidence_ids,
            risk_state,
            risk_limitations,
            tuple(sorted({
                *retained_advice,
                *impact_records,
                *risk_records,
                *complexity_records,
            })),
        )

    def _compact_impact(
        self,
        response: ImpactPredictionResponse | None,
        subject: SubjectCandidate,
        *,
        rejected: bool,
    ) -> tuple[TechnicalDebtImpact, tuple[EvidenceRecord, ...]]:
        if rejected:
            return (
                TechnicalDebtImpact(
                    TechnicalDebtState.INCOMPATIBLE,
                    limitations=(
                        "PR136 rejected the bounded impact request; this candidate remains unranked.",
                    ),
                ),
                (),
            )
        if response is None or (
            response.lineage != self._snapshot_id
            or response.graph_digest != self._graph_digest
        ):
            return (
                TechnicalDebtImpact(
                    TechnicalDebtState.UNAVAILABLE,
                    limitations=(
                        "Compatible bounded PR136 impact evidence was unavailable; this candidate remains unranked.",
                    ),
                ),
                (),
            )
        if not response.findings:
            return (
                TechnicalDebtImpact(
                    TechnicalDebtState.INSUFFICIENT,
                    limitations=(
                        "No represented dependency or import impact was found; absence does not prove no impact.",
                    ),
                ),
                (),
            )
        selected_ids = tuple(sorted({
            evidence_id
            for finding in response.findings
            for evidence_id in finding.evidence_ids
        }))
        records_by_id = {
            record.evidence_id: record for record in response.evidence_index.records
        }
        if any(evidence_id not in records_by_id for evidence_id in selected_ids):
            return (
                TechnicalDebtImpact(
                    TechnicalDebtState.INCOMPATIBLE,
                    limitations=(
                        "PR136 impact evidence closure was incompatible; this candidate remains unranked.",
                    ),
                ),
                (),
            )
        projected_refs = safe_edge_evidence_refs(selected_ids)
        if not projected_refs:
            projected_refs = (response.input_fingerprint,)
        omitted_reference_count = max(0, len(selected_ids) - len(projected_refs))
        direct = sum(finding.direct for finding in response.findings)
        impact_limitations = tuple(sorted({
            _IMPACT_LIMITATION,
            *response.limitations,
            "PR142 retains a bounded non-reversible projection of PR136 evidence references; the PR136 input fingerprint preserves recomputation lineage.",
        }))
        adapter = EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            subject.canonical_id,
            TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER,
            self._snapshot_id,
            source_refs=projected_refs,
            scope=subject.project or "repository",
            language=subject.language,
            detail={
                "impact_input_fingerprint": response.input_fingerprint,
                "finding_count": len(response.findings),
                "direct_count": direct,
                "transitive_count": len(response.findings) - direct,
                "upstream_evidence_count": len(selected_ids),
                "retained_reference_count": len(projected_refs),
                "omitted_reference_count": omitted_reference_count,
            },
            limitations=impact_limitations,
            reliability=min(
                finding.confidence.score for finding in response.findings
            ),
            specificity=0.9,
        )
        return (
            TechnicalDebtImpact(
                TechnicalDebtState.PARTIAL,
                len(response.findings),
                direct,
                len(response.findings) - direct,
                response.omitted_count,
                response.truncated,
                tuple(finding.category.value for finding in response.findings),
                (adapter.evidence_id,),
                impact_limitations,
            ),
            (adapter,),
        )

    @staticmethod
    def _risk_capability(
        capabilities,
        context: ImpactRiskContext | None,
    ) -> tuple[ImpactCapabilityState, tuple[str, ...]]:
        if context is not None:
            return (
                ImpactCapabilityState.AVAILABLE,
                (
                    "Compatible PR132 risk context was projected for one exact cycle participant.",
                ),
            )
        states = {item.state for item in capabilities}
        limitations = tuple(sorted({
            limitation
            for item in capabilities
            for limitation in item.limitations
        }))
        if ImpactCapabilityState.INCOMPATIBLE in states:
            state = ImpactCapabilityState.INCOMPATIBLE
        elif ImpactCapabilityState.UNAVAILABLE in states:
            state = ImpactCapabilityState.UNAVAILABLE
        elif ImpactCapabilityState.UNSUPPORTED in states:
            state = ImpactCapabilityState.UNSUPPORTED
        else:
            state = ImpactCapabilityState.PARTIAL
        return (
            state,
            limitations or (
                "No compatible exact-subject PR132 risk context was available.",
            ),
        )

    @staticmethod
    def _plan_sort_key(plan: _DebtPlan) -> tuple[object, ...]:
        return (
            not plan.impact.represented,
            -plan.impact.affected_count if plan.impact.represented else 0,
            -plan.impact.direct_count if plan.impact.represented else 0,
            (
                -plan.risk_context.score
                if plan.impact.represented and plan.risk_context is not None
                else 1.0
            ),
            plan.item_id,
        )

    @staticmethod
    def _capabilities(
        upstream,
        plans: tuple[_DebtPlan, ...],
        *,
        coverage_denominator: int,
    ) -> tuple[TechnicalDebtCapability, ...]:
        cycle = next(
            item for item in upstream.capabilities
            if item.family is RefactoringFamily.CYCLE_BREAKING
        )
        cycle_state = {
            RefactoringCapabilityState.AVAILABLE: TechnicalDebtState.AVAILABLE,
            RefactoringCapabilityState.PARTIAL: TechnicalDebtState.PARTIAL,
            RefactoringCapabilityState.INSUFFICIENT: TechnicalDebtState.INSUFFICIENT,
            RefactoringCapabilityState.INCOMPATIBLE: TechnicalDebtState.INCOMPATIBLE,
        }.get(cycle.state, TechnicalDebtState.UNAVAILABLE)
        represented = sum(plan.impact.represented for plan in plans)
        risk = sum(plan.risk_context is not None for plan in plans)
        complexity = sum(
            bool(plan.complexity_subject_ids)
            for plan in plans
        )
        denominator = coverage_denominator
        impact_states = {plan.impact.state for plan in plans}
        if represented:
            impact_state = TechnicalDebtState.PARTIAL
        elif TechnicalDebtState.INCOMPATIBLE in impact_states:
            impact_state = TechnicalDebtState.INCOMPATIBLE
        elif TechnicalDebtState.UNAVAILABLE in impact_states:
            impact_state = TechnicalDebtState.UNAVAILABLE
        else:
            impact_state = TechnicalDebtState.INSUFFICIENT
        impact_limitations = tuple(sorted({
            limitation
            for plan in plans
            for limitation in plan.impact.limitations
        })) or (
            "No dependency-cycle candidate was available for bounded PR136 impact evaluation.",
        )
        risk_states = {plan.risk_state for plan in plans}
        if risk:
            risk_state = TechnicalDebtState.PARTIAL
        elif ImpactCapabilityState.INCOMPATIBLE in risk_states:
            risk_state = TechnicalDebtState.INCOMPATIBLE
        elif ImpactCapabilityState.UNAVAILABLE in risk_states:
            risk_state = TechnicalDebtState.UNAVAILABLE
        else:
            risk_state = TechnicalDebtState.INSUFFICIENT
        risk_limitations = tuple(sorted({
            limitation
            for plan in plans
            for limitation in plan.risk_limitations
        })) or (
            "No dependency-cycle candidate was available for exact-subject PR132 risk projection.",
        )
        if risk_state is TechnicalDebtState.INCOMPATIBLE:
            complexity_state = TechnicalDebtState.INCOMPATIBLE
        elif risk_state is TechnicalDebtState.UNAVAILABLE:
            complexity_state = TechnicalDebtState.UNAVAILABLE
        elif complexity:
            complexity_state = TechnicalDebtState.PARTIAL
        else:
            complexity_state = TechnicalDebtState.INSUFFICIENT
        return (
            TechnicalDebtCapability(
                TechnicalDebtCapabilityKind.CYCLE_EVIDENCE,
                cycle_state,
                cycle.coverage,
                cycle.limitations,
            ),
            TechnicalDebtCapability(
                TechnicalDebtCapabilityKind.ENGINEERING_IMPACT,
                impact_state,
                represented / denominator if denominator else None,
                tuple(sorted({
                    *impact_limitations,
                    _IMPACT_LIMITATION,
                    "Missing represented impact is unknown, not zero impact.",
                    "Coverage uses all known upstream PR137 seam observations; equivalent seams are one item and are not double-counted in the numerator.",
                })),
            ),
            TechnicalDebtCapability(
                TechnicalDebtCapabilityKind.RISK_CONTEXT,
                risk_state,
                risk / denominator if denominator else None,
                tuple(sorted({
                    *risk_limitations,
                    "PR132 risk is optional context and neither creates nor rescales a technical-debt observation.",
                    "Missing exact-subject risk is unknown, not zero risk.",
                    "Coverage uses all known upstream PR137 seam observations; equivalent seams are one item and are not double-counted in the numerator.",
                })),
            ),
            TechnicalDebtCapability(
                TechnicalDebtCapabilityKind.STRUCTURED_COMPLEXITY,
                complexity_state,
                complexity / denominator if denominator else None,
                (
                    (
                        "Complexity is reported only when the exact PR132 risk signals contain complexity."
                        if complexity else
                        "No attached PR132 risk context contained a complexity signal; absence is not proof of low complexity."
                    ),
                    "Coverage uses all known upstream PR137 seam observations; equivalent seams are one item and are not double-counted in the numerator.",
                ),
            ),
        )
