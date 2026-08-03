"""PR136 deterministic impact prediction over the canonical PR129 graph."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import heapq
from pathlib import Path
from types import MappingProxyType

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeRelation,
)
from moughorai.knowledge_graph.evidence import safe_edge_evidence_refs
from moughorai.measurement import MeasurementSession
from moughorai.project_inventory import is_test_source_path
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.risk_analysis import RiskAnalysisReport, RiskHotspot
from moughorai.reachability import CoverageStatus, DeadCodeReport, RootCategory
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
    SubjectResolution,
)

from .models import (
    EXTERNAL_CONSUMER_LIMITATION,
    EXTERNAL_SCOPE_LIMITATION,
    BreakingChangeAssessment,
    BreakingChangeState,
    ImpactCapability,
    ImpactCapabilityState,
    ImpactCategory,
    ImpactChangeKind,
    ImpactFinding,
    ImpactPathStep,
    ImpactPredictionPath,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
    ImpactRiskContext,
    ImpactScore,
    ImpactScoreComponent,
    ImpactStrength,
    impact_prediction_fingerprint,
)


_PRODUCER = "atlas-pr136/1"
_GRAPH_PRODUCER = "atlas-pr129/1"
_CALL_GRAPH_PRODUCER = "moughorai.call_graph.v1"
_CALL_GRAPH_EVIDENCE = f"{_CALL_GRAPH_PRODUCER}:calls"
_MAXIMUM_VISITED_NODES = 1_000_000
_MAXIMUM_EDGES_PER_RELATION = 4_096
_MAXIMUM_AGGREGATION_BASES = 4_096
_MAXIMUM_TEST_PATHS = 20_000


@dataclass(frozen=True, slots=True)
class _EdgePolicy:
    reliability: float
    specificity: float
    coverage: float
    strength: ImpactStrength
    limitation: str
    producer: str = _GRAPH_PRODUCER


@dataclass(frozen=True, slots=True)
class _PathHop:
    source_graph_id: str
    target_graph_id: str
    edge: KnowledgeEdge
    reverse: bool
    policy: _EdgePolicy


@dataclass(frozen=True, slots=True)
class _CandidatePlan:
    target_graph_id: str
    category: ImpactCategory
    hops: tuple[_PathHop, ...]
    strength: ImpactStrength
    explanation: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Traversal:
    paths: Mapping[str, tuple[_PathHop, ...]]
    visited_nodes: int
    visited_edges: int
    cycle_count: int
    truncated: bool
    limitations: tuple[str, ...]


_RELATION_VALUES: Mapping[KnowledgeRelation, float] = MappingProxyType({
    KnowledgeRelation.CALLS: 0.98,
    KnowledgeRelation.OVERRIDES: 0.96,
    KnowledgeRelation.INHERITS: 0.90,
    KnowledgeRelation.IMPORTS: 0.86,
    KnowledgeRelation.DEPENDS_ON: 0.78,
    KnowledgeRelation.MEMBER_OF: 0.56,
    KnowledgeRelation.OWNS: 0.56,
})

_DEFAULT_RELATIONS = frozenset({
    KnowledgeRelation.DEPENDS_ON,
    KnowledgeRelation.IMPORTS,
    KnowledgeRelation.INHERITS,
    KnowledgeRelation.OVERRIDES,
    KnowledgeRelation.CALLS,
})

_CHANGE_RELATIONS: Mapping[ImpactChangeKind, frozenset[KnowledgeRelation]] = (
    MappingProxyType({
        ImpactChangeKind.IMPLEMENTATION: frozenset({
            KnowledgeRelation.DEPENDS_ON,
            KnowledgeRelation.IMPORTS,
            KnowledgeRelation.CALLS,
        }),
        ImpactChangeKind.SIGNATURE: _DEFAULT_RELATIONS,
        ImpactChangeKind.VISIBILITY: _DEFAULT_RELATIONS,
        ImpactChangeKind.REMOVAL: _DEFAULT_RELATIONS,
        ImpactChangeKind.RENAME: _DEFAULT_RELATIONS,
        ImpactChangeKind.MOVE: _DEFAULT_RELATIONS,
        ImpactChangeKind.DEPENDENCY: frozenset({
            KnowledgeRelation.DEPENDS_ON,
            KnowledgeRelation.IMPORTS,
        }),
        ImpactChangeKind.INHERITANCE: frozenset({
            KnowledgeRelation.DEPENDS_ON,
            KnowledgeRelation.IMPORTS,
            KnowledgeRelation.INHERITS,
            KnowledgeRelation.OVERRIDES,
        }),
        ImpactChangeKind.CONFIGURATION: frozenset({
            KnowledgeRelation.DEPENDS_ON,
        }),
        ImpactChangeKind.UNKNOWN: _DEFAULT_RELATIONS,
    })
)


class ImpactPredictionService:
    """Extend Atlas impact analysis with snapshot-backed canonical prediction.

    The legacy PR26 service remains a separate compatible API.  This service holds
    the resolver's existing graph rather than constructing another graph or reverse
    adjacency.  Predictions are ephemeral and reconstructible.
    """

    def __init__(
        self,
        resolver: CanonicalSubjectResolver,
        *,
        snapshot_id: str,
        analyzer_version: str,
        semantic_context: Mapping[str, object],
        measurement: MeasurementSession | None = None,
    ) -> None:
        if not isinstance(resolver, CanonicalSubjectResolver):
            raise TypeError("impact prediction requires a canonical subject resolver")
        if not snapshot_id.strip() or not analyzer_version.strip():
            raise ValueError("impact prediction requires snapshot lineage")
        self._resolver = resolver
        self._snapshot_id = snapshot_id
        self._analyzer_version = analyzer_version
        self._measurement = measurement or MeasurementSession()
        with self._measurement.scope(
            "impact_prediction.index",
            consumer="impact-prediction",
            sample_key=resolver.graph_digest,
        ) as scope:
            graph = resolver.graph
            relation_counts: Counter[KnowledgeRelation] = Counter()
            authoritative_counts: Counter[KnowledgeRelation] = Counter()
            languages: set[str] = set()
            policy_cache: dict[
                tuple[KnowledgeRelation, tuple[str, ...]], _EdgePolicy | None
            ] = {}
            if graph is not None:
                for node in graph.nodes:
                    if node.language and node.language != "unknown":
                        languages.add(node.language)
                for edge in graph.edges:
                    relation_counts[edge.relation] += 1
                    policy_key = (edge.relation, edge.evidence)
                    if policy_key not in policy_cache:
                        policy_cache[policy_key] = _edge_policy(edge)
                    if policy_cache[policy_key] is not None:
                        authoritative_counts[edge.relation] += 1
                scope.add_units(len(graph.nodes) + len(graph.edges))
                scope.add_objects_produced(len(relation_counts))
                scope.set_objects_retained(len(relation_counts))
            self._relation_counts = MappingProxyType(dict(relation_counts))
            self._authoritative_counts = MappingProxyType(
                dict(authoritative_counts)
            )
            self._languages = tuple(sorted(languages))
        self._risk_report, self._risk_state, self._risk_limitation = (
            self._load_risk_report(semantic_context)
        )
        (
            self._reachability_report,
            self._reachability_state,
            self._reachability_limitation,
            self._reachability_coverage,
        ) = (
            self._load_reachability_report(semantic_context)
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> ImpactPredictionService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("impact prediction snapshot is invalid")
        session = measurement or MeasurementSession()
        with session.scope(
            "impact_prediction.resolver_index",
            consumer="impact-prediction",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
            graph = resolver.graph
            scope.add_units(
                len(graph.nodes) + len(graph.edges) if graph is not None else 0
            )
            scope.set_objects_retained(
                len(graph.nodes) if graph is not None else 0
            )
        return cls(
            resolver,
            snapshot_id=snapshot.snapshot_id,
            analyzer_version=snapshot.analyzer_version,
            semantic_context=snapshot.semantic_context,
            measurement=session,
        )

    def predict(self, request: ImpactPredictionRequest) -> ImpactPredictionResponse:
        if not isinstance(request, ImpactPredictionRequest):
            raise TypeError("impact prediction request is invalid")
        with self._measurement.scope(
            "impact_prediction.query",
            consumer="impact-prediction",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            response = self._predict(request)
            scope.add_units(response.visited_node_count + response.visited_edge_count)
            scope.add_objects_produced(len(response.findings))
            scope.set_objects_retained(len(response.findings))
        return response

    def _predict(self, request: ImpactPredictionRequest) -> ImpactPredictionResponse:
        if not isinstance(request, ImpactPredictionRequest):
            raise TypeError("impact prediction request is invalid")
        with self._measurement.scope(
            "impact_prediction.resolve",
            consumer="impact-prediction",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            resolutions = tuple(
                self._resolve_with_scope(query, request)
                for query in (request.subject, *request.additional_subjects)
            )
            resolution = resolutions[0]
            additional_resolutions = resolutions[1:]
            scope.add_units(len(resolutions))
            scope.add_objects_produced(
                len(resolutions)
                + sum(item.total_candidate_count for item in resolutions)
            )
        fingerprint = impact_prediction_fingerprint(
            self._snapshot_id, self._resolver.graph_digest, request
        )
        if any(
            item.status is not ResolutionStatus.RESOLVED
            for item in resolutions
        ):
            unresolved_limitations = {
                limitation
                for item in resolutions
                for limitation in item.limitations
            }
            return ImpactPredictionResponse(
                request,
                resolution,
                (),
                self._capabilities(request),
                BreakingChangeAssessment(
                    BreakingChangeState.NOT_EVALUATED,
                    request.change_kind,
                    "Breaking-change analysis requires one resolved canonical subject.",
                    external_consumers_possible=True,
                    limitations=(EXTERNAL_CONSUMER_LIMITATION,),
                ),
                EvidenceIndex().freeze(),
                fingerprint,
                self._resolver.graph_digest,
                self._snapshot_id,
                limitations=tuple(sorted({
                    *unresolved_limitations,
                    "No impact traversal was attempted unless every requested source resolved exactly.",
                })),
                additional_resolutions=additional_resolutions,
            )

        graph = self._resolver.graph
        sources = tuple(
            item.subject for item in resolutions if item.subject is not None
        )
        if graph is None or len(sources) != len(resolutions):
            raise ValueError(
                "resolved impact subjects require the compatible canonical graph"
            )
        selected_relations = self._selected_relations(request)
        with self._measurement.scope(
            "impact_prediction.traverse",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            traversal = self._traverse(
                graph,
                tuple(source.graph_id for source in sources),
                request,
                selected_relations,
            )
            scope.add_units(traversal.visited_edges)
            scope.add_objects_produced(len(traversal.paths))
            scope.set_objects_retained(len(traversal.paths))
        with self._measurement.scope(
            "impact_prediction.cycle_check",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            scope.add_units(traversal.cycle_count)

        with self._measurement.scope(
            "impact_prediction.direct",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            plans = self._behavioral_plans(traversal)
            aggregation, aggregation_truncated, aggregation_edges = self._aggregation_plans(
                graph,
                tuple(source.graph_id for source in sources),
                traversal.paths,
                request,
            )
            plans.extend(aggregation)
            test_plans_truncated = False
            if request.include_tests:
                test_plans, test_plans_truncated = self._test_plans(
                    tuple(source.graph_id for source in sources),
                    traversal.paths,
                    request,
                )
                plans.extend(test_plans)
            plans.extend(self._api_plans(plans))
            plans = _deduplicate_plans(plans)
            scope.add_units(len(traversal.paths))
            scope.add_objects_produced(len(plans))

        with self._measurement.scope(
            "impact_prediction.sort",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            selected = tuple(heapq.nsmallest(
                request.limit, plans, key=self._plan_sort_key
            ))
            scope.add_units(len(plans))
            scope.add_objects_produced(len(selected))
            scope.set_objects_retained(len(selected))
        omitted = len(plans) - len(selected)
        truncated = (
            traversal.truncated
            or aggregation_truncated
            or test_plans_truncated
            or bool(omitted)
        )
        evidence = EvidenceIndex()
        with self._measurement.scope(
            "impact_prediction.score",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            findings = tuple(
                self._finding(plan, request, evidence)
                for plan in selected
            )
            scope.add_units(len(selected))
            scope.add_objects_produced(len(findings))

        local_consumers = any(
            item.strength is not ImpactStrength.STRUCTURAL_CONTEXT
            for item in findings
        )
        breaking = self._combined_breaking_assessment(
            sources, request, evidence, local_consumers=local_consumers
        )
        limitations = {
            *(
                limitation
                for item in resolutions
                for limitation in item.limitations
            ),
            *traversal.limitations,
        }
        if aggregation_truncated:
            limitations.add(
                "Owning-scope aggregation was bounded; additional containers may exist."
            )
        if test_plans_truncated:
            limitations.add(
                "Test-impact evaluation reached its bounded PR131 path limit; additional affected tests may exist."
            )
        if omitted:
            limitations.add(
                f"Returned {len(selected)} of {len(plans)} discovered impact classifications."
            )
        if request.changed_members:
            limitations.add(
                "Changed-member identifiers describe the scenario; they were not used as additional roots without separate canonical resolution."
            )
        if request.changed_api_surface:
            limitations.add(
                "Requested API-surface changes are hypothetical until a compatible before/after producer verifies them."
            )
        if not findings and breaking.external_consumers_possible:
            limitations.add(EXTERNAL_CONSUMER_LIMITATION)

        with self._measurement.scope(
            "impact_prediction.evidence",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            frozen_evidence = evidence.freeze()
            scope.add_units(len(frozen_evidence))
            scope.set_objects_retained(len(frozen_evidence))
        response = ImpactPredictionResponse(
            request,
            resolution,
            findings,
            self._capabilities(request),
            breaking,
            frozen_evidence,
            fingerprint,
            self._resolver.graph_digest,
            self._snapshot_id,
            len(plans),
            omitted,
            traversal.visited_nodes,
            traversal.visited_edges + aggregation_edges,
            truncated,
            tuple(sorted(limitations)),
            additional_resolutions=additional_resolutions,
        )
        with self._measurement.scope(
            "impact_prediction.serialize",
            consumer="impact-prediction",
            sample_key=fingerprint,
        ) as scope:
            payload_size = len(response.to_json().encode("utf-8"))
            scope.add_units(len(response.findings))
            scope.add_bytes(payload_size)
            scope.add_objects_produced(1)
        return response

    def _resolve_with_scope(
        self,
        query,
        request: ImpactPredictionRequest,
    ) -> SubjectResolution:
        resolution = self._resolver.resolve(query)
        if request.module is None and request.package is None:
            return resolution
        if resolution.status is ResolutionStatus.RESOLVED:
            candidates = (
                (resolution.subject,)
                if resolution.subject is not None
                and _matches_impact_scope(
                    resolution.subject, request, self._resolver.graph
                )
                else ()
            )
        elif resolution.status is ResolutionStatus.AMBIGUOUS:
            candidates = tuple(
                candidate
                for candidate in resolution.candidates
                if _matches_impact_scope(
                    candidate, request, self._resolver.graph
                )
            )
        else:
            return resolution
        limitation = (
            "Impact module/package constraints were applied after canonical subject resolution."
        )
        unseen_candidates = (
            resolution.omitted_candidate_count
            if resolution.status is ResolutionStatus.AMBIGUOUS
            else 0
        )
        if unseen_candidates:
            constrained_total = len(candidates) + unseen_candidates
            truncated_limitation = (
                "Canonical candidates were truncated before impact scope filtering; uniqueness cannot be established."
            )
            if constrained_total >= 2:
                return SubjectResolution(
                    query,
                    ResolutionStatus.AMBIGUOUS,
                    None,
                    candidates,
                    constrained_total,
                    unseen_candidates,
                    resolution.match_basis,
                    self._resolver.graph_digest,
                    tuple(sorted({
                        *resolution.limitations,
                        limitation,
                        truncated_limitation,
                    })),
                )
            return SubjectResolution(
                query,
                ResolutionStatus.UNAVAILABLE,
                None,
                (),
                unseen_candidates,
                unseen_candidates,
                SubjectMatchBasis.NONE,
                self._resolver.graph_digest,
                tuple(sorted({
                    *resolution.limitations,
                    limitation,
                    truncated_limitation,
                })),
            )
        if len(candidates) == 1:
            candidate = candidates[0]
            return SubjectResolution(
                query,
                ResolutionStatus.RESOLVED,
                candidate,
                (),
                0,
                0,
                candidate.match_basis,
                self._resolver.graph_digest,
                tuple(sorted({*resolution.limitations, limitation})),
            )
        if len(candidates) > 1:
            return SubjectResolution(
                query,
                ResolutionStatus.AMBIGUOUS,
                None,
                candidates,
                len(candidates),
                0,
                resolution.match_basis,
                self._resolver.graph_digest,
                tuple(sorted({*resolution.limitations, limitation})),
            )
        return SubjectResolution(
            query,
            ResolutionStatus.NOT_FOUND,
            None,
            (),
            0,
            0,
            SubjectMatchBasis.NONE,
            self._resolver.graph_digest,
            tuple(sorted({
                *resolution.limitations,
                "No canonical subject satisfies the impact module/package constraints.",
            })),
        )

    def _selected_relations(
        self, request: ImpactPredictionRequest
    ) -> tuple[KnowledgeRelation, ...]:
        permitted = set(_CHANGE_RELATIONS[request.change_kind])
        if not request.include_dependencies:
            permitted.discard(KnowledgeRelation.DEPENDS_ON)
        if request.relations:
            permitted.intersection_update(request.relations)
        return tuple(sorted(permitted, key=lambda item: item.value))

    def _traverse(
        self,
        graph: KnowledgeGraph,
        source_ids: tuple[str, ...],
        request: ImpactPredictionRequest,
        relations: tuple[KnowledgeRelation, ...],
    ) -> _Traversal:
        roots = tuple(sorted(set(source_ids)))
        seen = set(roots)
        paths: dict[str, tuple[_PathHop, ...]] = {}
        visited_edges = 0
        cycle_count = 0
        truncated = False
        limitations: set[str] = set()
        frontier = roots
        for _depth in range(request.max_depth):
            next_paths: dict[str, tuple[_PathHop, ...]] = {}
            for current in frontier:
                candidates: list[tuple[KnowledgeEdge, _EdgePolicy]] = []
                for relation in relations:
                    edges, total = graph.bounded_incoming(
                        current,
                        relation=relation,
                        limit=_MAXIMUM_EDGES_PER_RELATION,
                    )
                    visited_edges += total
                    if total > len(edges):
                        truncated = True
                        limitations.add(
                            f"Incoming {relation.value} adjacency exceeded the per-node bound."
                        )
                    for edge in edges:
                        policy = _edge_policy(edge)
                        if (
                            policy is not None
                            and _propagation_edge_supported(graph, edge)
                        ):
                            candidates.append((edge, policy))
                        elif policy is not None:
                            limitations.add(
                                "A relation with unsupported endpoint kinds was omitted from impact propagation."
                            )
                candidates.sort(key=lambda item: (
                    -_RELATION_VALUES.get(item[0].relation, 0.0),
                    item[0].relation.value,
                    item[0].source,
                    item[0].target,
                    item[0].evidence,
                ))
                prefix = paths.get(current, ())
                for edge, policy in candidates:
                    target = edge.source
                    if target in seen:
                        cycle_count += 1
                        continue
                    if self._resolver.candidate_for_graph_id(target) is None:
                        limitations.add(
                            "A canonical edge endpoint could not be projected safely and was omitted."
                        )
                        continue
                    candidate_path = (*prefix, _PathHop(
                        current, target, edge, True, policy
                    ))
                    previous = next_paths.get(target)
                    if (
                        previous is None
                        or _path_key(candidate_path) < _path_key(previous)
                    ):
                        next_paths[target] = candidate_path
            remaining = _MAXIMUM_VISITED_NODES - len(seen)
            ordered = sorted(
                next_paths.items(),
                key=lambda item: (_path_key(item[1]), item[0]),
            )
            if len(ordered) > remaining:
                ordered = ordered[:remaining]
                truncated = True
                limitations.add(
                    "Impact traversal reached the maximum visited-node bound."
                )
            if not ordered:
                break
            frontier = tuple(item[0] for item in ordered)
            for target, path in ordered:
                seen.add(target)
                paths[target] = path
            if len(seen) >= _MAXIMUM_VISITED_NODES:
                break
        return _Traversal(
            MappingProxyType(dict(paths)),
            len(seen),
            visited_edges,
            cycle_count,
            truncated,
            tuple(sorted(limitations)),
        )

    def _behavioral_plans(self, traversal: _Traversal) -> list[_CandidatePlan]:
        result = []
        for graph_id, hops in traversal.paths.items():
            last = hops[-1]
            candidate = self._resolver.candidate_for_graph_id(graph_id)
            if candidate is None:
                continue
            category = _category(last.edge.relation, candidate.kind)
            strength = (
                last.policy.strength
                if len(hops) == 1
                else ImpactStrength.EVIDENCE_BACKED_TRANSITIVE
            )
            result.append(_CandidatePlan(
                graph_id,
                category,
                hops,
                strength,
                _relation_explanation(last.edge.relation),
                tuple(sorted({
                    hop.policy.limitation for hop in hops if hop.policy.limitation
                })),
            ))
        return result

    def _aggregation_plans(
        self,
        graph: KnowledgeGraph,
        source_ids: tuple[str, ...],
        paths: Mapping[str, tuple[_PathHop, ...]],
        request: ImpactPredictionRequest,
    ) -> tuple[list[_CandidatePlan], bool, int]:
        bases = [(source_id, ()) for source_id in sorted(set(source_ids))]
        bases.extend(sorted(
            paths.items(), key=lambda item: (len(item[1]), item[0])
        ))
        truncated = len(bases) > _MAXIMUM_AGGREGATION_BASES
        bases = bases[:_MAXIMUM_AGGREGATION_BASES]
        best: dict[tuple[str, ImpactCategory], _CandidatePlan] = {}
        visited_edges = 0
        for base_id, base_hops in bases:
            queue = deque(((base_id, base_hops),))
            local_seen = {base_id}
            while queue:
                current, current_hops = queue.popleft()
                if len(current_hops) >= request.max_depth:
                    continue
                owner_edges: list[tuple[KnowledgeEdge, bool, str]] = []
                outgoing, outgoing_total = graph.bounded_outgoing(
                    current,
                    relation=KnowledgeRelation.MEMBER_OF,
                    limit=16,
                )
                incoming, incoming_total = graph.bounded_incoming(
                    current,
                    relation=KnowledgeRelation.OWNS,
                    limit=16,
                )
                visited_edges += outgoing_total + incoming_total
                if outgoing_total > len(outgoing) or incoming_total > len(incoming):
                    truncated = True
                owner_edges.extend((edge, False, edge.target) for edge in outgoing)
                owner_edges.extend((edge, True, edge.source) for edge in incoming)
                owner_edges.sort(key=lambda item: (
                    item[2], item[0].relation.value, item[1], item[0].evidence
                ))
                for edge, reverse, owner_id in owner_edges:
                    if owner_id in local_seen:
                        continue
                    policy = _edge_policy(edge)
                    candidate = self._resolver.candidate_for_graph_id(owner_id)
                    if policy is None or candidate is None:
                        continue
                    local_seen.add(owner_id)
                    hops = (*current_hops, _PathHop(
                        current, owner_id, edge, reverse, policy
                    ))
                    category = _owner_category(candidate.kind)
                    if category is not None:
                        plan = _CandidatePlan(
                            owner_id,
                            category,
                            hops,
                            ImpactStrength.STRUCTURAL_CONTEXT,
                            "Canonical containment identifies this owning scope; ownership does not prove behavioral impact.",
                            (
                                "Ownership was used only for upward aggregation; sibling subjects were not traversed.",
                            ),
                        )
                        key = (owner_id, category)
                        previous = best.get(key)
                        if previous is None or _path_key(hops) < _path_key(previous.hops):
                            best[key] = plan
                    queue.append((owner_id, hops))
        return list(best.values()), truncated, visited_edges

    def _api_plans(self, plans: Sequence[_CandidatePlan]) -> list[_CandidatePlan]:
        result = []
        for plan in plans:
            candidate = self._resolver.candidate_for_graph_id(plan.target_graph_id)
            node = (
                self._resolver.graph.get(plan.target_graph_id)
                if self._resolver.graph is not None
                else None
            )
            visibility = dict(node.metadata).get("visibility", "") if node else ""
            if candidate is None or visibility.casefold() not in {"public", "protected"}:
                continue
            result.append(_CandidatePlan(
                plan.target_graph_id,
                ImpactCategory.PUBLIC_API,
                plan.hops,
                plan.strength,
                "The impacted subject has structured public/protected visibility; external compatibility remains unverified.",
                (*plan.limitations, "Visibility is not proof of a supported external API contract."),
            ))
        return result

    def _test_plans(
        self,
        source_ids: tuple[str, ...],
        paths: Mapping[str, tuple[_PathHop, ...]],
        request: ImpactPredictionRequest,
    ) -> tuple[list[_CandidatePlan], bool]:
        report = self._reachability_report
        if report is None or (
            request.relations
            and KnowledgeRelation.CALLS not in request.relations
        ):
            return [], False
        test_roots = {
            item.subject_id
            for item in report.roots
            if item.category is RootCategory.TEST
        }
        base_paths: dict[str, tuple[_PathHop, ...]] = {
            source_id: () for source_id in source_ids
        }
        base_paths.update(paths)
        for graph_id in tuple(base_paths):
            candidate = self._resolver.candidate_for_graph_id(graph_id)
            if candidate is not None:
                base_paths.setdefault(candidate.canonical_id, base_paths[graph_id])
        result = []
        truncated = len(report.paths) > _MAXIMUM_TEST_PATHS
        for item in report.paths[:_MAXIMUM_TEST_PATHS]:
            if (
                item.root_subject_id not in test_roots
                or item.scope != "test"
                or item.truncated
            ):
                continue
            base = self._candidate_for_any_id(item.target_subject_id)
            test = self._candidate_for_any_id(item.root_subject_id)
            if base is None or test is None:
                continue
            base_hops = base_paths.get(base.graph_id)
            if base_hops is None:
                continue
            route = self._reachability_route(report, item)
            if route is None or len(base_hops) + len(route) > request.max_depth:
                continue
            reverse_hops: list[_PathHop] = []
            for source_graph_id, target_graph_id, relation, evidence_id in reversed(route):
                canonical_relation = (
                    KnowledgeRelation.CALLS
                    if relation in {"calls", "constructor"}
                    else KnowledgeRelation.MEMBER_OF
                )
                limitation = (
                    "PR131 constructor-call evidence is represented by the canonical calls relation."
                    if relation == "constructor"
                    else (
                        "PR131 member ownership is structural context inside the explicit test path."
                        if relation == "member_owner"
                        else "PR131 call evidence is bounded to the specialized analyzed scope."
                    )
                )
                policy = _EdgePolicy(
                    0.90 if canonical_relation is KnowledgeRelation.CALLS else 0.80,
                    0.90 if canonical_relation is KnowledgeRelation.CALLS else 0.85,
                    0.65,
                    ImpactStrength.PROBABLE_INCOMPLETE,
                    limitation,
                    "atlas-pr131/1",
                )
                edge = KnowledgeEdge(
                    source_graph_id,
                    target_graph_id,
                    canonical_relation,
                    (evidence_id,),
                )
                reverse_hops.append(_PathHop(
                    target_graph_id,
                    source_graph_id,
                    edge,
                    True,
                    policy,
                ))
            hops = (*base_hops, *reverse_hops)
            path_limitations = {
                "PR131 test linkage is bounded to its represented call/reference path."
            }
            if test.path is not None and not is_test_source_path(Path(test.path)):
                path_limitations.add(
                    "The explicit PR131 test root is outside a conventional test path."
                )
            result.append(_CandidatePlan(
                test.graph_id,
                ImpactCategory.TEST,
                hops,
                ImpactStrength.PROBABLE_INCOMPLETE,
                "A compatible PR131 test-root path links this test to an affected canonical subject.",
                tuple(sorted(path_limitations)),
            ))
        return result, truncated

    def _reachability_route(
        self,
        report: DeadCodeReport,
        path,
    ) -> tuple[tuple[str, str, str, str], ...] | None:
        allowed_relations = {"calls", "constructor", "member_owner"}
        if (
            not path.relationship_sequence
            or any(item not in allowed_relations for item in path.relationship_sequence)
            or not any(
                item in {"calls", "constructor"}
                for item in path.relationship_sequence
            )
        ):
            return None
        relation_edges: list[tuple[str, str, str, str]] = []
        for evidence_id in path.evidence_ids:
            record = report.evidence_index.get(evidence_id)
            if record is None or record.snapshot_id != report.snapshot_lineage:
                return None
            detail = dict(record.detail)
            raw_relation = detail.get("relation")
            if (
                raw_relation == "member_of"
                and record.kind is EvidenceKind.GRAPH_EDGE
                and record.producer == "knowledge-graph.v1"
            ):
                relation = "member_owner"
            elif (
                raw_relation == "calls"
                and (
                    (
                        record.kind is EvidenceKind.GRAPH_EDGE
                        and record.producer == "knowledge-graph.v1"
                    )
                    or (
                        record.kind is EvidenceKind.ANALYSIS_RESULT
                        and record.producer == "moughorai.call_graph.v1"
                    )
                )
            ):
                relation = "calls"
            elif (
                raw_relation == "constructor"
                and record.kind is EvidenceKind.ANALYSIS_RESULT
                and record.producer == "moughorai.call_graph.v1"
            ):
                relation = "constructor"
            else:
                continue
            target = self._candidate_for_any_id(record.subject_id)
            if target is None:
                return None
            endpoint_ids = {
                candidate.graph_id
                for reference in record.source_refs
                if (
                    candidate := self._resolver.candidate_for_graph_id(reference)
                ) is not None
            }
            endpoint_ids.discard(target.graph_id)
            if len(endpoint_ids) != 1:
                return None
            source_id = next(iter(endpoint_ids))
            relation_edges.append((
                source_id,
                target.graph_id,
                relation,
                evidence_id,
            ))
        if len(relation_edges) != len(path.relationship_sequence):
            return None
        root = self._candidate_for_any_id(path.root_subject_id)
        target = self._candidate_for_any_id(path.target_subject_id)
        if root is None or target is None:
            return None
        matches: list[tuple[tuple[str, str, str, str], ...]] = []

        def walk(
            current: str,
            index: int,
            remaining: tuple[tuple[str, str, str, str], ...],
            selected: tuple[tuple[str, str, str, str], ...],
        ) -> None:
            if len(matches) > 1:
                return
            if index == len(path.relationship_sequence):
                if current == target.graph_id and not remaining:
                    matches.append(selected)
                return
            expected = path.relationship_sequence[index]
            for offset, edge in enumerate(remaining):
                if edge[0] == current and edge[2] == expected:
                    walk(
                        edge[1],
                        index + 1,
                        (*remaining[:offset], *remaining[offset + 1 :]),
                        (*selected, edge),
                    )

        walk(root.graph_id, 0, tuple(sorted(relation_edges)), ())
        return matches[0] if len(matches) == 1 else None

    def _finding(
        self,
        plan: _CandidatePlan,
        request: ImpactPredictionRequest,
        evidence: EvidenceIndex,
    ) -> ImpactFinding:
        candidate = self._resolver.candidate_for_graph_id(plan.target_graph_id)
        if candidate is None:
            raise ValueError("impact plan target cannot be projected")
        with self._measurement.scope(
            "impact_prediction.neighbors",
            consumer="impact-prediction",
            sample_key=plan.target_graph_id,
        ) as scope:
            path, path_records = self._path(plan.hops)
            for record in path_records:
                evidence.add(record)
            scope.add_units(len(plan.hops))
        risk = self._risk_context(candidate, request, evidence)
        confidence = _confidence(plan.hops, path.evidence_ids, evidence)
        exposure_evidence_ids: tuple[str, ...] = ()
        exposure = _represented_api_exposure(candidate, self._resolver.graph)
        if exposure is not None:
            node = (
                self._resolver.graph.get(candidate.graph_id)
                if self._resolver.graph is not None
                else None
            )
            visibility = (
                dict(node.metadata).get("visibility", "unknown")
                if node is not None
                else "unknown"
            )
            exposure_record = EvidenceRecord.create(
                EvidenceKind.SEMANTIC_FACT,
                candidate.canonical_id,
                _GRAPH_PRODUCER,
                self._snapshot_id,
                source_refs=("global_symbol.metadata:visibility",),
                scope=candidate.project or "repository",
                language=candidate.language,
                detail={"visibility": visibility.casefold()},
                limitations=(
                    "Visibility describes represented exposure, not a verified external API contract.",
                ),
                reliability=1.0,
                specificity=1.0,
            )
            evidence.add(exposure_record)
            exposure_evidence_ids = (exposure_record.evidence_id,)
        score = _score(
            plan,
            path.evidence_ids,
            candidate,
            self._resolver.graph,
            exposure_evidence_ids,
        )
        evidence_ids = set(path.evidence_ids)
        evidence_ids.update(score.evidence_ids)
        if risk is not None:
            evidence_ids.update(risk.evidence_ids)
        module, package = _scope(candidate, self._resolver.graph)
        limitations = set(plan.limitations)
        if (
            request.include_risk
            and self._risk_state is ImpactCapabilityState.AVAILABLE
            and risk is None
        ):
            limitations.add(
                "The compatible PR132 report is bounded to ranked hotspots; absence from that list is unknown, not low risk."
            )
        if candidate.kind is KnowledgeKind.MODULE:
            limitations.add(
                "Module identity is project-derived; independent build/source-set identity remains partial."
            )
        attributes = _attributes(candidate, self._resolver.graph)
        if candidate.kind is KnowledgeKind.DEPENDENCY:
            attribute_names = {key for key, _ in attributes}
            if "version" not in attribute_names:
                limitations.add(
                    "Dependency version is unknown; no placeholder was presented as a real version."
                )
            if "scope" not in attribute_names:
                limitations.add(
                    "Dependency scope is unknown; runtime linkage was not inferred."
                )
        return ImpactFinding(
            candidate,
            plan.category,
            plan.strength,
            path.length == 1,
            path,
            score,
            confidence,
            tuple(sorted(evidence_ids)),
            plan.explanation,
            module,
            package,
            risk,
            None,
            ImpactCapabilityState.PARTIAL,
            tuple(sorted(limitations)),
            attributes,
        )

    def _path(
        self, hops: tuple[_PathHop, ...]
    ) -> tuple[ImpactPredictionPath, tuple[EvidenceRecord, ...]]:
        steps = []
        records = []
        for hop in hops:
            source = self._resolver.candidate_for_graph_id(hop.source_graph_id)
            target = self._resolver.candidate_for_graph_id(hop.target_graph_id)
            if source is None or target is None:
                raise ValueError("impact path endpoint cannot be projected")
            refs = safe_edge_evidence_refs(hop.edge.evidence)
            if not refs:
                raise ValueError("authoritative impact edge lacks portable evidence")
            record = EvidenceRecord.create(
                EvidenceKind.GRAPH_EDGE,
                target.canonical_id,
                hop.policy.producer,
                self._snapshot_id,
                source_refs=refs,
                scope=target.project or "repository",
                language=target.language,
                detail={
                    "relation": hop.edge.relation.value,
                    "source_subject_id": source.canonical_id,
                    "target_subject_id": target.canonical_id,
                    "traversal": "reverse" if hop.reverse else "forward",
                },
                limitations=(hop.policy.limitation,) if hop.policy.limitation else (),
                reliability=hop.policy.reliability,
                specificity=hop.policy.specificity,
            )
            records.append(record)
            steps.append(ImpactPathStep(
                source.canonical_id,
                target.canonical_id,
                hop.edge.relation,
                hop.reverse,
                hop.policy.strength,
                (record.evidence_id,),
            ))
        return ImpactPredictionPath(
            steps[0].source_subject_id,
            steps[-1].target_subject_id,
            tuple(steps),
            limitations=tuple(sorted({
                hop.policy.limitation for hop in hops if hop.policy.limitation
            })),
        ), tuple(records)

    def _breaking_assessment(
        self,
        source: SubjectCandidate,
        request: ImpactPredictionRequest,
        evidence: EvidenceIndex,
        *,
        local_consumers: bool,
    ) -> BreakingChangeAssessment:
        graph = self._resolver.graph
        node = graph.get(source.graph_id) if graph is not None else None
        metadata = dict(node.metadata) if node is not None else {}
        visibility = metadata.get("visibility", "unknown").casefold()
        api_kind = source.kind in {
            KnowledgeKind.TYPE,
            KnowledgeKind.METHOD,
            KnowledgeKind.FIELD,
            KnowledgeKind.PACKAGE,
            KnowledgeKind.PROJECT,
            KnowledgeKind.MODULE,
        }
        exposed = visibility in {"public", "protected"}
        risky_change = request.change_kind in {
            ImpactChangeKind.SIGNATURE,
            ImpactChangeKind.VISIBILITY,
            ImpactChangeKind.REMOVAL,
            ImpactChangeKind.RENAME,
            ImpactChangeKind.MOVE,
            ImpactChangeKind.INHERITANCE,
        }
        if not api_kind:
            return BreakingChangeAssessment(
                BreakingChangeState.UNSUPPORTED,
                request.change_kind,
                "This canonical subject kind has no compatible API-surface model.",
                external_consumers_possible=False,
            )
        evidence_ids: tuple[str, ...] = ()
        if exposed or request.changed_api_surface:
            record = EvidenceRecord.create(
                EvidenceKind.SEMANTIC_FACT,
                source.canonical_id,
                _PRODUCER,
                self._snapshot_id,
                source_refs=("global_symbol.metadata:visibility",),
                scope=source.project or "repository",
                language=source.language,
                detail={
                    "change_kind": request.change_kind.value,
                    "declared_api_surface_count": len(request.changed_api_surface),
                    "subject_kind": source.kind.value,
                    "visibility": visibility,
                },
                limitations=(
                    "The request describes a scenario, not a verified before/after API diff.",
                ),
                reliability=0.9 if exposed else 0.6,
                specificity=0.9 if exposed else 0.6,
            )
            evidence.add(record)
            evidence_ids = (record.evidence_id,)
        external_possible = exposed or visibility == "unknown" or bool(
            request.changed_api_surface
        )
        external_limitation = (
            EXTERNAL_SCOPE_LIMITATION
            if local_consumers
            else EXTERNAL_CONSUMER_LIMITATION
        )
        limitations = (external_limitation,) if external_possible else ()
        if (exposed or request.changed_api_surface) and risky_change:
            return BreakingChangeAssessment(
                BreakingChangeState.POTENTIALLY_BREAKING,
                request.change_kind,
                "The structured current API surface and requested change kind indicate potential compatibility impact; no compatible before/after diff proves breakage.",
                evidence_ids,
                external_possible,
                (*limitations, "Binary and source compatibility were not evaluated."),
            )
        if visibility in {"private", "package", "internal"}:
            return BreakingChangeAssessment(
                BreakingChangeState.NOT_APPLICABLE,
                request.change_kind,
                "The represented subject is not marked public or protected.",
                external_consumers_possible=False,
            )
        return BreakingChangeAssessment(
            BreakingChangeState.NOT_EVALUATED,
            request.change_kind,
            "A compatible before/after API producer is unavailable for this scenario.",
            evidence_ids,
            external_possible,
            limitations,
        )

    def _combined_breaking_assessment(
        self,
        sources: tuple[SubjectCandidate, ...],
        request: ImpactPredictionRequest,
        evidence: EvidenceIndex,
        *,
        local_consumers: bool,
    ) -> BreakingChangeAssessment:
        assessments = tuple(
            self._breaking_assessment(
                source,
                request,
                evidence,
                local_consumers=local_consumers,
            )
            for source in sources
        )
        if len(assessments) == 1:
            return assessments[0]
        priority = {
            BreakingChangeState.PROVEN_BREAKING: 0,
            BreakingChangeState.POTENTIALLY_BREAKING: 1,
            BreakingChangeState.NOT_EVALUATED: 2,
            BreakingChangeState.UNSUPPORTED: 3,
            BreakingChangeState.NOT_APPLICABLE: 4,
        }
        selected = min(assessments, key=lambda item: (
            priority[item.state], item.explanation, item.evidence_ids
        ))
        return BreakingChangeAssessment(
            selected.state,
            request.change_kind,
            "The multi-source result reports the most conservative supported breaking-change state across the resolved sources.",
            tuple(sorted({
                evidence_id
                for item in assessments
                for evidence_id in item.evidence_ids
            })),
            any(item.external_consumers_possible for item in assessments),
            tuple(sorted({
                limitation
                for item in assessments
                for limitation in item.limitations
            })),
        )

    def _risk_context(
        self,
        candidate: SubjectCandidate,
        request: ImpactPredictionRequest,
        evidence: EvidenceIndex,
    ) -> ImpactRiskContext | None:
        if not request.include_risk or self._risk_report is None:
            return None
        hotspot = self._risk_hotspot(candidate)
        if hotspot is None:
            return None
        refs = safe_edge_evidence_refs(hotspot.evidence_ids)
        if not refs:
            return None
        record = EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            candidate.canonical_id,
            self._risk_report.producer_version,
            self._snapshot_id,
            source_refs=refs,
            scope=candidate.project or "repository",
            language=candidate.language,
            detail={
                "hotspot_rank": hotspot.rank,
                "risk_score": hotspot.score,
                "signals": ",".join(
                    factor.metric.metric.value for factor in hotspot.factors
                ),
            },
            limitations=(
                "Risk context did not create or remove the impact finding.",
            ),
            reliability=hotspot.confidence.score,
            specificity=0.9,
        )
        evidence.add(record)
        return ImpactRiskContext(
            ImpactCapabilityState.AVAILABLE,
            hotspot.score,
            hotspot.rank,
            tuple(factor.metric.metric.value for factor in hotspot.factors),
            (record.evidence_id,),
            ("Risk context did not create or remove the impact finding.",),
        )

    def _risk_hotspot(self, candidate: SubjectCandidate) -> RiskHotspot | None:
        if self._risk_report is None:
            raise RuntimeError("risk context was requested without a compatible report")
        for identifier in (candidate.graph_id, candidate.canonical_id):
            if hotspot := self._risk_report.finding(identifier):
                return hotspot
        return None

    def _load_risk_report(
        self,
        semantic_context: Mapping[str, object],
    ) -> tuple[RiskAnalysisReport | None, ImpactCapabilityState, str]:
        raw = semantic_context.get("risk_analysis")
        if not isinstance(raw, Mapping):
            return None, ImpactCapabilityState.UNAVAILABLE, (
                "PR132 risk context is absent; impact membership remains available."
            )
        if (
            raw.get("producer_version") != "atlas-pr132/1"
            or raw.get("schema_version") != 1
            or raw.get("graph_digest") != self._resolver.graph_digest
        ):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR132 risk lineage does not match the canonical graph."
            )
        try:
            report = RiskAnalysisReport.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR132 risk context is malformed or uses an unsupported schema."
            )
        if any(
            record.snapshot_id != report.lineage
            for record in report.evidence_index.records
        ):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR132 evidence lineage does not match the active semantic snapshot."
            )
        return report, ImpactCapabilityState.AVAILABLE, (
            "PR132 risk is contextual and never creates an impact path."
        )

    def _load_reachability_report(
        self,
        semantic_context: Mapping[str, object],
    ) -> tuple[
        DeadCodeReport | None,
        ImpactCapabilityState,
        str,
        float | None,
    ]:
        raw = semantic_context.get("reachability")
        if not isinstance(raw, Mapping):
            return None, ImpactCapabilityState.UNAVAILABLE, (
                "Test linkage is unavailable because no compatible PR131 report exists."
            ), None
        if (
            raw.get("schema_version") != 1
            or raw.get("producer_version") != "atlas-pr131/1"
            or raw.get("graph_digest") != self._resolver.graph_digest
        ):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR131 reachability lineage is incompatible with the canonical graph."
            ), None
        try:
            report = DeadCodeReport.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR131 reachability data is malformed or uses unsupported evidence."
            ), None
        available_evidence = {
            record.evidence_id for record in report.evidence_index.records
        }
        canonical_evidence = all(
            EvidenceRecord.create(
                record.kind,
                record.subject_id,
                record.producer,
                record.snapshot_id,
                source_refs=record.source_refs,
                scope=record.scope,
                language=record.language,
                detail=record.detail,
                limitations=record.limitations,
                reliability=record.reliability,
                specificity=record.specificity,
            ) == record
            for record in report.evidence_index.records
        )
        referenced_evidence_exists = all(
            set(path.evidence_ids).issubset(available_evidence)
            for path in report.paths
        )
        if (
            not canonical_evidence
            or not referenced_evidence_exists
            or any(
                record.snapshot_id != report.snapshot_lineage
                for record in report.evidence_index.records
            )
        ):
            return None, ImpactCapabilityState.INCOMPATIBLE, (
                "PR131 evidence identity, closure, or lineage is inconsistent with its reachability report."
            ), None
        test_roots = {
            item.subject_id
            for item in report.roots
            if item.category is RootCategory.TEST
        }
        has_usable_path_shape = any(
            path.root_subject_id in test_roots
            and path.scope == "test"
            and not path.truncated
            and any(
                relation in {"calls", "constructor"}
                for relation in path.relationship_sequence
            )
            for path in report.paths
        )
        call_statuses = tuple(
            project.calls for project in report.coverage.projects
        )
        represented_call_coverage = any(
            status in {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}
            for status in call_statuses
        )
        if not has_usable_path_shape and not represented_call_coverage:
            return report, ImpactCapabilityState.UNAVAILABLE, (
                "PR131 contains no usable test call/reference paths and reports no represented call coverage."
            ), None
        coverage_weights = {
            CoverageStatus.COMPLETE: 1.0,
            CoverageStatus.PARTIAL: 0.5,
            CoverageStatus.UNAVAILABLE: 0.0,
            CoverageStatus.INSUFFICIENT: 0.0,
        }
        coverage = (
            round(
                sum(coverage_weights[item] for item in call_statuses)
                / len(call_statuses),
                4,
            )
            if call_statuses and represented_call_coverage
            else None
        )
        return report, ImpactCapabilityState.PARTIAL, (
            "PR131 test linkage is bounded and canonical call coverage may be unavailable."
        ), coverage

    def _capabilities(
        self, request: ImpactPredictionRequest
    ) -> tuple[ImpactCapability, ...]:
        graph_available = self._resolver.graph is not None
        capabilities = [
            ImpactCapability(
                "canonical_subjects",
                (
                    ImpactCapabilityState.AVAILABLE
                    if graph_available
                    else ImpactCapabilityState.UNAVAILABLE
                ),
                1.0 if graph_available else None,
                self._languages,
                limitations=(
                    "Identity remains owned by the compatible PR134 canonical subject resolver.",
                ),
            ),
            self._relation_capability(
                "dependencies", KnowledgeRelation.DEPENDS_ON,
                "Dependency declarations prove potential consumers, not runtime use."
            ),
            self._relation_capability(
                "imports", KnowledgeRelation.IMPORTS,
                "Java imports and ambiguous/external imports are not represented."
            ),
            self._relation_capability(
                "inheritance", KnowledgeRelation.INHERITS,
                "External and ambiguous bases remain unknown."
            ),
            self._relation_capability(
                "overrides", KnowledgeRelation.OVERRIDES,
                "Only conservative resolved Java override evidence is populated."
            ),
            self._relation_capability(
                "calls", KnowledgeRelation.CALLS,
                "Call-based impact was not evaluated for this scope."
            ),
            ImpactCapability(
                "composition",
                ImpactCapabilityState.UNSUPPORTED,
                None,
                limitations=(
                    "Typed field use does not prove lifecycle composition; no production canonical producer exists.",
                ),
            ),
            ImpactCapability(
                "api_surface",
                ImpactCapabilityState.PARTIAL if graph_available else ImpactCapabilityState.UNAVAILABLE,
                0.5 if graph_available else None,
                self._languages,
                limitations=(
                    "Current visibility/signature metadata is partial; binary and before/after compatibility are unavailable.",
                ),
            ),
            ImpactCapability(
                "modules",
                ImpactCapabilityState.PARTIAL if graph_available else ImpactCapabilityState.UNAVAILABLE,
                0.5 if graph_available else None,
                limitations=(
                    "Module identity is project-derived; independent build/source-set identity remains partial.",
                ),
            ),
            ImpactCapability(
                "tests",
                self._reachability_state,
                self._reachability_coverage,
                limitations=(self._reachability_limitation,),
            ),
            ImpactCapability(
                "reachability",
                self._reachability_state,
                self._reachability_coverage,
                limitations=(
                    "PR131 reachability is optional context and never proves absence of impact.",
                    self._reachability_limitation,
                ),
            ),
            ImpactCapability(
                "git",
                ImpactCapabilityState.UNAVAILABLE,
                None,
                limitations=(
                    (
                        "Compatible source-free Git enrichment was requested but no canonical subject adapter is available; structural impact remains available."
                        if request.include_git_context
                        else "Git enrichment was not requested; structural impact remains available."
                    ),
                ),
            ),
            ImpactCapability(
                "risk",
                self._risk_state,
                1.0 if self._risk_state is ImpactCapabilityState.AVAILABLE else None,
                limitations=(self._risk_limitation,),
            ),
            ImpactCapability(
                "search",
                ImpactCapabilityState.UNAVAILABLE,
                None,
                limitations=(
                    (
                        "PR135 enrichment was requested but no compatible result was supplied; search relevance was not used as impact proof."
                        if request.include_search_enrichment
                        else "PR135 search enrichment was not requested and is never required for impact traversal."
                    ),
                ),
            ),
        ]
        if not request.include_tests:
            capabilities = [
                item if item.name != "tests" else ImpactCapability(
                    item.name, item.state, item.coverage, item.scopes,
                    item.evidence_ids,
                    (*item.limitations, "Test findings were not requested."),
                )
                for item in capabilities
            ]
        elif request.relations and KnowledgeRelation.CALLS not in request.relations:
            capabilities = [
                item if item.name != "tests" else ImpactCapability(
                    item.name,
                    item.state,
                    item.coverage,
                    item.scopes,
                    item.evidence_ids,
                    (*item.limitations, "Explicit relation filters excluded call-based test linkage."),
                )
                for item in capabilities
            ]
        return tuple(capabilities)

    def _relation_capability(
        self,
        name: str,
        relation: KnowledgeRelation,
        limitation: str,
    ) -> ImpactCapability:
        total = self._relation_counts.get(relation, 0)
        authoritative = self._authoritative_counts.get(relation, 0)
        if relation is KnowledgeRelation.CALLS:
            state = (
                ImpactCapabilityState.PARTIAL
                if authoritative
                else ImpactCapabilityState.UNAVAILABLE
            )
            coverage = None
            if authoritative:
                limitation = (
                    "Authoritative call edges were evaluated only for their represented specialized scope; repository call coverage is unknown."
                )
        elif relation is KnowledgeRelation.COMPOSES and not authoritative:
            state = ImpactCapabilityState.UNSUPPORTED
            coverage = None
        elif self._resolver.graph is None:
            state = ImpactCapabilityState.UNAVAILABLE
            coverage = None
        else:
            state = ImpactCapabilityState.PARTIAL
            coverage = (
                authoritative / total if total else None
            )
        limitations = [limitation]
        if total and not authoritative:
            limitations.append(
                "Canonical model edges existed but lacked relation-specific authoritative evidence and were ignored."
            )
        return ImpactCapability(
            name,
            state,
            coverage,
            self._languages,
            limitations=tuple(limitations),
        )

    def _candidate_for_any_id(self, identifier: str) -> SubjectCandidate | None:
        candidate = self._resolver.candidate_for_graph_id(identifier)
        if candidate is not None:
            return candidate
        # Public canonical IDs are already indexed by the resolver.  A bounded
        # exact query keeps identity ownership in PR134 without fuzzy matching.
        from moughorai.subject_resolution import SubjectQuery
        resolved = self._resolver.resolve(SubjectQuery(identifier))
        return resolved.subject if resolved.status is ResolutionStatus.RESOLVED else None

    def _plan_sort_key(self, plan: _CandidatePlan) -> tuple[object, ...]:
        candidate = self._resolver.candidate_for_graph_id(plan.target_graph_id)
        score = _plan_score_value(plan, candidate, self._resolver.graph)
        return (
            len(plan.hops) != 1,
            len(plan.hops),
            -score,
            plan.category.value,
            candidate.qualified_name.casefold() if candidate else "",
            candidate.qualified_name if candidate else "",
            candidate.canonical_id if candidate else plan.target_graph_id,
        )


def _edge_policy(edge: KnowledgeEdge) -> _EdgePolicy | None:
    evidence = tuple(str(item) for item in edge.evidence)
    if not evidence or contains_absolute_path(evidence):
        return None
    relation = edge.relation
    authoritative = False
    if relation is KnowledgeRelation.CALLS:
        authoritative = any(item == _CALL_GRAPH_EVIDENCE for item in evidence)
        policy = _EdgePolicy(
            0.90, 0.90, 0.70, ImpactStrength.PROVEN_DIRECT,
            "Producer-bound call evidence is optional and may cover only a specialized scope.",
            _CALL_GRAPH_PRODUCER,
        )
    elif relation is KnowledgeRelation.IMPORTS:
        authoritative = any(
            item == "imports" or item.startswith("global_symbol.metadata:imports:")
            for item in evidence
        )
        policy = _EdgePolicy(
            0.90, 0.90, 0.80, ImpactStrength.PROVEN_DIRECT,
            "Import evidence proves a resolved structural consumer, not runtime behavior."
        )
    elif relation is KnowledgeRelation.INHERITS:
        authoritative = any(
            item in {"extends", "implements"}
            or item.startswith("global_symbol.metadata:inherits:")
            or item.startswith("global_symbol.metadata:bases:")
            for item in evidence
        )
        policy = _EdgePolicy(
            0.90, 0.95, 0.85, ImpactStrength.PROVEN_DIRECT,
            "Inheritance coverage excludes unresolved, ambiguous, and external bases."
        )
    elif relation is KnowledgeRelation.OVERRIDES:
        authoritative = any(
            item.startswith("global_symbol.metadata:overrides:")
            for item in evidence
        )
        policy = _EdgePolicy(
            0.95, 0.95, 0.85, ImpactStrength.PROVEN_DIRECT,
            "Override coverage is conservative and does not include unannotated or external methods."
        )
    elif relation is KnowledgeRelation.DEPENDS_ON:
        authoritative = any(
            item.startswith("workspace.projects:")
            or item.startswith("declared_dependency:")
            or item == "repository_summary.frameworks"
            or item.partition(":")[0] in {
                "project-local", "test-only", "test-or-sample", "documentation",
                "build-tooling", "optional", "optional-integration",
            }
            or item in {"calls", "uses", "imports", "extends", "implements"}
            for item in evidence
        )
        policy = _EdgePolicy(
            0.82, 0.88, 0.75, ImpactStrength.PROVEN_DIRECT,
            "A dependency declaration proves potential consumption, not runtime linkage."
        )
    elif relation is KnowledgeRelation.MEMBER_OF:
        authoritative = any(
            item == "global_symbol.owner_id" for item in evidence
        )
        policy = _EdgePolicy(
            0.90, 0.95, 0.80, ImpactStrength.STRUCTURAL_CONTEXT,
            "Membership is containment evidence only."
        )
    elif relation is KnowledgeRelation.OWNS:
        authoritative = any(item in {
            "workspace.root", "workspace.projects",
            "repository_summary.projects", "repository_summary.module_hierarchy",
            "semantic_graph.project_id", "global_symbol.owner_id",
        } for item in evidence)
        policy = _EdgePolicy(
            0.90, 0.95, 0.80, ImpactStrength.STRUCTURAL_CONTEXT,
            "Ownership is containment evidence only."
        )
    else:
        return None
    if not authoritative or not safe_edge_evidence_refs(evidence):
        return None
    return policy


def _propagation_edge_supported(
    graph: KnowledgeGraph,
    edge: KnowledgeEdge,
) -> bool:
    """Reject semantically impossible legacy/malformed propagation endpoints."""

    source = graph.get(edge.source)
    target = graph.get(edge.target)
    if source is None or target is None:
        return False
    if edge.relation is KnowledgeRelation.INHERITS:
        return source.kind is KnowledgeKind.TYPE and target.kind is KnowledgeKind.TYPE
    if edge.relation is KnowledgeRelation.OVERRIDES:
        return source.kind is KnowledgeKind.METHOD and target.kind is KnowledgeKind.METHOD
    if edge.relation is KnowledgeRelation.CALLS:
        # Specialized legacy producers can only project some call endpoints at
        # type granularity; the authoritative evidence and capability boundary
        # preserve that partial precision explicitly.
        callable_kinds = {
            KnowledgeKind.METHOD,
            KnowledgeKind.TYPE,
            KnowledgeKind.SYMBOL,
        }
        return source.kind in callable_kinds and target.kind in callable_kinds
    if edge.relation is KnowledgeRelation.IMPORTS:
        consumer_kinds = {
            KnowledgeKind.PROJECT,
            KnowledgeKind.MODULE,
            KnowledgeKind.PACKAGE,
            KnowledgeKind.TYPE,
            KnowledgeKind.METHOD,
            KnowledgeKind.SYMBOL,
        }
        target_kinds = {
            KnowledgeKind.PROJECT,
            KnowledgeKind.MODULE,
            KnowledgeKind.PACKAGE,
            KnowledgeKind.TYPE,
            KnowledgeKind.DEPENDENCY,
            KnowledgeKind.SYMBOL,
        }
        return source.kind in consumer_kinds and target.kind in target_kinds
    if edge.relation is KnowledgeRelation.DEPENDS_ON:
        excluded = {
            KnowledgeKind.CONCEPT,
            KnowledgeKind.DOMAIN,
            KnowledgeKind.CAPABILITY,
            KnowledgeKind.REPOSITORY,
            KnowledgeKind.WORKSPACE,
        }
        return source.kind not in excluded and target.kind not in excluded
    return False


def _category(
    relation: KnowledgeRelation, kind: KnowledgeKind
) -> ImpactCategory:
    if relation is KnowledgeRelation.CALLS:
        return ImpactCategory.CALLER
    if relation is KnowledgeRelation.IMPORTS:
        return ImpactCategory.IMPORTER
    if relation is KnowledgeRelation.INHERITS:
        return ImpactCategory.SUBTYPE
    if relation is KnowledgeRelation.OVERRIDES:
        return ImpactCategory.OVERRIDING_MEMBER
    if relation is KnowledgeRelation.DEPENDS_ON:
        return {
            KnowledgeKind.PROJECT: ImpactCategory.PROJECT_DEPENDENT,
            KnowledgeKind.MODULE: ImpactCategory.MODULE_DEPENDENT,
            KnowledgeKind.PACKAGE: ImpactCategory.PACKAGE_DEPENDENT,
        }.get(kind, ImpactCategory.DEPENDENCY)
    return ImpactCategory.UNKNOWN


def _owner_category(kind: KnowledgeKind) -> ImpactCategory | None:
    return {
        KnowledgeKind.PROJECT: ImpactCategory.OWNING_PROJECT,
        KnowledgeKind.MODULE: ImpactCategory.OWNING_MODULE,
        KnowledgeKind.PACKAGE: ImpactCategory.OWNING_PACKAGE,
    }.get(kind)


def _relation_explanation(relation: KnowledgeRelation) -> str:
    return {
        KnowledgeRelation.CALLS: (
            "An authoritative call edge identifies this caller; absent call edges were not treated as proof of no callers."
        ),
        KnowledgeRelation.IMPORTS: (
            "A resolved canonical import identifies this structural consumer; runtime behavior was not inferred."
        ),
        KnowledgeRelation.INHERITS: (
            "A resolved canonical inheritance edge identifies this subtype as structurally affected."
        ),
        KnowledgeRelation.OVERRIDES: (
            "A conservative canonical override edge identifies this overriding member."
        ),
        KnowledgeRelation.DEPENDS_ON: (
            "A canonical dependency declaration identifies this potential consumer; runtime use was not inferred."
        ),
    }.get(relation, "Structured canonical evidence identifies this impact classification.")


def _score(
    plan: _CandidatePlan,
    evidence_ids: tuple[str, ...],
    candidate: SubjectCandidate,
    graph: KnowledgeGraph | None,
    exposure_evidence_ids: tuple[str, ...],
) -> ImpactScore:
    relation_value = min(
        _RELATION_VALUES.get(hop.edge.relation, 0.5) for hop in plan.hops
    )
    proximity = 1.0 / (1.0 + 0.2 * (len(plan.hops) - 1))
    exposure = _represented_api_exposure(candidate, graph)
    raw_components = [
        ImpactScoreComponent(
            "relation_strength", relation_value, 0.60,
            relation_value * 0.60, evidence_ids,
            "Centralized strength of the weakest traversed authoritative relation.",
        ),
        ImpactScoreComponent(
            "path_proximity", proximity, 0.25,
            proximity * 0.25, (),
            "Shorter evidence paths receive higher deterministic priority.",
        ),
    ]
    if exposure is not None:
        raw_components.append(ImpactScoreComponent(
            "api_exposure", exposure, 0.15,
            exposure * 0.15, exposure_evidence_ids,
            "Structured public/protected visibility only; external contract support is unknown.",
        ))
        components = tuple(raw_components)
    else:
        scale = 1.0 / 0.85
        components = tuple(
            ImpactScoreComponent(
                item.name,
                item.value,
                item.weight * scale,
                item.value * item.weight * scale,
                item.evidence_ids,
                item.explanation,
            )
            for item in raw_components
        )
    value = sum(item.contribution for item in components)
    return ImpactScore(
        value,
        components,
        "Impact priority combines authoritative relation strength, path proximity, and represented API exposure; risk and search do not create impact.",
    )


def _plan_score_value(
    plan: _CandidatePlan,
    candidate: SubjectCandidate | None,
    graph: KnowledgeGraph | None,
) -> float:
    if candidate is None:
        return 0.0
    relation_value = min(
        _RELATION_VALUES.get(hop.edge.relation, 0.5) for hop in plan.hops
    )
    proximity = 1.0 / (1.0 + 0.2 * (len(plan.hops) - 1))
    exposure = _represented_api_exposure(candidate, graph)
    if exposure is None:
        return (relation_value * 0.60 + proximity * 0.25) / 0.85
    return relation_value * 0.60 + proximity * 0.25 + exposure * 0.15


def _represented_api_exposure(
    candidate: SubjectCandidate,
    graph: KnowledgeGraph | None,
) -> float | None:
    node = graph.get(candidate.graph_id) if graph is not None else None
    visibility = dict(node.metadata).get("visibility", "").casefold() if node else ""
    if visibility in {"public", "protected"}:
        return 1.0
    if visibility in {"private", "package", "internal"}:
        return 0.0
    return None


def _confidence(
    hops: tuple[_PathHop, ...],
    evidence_ids: tuple[str, ...],
    evidence: EvidenceIndex,
):
    support_values = [
        record.reliability * record.specificity
        for evidence_id in evidence_ids
        if (record := evidence.get(evidence_id)) is not None
    ]
    weakest = min(support_values, default=0.0)
    average = sum(support_values) / len(support_values) if support_values else 0.0
    base_coverage = min(hop.policy.coverage for hop in hops)
    depth_coverage = 1.0 / (1.0 + 0.1 * (len(hops) - 1))
    coverage = base_coverage * depth_coverage
    if average > 0:
        coverage *= weakest / average
    return ConfidenceCalculator().calculate(
        tuple(
            EvidenceRole(f"path_step_{index + 1}", (evidence_id,), True)
            for index, evidence_id in enumerate(evidence_ids)
        ),
        evidence,
        coverage=max(0.0, min(1.0, coverage)),
    )


def _scope(
    candidate: SubjectCandidate,
    graph: KnowledgeGraph | None,
) -> tuple[str | None, str | None]:
    module = candidate.name if candidate.kind is KnowledgeKind.MODULE else None
    package = candidate.qualified_name if candidate.kind is KnowledgeKind.PACKAGE else None
    if package is None and candidate.kind in {
        KnowledgeKind.TYPE, KnowledgeKind.METHOD, KnowledgeKind.FIELD,
    }:
        base = candidate.qualified_name.partition("#")[0]
        if "." in base:
            package = base.rsplit(".", 1)[0]
    if module is None and graph is not None:
        node = graph.get(candidate.graph_id)
        metadata = dict(node.metadata) if node is not None else {}
        module = metadata.get("scope_id") or candidate.project
    return module, package


def _matches_impact_scope(
    candidate: SubjectCandidate,
    request: ImpactPredictionRequest,
    graph: KnowledgeGraph | None,
) -> bool:
    module, package = _scope(candidate, graph)
    return (
        (request.module is None or request.module == module)
        and (request.package is None or request.package == package)
    )


def _attributes(
    candidate: SubjectCandidate,
    graph: KnowledgeGraph | None,
) -> tuple[tuple[str, str], ...]:
    if graph is None:
        return ()
    node = graph.get(candidate.graph_id)
    metadata = dict(node.metadata) if node is not None else {}
    result = {}
    for key in ("ecosystem", "optional", "source_scope", "visibility"):
        value = metadata.get(key)
        if value and not contains_absolute_path(value):
            result[key] = value
    version = metadata.get("version")
    scope = metadata.get("scope")
    if candidate.kind is KnowledgeKind.DEPENDENCY:
        if version and version != "unversioned":
            result["version"] = version
        if scope and scope != "unspecified":
            result["scope"] = scope
    if candidate.kind is KnowledgeKind.MODULE:
        result["identity_coverage"] = "project-derived"
    return tuple(sorted((key, value) for key, value in result.items()))


def _deduplicate_plans(plans: Sequence[_CandidatePlan]) -> list[_CandidatePlan]:
    result: dict[tuple[str, ImpactCategory], _CandidatePlan] = {}
    for plan in plans:
        key = (plan.target_graph_id, plan.category)
        existing = result.get(key)
        if existing is None or _path_key(plan.hops) < _path_key(existing.hops):
            result[key] = plan
    return list(result.values())


def _path_key(hops: tuple[_PathHop, ...]) -> tuple[object, ...]:
    return (
        len(hops),
        -min(
            (_RELATION_VALUES.get(hop.edge.relation, 0.0) for hop in hops),
            default=0.0,
        ),
        tuple(
            (
                -_RELATION_VALUES.get(hop.edge.relation, 0.0),
                hop.edge.relation.value,
                hop.source_graph_id,
                hop.target_graph_id,
                hop.reverse,
                hop.edge.evidence,
            )
            for hop in hops
        ),
    )
