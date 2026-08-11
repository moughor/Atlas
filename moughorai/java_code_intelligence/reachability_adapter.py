'''Non-persistent PR157-to-PR131 represented-call reachability adapter.'''

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import json

from .call_sites import CallResolutionState, InvocationKind
from .code_graph import CodeGraphEdgeKind, JavaCodeGraph
from .models import JavaCallableIndex, SourceClassification
from .test_evidence import JavaTestEvidence, RepresentedTestCallable


@dataclass(frozen=True, order=True, slots=True)
class JavaCallReachabilityRelation:
    source: str
    target: str
    kind: str
    evidence_id: str
    edge_kind: CodeGraphEdgeKind
    project: str
    limitations: tuple[str, ...]
    reliability: float
    specificity: float


@dataclass(frozen=True, order=True, slots=True)
class JavaReachabilityProjectCoverage:
    project: str
    represented_callables: int
    callables_with_bodies: int
    bodies_unavailable: int
    represented_test_callables: int
    represented_test_roots: int
    total_call_sites: int
    resolved_call_sites: int
    polymorphic_call_sites: int
    ambiguous_call_sites: int
    unresolved_call_sites: int
    external_call_sites: int
    unsupported_call_sites: int
    resolved_edges: int
    possible_edges: int
    method_references: int
    direct_test_to_production_calls: int
    retained_extraction_diagnostics: int

    @property
    def has_usable_call_evidence(self) -> bool:
        return self.resolved_edges + self.possible_edges > 0


@dataclass(frozen=True, slots=True)
class JavaReachabilityCoverage:
    represented_callables: int
    callables_with_bodies: int
    bodies_unavailable: int
    extraction_failures: int
    total_call_sites: int
    resolved_call_sites: int
    polymorphic_call_sites: int
    ambiguous_call_sites: int
    unresolved_call_sites: int
    external_call_sites: int
    unsupported_call_sites: int
    represented_test_callables: int
    represented_test_roots: int
    production_root_candidates: int
    resolved_edges: int
    possible_edges: int
    method_references: int
    direct_test_to_production_calls: int
    projects_with_test_roots: int
    projects_without_test_roots: int
    projects_with_usable_call_evidence: int
    projects_without_usable_call_evidence: int


@dataclass(frozen=True, slots=True)
class JavaReachabilityAdapter:
    '''A bounded view over authoritative PR156/PR157 artifacts.'''

    callable_index: JavaCallableIndex
    code_graph: JavaCodeGraph
    test_evidence: JavaTestEvidence
    projects: tuple[JavaReachabilityProjectCoverage, ...]
    coverage: JavaReachabilityCoverage
    input_fingerprint: str

    def __post_init__(self) -> None:
        if (
            self.code_graph.callable_index_fingerprint
            != self.callable_index.input_fingerprint
            or self.test_evidence.callable_index_fingerprint
            != self.callable_index.input_fingerprint
        ):
            raise ValueError('Java reachability input bindings are inconsistent')
        object.__setattr__(self, 'projects', tuple(sorted(self.projects)))
        if (
            not self.input_fingerprint.startswith('java-reachability-input:')
            or len(self.input_fingerprint) != 88
        ):
            raise ValueError('Java reachability input fingerprint is malformed')

    @property
    def roots(self) -> tuple[RepresentedTestCallable, ...]:
        return self.test_evidence.roots

    def eligible_relations(self) -> Iterator[JavaCallReachabilityRelation]:
        '''Project eligible PR157 edges without copying the complete graph.'''

        entries = {
            item.canonical_subject_id: item
            for item in self.callable_index.entries
        }
        sites = {item.evidence_id: item for item in self.code_graph.call_sites}
        for edge in self.code_graph.edges:
            if edge.kind is CodeGraphEdgeKind.METHOD_REFERENCE:
                continue
            site = sites[edge.evidence_id]
            if edge.kind is CodeGraphEdgeKind.RESOLVED_DIRECT_CALL:
                kind = 'calls'
                limitations = site.limitations
                reliability, specificity = 0.98, 1.0
            elif edge.kind is CodeGraphEdgeKind.CONSTRUCTOR_CALL:
                kind = 'constructor'
                limitations = site.limitations
                reliability, specificity = 0.98, 1.0
            elif edge.kind is CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET:
                kind = 'possible_dispatch'
                limitations = tuple(sorted(set((
                    *site.limitations,
                    'This path step is a conservative represented dispatch candidate, not a resolved runtime target.',
                ))))
                reliability, specificity = 0.72, 0.72
            elif edge.kind is CodeGraphEdgeKind.POSSIBLE_CALL_TARGET:
                kind = 'possible_call'
                limitations = tuple(sorted(set((
                    *site.limitations,
                    'This path step is a conservative represented call candidate, not a resolved target.',
                ))))
                reliability, specificity = 0.68, 0.68
            else:  # pragma: no cover - exhaustive enum guard
                continue
            yield JavaCallReachabilityRelation(
                edge.caller_subject_id,
                edge.target_subject_id,
                kind,
                edge.evidence_id,
                edge.kind,
                entries[edge.caller_subject_id].project_id,
                limitations,
                reliability,
                specificity,
            )


