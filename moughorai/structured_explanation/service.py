from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import re

from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    CodePathConfidence,
    JavaCodeIntelligenceService,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeKind,
    KnowledgeRelation,
)
from moughorai.java_code_intelligence import (
    CallableIndexEntry,
    CallableKind,
    callable_index_from_dict,
)
from moughorai.platform.safety import contains_absolute_path_text
from moughorai.repository_report import RepositoryReport
from moughorai.design_patterns.models import PatternKind
from moughorai.reachability.models import ReachabilityState
from moughorai.risk_analysis.models import RiskHotspot
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
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
    ExplanationAttribute,
    ExplanationAvailability,
    ExplanationCapability,
    ExplanationConfidenceBasis,
    ExplanationFact,
    ExplanationFactKind,
    ExplanationRequest,
    ExplanationSelection,
    ExplanationSubject,
    StructuredExplanation,
)
from .selection import StructuredExplanationSelector


class StructuredExplanationService:
    """Compose PR134 explanations from persisted, source-free Atlas facts."""

    PRODUCER_VERSION = "atlas-pr134/1"
    MAXIMUM_RELATION_FACTS = 48

    def __init__(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        resolver: CanonicalSubjectResolver | None = None,
        selector: StructuredExplanationSelector | None = None,
        include_code_intelligence: bool = True,
    ) -> None:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("structured explanations require an Atlas semantic snapshot")
        if not isinstance(include_code_intelligence, bool):
            raise TypeError('include_code_intelligence must be a boolean')
        self.snapshot = snapshot
        self.include_code_intelligence = include_code_intelligence
        self.context = snapshot.semantic_context
        if resolver is None:
            self.resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
        else:
            expected = CanonicalSubjectResolver.from_snapshot(snapshot)
            if (
                resolver.graph_digest != expected.graph_digest
                or (resolver.graph is None) != (expected.graph is None)
            ):
                raise ValueError(
                    "injected canonical subject resolver does not match the supplied snapshot graph"
                )
            self.resolver = resolver
        self.selector = selector or StructuredExplanationSelector()
        self._pattern_source = _compatible_mapping(
            self.context.get("design_patterns"), producer="atlas-pr130/1"
        )
        self._patterns_by_subject = _pattern_finding_index(self._pattern_source)
        self._reachability_source = _graph_compatible_mapping(
            self.context.get("reachability"),
            producer="atlas-pr131/1",
            graph_digest=self.resolver.graph_digest,
        )
        self._reachability_by_subject = _reachability_finding_index(
            self._reachability_source
        )
        self._risk_source = _graph_compatible_mapping(
            self.context.get("risk_analysis"),
            producer="atlas-pr132/1",
            graph_digest=self.resolver.graph_digest,
        )
        self._risks_by_subject = _subject_finding_index(
            self._risk_source.get("hotspots")
        )
        self._report_source = _graph_compatible_mapping(
            self.context.get("repository_report"),
            producer="atlas-pr133/1",
            graph_digest=self.resolver.graph_digest,
        )

    def explain(
        self,
        request: ExplanationRequest,
        *,
        token_budget: int | None = None,
    ) -> StructuredExplanation:
        if not isinstance(request, ExplanationRequest):
            raise TypeError("explanation request must be an ExplanationRequest")
        fingerprint = self._fingerprint(request)
        capabilities, capability_limitations = self._capabilities(request)

        if request.kind is not None:
            try:
                requested_kind = KnowledgeKind(request.kind)
            except ValueError:
                return self._select(
                    self._finish(
                        request,
                        ExplanationAvailability.UNSUPPORTED,
                        fingerprint,
                        capabilities,
                        limitations=(
                            f"Knowledge subject kind {request.kind!r} is unsupported.",
                            *capability_limitations,
                        ),
                    ),
                    token_budget,
                )
        else:
            requested_kind = None

        if request.relationship:
            result, omitted_facts, omitted_evidence = self._explain_relationship(
                request,
                requested_kind,
                fingerprint,
                capabilities,
                capability_limitations,
            )
        else:
            subject_query = SubjectQuery(
                request.subject,
                requested_kind,
                request.project,
                request.language,
                request.path_constraint,
            )
            reconciliation = _resolve_exact_java_subject(
                self.snapshot,
                self.resolver,
                subject_query,
            )
            if reconciliation is None:
                resolution = self.resolver.resolve(subject_query)
                semantic_subject = resolution.subject
                semantic_metadata_partial = False
            else:
                resolution = reconciliation.resolution
                semantic_subject = reconciliation.semantic_subject
                semantic_metadata_partial = (
                    reconciliation.semantic_metadata_partial
                )
            result, omitted_facts, omitted_evidence = self._explain_resolution(
                request,
                resolution,
                fingerprint,
                capabilities,
                capability_limitations,
                semantic_subject=semantic_subject,
                semantic_metadata_partial=semantic_metadata_partial,
            )
        return self._select(
            result,
            token_budget,
            omitted_facts=omitted_facts,
            omitted_evidence=omitted_evidence,
        )

    def _explain_resolution(
        self,
        request: ExplanationRequest,
        resolution: SubjectResolution,
        fingerprint: str,
        capabilities: tuple[ExplanationCapability, ...],
        capability_limitations: tuple[str, ...],
        *,
        semantic_subject: SubjectCandidate | None,
        semantic_metadata_partial: bool,
    ) -> tuple[StructuredExplanation, int, int]:
        if resolution.status is not ResolutionStatus.RESOLVED:
            return self._finish(
                request,
                _availability(resolution.status),
                fingerprint,
                capabilities,
                candidates=tuple(
                    _explanation_subject(item) for item in resolution.candidates
                ),
                limitations=(*resolution.limitations, *capability_limitations),
            ), 0, 0

        candidate = resolution.subject
        if candidate is None:  # Defensive boundary for externally supplied resolvers.
            return self._finish(
                request,
                ExplanationAvailability.UNAVAILABLE,
                fingerprint,
                capabilities,
                limitations=(
                    "The canonical resolver returned no subject for a resolved result.",
                    *capability_limitations,
                ),
            ), 0, 0
        facts, evidence, limitations, omitted_facts, omitted_evidence = (
            self._subject_facts(
                candidate,
                semantic_subject=semantic_subject,
            )
        )
        return self._finish(
            request,
            (
                ExplanationAvailability.PARTIAL
                if (
                    omitted_facts
                    or omitted_evidence
                    or semantic_metadata_partial
                )
                else ExplanationAvailability.AVAILABLE
            ),
            fingerprint,
            capabilities,
            subject=_explanation_subject(candidate),
            facts=facts,
            evidence=evidence,
            limitations=(
                *resolution.limitations,
                *limitations,
                *capability_limitations,
            ),
        ), omitted_facts, omitted_evidence

    def _explain_relationship(
        self,
        request: ExplanationRequest,
        requested_kind: KnowledgeKind | None,
        fingerprint: str,
        capabilities: tuple[ExplanationCapability, ...],
        capability_limitations: tuple[str, ...],
    ) -> tuple[StructuredExplanation, int, int]:
        source_name = request.relationship_source or request.subject
        target_name = request.relationship_target or ""
        source = self.resolver.resolve(SubjectQuery(
            source_name,
            requested_kind,
            request.project,
            request.language,
            request.path_constraint,
        ))
        target = self.resolver.resolve(SubjectQuery(
            target_name,
            project=request.project,
        ))
        unresolved = source if source.status is not ResolutionStatus.RESOLVED else target
        if unresolved.status is not ResolutionStatus.RESOLVED:
            label = "source" if unresolved is source else "target"
            return self._finish(
                request,
                _availability(unresolved.status),
                fingerprint,
                capabilities,
                candidates=tuple(
                    _explanation_subject(item) for item in unresolved.candidates
                ),
                limitations=(
                    f"The relationship {label} could not be resolved uniquely.",
                    *unresolved.limitations,
                    *capability_limitations,
                ),
            ), 0, 0
        try:
            relation = KnowledgeRelation(request.relationship_kind or "")
        except ValueError:
            return self._finish(
                request,
                ExplanationAvailability.UNSUPPORTED,
                fingerprint,
                capabilities,
                subject=_explanation_subject(source.subject),
                limitations=(
                    f"Canonical relationship kind {request.relationship_kind!r} is unsupported.",
                    *capability_limitations,
                ),
            ), 0, 0
        graph = self.resolver.graph
        if graph is None or source.subject is None or target.subject is None:
            return self._finish(
                request,
                ExplanationAvailability.UNAVAILABLE,
                fingerprint,
                capabilities,
                limitations=("Canonical relationship evidence is unavailable.",),
            ), 0, 0
        edges, matching_edge_count = graph.bounded_outgoing(
            source.subject.graph_id,
            limit=self.MAXIMUM_RELATION_FACTS,
            relation=relation,
            target_id=target.subject.graph_id,
        )
        if not edges:
            return self._finish(
                request,
                ExplanationAvailability.NOT_FOUND,
                fingerprint,
                capabilities,
                subject=_explanation_subject(source.subject),
                limitations=(
                    "No matching canonical relationship is present. Absence is not proof that the semantic relationship does not exist.",
                    *capability_limitations,
                ),
            ), 0, 0
        builder = _FactBuilder(self.snapshot.snapshot_id, self.PRODUCER_VERSION)
        self._add_identity_fact(builder, source.subject)
        for index, edge in enumerate(edges):
            self._add_relation_fact(
                builder,
                source.subject,
                target.subject,
                edge,
                "outgoing",
                priority=10 + index,
            )
        limitations: list[str] = list(capability_limitations)
        if matching_edge_count > len(edges):
            limitations.append(
                f"{matching_edge_count - len(edges)} duplicate-evidence relationship edge(s) were omitted by the deterministic bound."
            )
        omitted = matching_edge_count - len(edges)
        return self._finish(
            request,
            (
                ExplanationAvailability.PARTIAL
                if omitted
                else ExplanationAvailability.AVAILABLE
            ),
            fingerprint,
            capabilities,
            subject=_explanation_subject(source.subject),
            facts=builder.facts,
            evidence=builder.evidence,
            limitations=limitations,
        ), omitted, omitted

    def _subject_facts(
        self,
        subject: SubjectCandidate,
        *,
        semantic_subject: SubjectCandidate | None,
    ) -> tuple[
        tuple[ExplanationFact, ...],
        EvidenceIndex,
        tuple[str, ...],
        int,
        int,
    ]:
        builder = _FactBuilder(self.snapshot.snapshot_id, self.PRODUCER_VERSION)
        if semantic_subject is not None:
            self._add_identity_fact(builder, semantic_subject)
        limitations: list[str] = []
        omitted_relation_count = 0
        code_omitted, code_limitations = self._add_code_intelligence_facts(
            builder, subject,
        )
        omitted_relation_count += code_omitted
        limitations.extend(code_limitations)
        graph = self.resolver.graph
        if graph is not None and semantic_subject is not None:
            relations: list[tuple[str, KnowledgeEdge, SubjectCandidate]] = []
            bounded_relations, total_relation_count = graph.bounded_incident(
                semantic_subject.graph_id,
                limit=self.MAXIMUM_RELATION_FACTS,
            )
            for direction, edge in bounded_relations:
                neighbor_id = edge.source if direction == "incoming" else edge.target
                neighbor = self.resolver.candidate_for_graph_id(neighbor_id)
                if neighbor is not None:
                    relations.append((direction, edge, neighbor))
            relations.sort(key=lambda item: (
                item[1].relation.value,
                item[0],
                item[2].canonical_id,
                item[1].evidence,
            ))
            for index, (direction, edge, neighbor) in enumerate(relations):
                self._add_relation_fact(
                    builder,
                    semantic_subject,
                    neighbor,
                    edge,
                    direction,
                    priority=20 + index,
                )
            if total_relation_count > len(relations):
                omitted_relation_count += total_relation_count - len(relations)
                limitations.append(
                    f"{omitted_relation_count} direct canonical relationship(s) were omitted by the deterministic bound."
                )

        invalid = 0
        if semantic_subject is not None:
            self._add_repository_metadata(builder, semantic_subject)
            invalid += self._add_pattern_facts(builder, semantic_subject)
            invalid += self._add_reachability_facts(builder, semantic_subject)
            invalid += self._add_risk_facts(builder, semantic_subject)
            invalid += self._add_architecture_facts(builder, semantic_subject)
            self._add_report_metadata(builder, semantic_subject)
        if invalid:
            limitations.append(
                f"{invalid} upstream finding(s) were omitted because their evidence could not be verified."
            )
        return (
            builder.facts,
            builder.evidence,
            tuple(sorted(set(limitations))),
            omitted_relation_count,
            omitted_relation_count,
        )

    def _add_code_intelligence_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> tuple[int, tuple[str, ...]]:
        if (
            not self.include_code_intelligence
            or subject.kind is not KnowledgeKind.METHOD
            or subject.language != 'java'
        ):
            return 0, ()
        try:
            result = JavaCodeIntelligenceService.from_snapshot(
                self.snapshot
            ).query(
                subject.canonical_id,
                configuration=CodeIntelligenceConfiguration(
                    max_depth=6,
                    max_nodes=1_024,
                    max_direct_relationships=6,
                    max_paths_per_section=6,
                    max_limitation_representatives=2,
                ),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return 0, (
                'Java code intelligence could not be verified for this exact callable '
                f'({type(exc).__name__}).',
            )
        if result.report is None:
            return 0, tuple(sorted(set(result.limitations)))
        return self._add_code_intelligence_sections(
            builder, subject, result.report,
        )

    def _add_code_intelligence_sections(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        report,
    ) -> tuple[int, tuple[str, ...]]:
        trace = report.traceability
        builder.add(
            logical_key=f'java-code-subject:{subject.canonical_id}',
            kind=ExplanationFactKind.IDENTITY,
            subject_id=subject.canonical_id,
            title='Represented Java callable identity',
            statement=(
                f'PR156 identifies this exact {report.subject.kind.value} as '
                f'{report.subject.display_name}.'
            ),
            priority=11,
            attributes=(
                ExplanationAttribute('callable_kind', report.subject.kind.value),
                ExplanationAttribute(
                    'source_classification',
                    report.subject.source_classification.value,
                ),
                ExplanationAttribute('source_ref', report.subject.source.compact),
            ),
            evidence_kind=EvidenceKind.GRAPH_NODE,
            source_refs=(
                report.subject.canonical_id,
                report.subject.source.compact,
                trace.callable_index_fingerprint,
            ),
            producer_ids=('moughorai.java-callable-index.v1', 'atlas-pr159/1'),
            limitations=report.subject.limitations,
        )
        relationship_sections = (
            ('relationship', 'Direct high-confidence Java caller', report.direct_callers_high_confidence),
            ('group', 'Direct conservative Java caller call site', report.direct_caller_conservative_groups),
            ('relationship', 'Java caller method reference', report.direct_caller_method_references),
            ('relationship', 'Direct high-confidence Java callee', report.direct_callees_high_confidence),
            ('group', 'Direct conservative Java callee call site', report.direct_callee_conservative_groups),
            ('relationship', 'Java callee method reference', report.direct_callee_method_references),
            ('relationship', 'Direct represented TEST caller', report.direct_test_callers),
        )
        priority = 12
        omitted = 0
        omitted_candidates = 0
        for section_kind, title, section in relationship_sections:
            if section_kind == 'group':
                omitted += section.omitted_call_site_count
                omitted_candidates += section.omitted_candidate_count
            else:
                omitted += section.omitted_count
            for item in section.items:
                if section_kind == 'group':
                    self._add_code_call_group_fact(
                        builder,
                        subject,
                        item,
                        title=title,
                        priority=priority,
                        code_graph_fingerprint=trace.code_graph_fingerprint,
                    )
                else:
                    self._add_code_relationship_fact(
                        builder,
                        subject,
                        item,
                        title=title,
                        priority=priority,
                        code_graph_fingerprint=trace.code_graph_fingerprint,
                    )
                priority += 1
        return self._add_code_path_and_limitation_facts(
            builder, subject, report, priority, omitted, omitted_candidates,
        )

    def _add_code_call_group_fact(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        group,
        *,
        title: str,
        priority: int,
        code_graph_fingerprint: str,
    ) -> None:
        candidates = ','.join(group.included_candidate_ids)
        builder.add(
            logical_key=(
                f'java-call-site:{group.subject_relative_role.value}:'
                f'{group.producer_evidence_id}'
            ),
            kind=ExplanationFactKind.RELATIONSHIP,
            subject_id=subject.canonical_id,
            title=title,
            statement=(
                f'Represented Java evidence groups {group.total_candidate_count} '
                f'conservative target projection(s) for one '
                f'{group.resolution_state.value} source call site; canonical '
                f'direction remains caller-to-callee from {group.canonical_source}.'
            ),
            priority=priority,
            attributes=(
                ExplanationAttribute('canonical_source', group.canonical_source),
                ExplanationAttribute('project', group.project),
                ExplanationAttribute('canonical_relation', group.relation),
                ExplanationAttribute('canonical_direction', group.canonical_direction),
                ExplanationAttribute('subject_relative_role', group.subject_relative_role.value),
                ExplanationAttribute('invocation_kind', group.invocation_kind.value),
                ExplanationAttribute('resolution_state', group.resolution_state.value),
                ExplanationAttribute('path_confidence', group.confidence.value),
                ExplanationAttribute('source_ref', group.location.compact),
                ExplanationAttribute('call_site_count', 1),
                ExplanationAttribute('candidate_projection_count', group.total_candidate_count),
                ExplanationAttribute('included_candidate_count', group.included_candidate_count),
                ExplanationAttribute('omitted_candidate_count', group.omitted_candidate_count),
                ExplanationAttribute('included_candidate_ids', candidates),
            ),
            evidence_kind=EvidenceKind.GRAPH_EDGE,
            source_refs=(
                group.producer_evidence_id,
                group.location.compact,
                group.canonical_source,
                *group.included_candidate_ids,
                code_graph_fingerprint,
            ),
            producer_ids=('moughorai.java-code-graph.v1', 'atlas-pr159/1'),
            limitations=group.limitations,
            reliability=0.70,
            specificity=0.70,
        )

    def _add_code_relationship_fact(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        relationship,
        *,
        title: str,
        priority: int,
        code_graph_fingerprint: str,
    ) -> None:
        confidence = relationship.confidence
        reliability = (
            0.98
            if confidence
            is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            else 0.70
            if confidence
            is CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
            else 0.60
        )
        builder.add(
            logical_key=(
                f'java-call:{relationship.subject_relative_role.value}:'
                f'{relationship.producer_evidence_id}:'
                f'{relationship.canonical_target}'
            ),
            kind=ExplanationFactKind.RELATIONSHIP,
            subject_id=subject.canonical_id,
            title=title,
            statement=(
                f'Represented Java evidence records {relationship.canonical_source} '
                f'calls {relationship.canonical_target}; the subject-relative role is '
                f'{relationship.subject_relative_role.value}.'
            ),
            priority=priority,
            attributes=(
                ExplanationAttribute('canonical_source', relationship.canonical_source),
                ExplanationAttribute('canonical_target', relationship.canonical_target),
                ExplanationAttribute('canonical_relation', relationship.relation),
                ExplanationAttribute('subject_relative_role', relationship.subject_relative_role.value),
                ExplanationAttribute('edge_kind', relationship.edge_kind.value),
                ExplanationAttribute('path_confidence', confidence.value),
                ExplanationAttribute('execution_eligible', relationship.execution_eligible),
                ExplanationAttribute('source_ref', relationship.location.compact),
            ),
            evidence_kind=EvidenceKind.GRAPH_EDGE,
            source_refs=(
                relationship.producer_evidence_id,
                relationship.location.compact,
                relationship.canonical_source,
                relationship.canonical_target,
                code_graph_fingerprint,
            ),
            producer_ids=('moughorai.java-code-graph.v1', 'atlas-pr159/1'),
            limitations=relationship.limitations,
            reliability=reliability,
            specificity=reliability,
        )

    def _add_code_path_fact(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        path,
        *,
        title: str,
        priority: int,
        code_graph_fingerprint: str,
    ) -> None:
        reliability = (
            0.98
            if path.confidence
            is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            else 0.70
        )
        source_refs = {
            code_graph_fingerprint,
            subject.canonical_id,
            path.consumer_subject_id,
            *path.producer_evidence_ids,
            *(step.location.compact for step in path.steps),
        }
        builder.add(
            logical_key=(
                f'java-path:{path.traversal_direction.value}:'
                f'{path.consumer_subject_id}:{subject.canonical_id}:'
                f'{path.depth}:{path.producer_evidence_ids}'
            ),
            kind=ExplanationFactKind.RELATIONSHIP,
            subject_id=subject.canonical_id,
            title=title,
            statement=(
                f'Represented caller-to-callee edges form a depth-{path.depth} '
                f'path from {path.consumer_subject_id} to {subject.canonical_id}; '
                f'impact traversal is labeled {path.traversal_direction.value}.'
            ),
            priority=priority,
            attributes=(
                ExplanationAttribute('consumer_subject_id', path.consumer_subject_id),
                ExplanationAttribute('subject_id', path.subject_id),
                ExplanationAttribute('depth', path.depth),
                ExplanationAttribute('canonical_direction', 'caller_to_callee'),
                ExplanationAttribute('impact_traversal_direction', path.traversal_direction.value),
                ExplanationAttribute('path_confidence', path.confidence.value),
                ExplanationAttribute('root_evidence_id', path.root_evidence_id),
            ),
            evidence_kind=EvidenceKind.ANALYSIS_RESULT,
            source_refs=source_refs,
            producer_ids=(
                'moughorai.java-code-graph.v1',
                'moughorai.java-test-evidence.v1',
                'atlas-pr159/1',
            ),
            limitations=path.limitations,
            reliability=reliability,
            specificity=reliability,
        )

    def _add_code_path_and_limitation_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        report,
        priority: int,
        omitted: int,
        omitted_candidates: int,
    ) -> tuple[int, tuple[str, ...]]:
        path_sections = (
            ('Direct reverse upstream Java impact path', report.upstream_direct),
            ('Transitive reverse upstream Java impact path', report.upstream_transitive),
            ('High-confidence represented TEST path', report.high_confidence_test_paths),
            ('Possible represented TEST path', report.possible_test_paths),
        )
        for title, section in path_sections:
            omitted += section.omitted_count
            for path in section.items:
                self._add_code_path_fact(
                    builder,
                    subject,
                    path,
                    title=title,
                    priority=priority,
                    code_graph_fingerprint=report.traceability.code_graph_fingerprint,
                )
                priority += 1
        self._add_code_limitation_facts(builder, subject, report, priority)
        code_limitations = set(report.general_limitations)
        if omitted:
            code_limitations.add(
                f'{omitted} code-intelligence relationship or path fact(s) '
                'were omitted by deterministic section bounds.'
            )
        if omitted_candidates:
            code_limitations.add(
                f'{omitted_candidates} conservative candidate target '
                'representative(s) were omitted inside grouped call-site facts.'
            )
        return omitted, tuple(sorted(code_limitations))

    def _add_code_limitation_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        report,
        priority: int,
    ) -> None:
        trace = report.traceability
        for number, summary in enumerate(report.limitations):
            source_refs = {
                trace.code_graph_fingerprint,
                *(item.producer_evidence_id for item in summary.representatives),
                *(item.location.compact for item in summary.representatives),
            }
            builder.add(
                logical_key=f'java-limit:{summary.category}:{subject.canonical_id}',
                kind=ExplanationFactKind.LIMITATION,
                subject_id=subject.canonical_id,
                title=f'Java code evidence limitation: {summary.category}',
                statement=(
                    f'The bounded callable neighborhood contains '
                    f'{summary.total_count} {summary.category} record(s); '
                    f'{summary.omitted_count} representative record(s) are omitted.'
                ),
                priority=priority + number,
                attributes=(
                    ExplanationAttribute('category', summary.category),
                    ExplanationAttribute('total_count', summary.total_count),
                    ExplanationAttribute('included_count', len(summary.representatives)),
                    ExplanationAttribute('omitted_count', summary.omitted_count),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=source_refs,
                producer_ids=('moughorai.java-code-graph.v1', 'atlas-pr159/1'),
                limitations=(
                    'These records bound certainty and do not fabricate a represented target.',
                ),
                reliability=0.95,
            )
        offset = priority + len(report.limitations)
        traversal = report.traversal
        capability_states = {
            item.name: item.availability.value
            for item in report.capability_availability
        }
        builder.add(
            logical_key=f'java-traversal:{subject.canonical_id}',
            kind=ExplanationFactKind.METADATA,
            subject_id=subject.canonical_id,
            title='Bounded reverse Java impact traversal',
            statement=(
                f'PR159 visited {traversal.visited_node_count} node(s) and '
                f'{traversal.visited_edge_count} execution-eligible edge(s) '
                'by reverse upstream traversal while preserving caller-to-callee edges.'
            ),
            priority=offset,
            attributes=(
                ExplanationAttribute('canonical_direction', 'caller_to_callee'),
                ExplanationAttribute('impact_traversal_direction', traversal.traversal_direction.value),
                ExplanationAttribute('visited_node_count', traversal.visited_node_count),
                ExplanationAttribute('visited_edge_count', traversal.visited_edge_count),
                ExplanationAttribute('configured_max_depth', traversal.configured_max_depth),
                ExplanationAttribute('truncated', traversal.truncated),
                ExplanationAttribute('calls_availability', capability_states.get('calls', 'unavailable')),
                ExplanationAttribute('tests_availability', capability_states.get('tests', 'unavailable')),
                ExplanationAttribute('reachability_availability', capability_states.get('reachability', 'unavailable')),
            ),
            evidence_kind=EvidenceKind.ANALYSIS_RESULT,
            source_refs=(
                trace.callable_index_fingerprint,
                trace.code_graph_fingerprint,
                trace.test_evidence_fingerprint,
                trace.reachability_fingerprint or 'reachability:unavailable',
            ),
            producer_ids=('atlas-pr131/1', 'atlas-pr159/1'),
            limitations=report.general_limitations,
        )
        if report.negative_test_statement:
            builder.add(
                logical_key=f'java-no-test-path:{subject.canonical_id}',
                kind=ExplanationFactKind.LIMITATION,
                subject_id=subject.canonical_id,
                title='Represented TEST reachability',
                statement=report.negative_test_statement,
                priority=offset + 1,
                attributes=(
                    ExplanationAttribute('runtime_test_coverage_proven', False),
                    ExplanationAttribute('source_reachability_only', True),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=(
                    trace.code_graph_fingerprint,
                    trace.test_evidence_fingerprint,
                    subject.canonical_id,
                ),
                producer_ids=('moughorai.java-test-evidence.v1', 'atlas-pr159/1'),
                limitations=(
                    'Absence of a represented TEST-root path cannot establish that code is untested or lacks runtime coverage.',
                ),
                reliability=0.95,
            )

    def _add_identity_fact(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> None:
        attributes = [
            ExplanationAttribute("kind", subject.kind.value),
            ExplanationAttribute("language", subject.language),
            ExplanationAttribute("qualified_name", subject.qualified_name),
        ]
        if subject.project:
            attributes.append(ExplanationAttribute("project", subject.project))
        if subject.project_scopes:
            attributes.append(
                ExplanationAttribute("project_scope_count", len(subject.project_scopes))
            )
        builder.add(
            logical_key=f"identity:{subject.canonical_id}",
            kind=ExplanationFactKind.IDENTITY,
            subject_id=subject.canonical_id,
            title="Canonical subject identity",
            statement=(
                f"Atlas resolved {subject.name} as a canonical {subject.kind.value} subject."
            ),
            priority=0,
            attributes=attributes,
            evidence_kind=EvidenceKind.GRAPH_NODE,
            source_refs=(self._node_reference(subject),),
            producer_ids=("atlas-pr129/1", self.PRODUCER_VERSION),
        )

    def _add_relation_fact(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
        neighbor: SubjectCandidate,
        edge: KnowledgeEdge,
        direction: str,
        *,
        priority: int,
    ) -> None:
        source = subject if direction == "outgoing" else neighbor
        target = neighbor if direction == "outgoing" else subject
        attributes = [
            ExplanationAttribute("direction", direction),
            ExplanationAttribute("relation", edge.relation.value),
            ExplanationAttribute("neighbor_id", neighbor.canonical_id),
            ExplanationAttribute("neighbor_kind", neighbor.kind.value),
            ExplanationAttribute("producer_evidence_count", len(edge.evidence)),
        ]
        if edge.relation is KnowledgeRelation.DEPENDS_ON:
            attributes.extend((
                ExplanationAttribute(
                    "canonical_source_subject_id", source.canonical_id
                ),
                ExplanationAttribute(
                    "canonical_target_subject_id", target.canonical_id
                ),
                ExplanationAttribute(
                    "subject_relative_role",
                    (
                        "DEPENDENCY_OF_SUBJECT"
                        if direction == "outgoing"
                        else "DEPENDENT_OF_SUBJECT"
                    ),
                ),
            ))
        safe_upstream_refs = tuple(sorted({
            text for item in edge.evidence
            if (text := _safe_reference(item)) is not None
        }))
        upstream_refs = safe_upstream_refs[:16]
        edge_reference = self._edge_reference(source, target, edge)
        limitations: list[str] = []
        unsafe_or_duplicate_count = max(
            0,
            len(edge.evidence) - len(safe_upstream_refs),
        )
        bounded_omission_count = max(0, len(safe_upstream_refs) - len(upstream_refs))
        if not edge.evidence:
            limitations.append(
                "The canonical edge has no producer-specific evidence reference."
            )
        if unsafe_or_duplicate_count:
            limitations.append(
                f"{unsafe_or_duplicate_count} producer evidence reference(s) were excluded "
                "by source-free validation or deterministic deduplication."
            )
        if bounded_omission_count:
            limitations.append(
                f"{bounded_omission_count} safe producer evidence reference(s) were omitted "
                "by the 16-reference explanation bound."
            )
        builder.add(
            logical_key=(
                f"relationship:{direction}:{edge.relation.value}:"
                f"{source.canonical_id}:{target.canonical_id}:{edge_reference}"
            ),
            kind=ExplanationFactKind.RELATIONSHIP,
            subject_id=subject.canonical_id,
            title=f"Canonical {edge.relation.value} relationship",
            statement=(
                f"The canonical graph records a {edge.relation.value} relationship from {source.name} to {target.name}."
            ),
            priority=priority,
            attributes=(
                *attributes,
                ExplanationAttribute(
                    "retained_producer_evidence_count", len(upstream_refs)
                ),
            ),
            evidence_kind=EvidenceKind.GRAPH_EDGE,
            source_refs=(edge_reference, *upstream_refs),
            producer_ids=("atlas-pr129/1", self.PRODUCER_VERSION),
            limitations=tuple(limitations),
            references=(source.canonical_id, target.canonical_id),
            reliability=1.0 if upstream_refs else 0.8,
            specificity=1.0 if upstream_refs else 0.7,
        )

    def _add_repository_metadata(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> None:
        summary = _compatible_mapping(self.context.get("repository_summary"))
        if not summary:
            return
        if subject.kind in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
            projects_value = summary.get("projects")
            projects = _optional_sequence(projects_value)
            explicit_project_count = _nonnegative_integer(
                summary.get("project_count")
            )
            project_count = (
                len(projects) if projects is not None else explicit_project_count
            )
            languages = _optional_mapping(summary.get("language_file_counts"))
            build_systems = _optional_sequence(summary.get("build_systems"))
            frameworks = _optional_sequence(summary.get("frameworks"))
            entry_points = _optional_sequence(summary.get("entry_points"))
            counts = (
                ("project_count", project_count, "project(s)"),
                (
                    "language_count",
                    len(languages) if languages is not None else None,
                    "primary language bucket(s)",
                ),
                (
                    "build_system_count",
                    len(build_systems) if build_systems is not None else None,
                    "build system(s)",
                ),
                (
                    "framework_count",
                    len(frameworks) if frameworks is not None else None,
                    "framework record(s)",
                ),
                (
                    "entry_point_count",
                    len(entry_points) if entry_points is not None else None,
                    "entry point(s)",
                ),
            )
            known_counts = tuple(item for item in counts if item[1] is not None)
            if not known_counts:
                return
            missing_count = len(counts) - len(known_counts)
            attributes = tuple(
                ExplanationAttribute(name, value)
                for name, value, _ in known_counts
            )
            statement_counts = ", ".join(
                f"{value} {label}" for _, value, label in known_counts
            )
            source_refs: list[str] = []
            if project_count is not None:
                source_refs.append(
                    "repository_summary.projects"
                    if projects is not None
                    else "repository_summary.project_count"
                )
            for value, field in (
                (languages, "language_file_counts"),
                (build_systems, "build_systems"),
                (frameworks, "frameworks"),
                (entry_points, "entry_points"),
            ):
                if value is not None:
                    source_refs.append(f"repository_summary.{field}")
            builder.add(
                logical_key="repository-summary:inventory",
                kind=ExplanationFactKind.METADATA,
                subject_id=subject.canonical_id,
                title="Repository inventory",
                statement=(
                    "The repository summary provides structured inventory counts for "
                    f"{statement_counts}."
                ),
                priority=12,
                attributes=attributes,
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                source_refs=tuple(source_refs),
                producer_ids=("atlas-pr127/1", self.PRODUCER_VERSION),
                limitations=(
                    "One or more repository inventory counts are unavailable because "
                    "their structured fields are absent or malformed."
                ,) if missing_count else (),
                reliability=0.8,
            )

    def _add_pattern_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> int:
        source = self._pattern_source
        if not source or subject.kind not in {
            KnowledgeKind.SYMBOL,
            KnowledgeKind.TYPE,
            KnowledgeKind.METHOD,
            KnowledgeKind.FIELD,
        }:
            return 0
        identifiers = {
            subject.graph_id,
            subject.canonical_id,
        }
        matched_by_key: dict[str, Mapping[str, object]] = {}
        for identifier in identifiers:
            for finding in self._patterns_by_subject.get(identifier, ()):
                matched_by_key[_canonical_json(finding)] = finding
        matched = [
            (finding, _records(finding.get("participants")))
            for _, finding in sorted(matched_by_key.items())
        ]
        if not matched:
            return 0
        index = _evidence_index(source)
        invalid = 0
        for index_number, (finding, participants) in enumerate(sorted(
            matched,
            key=lambda item: (
                str(item[0].get("pattern", "")),
                json.dumps(item[0], ensure_ascii=False, sort_keys=True),
            ),
        )):
            confidence = _bounded_number(finding.get("confidence"))
            if confidence is None:
                invalid += 1
                continue
            evidence_ids = _verified_pattern_evidence_ids(
                index,
                finding.get("evidence_ids"),
                participants=participants,
                snapshot_id=f"semantic-graph:{source.get('input_fingerprint', '')}",
            )
            if not evidence_ids:
                invalid += 1
                continue
            try:
                pattern = PatternKind(str(finding.get("pattern", ""))).value
            except ValueError:
                invalid += 1
                continue
            builder.add(
                logical_key=f"pattern:{pattern}:{index_number}:{subject.canonical_id}",
                kind=ExplanationFactKind.FINDING,
                subject_id=subject.canonical_id,
                title=f"{pattern} pattern finding",
                statement=(
                    f"PR130 associates this subject with a {pattern} finding supported by {len(evidence_ids)} verified evidence record(s)."
                ),
                priority=80 + index_number,
                attributes=(
                    ExplanationAttribute("pattern", pattern),
                    ExplanationAttribute("participant_count", len(participants)),
                    ExplanationAttribute("confidence", confidence),
                    ExplanationAttribute(
                        "confidence_tier",
                        _safe_text(finding.get("confidence_tier")) or "unknown",
                    ),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=evidence_ids,
                producer_ids=("atlas-pr130/1", self.PRODUCER_VERSION),
                limitations=_strings(finding.get("limitations")),
                confidence_basis=ExplanationConfidenceBasis.LEGACY_UPSTREAM,
                reliability=0.9,
            )
        return invalid

    def _add_reachability_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> int:
        source = self._reachability_source
        if not source:
            return 0
        matched = _lookup_reachability_findings(
            self._reachability_by_subject,
            {subject.graph_id, subject.canonical_id},
        )
        if not matched:
            return 0
        index = _evidence_index(source)
        invalid = 0
        for number, finding in enumerate(matched):
            confidence = _bounded_number(finding.get("confidence"))
            if confidence is None:
                invalid += 1
                continue
            evidence_ids = _verified_reachability_evidence_ids(
                index,
                finding.get("evidence_ids"),
                source=source,
                finding=finding,
                subject_ids={subject.graph_id, subject.canonical_id},
                snapshot_id=str(source.get("snapshot_lineage", "")),
            )
            if not evidence_ids:
                invalid += 1
                continue
            try:
                state = ReachabilityState(str(finding.get("state", ""))).value
            except ValueError:
                invalid += 1
                continue
            production_reachable = finding.get("production_reachable")
            test_reachable = finding.get("test_reachable")
            if not isinstance(production_reachable, bool) or not isinstance(
                test_reachable, bool
            ):
                invalid += 1
                continue
            builder.add(
                logical_key=f"reachability:{state}:{number}:{subject.canonical_id}",
                kind=ExplanationFactKind.FINDING,
                subject_id=subject.canonical_id,
                title="Reachability finding",
                statement=f"PR131 classifies this subject's reachability as {state}.",
                priority=100 + number,
                attributes=(
                    ExplanationAttribute("state", state),
                    ExplanationAttribute(
                        "production_reachable",
                        production_reachable,
                    ),
                    ExplanationAttribute(
                        "test_reachable", test_reachable
                    ),
                    ExplanationAttribute("confidence", confidence),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=evidence_ids,
                producer_ids=("atlas-pr131/1", self.PRODUCER_VERSION),
                limitations=_strings(finding.get("limitations")),
                confidence_basis=ExplanationConfidenceBasis.LEGACY_UPSTREAM,
                reliability=0.9,
            )
        return invalid

    def _add_risk_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> int:
        source = self._risk_source
        if not source:
            return 0
        matched_by_key: dict[str, Mapping[str, object]] = {}
        for identifier in {subject.graph_id, subject.canonical_id}:
            for finding in self._risks_by_subject.get(identifier, ()):
                matched_by_key[_canonical_json(finding)] = finding
        matched = tuple(item for _, item in sorted(matched_by_key.items()))
        if not matched:
            return 0
        index = _evidence_index(source)
        invalid = 0
        for number, finding in enumerate(matched):
            if not _valid_confidence_payload(finding.get("confidence")):
                invalid += 1
                continue
            try:
                restored = RiskHotspot.from_dict(finding)
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            subject_ids = {subject.graph_id, subject.canonical_id}
            if restored.subject_id not in subject_ids:
                invalid += 1
                continue
            factor_evidence_ids = {
                evidence_id
                for factor in restored.factors
                for evidence_id in factor.metric.evidence_ids
            }
            if set(restored.evidence_ids) != factor_evidence_ids:
                invalid += 1
                continue
            metric_producers = {factor.metric.producer for factor in restored.factors}
            evidence_ids = _verified_evidence_ids(
                index,
                restored.evidence_ids,
                subject_ids=subject_ids,
                snapshot_ids={str(source.get("lineage", ""))},
                producer_ids=metric_producers,
            )
            if not evidence_ids:
                invalid += 1
                continue
            builder.add(
                logical_key=f"risk:{number}:{subject.canonical_id}",
                kind=ExplanationFactKind.FINDING,
                subject_id=subject.canonical_id,
                title="Risk hotspot finding",
                statement=(
                    f"PR132 ranks this subject as hotspot {restored.rank} with normalized score {restored.score:.4f}."
                ),
                priority=120 + number,
                attributes=(
                    ExplanationAttribute("rank", restored.rank),
                    ExplanationAttribute("score", restored.score),
                    ExplanationAttribute("cohort", restored.cohort),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=evidence_ids,
                producer_ids=("atlas-pr132/1", self.PRODUCER_VERSION),
                limitations=restored.limitations,
                confidence=restored.confidence,
                confidence_basis=ExplanationConfidenceBasis.UPSTREAM,
                reliability=0.9,
            )
        return invalid

    def _add_architecture_facts(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> int:
        if subject.kind not in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
            return 0
        source = _compatible_mapping(self.context.get("architecture"))
        if not source:
            return 0
        invalid = 0
        findings = sorted(
            _records(source.get("findings")),
            key=lambda item: (
                str(item.get("architecture", "")),
                _canonical_json(item),
            ),
        )
        for number, finding in enumerate(findings):
            confidence = _bounded_number(finding.get("confidence"))
            if confidence is None:
                invalid += 1
                continue
            all_evidence = _architecture_evidence_refs(finding.get("evidence"))
            evidence = all_evidence[:16]
            if not evidence:
                invalid += 1
                continue
            architecture = _safe_text(finding.get("architecture")) or "unknown"
            status = _safe_text(finding.get("status")) or "candidate"
            omitted_evidence = len(all_evidence) - len(evidence)
            architecture_limitations = list(_strings(finding.get("limitations")))
            if omitted_evidence:
                architecture_limitations.append(
                    f"{omitted_evidence} architecture evidence reference(s) were omitted by the deterministic per-fact bound."
                )
            builder.add(
                logical_key=f"architecture:{architecture}:{number}",
                kind=ExplanationFactKind.FINDING,
                subject_id=subject.canonical_id,
                title=f"{architecture} architecture finding",
                statement=(
                    f"PR128 records {architecture} with status {status}; this wording preserves the producer's evidence scope."
                ),
                priority=140 + number,
                attributes=(
                    ExplanationAttribute("architecture", architecture),
                    ExplanationAttribute("status", status),
                    ExplanationAttribute("confidence", confidence),
                    ExplanationAttribute("evidence_reference_count", len(all_evidence)),
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                source_refs=evidence,
                producer_ids=("architecture-detection.v1", self.PRODUCER_VERSION),
                limitations=architecture_limitations,
                confidence_basis=ExplanationConfidenceBasis.LEGACY_UPSTREAM,
                reliability=0.9,
            )
        return invalid

    def _add_report_metadata(
        self,
        builder: _FactBuilder,
        subject: SubjectCandidate,
    ) -> None:
        if subject.kind not in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
            return
        report = self._report_source
        if not report:
            return
        try:
            restored = RepositoryReport.from_dict(report)
        except (KeyError, TypeError, ValueError):
            return
        sections = restored.sections
        item_count = len(restored.items)
        builder.add(
            logical_key="repository-report:availability",
            kind=ExplanationFactKind.METADATA,
            subject_id=subject.canonical_id,
            title="Deterministic repository report",
            statement=(
                f"PR133 provides a deterministic repository report with {len(sections)} section(s) and {item_count} referenced item(s)."
            ),
            priority=160,
            attributes=(
                ExplanationAttribute("section_count", len(sections)),
                ExplanationAttribute("referenced_item_count", item_count),
            ),
            evidence_kind=EvidenceKind.ANALYSIS_RESULT,
            source_refs=(f"repository-report:{restored.stable_digest()}",),
            producer_ids=("atlas-pr133/1", self.PRODUCER_VERSION),
            reliability=0.9,
        )

    def _capabilities(
        self,
        request: ExplanationRequest,
    ) -> tuple[tuple[ExplanationCapability, ...], tuple[str, ...]]:
        values: list[ExplanationCapability] = []
        limitations: list[str] = []

        def add(
            name: str,
            availability: ExplanationAvailability,
            producer: str | None,
            *,
            coverage: float | None = None,
            capability_limitations: tuple[str, ...] = (),
            incompatible: bool = False,
        ) -> None:
            values.append(ExplanationCapability(
                name,
                availability,
                (producer,) if producer is not None else (),
                coverage,
                capability_limitations,
            ))
            if incompatible:
                limitations.extend(capability_limitations)

        graph_available = self.resolver.graph is not None
        graph_limitations = tuple(
            item for item in self.resolver.limitations
            if "dangling canonical graph relationship" in item
        )
        graph_partial = graph_available and bool(graph_limitations)
        graph_availability = (
            ExplanationAvailability.PARTIAL
            if graph_partial
            else ExplanationAvailability.AVAILABLE
            if graph_available
            else ExplanationAvailability.UNAVAILABLE
        )
        graph_capability_limitations = (
            graph_limitations
            if graph_partial
            else ()
            if graph_available
            else ("canonical_graph analysis is unavailable.",)
        )
        add(
            "canonical_graph",
            graph_availability,
            "atlas-pr129/1" if graph_available else None,
            coverage=1.0 if graph_available and not graph_partial else None,
            capability_limitations=graph_capability_limitations,
        )

        summary_raw = self.context.get("repository_summary")
        summary = _compatible_mapping(summary_raw, producer="atlas-pr127/1")
        summary_limitations = () if summary else (
            "repository_summary data is unavailable or schema-incompatible.",
        )
        add(
            "repository_summary",
            ExplanationAvailability.AVAILABLE
            if summary else ExplanationAvailability.UNAVAILABLE,
            "atlas-pr127/1" if summary else None,
            capability_limitations=summary_limitations,
            incompatible=isinstance(summary_raw, Mapping) and not summary,
        )

        architecture_raw = self.context.get("architecture")
        architecture = _compatible_mapping(architecture_raw)
        architecture_limitations = () if architecture else (
            "architecture data is unavailable or schema-incompatible.",
        )
        add(
            "architecture",
            ExplanationAvailability.AVAILABLE
            if architecture else ExplanationAvailability.UNAVAILABLE,
            "architecture-detection.v1" if architecture else None,
            capability_limitations=architecture_limitations,
            incompatible=isinstance(architecture_raw, Mapping) and not architecture,
        )

        pattern_raw = self.context.get("design_patterns")
        if self._pattern_source:
            pattern_lineage_limitation = (
                "PR130 v1 does not publish a standalone canonical graph digest; "
                "current-graph binding relies on validated semantic-snapshot co-publication.",
            )
            pattern_statuses = tuple(
                str(item.get("availability", ""))
                for item in _records(self._pattern_source.get("capabilities"))
            )
            available_patterns = sum(
                status == "available" for status in pattern_statuses
            )
            if pattern_statuses and available_patterns == len(pattern_statuses):
                pattern_availability = ExplanationAvailability.AVAILABLE
                pattern_coverage: float | None = 1.0
                pattern_limitations = pattern_lineage_limitation
            else:
                pattern_availability = ExplanationAvailability.PARTIAL
                pattern_coverage = (
                    available_patterns / len(pattern_statuses)
                    if pattern_statuses else None
                )
                pattern_limitations = pattern_lineage_limitation + (
                    "PR130 reports insufficient evidence for one or more pattern detectors."
                    if pattern_statuses else
                    "PR130 capability coverage is absent; pattern analysis completeness is unknown."
                ,)
            add(
                "design_patterns",
                pattern_availability,
                "atlas-pr130/1",
                coverage=pattern_coverage,
                capability_limitations=pattern_limitations,
            )
        else:
            message = (
                "design_patterns data is present but schema- or producer-incompatible."
                if isinstance(pattern_raw, Mapping) else
                "design_patterns analysis is unavailable."
            )
            add(
                "design_patterns",
                ExplanationAvailability.UNAVAILABLE,
                None,
                capability_limitations=(message,),
                incompatible=isinstance(pattern_raw, Mapping),
            )

        reachability_raw = self.context.get("reachability")
        if self._reachability_source:
            coverage = _mapping(self._reachability_source.get("coverage"))
            status = str(coverage.get("status", ""))
            if status == "complete":
                reachability_availability = ExplanationAvailability.AVAILABLE
                reachability_coverage: float | None = 1.0
                reachability_limitations = ()
            elif status in {"partial", "insufficient"}:
                reachability_availability = ExplanationAvailability.PARTIAL
                reachability_coverage = None
                reachability_limitations = (
                    f"PR131 reachability coverage is {status}.",
                )
            elif status == "unavailable":
                reachability_availability = ExplanationAvailability.UNAVAILABLE
                reachability_coverage = None
                reachability_limitations = (
                    "PR131 reachability coverage is unavailable.",
                )
            else:
                reachability_availability = ExplanationAvailability.PARTIAL
                reachability_coverage = None
                reachability_limitations = (
                    "PR131 reachability coverage status is absent or unrecognized.",
                )
            add(
                "reachability",
                reachability_availability,
                "atlas-pr131/1",
                coverage=reachability_coverage,
                capability_limitations=reachability_limitations,
            )
        else:
            message = _incompatible_graph_source_message(
                reachability_raw,
                producer="atlas-pr131/1",
                name="reachability",
                graph_digest=self.resolver.graph_digest,
            )
            add(
                "reachability",
                ExplanationAvailability.UNAVAILABLE,
                None,
                capability_limitations=(message,),
                incompatible=isinstance(reachability_raw, Mapping),
            )

        risk_raw = self.context.get("risk_analysis")
        if self._risk_source:
            risk_statuses = tuple(
                str(item.get("status", ""))
                for item in _records(self._risk_source.get("capabilities"))
            )
            if risk_statuses and all(item == "available" for item in risk_statuses):
                risk_availability = ExplanationAvailability.AVAILABLE
                risk_coverage: float | None = 1.0
                risk_limitations = ()
            elif risk_statuses and all(item == "unavailable" for item in risk_statuses):
                risk_availability = ExplanationAvailability.UNAVAILABLE
                risk_coverage = None
                risk_limitations = (
                    "PR132 reports all structured risk metric capabilities as unavailable.",
                )
            else:
                risk_availability = ExplanationAvailability.PARTIAL
                risk_coverage = None
                risk_limitations = (
                    "PR132 risk metric coverage is partial or unspecified.",
                )
            add(
                "risk_analysis",
                risk_availability,
                "atlas-pr132/1",
                coverage=risk_coverage,
                capability_limitations=risk_limitations,
            )
        else:
            message = _incompatible_graph_source_message(
                risk_raw,
                producer="atlas-pr132/1",
                name="risk_analysis",
                graph_digest=self.resolver.graph_digest,
            )
            add(
                "risk_analysis",
                ExplanationAvailability.UNAVAILABLE,
                None,
                capability_limitations=(message,),
                incompatible=isinstance(risk_raw, Mapping),
            )

        report_raw = self.context.get("repository_report")
        report = self._report_source
        restored_report: RepositoryReport | None = None
        if report:
            try:
                restored_report = RepositoryReport.from_dict(report)
            except (KeyError, TypeError, ValueError):
                restored_report = None
        if restored_report is None:
            report_limitations = (_incompatible_graph_source_message(
                report_raw,
                producer="atlas-pr133/1",
                name="repository_report",
                graph_digest=self.resolver.graph_digest,
            ),)
            add(
                "repository_report",
                ExplanationAvailability.UNAVAILABLE,
                None,
                capability_limitations=report_limitations,
                incompatible=isinstance(report_raw, Mapping),
            )
        else:
            report_partial = bool(restored_report.selection.omitted_item_count)
            add(
                "repository_report",
                ExplanationAvailability.PARTIAL
                if report_partial else ExplanationAvailability.AVAILABLE,
                "atlas-pr133/1",
                capability_limitations=(
                    "PR133 report selection omitted one or more structured items."
                ,) if report_partial else (),
            )

        raw_callable_index = self.context.get('java_callable_index')
        raw_code_graph = self.context.get('java_code_graph')
        raw_test_evidence = self.context.get('java_test_evidence')
        java_artifacts = (
            raw_callable_index,
            raw_code_graph,
            raw_test_evidence,
        )
        java_code_requested = (
            (
                request.kind == KnowledgeKind.METHOD.value
                or request.subject.startswith(('method:', 'constructor:'))
            )
            and (
                request.language is None
                or request.language.casefold() == 'java'
            )
            and any(isinstance(item, Mapping) for item in java_artifacts)
        )
        java_compatible = (
            all(isinstance(item, Mapping) for item in java_artifacts)
            and raw_callable_index.get('format')
            == 'moughorai.java-callable-index.v1'
            and raw_code_graph.get('format') == 'moughorai.java-code-graph.v1'
            and raw_test_evidence.get('format')
            == 'moughorai.java-test-evidence.v1'
        )
        if java_code_requested and java_compatible:
            graph_coverage = _mapping(raw_code_graph.get('coverage'))
            index_coverage = _mapping(raw_callable_index.get('coverage'))
            test_coverage = _mapping(raw_test_evidence.get('coverage'))
            partial = any(
                _nonnegative_integer(graph_coverage.get(name))
                for name in (
                    'callable_bodies_unavailable',
                    'extraction_failures',
                    'polymorphic_call_sites',
                    'ambiguous_call_sites',
                    'unresolved_call_sites',
                    'external_call_sites',
                    'unsupported_call_sites',
                )
            ) or bool(
                _nonnegative_integer(index_coverage.get('unindexed_callables'))
            ) or not bool(
                _nonnegative_integer(test_coverage.get('represented_test_roots'))
            )
            add(
                'java_code_intelligence',
                ExplanationAvailability.PARTIAL
                if partial else ExplanationAvailability.AVAILABLE,
                'atlas-pr159/1',
                coverage=None if partial else 1.0,
                capability_limitations=(
                    'Detailed Java code intelligence activates only for an exact represented method or constructor.',
                    'Represented source reachability does not prove runtime dispatch or runtime test coverage.',
                ) + ((
                    'Unavailable bodies or uncertain call and TEST-root evidence make Java code intelligence partial.',
                ) if partial else ()),
            )
        elif java_code_requested:
            add(
                'java_code_intelligence',
                ExplanationAvailability.UNAVAILABLE,
                None,
                capability_limitations=(
                    'Compatible PR156, PR157, and PR158 Java artifacts are required for code intelligence.',
                ),
                incompatible=any(isinstance(item, Mapping) for item in java_artifacts),
            )

        build_targets_available = self.resolver.has_kind(KnowledgeKind.BUILD_TARGET)
        add(
            "build_targets",
            ExplanationAvailability.AVAILABLE
            if build_targets_available else ExplanationAvailability.UNAVAILABLE,
            "atlas-pr129/1" if build_targets_available else None,
            capability_limitations=() if build_targets_available else (
                "No authoritative real build-target or task producer populated the canonical graph.",
            ),
        )
        return tuple(values), tuple(sorted(set(limitations)))

    def _finish(
        self,
        request: ExplanationRequest,
        availability: ExplanationAvailability,
        fingerprint: str,
        capabilities: tuple[ExplanationCapability, ...],
        *,
        subject: ExplanationSubject | None = None,
        candidates: tuple[ExplanationSubject, ...] = (),
        facts: tuple[ExplanationFact, ...] = (),
        evidence: EvidenceIndex | None = None,
        limitations: Iterable[str] = (),
    ) -> StructuredExplanation:
        return StructuredExplanation(
            request,
            availability,
            self.snapshot.snapshot_id,
            self.resolver.graph_digest,
            fingerprint,
            self.snapshot.snapshot_id,
            subject,
            candidates,
            facts,
            capabilities,
            evidence or EvidenceIndex(),
            tuple(limitations),
            ExplanationSelection(),
        )

    def _select(
        self,
        explanation: StructuredExplanation,
        token_budget: int | None,
        *,
        omitted_facts: int = 0,
        omitted_evidence: int = 0,
    ) -> StructuredExplanation:
        if token_budget is None:
            return explanation
        return self.selector.select(
            explanation,
            token_budget=token_budget,
            preselection_omitted_fact_count=omitted_facts,
            preselection_omitted_evidence_count=omitted_evidence,
        )

    def _fingerprint(self, request: ExplanationRequest) -> str:
        payload = {
            "snapshot_id": self.snapshot.snapshot_id,
            "graph_digest": self.resolver.graph_digest,
            "request": request.to_dict(),
            "producer_version": self.PRODUCER_VERSION,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _node_reference(subject: SubjectCandidate) -> str:
        digest = hashlib.sha256(_canonical_json({
            "id": subject.canonical_id,
            "kind": subject.kind.value,
            "qualified_name": subject.qualified_name,
        }).encode("utf-8")).hexdigest()
        return f"semantic-graph-node:{digest}"

    @staticmethod
    def _edge_reference(
        source: SubjectCandidate,
        target: SubjectCandidate,
        edge: KnowledgeEdge,
    ) -> str:
        digest = hashlib.sha256(_canonical_json({
            "source": source.canonical_id,
            "target": target.canonical_id,
            "relation": edge.relation.value,
            "evidence": sorted(edge.evidence),
        }).encode("utf-8")).hexdigest()
        return f"semantic-graph-edge:{digest}"


class _FactBuilder:
    def __init__(self, lineage: str, producer_version: str) -> None:
        self.lineage = lineage
        self.producer_version = producer_version
        self._facts: list[ExplanationFact] = []
        self._evidence = EvidenceIndex()

    @property
    def facts(self) -> tuple[ExplanationFact, ...]:
        return tuple(self._facts)

    @property
    def evidence(self) -> EvidenceIndex:
        return self._evidence.freeze()

    def add(
        self,
        *,
        logical_key: str,
        kind: ExplanationFactKind,
        subject_id: str,
        title: str,
        statement: str,
        priority: int,
        attributes: Iterable[ExplanationAttribute],
        evidence_kind: EvidenceKind,
        source_refs: Iterable[str],
        producer_ids: Iterable[str],
        limitations: Iterable[str] = (),
        references: Iterable[str] = (),
        confidence: ConfidenceResult | None = None,
        confidence_basis: ExplanationConfidenceBasis = ExplanationConfidenceBasis.DIRECT_EVIDENCE,
        reliability: float = 1.0,
        specificity: float = 1.0,
    ) -> None:
        safe_refs = tuple(sorted({
            text for item in source_refs
            if (text := _safe_reference(item)) is not None
        }))
        safe_limitations = tuple(sorted({
            text for item in limitations
            if (text := _safe_text(item)) is not None
        }))
        fact_payload = {
            "logical_key": logical_key,
            "subject_id": subject_id,
            "source_refs": safe_refs,
            "statement": statement,
        }
        fact_id = "explanation-fact:" + hashlib.sha256(
            _canonical_json(fact_payload).encode("utf-8")
        ).hexdigest()
        record = EvidenceRecord.create(
            evidence_kind,
            fact_id,
            self.producer_version,
            self.lineage,
            source_refs=safe_refs,
            scope=subject_id,
            detail={"logical_key": logical_key},
            limitations=safe_limitations,
            reliability=reliability,
            specificity=specificity,
        )
        self._evidence.add(record)
        if confidence is None and confidence_basis is ExplanationConfidenceBasis.DIRECT_EVIDENCE:
            confidence = ConfidenceCalculator().calculate(
                (EvidenceRole("direct-structured-evidence", (record.evidence_id,)),),
                self._evidence,
            )
        fact = ExplanationFact(
            fact_id,
            kind,
            subject_id,
            title,
            statement,
            ExplanationAvailability.AVAILABLE,
            priority,
            tuple(attributes),
            confidence,
            confidence_basis,
            tuple(producer_ids),
            (record.evidence_id,),
            safe_limitations,
            tuple(references),
        )
        self._facts.append(fact)


def _explanation_subject(candidate: SubjectCandidate | None) -> ExplanationSubject | None:
    if candidate is None:
        return None
    return ExplanationSubject(
        candidate.canonical_id,
        candidate.kind.value,
        candidate.name,
        candidate.qualified_name,
        candidate.project,
        candidate.language,
        candidate.match_basis.value,
    )


@dataclass(frozen=True, slots=True)
class _ExactJavaSubjectReconciliation:
    """Authoritative Java identity with separately sourced semantic metadata."""

    resolution: SubjectResolution
    java_callable_project: str | None
    semantic_subject: SubjectCandidate | None
    semantic_subject_project: str | None
    semantic_metadata_partial: bool


def _resolve_exact_java_subject(
    snapshot: AtlasSemanticSnapshot,
    resolver: CanonicalSubjectResolver,
    query: SubjectQuery,
) -> _ExactJavaSubjectReconciliation | None:
    """Resolve represented method IDs against PR156 project ownership."""

    if not query.identifier.startswith("method:"):
        return None
    raw_index = snapshot.semantic_context.get("java_callable_index")
    if not isinstance(raw_index, Mapping):
        return None
    try:
        callable_index = callable_index_from_dict(raw_index)
    except (KeyError, TypeError, ValueError, OverflowError):
        return _ExactJavaSubjectReconciliation(
            _unresolved_exact_java_subject(
                query,
                resolver,
                ResolutionStatus.UNAVAILABLE,
                (
                    "The PR156 Java callable index could not be validated for "
                    "this exact subject.",
                ),
            ),
            None,
            None,
            None,
            True,
        )
    entry = next(
        (
            item
            for item in callable_index.entries
            if item.canonical_subject_id == query.identifier
        ),
        None,
    )
    if entry is None or entry.identity.kind is not CallableKind.METHOD:
        return None

    constraint_limitation = _exact_java_constraint_limitation(entry, query)
    if constraint_limitation is not None:
        return _ExactJavaSubjectReconciliation(
            _unresolved_exact_java_subject(
                query,
                resolver,
                ResolutionStatus.NOT_FOUND,
                (constraint_limitation,),
            ),
            entry.project_id,
            None,
            None,
            False,
        )

    constrained = resolver.resolve(query)
    constrained_subject = _matching_semantic_java_subject(constrained, entry)
    semantic_subject = (
        constrained_subject
        or _matching_semantic_java_subject(
            resolver.resolve(
                SubjectQuery(
                    query.identifier,
                    KnowledgeKind.METHOD,
                    language="java",
                )
            ),
            entry,
        )
    )
    authoritative = _java_subject_candidate(entry, semantic_subject)
    semantic_project = (
        semantic_subject.project if semantic_subject is not None else None
    )
    if semantic_subject is None:
        limitations = (
            "PR156 resolved the exact Java callable, but matching semantic graph "
            "metadata is unavailable; Java code-intelligence facts remain "
            "authoritative.",
        )
        semantic_metadata_partial = True
    elif semantic_project != entry.project_id:
        limitations = (
            "Exact Java subject project identities differ: PR156 callable project "
            f"{entry.project_id!r} is authoritative for Java code intelligence; "
            f"semantic subject metadata uses {semantic_project!r}.",
        )
        semantic_metadata_partial = True
    else:
        limitations = ()
        semantic_metadata_partial = False
    resolution = SubjectResolution(
        query,
        ResolutionStatus.RESOLVED,
        authoritative,
        (),
        0,
        0,
        SubjectMatchBasis.CANONICAL_ID,
        resolver.graph_digest,
        limitations,
    )
    return _ExactJavaSubjectReconciliation(
        resolution,
        entry.project_id,
        semantic_subject,
        semantic_project,
        semantic_metadata_partial,
    )


def _exact_java_constraint_limitation(
    entry: CallableIndexEntry,
    query: SubjectQuery,
) -> str | None:
    if query.kind is not None and query.kind is not KnowledgeKind.METHOD:
        return (
            "The exact PR156 Java callable exists, but its authoritative callable "
            "kind does not match the supplied kind constraint."
        )
    if query.language is not None and query.language.casefold() != "java":
        return (
            "The exact PR156 Java callable exists, but its authoritative language "
            "does not match the supplied language constraint."
        )
    if query.project is not None and query.project != entry.project_id:
        return (
            "The exact PR156 Java callable exists, but its authoritative Java "
            "project does not match the supplied project constraint."
        )
    if query.path is not None and query.path != entry.source.path:
        return (
            "The exact PR156 Java callable exists, but its authoritative source "
            "path does not match the supplied path constraint."
        )
    return None


def _matching_semantic_java_subject(
    resolution: SubjectResolution,
    entry: CallableIndexEntry,
) -> SubjectCandidate | None:
    subject = resolution.subject
    if (
        resolution.status is ResolutionStatus.RESOLVED
        and subject is not None
        and subject.canonical_id == entry.canonical_subject_id
        and subject.kind is KnowledgeKind.METHOD
        and subject.language.casefold() == "java"
    ):
        return subject
    return None


def _java_subject_candidate(
    entry: CallableIndexEntry,
    semantic_subject: SubjectCandidate | None,
) -> SubjectCandidate:
    return SubjectCandidate(
        entry.canonical_subject_id,
        KnowledgeKind.METHOD,
        entry.identity.name,
        entry.identity.raw_signature,
        entry.project_id,
        "java",
        entry.source.path,
        (entry.project_id,),
        SubjectMatchBasis.CANONICAL_ID,
        semantic_subject.graph_id if semantic_subject is not None else "",
    )


def _unresolved_exact_java_subject(
    query: SubjectQuery,
    resolver: CanonicalSubjectResolver,
    status: ResolutionStatus,
    limitations: tuple[str, ...],
) -> SubjectResolution:
    return SubjectResolution(
        query,
        status,
        None,
        (),
        0,
        0,
        SubjectMatchBasis.NONE,
        resolver.graph_digest,
        limitations,
    )


def _availability(status: ResolutionStatus) -> ExplanationAvailability:
    return {
        ResolutionStatus.RESOLVED: ExplanationAvailability.AVAILABLE,
        ResolutionStatus.AMBIGUOUS: ExplanationAvailability.AMBIGUOUS,
        ResolutionStatus.NOT_FOUND: ExplanationAvailability.NOT_FOUND,
        ResolutionStatus.UNAVAILABLE: ExplanationAvailability.UNAVAILABLE,
        ResolutionStatus.UNSUPPORTED: ExplanationAvailability.UNSUPPORTED,
    }[status]


def _compatible_mapping(
    value: object,
    *,
    producer: str | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    try:
        if int(value.get("schema_version", 1)) != 1:
            return {}
    except (OverflowError, TypeError, ValueError):
        return {}
    if producer is not None and str(value.get("producer_version", producer)) != producer:
        return {}
    return value


def _graph_compatible_mapping(
    value: object,
    *,
    producer: str,
    graph_digest: str,
) -> Mapping[str, object]:
    compatible = _compatible_mapping(value, producer=producer)
    if not compatible or graph_digest == "unavailable":
        return {}
    candidate_digest = _safe_text(compatible.get("graph_digest"))
    return compatible if candidate_digest == graph_digest else {}


def _incompatible_graph_source_message(
    value: object,
    *,
    producer: str,
    name: str,
    graph_digest: str,
) -> str:
    if not isinstance(value, Mapping):
        return f"{name} analysis is unavailable."
    compatible = _compatible_mapping(value, producer=producer)
    if not compatible:
        return f"{name} data is present but schema- or producer-incompatible."
    candidate = _safe_text(compatible.get("graph_digest"))
    if graph_digest == "unavailable":
        return f"{name} data cannot be used because the canonical graph is unavailable."
    if candidate is None:
        return f"{name} data lacks a canonical graph digest and cannot be lineage-verified."
    return f"{name} data is stale because its canonical graph digest does not match the current snapshot."


def _evidence_index(
    value: Mapping[str, object],
) -> Mapping[str, Mapping[str, object] | None]:
    raw = value.get("evidence_index")
    if not isinstance(raw, Mapping):
        return {}
    records: dict[str, Mapping[str, object] | None] = {}
    for item in _records(raw.get("records")):
        evidence_id = str(item.get("evidence_id", ""))
        if not evidence_id:
            continue
        previous = records.get(evidence_id)
        if previous is not None and previous != item:
            records[evidence_id] = None
        elif evidence_id not in records:
            records[evidence_id] = item
    return records


def _verified_evidence_ids(
    index: Mapping[str, Mapping[str, object] | None],
    value: object,
    *,
    subject_ids: set[str] | None = None,
    snapshot_ids: set[str] | None = None,
    producer_ids: set[str] | None = None,
) -> tuple[str, ...]:
    requested = _strings(value)
    if not requested:
        return ()
    records: list[EvidenceRecord] = []
    for evidence_id in requested:
        raw = index.get(evidence_id)
        if not isinstance(raw, Mapping):
            return ()
        for numeric_name in ("reliability", "specificity"):
            numeric_value = raw.get(numeric_name, 1.0)
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, (int, float))
                or not math.isfinite(float(numeric_value))
            ):
                return ()
        try:
            record = EvidenceRecord.from_dict(raw)
            expected = EvidenceRecord.create(
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
            )
        except (KeyError, TypeError, ValueError):
            return ()
        if expected != record:
            return ()
        if snapshot_ids is not None and record.snapshot_id not in snapshot_ids:
            return ()
        if producer_ids is not None and record.producer not in producer_ids:
            return ()
        records.append(record)
    if subject_ids is not None and any(
        record.subject_id not in subject_ids for record in records
    ):
        return ()
    return requested


def _verified_pattern_evidence_ids(
    index: Mapping[str, Mapping[str, object] | None],
    value: object,
    *,
    participants: tuple[Mapping[str, object], ...],
    snapshot_id: str,
) -> tuple[str, ...]:
    """Bind PR130 evidence to the finding's canonical participant set."""

    participant_ids = {
        identifier for participant in participants
        if (identifier := _safe_text(participant.get("symbol_id"))) is not None
    }
    if not participant_ids:
        return ()
    verified = _verified_evidence_ids(
        index,
        value,
        snapshot_ids={snapshot_id},
        producer_ids={
            "knowledge-graph/1",
            "java-architecture/1",
            "call-graph/1",
        },
    )
    if not verified:
        return ()
    for evidence_id in verified:
        raw = index.get(evidence_id)
        if not isinstance(raw, Mapping):
            return ()
        try:
            record = EvidenceRecord.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return ()
        detail = dict(record.detail)
        linked_ids = {
            identifier for key in ("source", "target")
            if (identifier := _safe_text(detail.get(key))) is not None
        }
        linked_ids.update(
            reference.removeprefix("canonical:")
            for reference in record.source_refs
            if reference.startswith("canonical:")
            and _safe_text(reference.removeprefix("canonical:")) is not None
        )
        if not linked_ids or not linked_ids.issubset(participant_ids):
            return ()
    return verified


def _verified_reachability_evidence_ids(
    index: Mapping[str, Mapping[str, object] | None],
    value: object,
    *,
    source: Mapping[str, object],
    finding: Mapping[str, object],
    subject_ids: set[str],
    snapshot_id: str,
) -> tuple[str, ...]:
    """Verify the bounded PR131 evidence roles without expanding its full report."""

    verified = _verified_evidence_ids(
        index,
        value,
        snapshot_ids={snapshot_id},
    )
    if not verified:
        return ()
    project = _safe_text(finding.get("project"))
    if project is None:
        return ()
    root_categories = set(_strings(finding.get("root_categories")))
    production_reachable = finding.get("production_reachable") is True
    test_reachable = finding.get("test_reachable") is True
    expected_scopes = {
        scope for scope, available in (
            ("production", production_reachable),
            ("test", test_reachable),
        )
        if available
    }

    coverage_ids: set[str] = set()
    coverage = _mapping(source.get("coverage"))
    for item in _records(coverage.get("projects")):
        if _safe_text(item.get("project")) == project:
            coverage_ids.update(_strings(item.get("evidence_ids")))

    relationship_ids: set[str] = set()
    root_subject_ids: set[str] = set()
    matched_scopes: set[str] = set()
    nontrivial_path_without_evidence = False
    for path in _records(source.get("paths")):
        target = _safe_text(path.get("target_subject_id"))
        scope = _safe_text(path.get("scope"))
        if target not in subject_ids:
            continue
        if scope == "production" and not production_reachable:
            continue
        if scope == "test" and not test_reachable:
            continue
        if scope not in {"production", "test"}:
            continue
        matched_scopes.add(scope)
        path_evidence_ids = set(_strings(path.get("evidence_ids")))
        relationship_ids.update(path_evidence_ids)
        root_subject = _safe_text(path.get("root_subject_id"))
        if root_subject is not None:
            root_subject_ids.add(root_subject)
            if root_subject != target and not path_evidence_ids:
                nontrivial_path_without_evidence = True

    if not expected_scopes.issubset(matched_scopes):
        return ()
    if nontrivial_path_without_evidence:
        return ()

    root_ids: set[str] = set()
    for root in _records(source.get("roots")):
        if _safe_text(root.get("subject_id")) not in root_subject_ids:
            continue
        if _safe_text(root.get("project")) != project:
            continue
        if _safe_text(root.get("category")) not in root_categories:
            continue
        root_ids.update(_strings(root.get("evidence_ids")))

    seen_coverage = False
    seen_root = False
    seen_subject_node = False
    seen_protection = False
    verified_set = set(verified)
    if not coverage_ids or not coverage_ids.issubset(verified_set):
        return ()
    if expected_scopes and (
        not root_ids or not root_ids.issubset(verified_set)
    ):
        return ()
    if not relationship_ids.issubset(verified_set):
        return ()
    for evidence_id in verified:
        raw = index.get(evidence_id)
        if not isinstance(raw, Mapping):
            return ()
        try:
            record = EvidenceRecord.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return ()
        detail = dict(record.detail)
        if (
            evidence_id in coverage_ids
            and record.subject_id == f"project:{project}"
            and record.producer == "atlas-pr131/1"
            and {"roots", "calls", "cfg"}.intersection(detail)
        ):
            seen_coverage = True
            continue
        if (
            evidence_id in root_ids
            and detail.get("root_category") in root_categories
            and record.kind is EvidenceKind.REPOSITORY_METADATA
        ):
            seen_root = True
            continue
        if (
            evidence_id in relationship_ids
            and "relation" in detail
            and record.kind in {EvidenceKind.GRAPH_EDGE, EvidenceKind.ANALYSIS_RESULT}
        ):
            continue
        if (
            record.subject_id in subject_ids
            and record.kind is EvidenceKind.GRAPH_NODE
            and record.producer == "knowledge-graph.v1"
            and detail.get("kind") == finding.get("symbol_kind")
        ):
            seen_subject_node = True
            continue
        if (
            record.subject_id in subject_ids
            and record.kind is EvidenceKind.ANALYSIS_RESULT
            and detail.get("state") == finding.get("state")
            and "mechanism" in detail
        ):
            seen_protection = True
            continue
        return ()
    if not seen_coverage:
        return ()
    state = _safe_text(finding.get("state"))
    if (production_reachable or test_reachable) and not seen_root:
        return ()
    if state in {ReachabilityState.UNUSED.value, ReachabilityState.LIKELY_DEAD.value}:
        if not seen_subject_node:
            return ()
    protected_states = {
        ReachabilityState.EXTERNALLY_REACHABLE.value,
        ReachabilityState.FRAMEWORK_MANAGED.value,
        ReachabilityState.REFLECTION_DISCOVERED.value,
        ReachabilityState.SERVICE_LOADER_DISCOVERED.value,
        ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED.value,
        ReachabilityState.CONDITIONALLY_REACHABLE.value,
        ReachabilityState.UNREACHABLE.value,
    }
    if state in protected_states and not (seen_root or seen_protection):
        return ()
    return verified


def _architecture_evidence_refs(value: object) -> tuple[str, ...]:
    references: set[str] = set()
    for item in _records(value):
        normalized = {
            key: text
            for key in ("kind", "reference", "detail")
            if (text := _safe_text(item.get(key))) is not None
        }
        if not normalized:
            continue
        digest = hashlib.sha256(
            _canonical_json(normalized).encode("utf-8")
        ).hexdigest()
        references.add(f"architecture-evidence:{digest}")
    return tuple(sorted(references))


def _lookup_reachability_findings(
    index: _ReachabilityFindingIndex,
    subject_ids: set[str],
) -> tuple[Mapping[str, object], ...]:
    """Project only indexed PR131 groups selected for the requested subject."""

    found: dict[str, Mapping[str, object]] = {}
    for subject_id in sorted(subject_ids):
        for item in index.direct.get(subject_id, ()):
            found[_canonical_json(item)] = item
        for prefix, suffixes, item in index.groups:
            if not subject_id.startswith(prefix):
                continue
            suffix = subject_id[len(prefix):]
            position = bisect_left(suffixes, suffix)
            if position >= len(suffixes) or suffixes[position] != suffix:
                continue
            if "subject_ids" not in item:
                finding = item
            else:
                finding = {
                    key: value
                    for key, value in item.items()
                    if key not in {"subject_ids", "subject_id_prefix"}
                }
                finding["subject_id"] = subject_id
            found[_canonical_json(finding)] = finding
    return tuple(item for _, item in sorted(found.items()))


def _pattern_finding_index(
    value: Mapping[str, object],
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for finding in _records(value.get("findings")):
        identifiers = {
            str(identifier)
            for participant in _records(finding.get("participants"))
            for identifier in (participant.get("symbol_id"),)
            if identifier is not None and str(identifier)
        }
        for identifier in identifiers:
            result.setdefault(identifier, []).append(finding)
    return {
        key: tuple(sorted(items, key=_canonical_json))
        for key, items in result.items()
    }


@dataclass(frozen=True, slots=True)
class _ReachabilityFindingIndex:
    direct: Mapping[str, tuple[Mapping[str, object], ...]]
    groups: tuple[
        tuple[str, tuple[str, ...], Mapping[str, object]],
        ...,
    ]


def _reachability_finding_index(
    value: Mapping[str, object],
) -> _ReachabilityFindingIndex:
    result: dict[str, list[Mapping[str, object]]] = {}
    for finding in _records(value.get("findings")):
        subject_id = str(finding.get("subject_id", ""))
        if subject_id:
            result.setdefault(subject_id, []).append(finding)
    groups: list[tuple[str, tuple[str, ...], Mapping[str, object]]] = []
    for group in sorted(
        _records(value.get("finding_groups")),
        key=lambda item: (
            str(item.get("subject_id_prefix", "")),
            _canonical_json(item),
        ),
    ):
        prefix = str(group.get("subject_id_prefix", ""))
        suffixes = tuple(sorted({str(item) for item in _sequence(
            group.get("subject_ids")
        )}))
        if suffixes:
            groups.append((prefix, suffixes, group))
    return _ReachabilityFindingIndex(
        {
            key: tuple(sorted(items, key=_canonical_json))
            for key, items in result.items()
        },
        tuple(groups),
    )


def _subject_finding_index(
    value: object,
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for finding in _records(value):
        subject_id = str(finding.get("subject_id", ""))
        if subject_id:
            result.setdefault(subject_id, []).append(finding)
    return {
        key: tuple(sorted(items, key=_canonical_json))
        for key, items in result.items()
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _records(value: object) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in _sequence(value) if isinstance(item, Mapping))


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _strings(value: object) -> tuple[str, ...]:
    return tuple(sorted({
        text for item in _sequence(value)
        if (text := _safe_text(item)) is not None
    }))


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > 4_096 or contains_absolute_path_text(text):
        return None
    return text


_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9_.:/#%+@=\-]+$")


def _safe_reference(value: object) -> str | None:
    text = _safe_text(value)
    if text is None or len(text) > 512 or _SAFE_REFERENCE.fullmatch(text) is None:
        return None
    return text


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _optional_sequence(value: object) -> tuple[object, ...] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return None


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _bounded_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and 0.0 <= result <= 1.0 else None


def _valid_confidence_payload(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    for name in (
        "score",
        "support",
        "coverage",
        "agreement",
        "contradiction_penalty",
        "ambiguity_penalty",
    ):
        raw = value.get(name)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
            or not 0.0 <= float(raw) <= 1.0
        ):
            return False
    model_version = value.get("model_version")
    if (
        isinstance(model_version, bool)
        or not isinstance(model_version, int)
        or model_version <= 0
    ):
        return False
    missing_roles = value.get("missing_roles")
    return isinstance(missing_roles, Sequence) and not isinstance(
        missing_roles, (str, bytes, bytearray)
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
