"""Bounded query service over persisted PR156--158 Java evidence."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    InvocationKind,
)
from moughorai.java_code_intelligence.code_graph import (
    CodeGraphEdge,
    CodeGraphEdgeKind,
    JavaCodeGraph,
    code_graph_from_dict,
)
from moughorai.java_code_intelligence.models import (
    CallableIndexEntry,
    CallableKind,
    JavaCallableIndex,
    SourceClassification,
)
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.java_code_intelligence.test_evidence import (
    JavaTestEvidence,
    RepresentedTestCallable,
    java_test_evidence_from_dict,
)
from moughorai.reachability import DeadCodeReport
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from .models import (
    CODE_INTELLIGENCE_PRODUCER,
    AmbiguousCallGroup,
    BoundedAmbiguousCallGroups,
    BoundedPaths,
    BoundedRelationships,
    CodeCallRelationship,
    CodeCapability,
    CodeImpactPath,
    CodeIntelligenceAvailability,
    CodeLimitationSummary,
    CodePathConfidence,
    CodeRelationshipRole,
    CodeSiteEvidence,
    CodeSourceReference,
    CodeSubject,
    CodeSubjectResolution,
    CodeSubjectResolutionStatus,
    CodeTraceability,
    CodeTraversalDirection,
    CodeTraversalSummary,
    JavaCodeIntelligenceReport,
    JavaCodeIntelligenceResult,
)


_HIGH_CONFIDENCE_KINDS = frozenset({
    CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
    CodeGraphEdgeKind.CONSTRUCTOR_CALL,
})
_CONSERVATIVE_KINDS = frozenset({
    CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
    CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
})
_EXECUTION_KINDS = _HIGH_CONFIDENCE_KINDS | _CONSERVATIVE_KINDS


@dataclass(frozen=True, slots=True)
class CodeIntelligenceConfiguration:
    """Query-time bounds; no transitive closure is persisted."""

    max_depth: int = 8
    max_nodes: int = 4_096
    max_direct_relationships: int = 64
    max_paths_per_section: int = 64
    max_limitation_representatives: int = 8
    max_resolution_candidates: int = 12
    max_candidates_per_call_site: int = 5

    def __post_init__(self) -> None:
        for name in (
            "max_depth",
            "max_nodes",
            "max_direct_relationships",
            "max_paths_per_section",
            "max_limitation_representatives",
            "max_resolution_candidates",
            "max_candidates_per_call_site",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class _TraversalResult:
    paths: Mapping[str, tuple[CodeCallRelationship, ...]]
    visited_edges: int
    depth_histogram: tuple[tuple[int, int], ...]
    truncated: bool


class JavaCodeIntelligenceService:
    """Interpret one immutable snapshot's represented Java call evidence.

    Construction validates the existing artifacts and builds reusable direct
    adjacency.  Queries perform one bounded reverse BFS; they never parse source,
    mutate the canonical graph, or persist a transitive closure.
    """

    def __init__(
        self,
        *,
        snapshot_id: str,
        callable_index: JavaCallableIndex | None,
        code_graph: JavaCodeGraph | None,
        test_evidence: JavaTestEvidence | None,
        reachability_report: DeadCodeReport | None = None,
        limitations: Sequence[str] = (),
    ) -> None:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("code intelligence requires snapshot identity")
        self.snapshot_id = snapshot_id.strip()
        self.callable_index = callable_index
        self.code_graph = code_graph
        self.test_evidence = test_evidence
        self.reachability_report = reachability_report
        self.limitations = tuple(sorted(set(
            item.strip() for item in limitations if item.strip()
        )))

        self._entries: Mapping[str, CallableIndexEntry] = {}
        self._sites: Mapping[str, CallSiteEvidence] = {}
        self._incoming: Mapping[str, tuple[CodeGraphEdge, ...]] = {}
        self._outgoing: Mapping[str, tuple[CodeGraphEdge, ...]] = {}
        self._sites_by_caller: Mapping[str, tuple[CallSiteEvidence, ...]] = {}
        self._test_records: Mapping[str, RepresentedTestCallable] = {}
        self._exact_names: Mapping[str, tuple[str, ...]] = {}

        if not self.available:
            return
        if (
            code_graph.callable_index_fingerprint
            != callable_index.input_fingerprint
            or test_evidence.callable_index_fingerprint
            != callable_index.input_fingerprint
        ):
            raise ValueError("PR156/PR157/PR158 artifact bindings are inconsistent")

        entries = {
            item.canonical_subject_id: item for item in callable_index.entries
        }
        sites = {item.evidence_id: item for item in code_graph.call_sites}
        incoming: dict[str, list[CodeGraphEdge]] = defaultdict(list)
        outgoing: dict[str, list[CodeGraphEdge]] = defaultdict(list)
        for edge in code_graph.edges:
            incoming[edge.target_subject_id].append(edge)
            outgoing[edge.caller_subject_id].append(edge)
        sites_by_caller: dict[str, list[CallSiteEvidence]] = defaultdict(list)
        for site in code_graph.call_sites:
            sites_by_caller[site.request.caller_subject_id].append(site)
        exact_names: dict[str, set[str]] = defaultdict(set)
        for entry in callable_index.entries:
            subject_id = entry.canonical_subject_id
            for value in (
                subject_id,
                entry.identity.normalized_key,
                entry.identity.raw_signature,
                f"{entry.identity.owner_type}#{entry.identity.name}",
            ):
                exact_names[value].add(subject_id)

        self._entries = entries
        self._sites = sites
        self._incoming = {
            key: tuple(sorted(values, key=_edge_sort_key))
            for key, values in incoming.items()
        }
        self._outgoing = {
            key: tuple(sorted(values, key=_edge_sort_key))
            for key, values in outgoing.items()
        }
        self._sites_by_caller = {
            key: tuple(sorted(values, key=_site_sort_key))
            for key, values in sites_by_caller.items()
        }
        self._test_records = {
            item.subject_id: item for item in test_evidence.records
        }
        self._exact_names = {
            key: tuple(sorted(values)) for key, values in exact_names.items()
        }

    @property
    def available(self) -> bool:
        return all((
            isinstance(self.callable_index, JavaCallableIndex),
            isinstance(self.code_graph, JavaCodeGraph),
            isinstance(self.test_evidence, JavaTestEvidence),
        ))

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
    ) -> JavaCodeIntelligenceService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("code intelligence requires an Atlas semantic snapshot")
        return cls.from_context(
            snapshot_id=snapshot.snapshot_id,
            semantic_context=snapshot.semantic_context,
        )

    @classmethod
    def from_context(
        cls,
        *,
        snapshot_id: str,
        semantic_context: Mapping[str, object],
    ) -> JavaCodeIntelligenceService:
        if not isinstance(semantic_context, Mapping):
            raise TypeError("code intelligence semantic context must be a mapping")
        limitations: list[str] = []
        raw_index = semantic_context.get("java_callable_index")
        raw_graph = semantic_context.get("java_code_graph")
        raw_tests = semantic_context.get("java_test_evidence")
        if not isinstance(raw_index, Mapping):
            limitations.append(
                "moughorai.java-callable-index.v1 is unavailable in this snapshot."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=None,
                code_graph=None,
                test_evidence=None,
                limitations=limitations,
            )
        try:
            callable_index = callable_index_from_dict(raw_index)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            limitations.append(
                "moughorai.java-callable-index.v1 is schema-incompatible "
                f"({type(exc).__name__})."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=None,
                code_graph=None,
                test_evidence=None,
                limitations=limitations,
            )
        if not isinstance(raw_graph, Mapping):
            limitations.append(
                "moughorai.java-code-graph.v1 is unavailable in this snapshot."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=callable_index,
                code_graph=None,
                test_evidence=None,
                limitations=limitations,
            )
        try:
            code_graph = code_graph_from_dict(raw_graph, callable_index)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            limitations.append(
                "moughorai.java-code-graph.v1 is schema- or lineage-incompatible "
                f"({type(exc).__name__})."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=callable_index,
                code_graph=None,
                test_evidence=None,
                limitations=limitations,
            )
        if not isinstance(raw_tests, Mapping):
            limitations.append(
                "moughorai.java-test-evidence.v1 is unavailable in this snapshot."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=callable_index,
                code_graph=code_graph,
                test_evidence=None,
                limitations=limitations,
            )
        try:
            test_evidence = java_test_evidence_from_dict(raw_tests, callable_index)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            limitations.append(
                "moughorai.java-test-evidence.v1 is schema- or lineage-incompatible "
                f"({type(exc).__name__})."
            )
            return cls(
                snapshot_id=snapshot_id,
                callable_index=callable_index,
                code_graph=code_graph,
                test_evidence=None,
                limitations=limitations,
            )

        reachability_report = None
        raw_reachability = semantic_context.get("reachability")
        if isinstance(raw_reachability, Mapping):
            try:
                candidate = DeadCodeReport.from_dict(raw_reachability)
                if candidate.producer_version == "atlas-pr131/1":
                    reachability_report = candidate
                else:
                    limitations.append(
                        "Persisted reachability uses an unsupported producer version."
                    )
            except (KeyError, TypeError, ValueError, OverflowError):
                limitations.append(
                    "Persisted PR131 reachability is incompatible; bounded PR159 "
                    "queries still use the validated PR157 edge corpus and PR158 roots."
                )
        else:
            limitations.append(
                "Persisted PR131 reachability is unavailable; bounded PR159 queries "
                "use the validated PR157 edge corpus and PR158 roots."
            )
        return cls(
            snapshot_id=snapshot_id,
            callable_index=callable_index,
            code_graph=code_graph,
            test_evidence=test_evidence,
            reachability_report=reachability_report,
            limitations=limitations,
        )

    def query(
        self,
        identifier: str,
        *,
        kind: CallableKind | str | None = None,
        project: str | None = None,
        configuration: CodeIntelligenceConfiguration | None = None,
    ) -> JavaCodeIntelligenceResult:
        query = identifier.strip() if isinstance(identifier, str) else ""
        if not query:
            raise ValueError("code intelligence subject is required")
        selected = configuration or CodeIntelligenceConfiguration()
        requested_kind: CallableKind | None
        if kind is None:
            requested_kind = None
        else:
            try:
                requested_kind = kind if isinstance(kind, CallableKind) else CallableKind(
                    str(kind).strip().casefold()
                )
            except ValueError:
                resolution = CodeSubjectResolution(
                    CodeSubjectResolutionStatus.UNSUPPORTED,
                    query,
                    limitations=(
                        "PR159 supports exact Java method and constructor subjects only.",
                    ),
                )
                return JavaCodeIntelligenceResult(
                    resolution,
                    self.snapshot_id,
                    limitations=(*self.limitations, *resolution.limitations),
                )
        if not self.available:
            resolution = CodeSubjectResolution(
                CodeSubjectResolutionStatus.UNAVAILABLE,
                query,
                limitations=(
                    *self.limitations,
                    "Java code intelligence requires compatible PR156, PR157, and PR158 artifacts.",
                ),
            )
            return JavaCodeIntelligenceResult(
                resolution,
                self.snapshot_id,
                limitations=resolution.limitations,
            )

        matches = tuple(
            self._entries[subject_id]
            for subject_id in self._exact_names.get(query, ())
            if (requested_kind is None or self._entries[subject_id].identity.kind is requested_kind)
            and (project is None or self._entries[subject_id].project_id == project)
        )
        if not matches:
            resolution = CodeSubjectResolution(
                CodeSubjectResolutionStatus.NOT_FOUND,
                query,
                limitations=(
                    "No exact represented Java method or constructor matched the supplied subject.",
                    "Type-level aggregation is intentionally deferred in PR159.",
                ),
            )
            return JavaCodeIntelligenceResult(
                resolution,
                self.snapshot_id,
                limitations=(*self.limitations, *resolution.limitations),
            )
        if len(matches) > 1:
            all_candidates = tuple(self._subject(item) for item in matches)
            retained = all_candidates[: selected.max_resolution_candidates]
            resolution = CodeSubjectResolution(
                CodeSubjectResolutionStatus.AMBIGUOUS,
                query,
                candidates=retained,
                total_candidate_count=len(all_candidates),
                omitted_candidate_count=len(all_candidates) - len(retained),
                limitations=(
                    "The exact semantic name identifies multiple represented callables; use a canonical callable ID.",
                ),
            )
            return JavaCodeIntelligenceResult(
                resolution,
                self.snapshot_id,
                limitations=(*self.limitations, *resolution.limitations),
            )

        entry = matches[0]
        subject = self._subject(entry)
        resolution = CodeSubjectResolution(
            CodeSubjectResolutionStatus.RESOLVED,
            query,
            subject=subject,
        )
        report = self._report(entry, selected)
        return JavaCodeIntelligenceResult(
            resolution,
            self.snapshot_id,
            report,
            self.limitations,
        )

    def _report(
        self,
        entry: CallableIndexEntry,
        configuration: CodeIntelligenceConfiguration,
    ) -> JavaCodeIntelligenceReport:
        subject_id = entry.canonical_subject_id
        incoming = tuple(
            self._relationship(edge, CodeRelationshipRole.CALLER_OF_SUBJECT)
            for edge in self._incoming.get(subject_id, ())
        )
        outgoing = tuple(
            self._relationship(edge, CodeRelationshipRole.CALLEE_OF_SUBJECT)
            for edge in self._outgoing.get(subject_id, ())
        )
        caller_high = _bounded_relationships(
            (item for item in incoming if item.edge_kind in _HIGH_CONFIDENCE_KINDS),
            configuration.max_direct_relationships,
        )
        caller_possible = _bounded_relationships(
            (item for item in incoming if item.edge_kind in _CONSERVATIVE_KINDS),
            configuration.max_direct_relationships,
        )
        caller_possible_groups = _bounded_ambiguous_call_groups(
            (item for item in incoming if item.edge_kind in _CONSERVATIVE_KINDS),
            self._sites,
            configuration.max_direct_relationships,
            configuration.max_candidates_per_call_site,
        )
        caller_references = _bounded_relationships(
            (
                item for item in incoming
                if item.edge_kind is CodeGraphEdgeKind.METHOD_REFERENCE
            ),
            configuration.max_direct_relationships,
        )
        callee_high = _bounded_relationships(
            (item for item in outgoing if item.edge_kind in _HIGH_CONFIDENCE_KINDS),
            configuration.max_direct_relationships,
        )
        callee_possible = _bounded_relationships(
            (item for item in outgoing if item.edge_kind in _CONSERVATIVE_KINDS),
            configuration.max_direct_relationships,
        )
        callee_possible_groups = _bounded_ambiguous_call_groups(
            (item for item in outgoing if item.edge_kind in _CONSERVATIVE_KINDS),
            self._sites,
            configuration.max_direct_relationships,
            configuration.max_candidates_per_call_site,
        )
        callee_references = _bounded_relationships(
            (
                item for item in outgoing
                if item.edge_kind is CodeGraphEdgeKind.METHOD_REFERENCE
            ),
            configuration.max_direct_relationships,
        )

        traversal = self._reverse_traversal(subject_id, configuration)
        upstream_paths = tuple(
            CodeImpactPath(
                consumer,
                subject_id,
                len(steps),
                _path_confidence(steps),
                steps,
                CodeTraversalDirection.REVERSE_UPSTREAM,
                limitations=_path_limitations(steps),
            )
            for consumer, steps in traversal.paths.items()
            if consumer != subject_id
        )
        direct_paths = _bounded_paths(
            (item for item in upstream_paths if item.depth == 1),
            configuration.max_paths_per_section,
        )
        transitive_paths = _bounded_paths(
            (item for item in upstream_paths if item.depth > 1),
            configuration.max_paths_per_section,
        )

        direct_test_relationships = tuple(
            CodeCallRelationship(
                item.canonical_source,
                item.canonical_target,
                CodeRelationshipRole.TEST_CALLER_OF_SUBJECT,
                item.edge_kind,
                item.producer_evidence_id,
                item.project,
                item.location,
                item.confidence,
                item.limitations,
            )
            for item in incoming
            if item.execution_eligible
            and self._entries[item.canonical_source].source_classification
            is SourceClassification.TEST
        )
        direct_test_callers = _bounded_relationships(
            direct_test_relationships,
            configuration.max_direct_relationships,
        )

        test_paths = []
        for root_id in sorted(traversal.paths):
            root = self._test_records.get(root_id)
            if root is None or not root.is_root:
                continue
            steps = tuple(
                CodeCallRelationship(
                    item.canonical_source,
                    item.canonical_target,
                    CodeRelationshipRole.TEST_REACHES_SUBJECT,
                    item.edge_kind,
                    item.producer_evidence_id,
                    item.project,
                    item.location,
                    item.confidence,
                    item.limitations,
                )
                for item in traversal.paths[root_id]
            )
            test_paths.append(CodeImpactPath(
                root_id,
                subject_id,
                len(steps),
                _path_confidence(steps),
                steps,
                CodeTraversalDirection.FORWARD_TEST_REACHABILITY,
                root.evidence_id,
                tuple(sorted(set((*root.limitations, *_path_limitations(steps))))),
            ))
        high_test_paths = _bounded_paths(
            (
                item for item in test_paths
                if item.confidence
                is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            ),
            configuration.max_paths_per_section,
        )
        possible_test_paths = _bounded_paths(
            (
                item for item in test_paths
                if item.confidence
                is CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
            ),
            configuration.max_paths_per_section,
        )

        neighborhood = set(traversal.paths)
        limitations = self._limitation_summaries(neighborhood, configuration)
        capabilities = self._capabilities(entry, traversal.truncated)
        negative_test_statement = None
        if not test_paths:
            negative_test_statement = (
                "No represented TEST-root path reaches this subject in the current artifact."
            )
        reachability_fingerprint = (
            self.reachability_report.input_fingerprint
            if self.reachability_report is not None else None
        )
        traceability = CodeTraceability(
            self.snapshot_id,
            self.callable_index.input_fingerprint,
            self.code_graph.input_fingerprint,
            self.test_evidence.input_fingerprint,
            reachability_fingerprint,
        )
        summary = CodeTraversalSummary(
            CodeTraversalDirection.REVERSE_UPSTREAM,
            configuration.max_depth,
            configuration.max_nodes,
            len(traversal.paths),
            traversal.visited_edges,
            traversal.depth_histogram,
            traversal.truncated,
        )
        general_limitations = {
            *self.limitations,
            "Relationships are represented source evidence and do not prove runtime invocation.",
            "Runtime dispatch, reflection, dependency injection, generated wiring, and framework dispatch are not proven by PR159.",
            "Represented TEST reachability is not runtime test coverage or proof that a test executed.",
            "Absence of a represented TEST-root path cannot establish that code is untested.",
            "PR159 supports exact method and constructor subjects; type-level aggregation is deferred.",
        }
        if traversal.truncated:
            general_limitations.add(
                "Reverse upstream traversal was truncated at a deterministic query bound."
            )
        return JavaCodeIntelligenceReport(
            self._subject(entry),
            caller_high,
            caller_possible,
            caller_references,
            callee_high,
            callee_possible,
            callee_references,
            direct_paths,
            transitive_paths,
            direct_test_callers,
            high_test_paths,
            possible_test_paths,
            limitations,
            capabilities,
            summary,
            traceability,
            negative_test_statement,
            tuple(general_limitations),
            direct_caller_conservative_groups=caller_possible_groups,
            direct_callee_conservative_groups=callee_possible_groups,
        )

    def _reverse_traversal(
        self,
        subject_id: str,
        configuration: CodeIntelligenceConfiguration,
    ) -> _TraversalResult:
        paths: dict[str, tuple[CodeCallRelationship, ...]] = {subject_id: ()}
        queue: deque[str] = deque((subject_id,))
        histogram: Counter[int] = Counter()
        visited_edges = 0
        truncated = False
        stop = False
        while queue and not stop:
            current = queue.popleft()
            current_steps = paths[current]
            depth = len(current_steps)
            eligible = tuple(
                edge for edge in self._incoming.get(current, ())
                if edge.kind in _EXECUTION_KINDS
            )
            if depth >= configuration.max_depth:
                if any(edge.caller_subject_id not in paths for edge in eligible):
                    truncated = True
                continue
            for edge in eligible:
                visited_edges += 1
                caller = edge.caller_subject_id
                if caller in paths:
                    continue
                if len(paths) >= configuration.max_nodes:
                    truncated = True
                    stop = True
                    break
                step = self._relationship(
                    edge, CodeRelationshipRole.UPSTREAM_CONSUMER_OF_SUBJECT,
                )
                caller_steps = (step, *current_steps)
                paths[caller] = caller_steps
                histogram[len(caller_steps)] += 1
                queue.append(caller)
        return _TraversalResult(
            paths,
            visited_edges,
            tuple(sorted(histogram.items())),
            truncated,
        )

    def _limitation_summaries(
        self,
        neighborhood: set[str],
        configuration: CodeIntelligenceConfiguration,
    ) -> tuple[CodeLimitationSummary, ...]:
        grouped: dict[str, list[CodeSiteEvidence]] = defaultdict(list)
        for caller in sorted(neighborhood):
            for site in self._sites_by_caller.get(caller, ()):
                categories = []
                if site.state is CallResolutionState.UNRESOLVED:
                    categories.append("unresolved_sites")
                elif site.state is CallResolutionState.EXTERNAL:
                    categories.append("external_sites")
                elif site.state is CallResolutionState.UNSUPPORTED:
                    categories.append("unsupported_sites")
                elif site.state is CallResolutionState.AMBIGUOUS:
                    categories.append("ambiguous_candidates")
                elif site.state is CallResolutionState.POLYMORPHIC:
                    categories.append("possible_dispatch_candidates")
                if site.request.invocation_kind is InvocationKind.METHOD_REFERENCE:
                    categories.append("method_references")
                for category in categories:
                    grouped[category].append(CodeSiteEvidence(
                        category,
                        caller,
                        site.evidence_id,
                        CodeSourceReference(
                            site.request.source_path,
                            site.request.source_range,
                        ),
                        site.request.invocation_kind.value,
                        site.limitations,
                    ))
        summaries = [
            CodeLimitationSummary(
                category,
                len(values),
                tuple(sorted(values))[: configuration.max_limitation_representatives],
            )
            for category, values in grouped.items()
        ]
        global_counts = {
            "callable_bodies_unavailable": self.code_graph.coverage.callable_bodies_unavailable,
            "call_extraction_failures": self.code_graph.coverage.extraction_failures,
            "unindexed_callables": self.callable_index.coverage.unindexed_callables,
            "omitted_callable_diagnostics": self.callable_index.coverage.omitted_diagnostic_count,
            "omitted_code_graph_diagnostics": self.code_graph.coverage.omitted_diagnostic_count,
        }
        summaries.extend(
            CodeLimitationSummary(category, count)
            for category, count in global_counts.items()
            if count
        )
        return tuple(sorted(summaries))

    def _capabilities(
        self,
        subject: CallableIndexEntry,
        traversal_truncated: bool,
    ) -> tuple[CodeCapability, ...]:
        call_coverage = self.code_graph.coverage
        call_partial = any((
            self.callable_index.coverage.unindexed_callables,
            call_coverage.callable_bodies_unavailable,
            call_coverage.extraction_failures,
            call_coverage.polymorphic_call_sites,
            call_coverage.ambiguous_call_sites,
            call_coverage.unresolved_call_sites,
            call_coverage.external_call_sites,
            call_coverage.unsupported_call_sites,
        ))
        call_limitations = (
            "Unavailable bodies or unresolved, external, unsupported, ambiguous, or polymorphic sites make represented Java call coverage partial.",
        ) if call_partial else ()

        project_test_records = tuple(
            record for record in self.test_evidence.records
            if self._entries[record.subject_id].project_id == subject.project_id
        )
        project_roots = tuple(item for item in project_test_records if item.is_root)
        test_partial = (
            not project_roots
            or any(not item.is_root for item in project_test_records)
        )
        test_limitations = []
        if not project_roots:
            test_limitations.append(
                "No represented TEST root is available for the subject's project."
            )
        if any(not item.is_root for item in project_test_records):
            test_limitations.append(
                "Some TEST-scoped callables could not be established as represented TEST roots."
            )
        test_limitations.append(
            "Represented TEST evidence does not prove runtime execution or behavioral coverage."
        )
        reachability_partial = call_partial or test_partial or traversal_truncated
        reachability_limitations = []
        if call_partial or test_partial:
            reachability_limitations.append(
                "Represented reachability inherits partial call or TEST-root producer coverage."
            )
        if traversal_truncated:
            reachability_limitations.append(
                "This query reached a deterministic reverse-traversal bound."
            )
        if self.reachability_report is None:
            reachability_partial = True
            reachability_limitations.append(
                "A compatible persisted PR131 reachability identity was unavailable."
            )
        return tuple(sorted((
            CodeCapability(
                "calls",
                CodeIntelligenceAvailability.PARTIAL
                if call_partial else CodeIntelligenceAvailability.AVAILABLE,
                ("moughorai.java-code-graph.v1", CODE_INTELLIGENCE_PRODUCER),
                call_limitations,
            ),
            CodeCapability(
                "tests",
                CodeIntelligenceAvailability.PARTIAL
                if test_partial else CodeIntelligenceAvailability.AVAILABLE,
                ("moughorai.java-test-evidence.v1", CODE_INTELLIGENCE_PRODUCER),
                tuple(test_limitations),
            ),
            CodeCapability(
                "reachability",
                CodeIntelligenceAvailability.PARTIAL
                if reachability_partial else CodeIntelligenceAvailability.AVAILABLE,
                (
                    "atlas-pr131/1",
                    "moughorai.java-code-graph.v1",
                    "moughorai.java-test-evidence.v1",
                    CODE_INTELLIGENCE_PRODUCER,
                ),
                tuple(reachability_limitations),
            ),
        ), key=lambda item: item.name))

    def _subject(self, entry: CallableIndexEntry) -> CodeSubject:
        return CodeSubject(
            entry.canonical_subject_id,
            entry.project_id,
            entry.identity.kind,
            entry.identity.owner_type,
            entry.identity.name,
            entry.identity.normalized_key,
            entry.source_classification,
            CodeSourceReference(entry.source.path, entry.source.declaration),
            entry.identity.limitations,
        )

    def _relationship(
        self,
        edge: CodeGraphEdge,
        role: CodeRelationshipRole,
    ) -> CodeCallRelationship:
        site = self._sites[edge.evidence_id]
        limitations = set(site.limitations)
        if edge.kind is CodeGraphEdgeKind.POSSIBLE_CALL_TARGET:
            limitations.add(
                "This edge is a conservative represented call candidate, not a resolved target."
            )
        elif edge.kind is CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET:
            limitations.add(
                "This edge is a conservative represented dispatch candidate, not a resolved runtime target."
            )
        elif edge.kind is CodeGraphEdgeKind.METHOD_REFERENCE:
            limitations.add(
                "A method reference is reported separately and does not establish execution impact."
            )
        confidence = (
            CodePathConfidence.METHOD_REFERENCE_ONLY
            if edge.kind is CodeGraphEdgeKind.METHOD_REFERENCE
            else CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
            if edge.kind in _HIGH_CONFIDENCE_KINDS
            else CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
        )
        return CodeCallRelationship(
            edge.caller_subject_id,
            edge.target_subject_id,
            role,
            edge.kind,
            edge.evidence_id,
            site.request.project_id,
            CodeSourceReference(
                site.request.source_path,
                site.request.source_range,
            ),
            confidence,
            tuple(limitations),
        )


def _edge_sort_key(edge: CodeGraphEdge) -> tuple[object, ...]:
    confidence_rank = (
        0 if edge.kind in _HIGH_CONFIDENCE_KINDS
        else 1 if edge.kind in _CONSERVATIVE_KINDS
        else 2
    )
    return (
        confidence_rank,
        edge.caller_subject_id,
        edge.target_subject_id,
        edge.kind.value,
        edge.evidence_id,
    )


def _site_sort_key(site: CallSiteEvidence) -> tuple[object, ...]:
    request = site.request
    return (
        request.source_path,
        request.source_range.start,
        request.source_range.end,
        request.caller_subject_id,
        site.evidence_id,
    )


def _path_confidence(
    steps: Sequence[CodeCallRelationship],
) -> CodePathConfidence:
    return (
        CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
        if any(
            item.confidence is CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH
            for item in steps
        )
        else CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH
    )


def _path_limitations(
    steps: Sequence[CodeCallRelationship],
) -> tuple[str, ...]:
    return tuple(sorted({
        limitation for item in steps for limitation in item.limitations
    }))


def _bounded_relationships(
    values,
    maximum: int,
) -> BoundedRelationships:
    items = tuple(sorted(values))
    return BoundedRelationships(len(items), items[:maximum])


def _bounded_ambiguous_call_groups(
    values,
    sites: Mapping[str, CallSiteEvidence],
    maximum_groups: int,
    maximum_candidates: int,
) -> BoundedAmbiguousCallGroups:
    relationships = tuple(values)
    grouped: dict[tuple[object, ...], list[CodeCallRelationship]] = defaultdict(list)
    for item in relationships:
        site = sites[item.producer_evidence_id]
        key = (
            item.canonical_source,
            item.project,
            item.location,
            item.producer_evidence_id,
            site.request.invocation_kind,
            site.state,
            item.subject_relative_role,
        )
        grouped[key].append(item)

    groups = []
    for key, projections in grouped.items():
        (
            canonical_source,
            project,
            location,
            evidence_id,
            invocation_kind,
            resolution_state,
            role,
        ) = key
        candidates = tuple(sorted({
            item.canonical_target for item in projections
        }))
        limitations = {
            limitation
            for item in projections
            for limitation in item.limitations
        }
        limitations.add(
            "Multiple represented targets may remain legal at this source call site; no candidate is proven as the runtime target."
        )
        groups.append(AmbiguousCallGroup(
            canonical_source,
            project,
            location,
            evidence_id,
            invocation_kind,
            resolution_state,
            role,
            CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH,
            tuple(item.edge_kind for item in projections),
            len(candidates),
            candidates[:maximum_candidates],
            tuple(limitations),
        ))
    ordered = tuple(sorted(groups, key=lambda item: item.sort_key))
    return BoundedAmbiguousCallGroups(
        len(ordered),
        len(relationships),
        ordered[:maximum_groups],
    )


def _bounded_paths(values, maximum: int) -> BoundedPaths:
    items = tuple(sorted(values, key=lambda item: (
        item.depth,
        0 if item.confidence
        is CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH else 1,
        item.consumer_subject_id,
        item.producer_evidence_ids,
    )))
    return BoundedPaths(len(items), items[:maximum])
