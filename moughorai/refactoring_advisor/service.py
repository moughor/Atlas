"""Deterministic, source-free PR137 refactoring advice.

The first PR137 slice deliberately consumes dependency cycles already reported by
PR128.  It does not discover cycles, infer architecture from names, or manufacture
unused-dependency, clone, complexity, cohesion, or layer evidence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import heapq

from moughorai.impact_analysis import (
    BreakingChangeState,
    ImpactChangeKind,
    ImpactPredictionRequest,
    ImpactPredictionService,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeRelation,
)
from moughorai.knowledge_graph.evidence import (
    has_authoritative_edge_evidence,
    safe_edge_evidence_refs,
)
from moughorai.measurement import MeasurementSession
from moughorai.repository_report.safety import contains_absolute_path_text
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    ResolutionStatus,
    SubjectCandidate,
    SubjectMatchBasis,
    SubjectQuery,
    SubjectResolution,
)

from .models import (
    EstimateLevel,
    RefactoringAdvice,
    RefactoringCapability,
    RefactoringEstimate,
    RefactoringEstimateComponent,
    RefactoringFamily,
    RefactoringImpact,
    RefactoringOperation,
    RefactoringRequest,
    RefactoringResponse,
    RefactoringCapabilityState as RefactoringState,
    _validate_subject_resolution,
    refactoring_advice_id,
    refactoring_fingerprint,
)


_CYCLE_ADAPTER_PRODUCER = "atlas-pr137-cycle-adapter/1"
_IMPACT_ADAPTER_PRODUCER = "atlas-pr137-impact-adapter/1"
_MAX_CYCLE_LENGTH = 64
_MAX_ARCHITECTURE_CYCLES = 4_096
_MAX_DEPENDENCY_EDGES_PER_STEP = 64
_MAX_IMPACT_CANDIDATES = 256
_IMPACT_RESULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _ArchitectureCycles:
    state: RefactoringState
    cycles: tuple[tuple[str, ...], ...]
    limitations: tuple[str, ...] = ()
    omitted_count: int = 0


@dataclass(frozen=True, slots=True)
class _VerifiedCycle:
    subjects: tuple[SubjectCandidate, ...]
    evidence: tuple[EvidenceRecord, ...]
    degree: int

    @property
    def identity(self) -> tuple[str, ...]:
        return tuple(item.canonical_id for item in self.subjects)


@dataclass(frozen=True, slots=True)
class _SeamPlan:
    cycle: _VerifiedCycle
    source: SubjectCandidate
    target: SubjectCandidate
    impact: RefactoringImpact
    impact_evidence: tuple[EvidenceRecord, ...] = ()
    visited_node_count: int = 0
    visited_edge_count: int = 0


class RefactoringAdvisorService:
    """Create bounded advice from existing, traceable Atlas findings only."""

    def __init__(
        self,
        resolver: CanonicalSubjectResolver,
        *,
        snapshot_id: str,
        analyzer_version: str,
        semantic_context: Mapping[str, object],
        measurement: MeasurementSession | None = None,
        confidence: ConfidenceCalculator | None = None,
    ) -> None:
        if not isinstance(resolver, CanonicalSubjectResolver):
            raise TypeError("refactoring advice requires a canonical subject resolver")
        if not snapshot_id.strip() or not analyzer_version.strip():
            raise ValueError("refactoring advice requires snapshot lineage")
        self._resolver = resolver
        self._snapshot_id = snapshot_id
        self._analyzer_version = analyzer_version
        self._context = semantic_context
        self._measurement = measurement or MeasurementSession()
        self._confidence = confidence or ConfidenceCalculator()
        self._architecture = self._architecture_cycles(semantic_context)
        # Accepted large-repository snapshots currently publish no usable PR128
        # cycles.  Avoid a second full graph scan unless there is an upstream
        # observation to revalidate.
        with self._measurement.scope(
            "refactoring_advisor.evidence_index",
            consumer="refactoring-advisor",
            sample_key=resolver.graph_digest,
        ) as scope:
            if self._architecture.cycles:
                self._dependency_steps, self._project_degrees = (
                    self._dependency_index(resolver.graph)
                )
                graph = resolver.graph
                scope.add_units(
                    len(graph.nodes) + len(graph.edges)
                    if graph is not None else 0
                )
                scope.set_objects_retained(len(self._dependency_steps))
            else:
                self._dependency_steps, self._project_degrees = {}, {}

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> RefactoringAdvisorService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("refactoring advisor snapshot is invalid")
        session = measurement or MeasurementSession()
        with session.scope(
            "refactoring_advisor.resolver_index",
            consumer="refactoring-advisor",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
            graph = resolver.graph
            scope.add_units(
                len(graph.nodes) + len(graph.edges) if graph is not None else 0
            )
            scope.set_objects_retained(len(graph.nodes) if graph is not None else 0)
        return cls(
            resolver,
            snapshot_id=snapshot.snapshot_id,
            analyzer_version=snapshot.analyzer_version,
            semantic_context=snapshot.semantic_context,
            measurement=session,
        )

    def advise(self, request: RefactoringRequest) -> RefactoringResponse:
        if not isinstance(request, RefactoringRequest):
            raise TypeError("refactoring request is invalid")
        with self._measurement.scope(
            "refactoring_advisor.query",
            consumer="refactoring-advisor",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            response = self._advise(request)
            scope.add_units(response.total_candidate_count)
            scope.add_objects_produced(response.total_candidate_count)
            scope.set_objects_retained(len(response.advice))
            return response

    def _advise(self, request: RefactoringRequest) -> RefactoringResponse:
        with self._measurement.scope(
            "refactoring_advisor.resolve",
            consumer="refactoring-advisor",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            resolution = self._resolver.resolve(request.subject)
            try:
                _validate_subject_resolution(resolution)
            except (TypeError, ValueError):
                resolution = SubjectResolution(
                    request.subject,
                    ResolutionStatus.UNAVAILABLE,
                    None,
                    (),
                    0,
                    0,
                    SubjectMatchBasis.NONE,
                    self._resolver.graph_digest,
                    (
                        "Canonical subject metadata violated the PR137 source-free boundary.",
                    ),
                )
            scope.add_units(1)
            scope.set_objects_retained(1 if resolution.subject is not None else 0)

        fingerprint = refactoring_fingerprint(
            self._snapshot_id, self._resolver.graph_digest, request
        )
        if (
            resolution.status is not ResolutionStatus.RESOLVED
            or resolution.subject is None
            or self._resolver.graph is None
        ):
            capabilities = self._capabilities(
                request,
                cycle_count=0,
                cycle_state=RefactoringState.UNAVAILABLE,
                cycle_limitations=(
                    "Canonical subject resolution is required before refactoring advice can be evaluated.",
                ),
            )
            return RefactoringResponse(
                request,
                resolution,
                (),
                capabilities,
                EvidenceIndex().freeze(),
                fingerprint,
                self._resolver.graph_digest,
                self._snapshot_id,
                limitations=tuple(sorted({
                    *resolution.limitations,
                    "No advice was created because the requested canonical scope was unresolved.",
                })),
            )

        selected = not request.families or (
            RefactoringFamily.CYCLE_BREAKING in request.families
        )
        verified: tuple[_VerifiedCycle, ...] = ()
        invalid_cycle_count = 0
        out_of_scope_cycle_count = 0
        visited_node_count = 0
        visited_edge_count = 0
        if selected and self._architecture.cycles:
            with self._measurement.scope(
                "refactoring_advisor.cycle_validate",
                consumer="refactoring-advisor",
                sample_key=self._resolver.graph_digest,
            ) as scope:
                (
                    verified,
                    invalid_cycle_count,
                    out_of_scope_cycle_count,
                    visited_node_count,
                    visited_edge_count,
                ) = self._verified_cycles(
                    self._architecture.cycles,
                    resolution,
                )
                scope.add_units(len(self._architecture.cycles))
                scope.add_objects_produced(sum(len(item.subjects) for item in verified))
                scope.set_objects_retained(len(verified))

        total_candidate_count = sum(len(cycle.subjects) for cycle in verified)
        preselected = tuple(heapq.nsmallest(
            min(total_candidate_count, _MAX_IMPACT_CANDIDATES),
            (
                (
                    cycle,
                    cycle.subjects[index],
                    cycle.subjects[(index + 1) % len(cycle.subjects)],
                )
                for cycle in verified
                for index in range(len(cycle.subjects))
            ),
            key=lambda item: (
                item[0].degree,
                item[1].canonical_id,
                item[2].canonical_id,
                item[0].identity,
            ),
        ))
        bounded_before_impact = total_candidate_count - len(preselected)
        impact_service = (
            ImpactPredictionService(
                self._resolver,
                snapshot_id=self._snapshot_id,
                analyzer_version=self._analyzer_version,
                semantic_context=self._context,
                measurement=self._measurement,
            )
            if request.include_impact and preselected
            else None
        )

        with self._measurement.scope(
            "refactoring_advisor.impact",
            consumer="refactoring-advisor",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            plans = tuple(
                self._with_impact(
                    cycle,
                    source,
                    target,
                    request,
                    impact_service,
                )
                for cycle, source, target in preselected
            )
            scope.add_units(len(preselected))
            scope.add_objects_produced(sum(item.impact.affected_count for item in plans))
            scope.set_objects_retained(len(plans))
        visited_node_count += sum(item.visited_node_count for item in plans)
        visited_edge_count += sum(item.visited_edge_count for item in plans)

        ordered = tuple(sorted(plans, key=self._plan_sort_key))
        retained = ordered[: request.limit]
        omitted_count = total_candidate_count - len(retained)
        evidence = EvidenceIndex()
        advice = []
        with self._measurement.scope(
            "refactoring_advisor.materialize",
            consumer="refactoring-advisor",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            for plan in retained:
                for record in (*plan.cycle.evidence, *plan.impact_evidence):
                    evidence.add(record)
                advice.append(self._advice(plan, evidence))
            scope.add_units(len(retained))
            scope.add_objects_produced(len(advice) + len(evidence))
            scope.set_objects_retained(len(advice) + len(evidence))

        cycle_limitations = set(self._architecture.limitations)
        if invalid_cycle_count:
            cycle_limitations.add(
                f"Ignored {invalid_cycle_count} reported cycle(s) that could not be fully and uniquely revalidated."
            )
        if bounded_before_impact:
            cycle_limitations.add(
                "Candidate impact evaluation reached its deterministic hard bound."
            )
        cycle_state = self._architecture.state
        if verified:
            cycle_state = (
                RefactoringState.PARTIAL
                if self._architecture.state is not RefactoringState.AVAILABLE
                or invalid_cycle_count or self._architecture.omitted_count
                or bounded_before_impact
                else RefactoringState.AVAILABLE
            )
            cycle_limitations.add(
                "Availability applies only to the cited PR128 cycles; complete repository dependency-cycle coverage is not implied."
            )
        elif (
            selected
            and self._architecture.cycles
            and self._architecture.state is RefactoringState.AVAILABLE
            and not out_of_scope_cycle_count
        ):
            cycle_state = RefactoringState.INSUFFICIENT
            cycle_limitations.add(
                "No reported cycle had complete authoritative canonical edge evidence."
            )
        elif selected and out_of_scope_cycle_count and not verified:
            cycle_limitations.add(
                "No reported dependency cycle intersects the requested canonical scope."
            )
        elif (
            selected
            and not self._architecture.cycles
            and self._architecture.state is RefactoringState.AVAILABLE
        ):
            cycle_limitations.add(
                "PR128 reported no cycle within represented dependency evidence; unrepresented relationships remain unknown."
            )

        capabilities = self._capabilities(
            request,
            cycle_count=total_candidate_count,
            cycle_state=cycle_state,
            cycle_limitations=tuple(sorted(cycle_limitations)),
        )
        limitations = set(resolution.limitations)
        limitations.update(self._architecture.limitations)
        if omitted_count:
            limitations.add(
                "Refactoring advice was deterministically bounded; omitted candidates were not presented as evaluated advice."
            )
        if invalid_cycle_count:
            limitations.add(
                "Some upstream cycle records were ignored because canonical identity or relationship evidence was incomplete."
            )
        return RefactoringResponse(
            request=request,
            resolution=resolution,
            advice=tuple(advice),
            capabilities=capabilities,
            evidence_index=evidence.freeze(),
            input_fingerprint=fingerprint,
            graph_digest=self._resolver.graph_digest,
            lineage=self._snapshot_id,
            total_candidate_count=total_candidate_count,
            omitted_count=omitted_count,
            truncated=bool(omitted_count),
            limitations=tuple(sorted(limitations)),
            visited_node_count=visited_node_count,
            visited_edge_count=visited_edge_count,
        )

    def _verified_cycles(
        self,
        cycles: tuple[tuple[str, ...], ...],
        scope: SubjectResolution,
    ) -> tuple[tuple[_VerifiedCycle, ...], int, int, int, int]:
        verified: dict[tuple[str, ...], _VerifiedCycle] = {}
        invalid = 0
        out_of_scope = 0
        visited_nodes = 0
        visited_edges = 0
        for raw_cycle in cycles:
            visited_nodes += len(raw_cycle)
            resolved = self._resolve_cycle(raw_cycle)
            if resolved is None:
                invalid += 1
                continue
            if not self._in_scope(resolved, scope):
                out_of_scope += 1
                continue
            canonical = self._rotate_cycle(resolved)
            identity = tuple(item.canonical_id for item in canonical)
            if identity in verified:
                continue
            step_records = []
            valid = True
            for index, source in enumerate(canonical):
                visited_edges += 1
                target = canonical[(index + 1) % len(canonical)]
                matches = self._dependency_steps.get(
                    (source.graph_id, target.graph_id), ()
                )
                if not matches:
                    valid = False
                    break
                refs = safe_edge_evidence_refs(
                    reference
                    for edge in matches
                    for reference in edge.evidence
                )
                if not refs:
                    valid = False
                    break
                step_records.append(EvidenceRecord.create(
                    EvidenceKind.GRAPH_EDGE,
                    f"{source.canonical_id}|dependency-cycle-step|{target.canonical_id}",
                    _CYCLE_ADAPTER_PRODUCER,
                    self._snapshot_id,
                    source_refs=refs,
                    scope="repository",
                    detail={
                        "source": source.canonical_id,
                        "target": target.canonical_id,
                        "relations": ",".join(sorted({
                            edge.relation.value for edge in matches
                        })),
                    },
                    reliability=1.0,
                    specificity=1.0,
                ))
            if not valid:
                invalid += 1
                continue
            cycle_digest = hashlib.sha256(
                "\0".join(identity).encode("utf-8")
            ).hexdigest()
            cycle_record = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                f"dependency-cycle:{cycle_digest}",
                _CYCLE_ADAPTER_PRODUCER,
                self._snapshot_id,
                source_refs=tuple(item.evidence_id for item in step_records),
                scope="repository",
                detail={
                    "cycle_length": str(len(canonical)),
                    "upstream": "architecture.dependency_cycles",
                    "validation": "all-steps-authoritative",
                },
                limitations=(
                    "Cycle coverage is bounded to relationships represented by PR128 and PR129.",
                ),
                reliability=0.9,
                specificity=1.0,
            )
            degree = sum(
                self._project_degrees.get(item.graph_id, 0) for item in canonical
            )
            verified[identity] = _VerifiedCycle(
                canonical,
                (*tuple(step_records), cycle_record),
                degree,
            )
        return (
            tuple(verified[key] for key in sorted(verified)),
            invalid,
            out_of_scope,
            visited_nodes,
            visited_edges,
        )

    def _resolve_cycle(
        self,
        raw_cycle: tuple[str, ...],
    ) -> tuple[SubjectCandidate, ...] | None:
        values = raw_cycle[:-1] if len(raw_cycle) > 1 and raw_cycle[0] == raw_cycle[-1] else raw_cycle
        if (
            len(values) < 2
            or len(values) > _MAX_CYCLE_LENGTH
            or len(set(values)) != len(values)
        ):
            return None
        result = []
        for value in values:
            try:
                resolution = self._resolver.resolve(
                    SubjectQuery(value, KnowledgeKind.PROJECT)
                )
                _validate_subject_resolution(resolution)
            except (TypeError, ValueError):
                return None
            if (
                resolution.status is not ResolutionStatus.RESOLVED
                or resolution.subject is None
                or resolution.subject.kind is not KnowledgeKind.PROJECT
            ):
                return None
            result.append(resolution.subject)
        return tuple(result)

    @staticmethod
    def _rotate_cycle(
        values: tuple[SubjectCandidate, ...],
    ) -> tuple[SubjectCandidate, ...]:
        rotations = tuple(values[index:] + values[:index] for index in range(len(values)))
        return min(
            rotations,
            key=lambda items: tuple(item.canonical_id for item in items),
        )

    @staticmethod
    def _in_scope(
        cycle: tuple[SubjectCandidate, ...],
        resolution: SubjectResolution,
    ) -> bool:
        subject = resolution.subject
        if subject is None:
            return False
        if subject.kind in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
            return True
        if subject.kind is KnowledgeKind.PROJECT:
            return subject.canonical_id in {item.canonical_id for item in cycle}
        if subject.project is None:
            return False
        return subject.project in {
            value
            for item in cycle
            for value in (item.name, item.qualified_name, item.project or "")
        }

    def _with_impact(
        self,
        cycle: _VerifiedCycle,
        source: SubjectCandidate,
        target: SubjectCandidate,
        request: RefactoringRequest,
        impact_service: ImpactPredictionService | None,
    ) -> _SeamPlan:
        if not request.include_impact or impact_service is None:
            return _SeamPlan(
                cycle,
                source,
                target,
                RefactoringImpact(
                    RefactoringState.UNAVAILABLE,
                    limitations=(
                        "Impact enrichment was disabled by the request; no low-effort conclusion was inferred.",
                    ),
                ),
            )
        try:
            response = impact_service.predict(ImpactPredictionRequest(
                SubjectQuery(source.canonical_id, KnowledgeKind.PROJECT),
                ImpactChangeKind.DEPENDENCY,
                relations=(KnowledgeRelation.DEPENDS_ON, KnowledgeRelation.IMPORTS),
                max_depth=request.impact_depth,
                limit=_IMPACT_RESULT_LIMIT,
                include_tests=False,
                include_dependencies=True,
                include_risk=False,
                additional_subjects=(
                    SubjectQuery(target.canonical_id, KnowledgeKind.PROJECT),
                ),
            ))
        except (TypeError, ValueError):
            return _SeamPlan(
                cycle,
                source,
                target,
                RefactoringImpact(
                    RefactoringState.UNAVAILABLE,
                    limitations=(
                        "Compatible bounded PR136 impact evidence was unavailable; effort remains unknown.",
                    ),
                ),
            )
        upstream_records = response.evidence_index.records
        if (
            response.lineage != self._snapshot_id
            or response.graph_digest != self._resolver.graph_digest
            or any(
                record.snapshot_id != self._snapshot_id
                for record in upstream_records
            )
        ):
            return _SeamPlan(
                cycle,
                source,
                target,
                RefactoringImpact(
                    RefactoringState.INCOMPATIBLE,
                    limitations=(
                        "PR136 impact evidence did not match the current snapshot lineage.",
                    ),
                ),
            )
        upstream_ids = {record.evidence_id for record in upstream_records}
        adapters = []
        for finding in response.findings:
            if not set(finding.evidence_ids).issubset(upstream_ids):
                return _SeamPlan(
                    cycle,
                    source,
                    target,
                    RefactoringImpact(
                        RefactoringState.INCOMPATIBLE,
                        limitations=(
                            "PR136 impact evidence closure was incomplete.",
                        ),
                    ),
                )
            adapters.append(EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                f"{source.canonical_id}|impact|{finding.subject.canonical_id}",
                _IMPACT_ADAPTER_PRODUCER,
                self._snapshot_id,
                source_refs=finding.evidence_ids,
                scope="repository",
                detail={
                    "affected_subject": finding.subject.canonical_id,
                    "category": finding.category.value,
                    "direct": str(finding.direct).lower(),
                    "path_length": str(finding.path.length),
                },
                reliability=0.9,
                specificity=0.9,
            ))
        breaking_refs = response.breaking_change.evidence_ids
        if breaking_refs:
            if not set(breaking_refs).issubset(upstream_ids):
                return _SeamPlan(
                    cycle,
                    source,
                    target,
                    RefactoringImpact(
                        RefactoringState.INCOMPATIBLE,
                        limitations=(
                            "PR136 breaking-change evidence closure was incomplete.",
                        ),
                    ),
                )
            adapters.append(EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                f"{source.canonical_id}|breaking-change",
                _IMPACT_ADAPTER_PRODUCER,
                self._snapshot_id,
                source_refs=breaking_refs,
                scope="repository",
                detail={"state": response.breaking_change.state.value},
                reliability=0.9,
                specificity=0.9,
            ))
        adapters_tuple = tuple(sorted(set(adapters)))
        evidence_ids = tuple(item.evidence_id for item in adapters_tuple)
        direct_count = sum(item.direct for item in response.findings)
        possible_breaking_count = sum(
            item.breaking_change is not None
            and item.breaking_change.state in {
                BreakingChangeState.PROVEN_BREAKING,
                BreakingChangeState.POTENTIALLY_BREAKING,
            }
            for item in response.findings
        )
        impact = RefactoringImpact(
            state=RefactoringState.PARTIAL,
            affected_count=len(response.findings),
            direct_count=direct_count,
            transitive_count=len(response.findings) - direct_count,
            omitted_count=response.omitted_count,
            possible_breaking_count=possible_breaking_count,
            truncated=response.truncated,
            breaking_state=response.breaking_change.state.value,
            evidence_ids=evidence_ids,
            limitations=(
                "PR136 impact is bounded and repository-local; missing call, test, composition, and external-consumer evidence remains unknown.",
            ),
        )
        return _SeamPlan(
            cycle,
            source,
            target,
            impact,
            adapters_tuple,
            response.visited_node_count,
            response.visited_edge_count,
        )

    def _advice(
        self,
        plan: _SeamPlan,
        evidence: EvidenceIndex,
    ) -> RefactoringAdvice:
        cycle_ids = tuple(item.evidence_id for item in plan.cycle.evidence)
        confidence = self._confidence.calculate(
            (
                EvidenceRole("reported dependency cycle", (cycle_ids[-1],)),
                EvidenceRole("revalidated cycle steps", cycle_ids[:-1]),
            ),
            evidence,
            coverage=1.0,
        )
        expected_gain = RefactoringEstimate(
            EstimateLevel.UNKNOWN,
            None,
            (
                RefactoringEstimateComponent(
                    "verified_cycle_coverage",
                    True,
                    1.0,
                    1.0,
                    1.0,
                    cycle_ids,
                ),
            ),
            (
                "The cycle seam is proven, but available evidence cannot quantify the architectural or build benefit of changing it.",
            ),
        )
        effort = self._effort(plan)
        all_evidence_ids = tuple(sorted({
            *cycle_ids,
            *plan.impact.evidence_ids,
        }))
        attributes = (
            ("source", plan.source.canonical_id),
            ("target", plan.target.canonical_id),
        )
        advice_id = refactoring_advice_id(
            RefactoringFamily.CYCLE_BREAKING,
            RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM,
            (plan.source, plan.target),
            all_evidence_ids,
            attributes,
        )
        return RefactoringAdvice(
            advice_id,
            RefactoringFamily.CYCLE_BREAKING,
            RefactoringOperation.REVIEW_DEPENDENCY_CYCLE_SEAM,
            (plan.source, plan.target),
            confidence,
            all_evidence_ids,
            (
                "Review this canonical project dependency seam because it participates in a PR128 cycle whose every step was revalidated against authoritative PR129 relationships."
            ),
            (
                "Confirm a stable alternative dependency direction or abstraction before changing the seam.",
                "Preserve represented public API and build semantics.",
            ),
            expected_gain,
            effort,
            plan.impact,
            (
                "Advice identifies a review seam, not an automatically safe edge removal.",
                "The cycle result is bounded to represented static dependency evidence.",
            ),
            (
                "Re-run dependency-cycle analysis and confirm the cited cycle is absent.",
                "Run affected project builds and tests after any manually reviewed change.",
            ),
            attributes,
        )

    @staticmethod
    def _effort(plan: _SeamPlan) -> RefactoringEstimate:
        components = (
            RefactoringEstimateComponent(
                "public_api_exposure", False, None, 0.0, 0.0, (),
                "Complete public and external API exposure is unavailable.",
            ),
            RefactoringEstimateComponent(
                "test_coverage", False, None, 0.0, 0.0, (),
                "Resolved test coverage for the proposed seam change is unavailable.",
            ),
            RefactoringEstimateComponent(
                "language_support", False, None, 0.0, 0.0, (),
                "Cross-project language and build semantics are not completely represented.",
            ),
        )
        limitations = {
            "Missing API, test, and language signals prevent an effort estimate.",
        }
        if plan.impact.state in {RefactoringState.AVAILABLE, RefactoringState.PARTIAL}:
            limitations.add(
                "Bounded PR136 blast radius is reported separately and does not establish total refactoring effort."
            )
        else:
            limitations.add("Bounded PR136 blast-radius evidence is unavailable.")
        return RefactoringEstimate(
            EstimateLevel.UNKNOWN,
            None,
            components,
            tuple(sorted(limitations)),
        )

    @staticmethod
    def _plan_sort_key(plan: _SeamPlan) -> tuple[object, ...]:
        impact_unknown = plan.impact.state not in {
            RefactoringState.AVAILABLE,
            RefactoringState.PARTIAL,
        }
        return (
            impact_unknown,
            plan.impact.affected_count if not impact_unknown else 0,
            plan.impact.omitted_count if not impact_unknown else 0,
            plan.impact.truncated if not impact_unknown else False,
            plan.cycle.degree,
            plan.source.canonical_id,
            plan.target.canonical_id,
            plan.cycle.identity,
        )

    def _capabilities(
        self,
        request: RefactoringRequest,
        *,
        cycle_count: int,
        cycle_state: RefactoringState,
        cycle_limitations: tuple[str, ...],
    ) -> tuple[RefactoringCapability, ...]:
        selected = set(request.families) if request.families else set(RefactoringFamily)
        values = {
            RefactoringFamily.DUPLICATE_CONSOLIDATION: RefactoringCapability(
                RefactoringFamily.DUPLICATE_CONSOLIDATION,
                RefactoringState.UNAVAILABLE,
                limitations=(
                    "Atlas has no authoritative structural duplicate or clone producer; identity-collision checks are not duplicate-code evidence.",
                ),
            ),
            RefactoringFamily.EXTRACTION: RefactoringCapability(
                RefactoringFamily.EXTRACTION,
                RefactoringState.INSUFFICIENT,
                limitations=(
                    "Production complexity, cohesion, and symbol-size evidence is unavailable; graph degree is not a substitute.",
                ),
            ),
            RefactoringFamily.PACKAGE_RESTRUCTURING: RefactoringCapability(
                RefactoringFamily.PACKAGE_RESTRUCTURING,
                RefactoringState.INSUFFICIENT,
                limitations=(
                    "No authoritative dependency-cluster and target-boundary producer is available; package names do not establish architecture.",
                ),
            ),
            RefactoringFamily.DEPENDENCY_CLEANUP: RefactoringCapability(
                RefactoringFamily.DEPENDENCY_CLEANUP,
                RefactoringState.INSUFFICIENT,
                limitations=(
                    "Declared dependencies do not prove usage, and complete dependency usage/build evidence is unavailable.",
                ),
            ),
            RefactoringFamily.CYCLE_BREAKING: RefactoringCapability(
                family=RefactoringFamily.CYCLE_BREAKING,
                state=(
                    cycle_state
                    if RefactoringFamily.CYCLE_BREAKING in selected
                    else RefactoringState.UNAVAILABLE
                ),
                candidate_count=(
                    cycle_count
                    if RefactoringFamily.CYCLE_BREAKING in selected
                    else 0
                ),
                coverage=(
                    1.0
                    if RefactoringFamily.CYCLE_BREAKING in selected
                    and cycle_state is RefactoringState.AVAILABLE
                    else None
                ),
                limitations=(
                    cycle_limitations
                    if RefactoringFamily.CYCLE_BREAKING in selected
                    else ("Cycle-breaking advice was not requested.",)
                ),
            ),
            RefactoringFamily.LAYER_VIOLATION: RefactoringCapability(
                RefactoringFamily.LAYER_VIOLATION,
                RefactoringState.UNAVAILABLE,
                limitations=(
                    "Typed Java layer-policy findings are not published in semantic snapshots; PR128 name matches cannot establish a violation.",
                ),
            ),
        }
        return tuple(values[family] for family in RefactoringFamily)

    @staticmethod
    def _architecture_cycles(
        context: Mapping[str, object],
    ) -> _ArchitectureCycles:
        raw = context.get("architecture")
        if raw is None:
            return _ArchitectureCycles(
                RefactoringState.UNAVAILABLE,
                (),
                ("PR128 architecture analysis is unavailable in this snapshot.",),
            )
        if not isinstance(raw, Mapping):
            return _ArchitectureCycles(
                RefactoringState.INCOMPATIBLE,
                (),
                ("PR128 architecture analysis is malformed.",),
            )
        schema = raw.get("schema_version")
        if isinstance(schema, bool) or not isinstance(schema, int) or schema != 1:
            return _ArchitectureCycles(
                RefactoringState.INCOMPATIBLE,
                (),
                ("Only PR128 architecture schema version 1 is supported.",),
            )
        dependency = raw.get("dependency_analysis")
        if not isinstance(dependency, Mapping) or dependency.get("executed") is not True:
            return _ArchitectureCycles(
                RefactoringState.INSUFFICIENT,
                (),
                ("PR128 dependency analysis did not execute; missing cycles are not a negative result.",),
            )
        raw_cycles = raw.get("dependency_cycles")
        if not isinstance(raw_cycles, Sequence) or isinstance(
            raw_cycles, (str, bytes, bytearray)
        ):
            return _ArchitectureCycles(
                RefactoringState.INCOMPATIBLE,
                (),
                ("PR128 dependency-cycle records are malformed.",),
            )
        evidence_edge_count = dependency.get("evidence_edge_count")
        if (
            isinstance(evidence_edge_count, bool)
            or not isinstance(evidence_edge_count, int)
            or evidence_edge_count <= 0
        ):
            return _ArchitectureCycles(
                RefactoringState.INSUFFICIENT,
                (),
                (
                    "PR128 dependency analysis did not report a positive authoritative dependency evidence-edge count.",
                ),
            )
        normalized = set()
        malformed = 0
        for raw_cycle in raw_cycles:
            if not isinstance(raw_cycle, Sequence) or isinstance(
                raw_cycle, (str, bytes, bytearray)
            ):
                malformed += 1
                continue
            if any(not isinstance(item, str) for item in raw_cycle):
                malformed += 1
                continue
            values = tuple(item.strip() for item in raw_cycle)
            if any(
                not item or contains_absolute_path_text(item)
                for item in values
            ):
                malformed += 1
                continue
            open_cycle = (
                values[:-1]
                if len(values) > 1 and values[0] == values[-1]
                else values
            )
            if not open_cycle:
                malformed += 1
                continue
            normalized.add(min(
                open_cycle[index:] + open_cycle[:index]
                for index in range(len(open_cycle))
            ))
        ordered = tuple(sorted(normalized))
        retained = ordered[:_MAX_ARCHITECTURE_CYCLES]
        omitted = len(ordered) - len(retained)
        limitations = []
        if malformed:
            limitations.append(
                f"Ignored {malformed} malformed PR128 dependency-cycle record(s)."
            )
        if omitted:
            limitations.append(
                "PR128 dependency-cycle input reached the deterministic adapter bound."
            )
        return _ArchitectureCycles(
            (
                RefactoringState.PARTIAL
                if malformed or omitted
                else RefactoringState.AVAILABLE
            ),
            retained,
            tuple(limitations),
            omitted,
        )

    @staticmethod
    def _dependency_index(
        graph: KnowledgeGraph | None,
    ) -> tuple[
        Mapping[tuple[str, str], tuple[KnowledgeEdge, ...]],
        Mapping[str, int],
    ]:
        if graph is None:
            return {}, {}
        projects = {
            node.id: node for node in graph.by_kind(KnowledgeKind.PROJECT)
        }
        project_name_candidates: dict[str, list[str]] = defaultdict(list)
        for node in projects.values():
            project_name_candidates[node.name].append(node.id)
        project_ids_by_name = {
            name: identifiers[0]
            for name, identifiers in project_name_candidates.items()
            if len(identifiers) == 1
        }
        steps: dict[tuple[str, str], list[KnowledgeEdge]] = defaultdict(list)
        neighbors: dict[str, set[str]] = defaultdict(set)
        for edge in graph.edges:
            if not has_authoritative_edge_evidence(edge.relation, edge.evidence):
                continue
            source = graph.get(edge.source)
            target = graph.get(edge.target)
            if source is None or target is None:
                continue
            source_project_id: str | None = None
            target_project_id: str | None = None
            if (
                edge.relation is KnowledgeRelation.DEPENDS_ON
                and source.kind is KnowledgeKind.PROJECT
                and target.kind is KnowledgeKind.PROJECT
            ):
                source_project_id = source.id
                target_project_id = target.id
            elif (
                edge.relation is KnowledgeRelation.IMPORTS
                and source.project_id
                and target.project_id
                and source.project_id != target.project_id
            ):
                source_project_id = project_ids_by_name.get(source.project_id)
                target_project_id = project_ids_by_name.get(target.project_id)
            if (
                source_project_id is None
                or target_project_id is None
                or source_project_id == target_project_id
            ):
                continue
            step = steps[(source_project_id, target_project_id)]
            if len(step) < _MAX_DEPENDENCY_EDGES_PER_STEP:
                step.append(edge)
            neighbors[source_project_id].add(target_project_id)
            neighbors[target_project_id].add(source_project_id)
        return (
            {
                key: tuple(sorted(value))
                for key, value in sorted(steps.items())
            },
            {key: len(value) for key, value in neighbors.items()},
        )