def build_java_reachability_adapter(
    callable_index: JavaCallableIndex,
    code_graph: JavaCodeGraph,
    test_evidence: JavaTestEvidence,
) -> JavaReachabilityAdapter:
    if not isinstance(callable_index, JavaCallableIndex):
        raise TypeError('authoritative callable index is required')
    if not isinstance(code_graph, JavaCodeGraph):
        raise TypeError('authoritative Java code graph is required')
    if not isinstance(test_evidence, JavaTestEvidence):
        raise TypeError('authoritative Java test evidence is required')
    if (
        code_graph.callable_index_fingerprint != callable_index.input_fingerprint
        or test_evidence.callable_index_fingerprint
        != callable_index.input_fingerprint
    ):
        raise ValueError('PR156/PR157/PR158 artifact bindings are inconsistent')

    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    test_records = {item.subject_id: item for item in test_evidence.records}
    project_entries: dict[str, list[object]] = defaultdict(list)
    for entry in callable_index.entries:
        project_entries[entry.project_id].append(entry)
    project_sites: dict[str, list[object]] = defaultdict(list)
    for site in code_graph.call_sites:
        project_sites[entries[site.request.caller_subject_id].project_id].append(site)
    project_edges: dict[str, list[object]] = defaultdict(list)
    for edge in code_graph.edges:
        project_edges[entries[edge.caller_subject_id].project_id].append(edge)
    diagnostics = Counter(item.project_id for item in code_graph.diagnostics)

    projects: list[JavaReachabilityProjectCoverage] = []
    for project in sorted(project_entries):
        represented = tuple(project_entries[project])
        sites = tuple(project_sites.get(project, ()))
        edges = tuple(project_edges.get(project, ()))
        states = Counter(item.state for item in sites)
        test_subjects = {
            item.canonical_subject_id for item in represented
            if item.source_classification is SourceClassification.TEST
        }
        test_roots = sum(
            record.is_root for subject in test_subjects
            if (record := test_records.get(subject)) is not None
        )
        direct_test_to_production = sum(
            edge.kind is not CodeGraphEdgeKind.METHOD_REFERENCE
            and entries[edge.caller_subject_id].source_classification
            is SourceClassification.TEST
            and entries[edge.target_subject_id].source_classification
            is SourceClassification.PRODUCTION
            for edge in edges
        )
        projects.append(JavaReachabilityProjectCoverage(
            project,
            len(represented),
            sum(item.source.body is not None for item in represented),
            sum(item.source.body is None for item in represented),
            len(test_subjects),
            test_roots,
            len(sites),
            states[CallResolutionState.RESOLVED],
            states[CallResolutionState.POLYMORPHIC],
            states[CallResolutionState.AMBIGUOUS],
            states[CallResolutionState.UNRESOLVED],
            states[CallResolutionState.EXTERNAL],
            states[CallResolutionState.UNSUPPORTED],
            sum(edge.kind in {
                CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
                CodeGraphEdgeKind.CONSTRUCTOR_CALL,
            } for edge in edges),
            sum(edge.kind in {
                CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
                CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
            } for edge in edges),
            sum(
                site.request.invocation_kind is InvocationKind.METHOD_REFERENCE
                for site in sites
            ),
            direct_test_to_production,
            diagnostics[project],
        ))

    resolved_edges = sum(
        edge.kind in {
            CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
            CodeGraphEdgeKind.CONSTRUCTOR_CALL,
        }
        for edge in code_graph.edges
    )
    possible_edges = sum(
        edge.kind in {
            CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
            CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
        }
        for edge in code_graph.edges
    )
    project_tuple = tuple(sorted(projects))
    coverage = JavaReachabilityCoverage(
        callable_index.coverage.represented_callables,
        code_graph.coverage.callable_bodies_examined,
        code_graph.coverage.callable_bodies_unavailable,
        code_graph.coverage.extraction_failures,
        code_graph.coverage.total_call_sites,
        code_graph.coverage.resolved_call_sites,
        code_graph.coverage.polymorphic_call_sites,
        code_graph.coverage.ambiguous_call_sites,
        code_graph.coverage.unresolved_call_sites,
        code_graph.coverage.external_call_sites,
        code_graph.coverage.unsupported_call_sites,
        test_evidence.coverage.represented_test_callables,
        test_evidence.coverage.represented_test_roots,
        test_evidence.coverage.production_root_candidates,
        resolved_edges,
        possible_edges,
        code_graph.coverage.method_references,
        sum(item.direct_test_to_production_calls for item in project_tuple),
        sum(item.represented_test_roots > 0 for item in project_tuple),
        sum(item.represented_test_roots == 0 for item in project_tuple),
        sum(item.has_usable_call_evidence for item in project_tuple),
        sum(not item.has_usable_call_evidence for item in project_tuple),
    )
    coverage_payload = {
        name: getattr(coverage, name)
        for name in JavaReachabilityCoverage.__dataclass_fields__
    }
    digest = hashlib.sha256(json.dumps({
        'callable_index_fingerprint': callable_index.input_fingerprint,
        'code_graph_fingerprint': code_graph.input_fingerprint,
        'test_evidence_fingerprint': test_evidence.input_fingerprint,
        'coverage': coverage_payload,
    }, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode(
        'utf-8'
    )).hexdigest()
    return JavaReachabilityAdapter(
        callable_index,
        code_graph,
        test_evidence,
        project_tuple,
        coverage,
        f'java-reachability-input:{digest}',
    )
