'''Compact deterministic represented Java direct-call graph artifact.'''

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
    InvocationKind,
    ReceiverKind,
)
from .models import (
    CallableIndexEntry,
    JavaCallableIndex,
    PathScope,
    SourcePosition,
    SourceRange,
)


JAVA_CODE_GRAPH_FORMAT = 'moughorai.java-code-graph.v1'
JAVA_CODE_GRAPH_PRODUCER = 'atlas-pr157/1'
JAVA_CODE_GRAPH_SCHEMA_VERSION = 1
JAVA_CODE_GRAPH_ENCODING = 'canonical-row-json-v1'
MAXIMUM_CODE_GRAPH_DIAGNOSTICS = 4_096

_INVOCATION_KINDS = (
    InvocationKind.METHOD_INVOCATION,
    InvocationKind.CONSTRUCTOR_INVOCATION,
    InvocationKind.METHOD_REFERENCE,
)
_RECEIVER_KINDS = (
    ReceiverKind.UNQUALIFIED,
    ReceiverKind.TYPE,
    ReceiverKind.INSTANCE,
    ReceiverKind.THIS,
    ReceiverKind.SUPER,
    ReceiverKind.STATIC_IMPORT,
    ReceiverKind.WILDCARD_STATIC_IMPORT,
    ReceiverKind.CONSTRUCTOR,
    ReceiverKind.UNKNOWN,
)
_RESOLUTION_STATES = (
    CallResolutionState.RESOLVED,
    CallResolutionState.POLYMORPHIC,
    CallResolutionState.AMBIGUOUS,
    CallResolutionState.UNRESOLVED,
    CallResolutionState.EXTERNAL,
    CallResolutionState.UNSUPPORTED,
)


class CodeGraphEdgeKind(str, Enum):
    RESOLVED_DIRECT_CALL = 'resolved_direct_call'
    POSSIBLE_CALL_TARGET = 'possible_call_target'
    POSSIBLE_DISPATCH_TARGET = 'possible_dispatch_target'
    CONSTRUCTOR_CALL = 'constructor_call'
    METHOD_REFERENCE = 'method_reference'


_EDGE_KINDS = (
    CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
    CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
    CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
    CodeGraphEdgeKind.CONSTRUCTOR_CALL,
    CodeGraphEdgeKind.METHOD_REFERENCE,
)


@dataclass(frozen=True, order=True, slots=True)
class CodeGraphEdge:
    caller_subject_id: str
    target_subject_id: str
    evidence_id: str
    kind: CodeGraphEdgeKind

    def __post_init__(self) -> None:
        if not self.caller_subject_id or not self.target_subject_id:
            raise ValueError('code-graph edge subjects must be present')
        if not self.evidence_id.startswith('evidence:'):
            raise ValueError('code-graph edge evidence ID is malformed')
        if not isinstance(self.kind, CodeGraphEdgeKind):
            raise TypeError('code-graph edge kind is invalid')

    def to_dict(self) -> dict[str, str]:
        return {
            'caller_subject_id': self.caller_subject_id,
            'target_subject_id': self.target_subject_id,
            'evidence_id': self.evidence_id,
            'kind': self.kind.value,
        }


@dataclass(frozen=True, order=True, slots=True)
class CodeGraphDiagnostic:
    code: str
    message: str
    project_id: str
    caller_subject_id: str | None = None
    evidence_id: str | None = None
    source_path: str | None = None
    source_range: SourceRange | None = None
    mandatory: bool = False

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.code, 'diagnostic code', 96),
            (self.message, 'diagnostic message', 512),
            (self.project_id, 'diagnostic project', 256),
        ):
            if (
                not isinstance(value, str) or not value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f'{label} is invalid')
        if self.caller_subject_id is not None and not self.caller_subject_id:
            raise ValueError('diagnostic caller ID is invalid')
        if self.evidence_id is not None and not self.evidence_id.startswith(
            'evidence:'
        ):
            raise ValueError('diagnostic evidence ID is malformed')
        if (self.source_path is None) != (self.source_range is None):
            raise ValueError(
                'diagnostic source path and range must be present together'
            )
        if self.mandatory and any(item is None for item in (
            self.caller_subject_id,
            self.evidence_id,
            self.source_path,
            self.source_range,
        )):
            raise ValueError(
                'mandatory diagnostic must identify its call site and source'
            )
        if self.source_path is not None:
            CallSiteRequest(
                self.caller_subject_id or 'method:diagnostic',
                'java-callable:v1:diagnostic#diagnostic()',
                self.project_id,
                self.source_path,
                self.source_range or SourceRange.from_dict({
                    'start': {'line': 1, 'column': 1},
                    'end': {'line': 1, 'column': 1},
                }),
                InvocationKind.METHOD_INVOCATION,
                ReceiverKind.UNKNOWN,
                '<diagnostic>',
                None,
                (),
                (),
            )
        if self.source_range is not None and not isinstance(
            self.source_range, SourceRange
        ):
            raise TypeError('diagnostic source range is invalid')
        if not isinstance(self.mandatory, bool):
            raise TypeError('diagnostic mandatory flag is invalid')

    def to_dict(self) -> dict[str, object]:
        return {
            'code': self.code,
            'message': self.message,
            'project_id': self.project_id,
            'caller_subject_id': self.caller_subject_id,
            'evidence_id': self.evidence_id,
            'source_path': self.source_path,
            'source_range': (
                self.source_range.to_dict()
                if self.source_range is not None else None
            ),
            'mandatory': self.mandatory,
        }


@dataclass(frozen=True, slots=True)
class CodeGraphCoverage:
    callable_bodies_examined: int
    callable_bodies_unavailable: int
    extraction_failures: int
    total_call_sites: int
    resolved_call_sites: int
    polymorphic_call_sites: int
    ambiguous_call_sites: int
    unresolved_call_sites: int
    external_call_sites: int
    unsupported_call_sites: int
    constructor_calls: int
    method_references: int
    diagnostic_count: int
    omitted_diagnostic_count: int = 0

    def __post_init__(self) -> None:
        values = tuple(self.to_dict().values())
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ValueError('code-graph coverage counts must be non-negative')
        if sum((
            self.resolved_call_sites,
            self.polymorphic_call_sites,
            self.ambiguous_call_sites,
            self.unresolved_call_sites,
            self.external_call_sites,
            self.unsupported_call_sites,
        )) != self.total_call_sites:
            raise ValueError('code-graph call-site state accounting is inconsistent')

    def to_dict(self) -> dict[str, int]:
        return {
            'callable_bodies_examined': self.callable_bodies_examined,
            'callable_bodies_unavailable': self.callable_bodies_unavailable,
            'extraction_failures': self.extraction_failures,
            'total_call_sites': self.total_call_sites,
            'resolved_call_sites': self.resolved_call_sites,
            'polymorphic_call_sites': self.polymorphic_call_sites,
            'ambiguous_call_sites': self.ambiguous_call_sites,
            'unresolved_call_sites': self.unresolved_call_sites,
            'external_call_sites': self.external_call_sites,
            'unsupported_call_sites': self.unsupported_call_sites,
            'constructor_calls': self.constructor_calls,
            'method_references': self.method_references,
            'diagnostic_count': self.diagnostic_count,
            'omitted_diagnostic_count': self.omitted_diagnostic_count,
        }


@dataclass(frozen=True, slots=True)
class JavaCodeGraph:
    lineage: str
    path_scope: PathScope
    callable_index_fingerprint: str
    call_sites: tuple[CallSiteEvidence, ...]
    edges: tuple[CodeGraphEdge, ...]
    diagnostics: tuple[CodeGraphDiagnostic, ...]
    coverage: CodeGraphCoverage
    digest: str
    input_fingerprint: str
    producer_version: str = JAVA_CODE_GRAPH_PRODUCER
    schema_version: int = JAVA_CODE_GRAPH_SCHEMA_VERSION
    format: str = JAVA_CODE_GRAPH_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, str) or not self.lineage:
            raise ValueError('code-graph lineage is invalid')
        if not isinstance(self.path_scope, PathScope):
            raise TypeError('code-graph path scope is invalid')
        if (
            not isinstance(self.callable_index_fingerprint, str)
            or not self.callable_index_fingerprint.startswith(
                'java-callable-index:'
            )
            or len(self.callable_index_fingerprint) != 84
        ):
            raise ValueError('callable-index binding is malformed')
        call_sites = tuple(sorted(self.call_sites, key=_site_sort_key))
        edges = tuple(sorted(set(self.edges), key=_edge_sort_key))
        diagnostics = tuple(
            sorted(set(self.diagnostics), key=_diagnostic_sort_key)
        )
        if len({item.evidence_id for item in call_sites}) != len(call_sites):
            raise ValueError('code-graph evidence IDs must be unique')
        evidence = {item.evidence_id for item in call_sites}
        if any(item.evidence_id not in evidence for item in edges):
            raise ValueError('code-graph edge references unknown evidence')
        if self.coverage.total_call_sites != len(call_sites):
            raise ValueError('code-graph call-site count is inconsistent')
        if self.coverage.diagnostic_count != len(diagnostics):
            raise ValueError('code-graph diagnostic count is inconsistent')
        if any(item.mandatory for item in diagnostics):
            raise ValueError('mandatory uncertain-site diagnostics are forbidden')
        if any(
            item.evidence_id is not None and item.evidence_id not in evidence
            for item in diagnostics
        ):
            raise ValueError('code-graph diagnostic references unknown evidence')
        _validate_site_accounting(call_sites, self.coverage)
        if edges != _edges(call_sites):
            raise ValueError('code-graph edges are not the exact site projection')
        if (
            not isinstance(self.digest, str) or len(self.digest) != 64
            or self.input_fingerprint != f'java-code-graph:{self.digest}'
        ):
            raise ValueError('code-graph digest or fingerprint is malformed')
        if (
            self.format != JAVA_CODE_GRAPH_FORMAT
            or self.schema_version != JAVA_CODE_GRAPH_SCHEMA_VERSION
            or self.producer_version != JAVA_CODE_GRAPH_PRODUCER
        ):
            raise ValueError('unsupported Java code-graph schema')
        object.__setattr__(self, 'call_sites', call_sites)
        object.__setattr__(self, 'edges', edges)
        object.__setattr__(self, 'diagnostics', diagnostics)

    def to_dict(self) -> dict[str, object]:
        return code_graph_to_dict(self)


def create_code_graph(
    *,
    lineage: str,
    path_scope: PathScope,
    callable_index: JavaCallableIndex,
    call_sites: Iterable[CallSiteEvidence],
    diagnostics: Iterable[CodeGraphDiagnostic] = (),
    callable_bodies_examined: int,
    callable_bodies_unavailable: int,
    extraction_failures: int,
    omitted_diagnostic_count: int = 0,
) -> JavaCodeGraph:
    graph, _ = _create_code_graph_with_projection(
        lineage=lineage,
        path_scope=path_scope,
        callable_index=callable_index,
        call_sites=call_sites,
        diagnostics=diagnostics,
        callable_bodies_examined=callable_bodies_examined,
        callable_bodies_unavailable=callable_bodies_unavailable,
        extraction_failures=extraction_failures,
        omitted_diagnostic_count=omitted_diagnostic_count,
    )
    return graph


def _create_code_graph_with_projection(
    *,
    lineage: str,
    path_scope: PathScope,
    callable_index: JavaCallableIndex,
    call_sites: Iterable[CallSiteEvidence],
    diagnostics: Iterable[CodeGraphDiagnostic] = (),
    callable_bodies_examined: int,
    callable_bodies_unavailable: int,
    extraction_failures: int,
    omitted_diagnostic_count: int = 0,
) -> tuple[JavaCodeGraph, dict[str, object]]:
    if not isinstance(callable_index, JavaCallableIndex):
        raise TypeError('authoritative callable index is required')
    sites = tuple(sorted(set(call_sites), key=_site_sort_key))
    diagnostic_values = tuple(diagnostics)
    _validate_callable_binding(sites, diagnostic_values, callable_index)
    unique_diagnostics = tuple(sorted(
        set(diagnostic_values), key=_diagnostic_sort_key,
    ))
    retained = unique_diagnostics[:MAXIMUM_CODE_GRAPH_DIAGNOSTICS]
    omitted = (
        omitted_diagnostic_count
        + len(unique_diagnostics)
        - len(retained)
    )
    edges = _edges(sites)
    states = Counter(item.state for item in sites)
    coverage = CodeGraphCoverage(
        callable_bodies_examined,
        callable_bodies_unavailable,
        extraction_failures,
        len(sites),
        states[CallResolutionState.RESOLVED],
        states[CallResolutionState.POLYMORPHIC],
        states[CallResolutionState.AMBIGUOUS],
        states[CallResolutionState.UNRESOLVED],
        states[CallResolutionState.EXTERNAL],
        states[CallResolutionState.UNSUPPORTED],
        sum(
            item.request.invocation_kind
            is InvocationKind.CONSTRUCTOR_INVOCATION
            for item in sites
        ),
        sum(
            item.request.invocation_kind is InvocationKind.METHOD_REFERENCE
            for item in sites
        ),
        len(retained),
        omitted,
    )
    payload = _compact_projection(
        lineage=lineage,
        path_scope=path_scope,
        callable_index_fingerprint=callable_index.input_fingerprint,
        call_sites=sites,
        edges=edges,
        diagnostics=retained,
        coverage=coverage,
    )
    digest = _digest(payload)
    graph = JavaCodeGraph(
        lineage,
        path_scope,
        callable_index.input_fingerprint,
        sites,
        edges,
        retained,
        coverage,
        digest,
        f'java-code-graph:{digest}',
    )
    return graph, payload


def code_graph_to_dict(value: JavaCodeGraph) -> dict[str, object]:
    if not isinstance(value, JavaCodeGraph):
        raise TypeError('Java code graph is invalid')
    projection = _compact_projection(
        lineage=value.lineage,
        path_scope=value.path_scope,
        callable_index_fingerprint=value.callable_index_fingerprint,
        call_sites=value.call_sites,
        edges=value.edges,
        diagnostics=value.diagnostics,
        coverage=value.coverage,
    )
    if _digest(projection) != value.digest:
        raise ValueError('Java code graph digest is inconsistent')
    return _code_graph_envelope(value, projection)


def _code_graph_envelope(
    value: JavaCodeGraph,
    projection: Mapping[str, object],
) -> dict[str, object]:
    return {
        'format': value.format,
        'schema_version': value.schema_version,
        'producer_version': value.producer_version,
        **projection,
        'digest': value.digest,
        'input_fingerprint': value.input_fingerprint,
    }


def code_graph_from_dict(
    value: object,
    callable_index: JavaCallableIndex,
) -> JavaCodeGraph:
    if not isinstance(callable_index, JavaCallableIndex):
        raise TypeError('authoritative callable index is required')
    root = _mapping(value, 'Java code graph')
    _exact(root, {
        'format', 'schema_version', 'producer_version', 'encoding',
        'lineage', 'path_scope', 'callable_index_fingerprint', 'subjects',
        'files', 'lexical', 'reasons', 'diagnostic_codes',
        'diagnostic_messages', 'diagnostic_projects', 'call_sites', 'edges',
        'diagnostics', 'coverage', 'digest', 'input_fingerprint',
    }, 'Java code graph')
    if (
        root['format'] != JAVA_CODE_GRAPH_FORMAT
        or root['producer_version'] != JAVA_CODE_GRAPH_PRODUCER
        or root['schema_version'] != JAVA_CODE_GRAPH_SCHEMA_VERSION
        or root['encoding'] != JAVA_CODE_GRAPH_ENCODING
    ):
        raise ValueError('unsupported Java code-graph schema or encoding')
    binding = _string(
        root['callable_index_fingerprint'], 'callable-index fingerprint',
    )
    if binding != callable_index.input_fingerprint:
        raise ValueError('Java code graph callable-index binding is inconsistent')

    subjects = _table(root['subjects'], 'subject table')
    files = _table(root['files'], 'file table')
    lexical = _table(root['lexical'], 'lexical table')
    reasons = _table(root['reasons'], 'reason table')
    diagnostic_codes = _table(
        root['diagnostic_codes'], 'diagnostic code table',
    )
    diagnostic_messages = _table(
        root['diagnostic_messages'], 'diagnostic message table',
    )
    diagnostic_projects = _table(
        root['diagnostic_projects'], 'diagnostic project table',
    )
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    if any(subject not in entries for subject in subjects):
        raise ValueError('subject table references an unknown callable')
    for path in files:
        _validate_relative_path(path)

    sites = tuple(
        _call_site_row(
            _row(item, 'call-site row'), subjects, files, lexical, reasons,
            entries,
        )
        for item in _array(root['call_sites'], 'call-site rows')
    )
    if len({item.evidence_id for item in sites}) != len(sites):
        raise ValueError('duplicate call-site evidence IDs are forbidden')
    edges = tuple(
        _edge_row(_row(item, 'edge row'), sites, subjects)
        for item in _array(root['edges'], 'edge rows')
    )
    diagnostics = tuple(
        _diagnostic_row(
            _row(item, 'diagnostic row'), subjects, files,
            diagnostic_codes, diagnostic_messages, diagnostic_projects,
            sites,
        )
        for item in _array(root['diagnostics'], 'diagnostic rows')
    )
    coverage = _coverage(root['coverage'])
    rebuilt, projection = _create_code_graph_with_projection(
        lineage=_string(root['lineage'], 'lineage'),
        path_scope=PathScope(_string(root['path_scope'], 'path scope')),
        callable_index=callable_index,
        call_sites=sites,
        diagnostics=diagnostics,
        callable_bodies_examined=coverage.callable_bodies_examined,
        callable_bodies_unavailable=coverage.callable_bodies_unavailable,
        extraction_failures=coverage.extraction_failures,
        omitted_diagnostic_count=coverage.omitted_diagnostic_count,
    )
    if _code_graph_envelope(rebuilt, projection) != dict(root):
        raise ValueError(
            'Java code graph digest, ordering, tables, or coverage is inconsistent'
        )
    if (
        edges != rebuilt.edges
        or len(edges) != len(set(edges))
    ):
        raise ValueError('persisted code-graph edges are inconsistent')
    return rebuilt


def _compact_projection(
    *,
    lineage: str,
    path_scope: PathScope,
    callable_index_fingerprint: str,
    call_sites: Sequence[CallSiteEvidence],
    edges: Sequence[CodeGraphEdge],
    diagnostics: Sequence[CodeGraphDiagnostic],
    coverage: CodeGraphCoverage,
) -> dict[str, object]:
    subject_values: set[str] = set()
    file_values: set[str] = set()
    lexical_values: set[str] = set()
    reason_values: set[str] = set()
    for site in call_sites:
        request = site.request
        subject_values.add(request.caller_subject_id)
        subject_values.update(item for item in (
            site.target_subject_id,
            site.declared_target_id,
            *site.candidate_target_ids,
        ) if item is not None)
        file_values.add(request.source_path)
        lexical_values.add(request.member_name)
        if request.receiver is not None:
            lexical_values.add(request.receiver)
        lexical_values.update(request.owner_type_hints)
        lexical_values.update(request.argument_hints)
        reason_values.update(request.limitations)
        reason_values.update(site.limitations)
    for diagnostic in diagnostics:
        if diagnostic.caller_subject_id is not None:
            subject_values.add(diagnostic.caller_subject_id)
        if diagnostic.source_path is not None:
            file_values.add(diagnostic.source_path)

    subjects = tuple(sorted(subject_values))
    files = tuple(sorted(file_values))
    lexical = tuple(sorted(lexical_values))
    reasons = tuple(sorted(reason_values))
    diagnostic_codes = tuple(sorted({item.code for item in diagnostics}))
    diagnostic_messages = tuple(sorted({item.message for item in diagnostics}))
    diagnostic_projects = tuple(sorted({item.project_id for item in diagnostics}))
    subject_ref = _references(subjects)
    file_ref = _references(files)
    lexical_ref = _references(lexical)
    reason_ref = _references(reasons)
    code_ref = _references(diagnostic_codes)
    message_ref = _references(diagnostic_messages)
    project_ref = _references(diagnostic_projects)
    site_ref = {
        item.evidence_id: index for index, item in enumerate(call_sites)
    }
    return {
        'encoding': JAVA_CODE_GRAPH_ENCODING,
        'lineage': lineage,
        'path_scope': path_scope.value,
        'callable_index_fingerprint': callable_index_fingerprint,
        'subjects': list(subjects),
        'files': list(files),
        'lexical': list(lexical),
        'reasons': list(reasons),
        'diagnostic_codes': list(diagnostic_codes),
        'diagnostic_messages': list(diagnostic_messages),
        'diagnostic_projects': list(diagnostic_projects),
        'call_sites': [
            _canonical_row(_site_row(
                item, subject_ref, file_ref, lexical_ref, reason_ref,
            ))
            for item in call_sites
        ],
        'edges': [
            _canonical_row([
                site_ref[item.evidence_id],
                subject_ref[item.target_subject_id],
                _EDGE_KINDS.index(item.kind),
            ])
            for item in edges
        ],
        'diagnostics': [
            _canonical_row(_diagnostic_compact_row(
                item, subject_ref, file_ref, code_ref, message_ref,
                project_ref, site_ref,
            ))
            for item in diagnostics
        ],
        'coverage': coverage.to_dict(),
    }


def _site_row(
    site: CallSiteEvidence,
    subjects: Mapping[str, int],
    files: Mapping[str, int],
    lexical: Mapping[str, int],
    reasons: Mapping[str, int],
) -> list[object]:
    request = site.request
    span = request.source_range
    return [
        subjects[request.caller_subject_id],
        files[request.source_path],
        span.start.line,
        span.start.column,
        span.end.line,
        span.end.column,
        _INVOCATION_KINDS.index(request.invocation_kind),
        _RECEIVER_KINDS.index(request.receiver_kind),
        lexical[request.member_name],
        lexical[request.receiver] if request.receiver is not None else -1,
        [lexical[item] for item in request.owner_type_hints],
        [lexical[item] for item in request.argument_hints],
        [reasons[item] for item in request.limitations],
        _RESOLUTION_STATES.index(site.state),
        subjects[site.target_subject_id]
        if site.target_subject_id is not None else -1,
        subjects[site.declared_target_id]
        if site.declared_target_id is not None else -1,
        [subjects[item] for item in site.candidate_target_ids],
        [reasons[item] for item in site.limitations],
        site.evidence_id,
    ]


def _diagnostic_compact_row(
    diagnostic: CodeGraphDiagnostic,
    subjects: Mapping[str, int],
    files: Mapping[str, int],
    codes: Mapping[str, int],
    messages: Mapping[str, int],
    projects: Mapping[str, int],
    sites: Mapping[str, int],
) -> list[object]:
    span = diagnostic.source_range
    return [
        codes[diagnostic.code],
        messages[diagnostic.message],
        projects[diagnostic.project_id],
        subjects[diagnostic.caller_subject_id]
        if diagnostic.caller_subject_id is not None else -1,
        sites[diagnostic.evidence_id]
        if diagnostic.evidence_id is not None else -1,
        files[diagnostic.source_path]
        if diagnostic.source_path is not None else -1,
        span.start.line if span is not None else 0,
        span.start.column if span is not None else 0,
        span.end.line if span is not None else 0,
        span.end.column if span is not None else 0,
    ]


def _call_site_row(
    row: tuple[object, ...],
    subjects: tuple[str, ...],
    files: tuple[str, ...],
    lexical: tuple[str, ...],
    reasons: tuple[str, ...],
    entries: Mapping[str, CallableIndexEntry],
) -> CallSiteEvidence:
    if len(row) != 19:
        raise ValueError('call-site row has invalid arity')
    caller = subjects[_ref(row[0], subjects, 'caller reference')]
    entry = entries[caller]
    request = CallSiteRequest(
        caller,
        entry.identity.normalized_key,
        entry.project_id,
        files[_ref(row[1], files, 'file reference')],
        SourceRange(
            SourcePosition(
                _positive(row[2], 'call-site start line'),
                _positive(row[3], 'call-site start column'),
            ),
            SourcePosition(
                _positive(row[4], 'call-site end line'),
                _positive(row[5], 'call-site end column'),
            ),
        ),
        _enum_ref(row[6], _INVOCATION_KINDS, 'invocation kind'),
        _enum_ref(row[7], _RECEIVER_KINDS, 'receiver kind'),
        lexical[_ref(row[8], lexical, 'member reference')],
        _nullable_table_value(row[9], lexical, 'receiver reference'),
        tuple(lexical[index] for index in _refs(
            row[10], lexical, 'owner references',
        )),
        tuple(lexical[index] for index in _refs(
            row[11], lexical, 'argument references',
        )),
        tuple(reasons[index] for index in _refs(
            row[12], reasons, 'request limitation references',
        )),
        _cache_transport_validation=True,
    )
    rebuilt = CallSiteEvidence.create(
        request,
        _enum_ref(row[13], _RESOLUTION_STATES, 'resolution state'),
        target_subject_id=_nullable_table_value(
            row[14], subjects, 'target reference',
        ),
        declared_target_id=_nullable_table_value(
            row[15], subjects, 'declared-target reference',
        ),
        candidate_target_ids=tuple(subjects[index] for index in _refs(
            row[16], subjects, 'candidate references',
        )),
        limitations=tuple(reasons[index] for index in _refs(
            row[17], reasons, 'resolution limitation references',
        )),
    )
    if rebuilt.evidence_id != _string(row[18], 'call evidence ID'):
        raise ValueError('call evidence ID is inconsistent')
    return rebuilt


def _edge_row(
    row: tuple[object, ...],
    sites: tuple[CallSiteEvidence, ...],
    subjects: tuple[str, ...],
) -> CodeGraphEdge:
    if len(row) != 3:
        raise ValueError('edge row has invalid arity')
    site = sites[_ref(row[0], sites, 'edge site reference')]
    return CodeGraphEdge(
        site.request.caller_subject_id,
        subjects[_ref(row[1], subjects, 'edge target reference')],
        site.evidence_id,
        _enum_ref(row[2], _EDGE_KINDS, 'edge kind'),
    )


def _diagnostic_row(
    row: tuple[object, ...],
    subjects: tuple[str, ...],
    files: tuple[str, ...],
    codes: tuple[str, ...],
    messages: tuple[str, ...],
    projects: tuple[str, ...],
    sites: tuple[CallSiteEvidence, ...],
) -> CodeGraphDiagnostic:
    if len(row) != 10:
        raise ValueError('diagnostic row has invalid arity')
    source_path = _nullable_table_value(row[5], files, 'diagnostic file')
    positions = tuple(
        _non_negative(item, 'diagnostic position') for item in row[6:10]
    )
    if source_path is None:
        if positions != (0, 0, 0, 0):
            raise ValueError('diagnostic range exists without a file')
        source_range = None
    else:
        if any(item == 0 for item in positions):
            raise ValueError('diagnostic file exists without a complete range')
        source_range = SourceRange(
            SourcePosition(positions[0], positions[1]),
            SourcePosition(positions[2], positions[3]),
        )
    site_index = _nullable_ref(row[4], sites, 'diagnostic site reference')
    return CodeGraphDiagnostic(
        codes[_ref(row[0], codes, 'diagnostic code reference')],
        messages[_ref(row[1], messages, 'diagnostic message reference')],
        projects[_ref(row[2], projects, 'diagnostic project reference')],
        _nullable_table_value(row[3], subjects, 'diagnostic caller'),
        sites[site_index].evidence_id if site_index is not None else None,
        source_path,
        source_range,
        False,
    )


def _coverage(value: object) -> CodeGraphCoverage:
    raw = _mapping(value, 'code-graph coverage')
    names = (
        'callable_bodies_examined', 'callable_bodies_unavailable',
        'extraction_failures', 'total_call_sites', 'resolved_call_sites',
        'polymorphic_call_sites', 'ambiguous_call_sites',
        'unresolved_call_sites', 'external_call_sites',
        'unsupported_call_sites', 'constructor_calls', 'method_references',
        'diagnostic_count', 'omitted_diagnostic_count',
    )
    _exact(raw, set(names), 'code-graph coverage')
    return CodeGraphCoverage(*(
        _non_negative(raw[name], name) for name in names
    ))


def _validate_callable_binding(
    sites: Sequence[CallSiteEvidence],
    diagnostics: Iterable[CodeGraphDiagnostic],
    callable_index: JavaCallableIndex,
) -> None:
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    evidence = {item.evidence_id for item in sites}
    for site in sites:
        request = site.request
        caller = entries.get(request.caller_subject_id)
        if caller is None:
            raise ValueError('call site references an unknown caller')
        if (
            request.caller_normalized_key != caller.identity.normalized_key
            or request.project_id != caller.project_id
        ):
            raise ValueError('call site conflicts with callable-index identity')
        targets = tuple(item for item in (
            site.target_subject_id,
            site.declared_target_id,
            *site.candidate_target_ids,
        ) if item is not None)
        if any(item not in entries for item in targets):
            raise ValueError('call site references an unknown represented target')
    for diagnostic in diagnostics:
        if diagnostic.mandatory:
            raise ValueError('mandatory uncertain-site diagnostics are forbidden')
        if (
            diagnostic.caller_subject_id is not None
            and diagnostic.caller_subject_id not in entries
        ):
            raise ValueError('diagnostic references an unknown callable')
        if (
            diagnostic.evidence_id is not None
            and diagnostic.evidence_id not in evidence
        ):
            raise ValueError('diagnostic references an unknown call site')


def _validate_site_accounting(
    sites: Sequence[CallSiteEvidence],
    coverage: CodeGraphCoverage,
) -> None:
    states = Counter(item.state for item in sites)
    expected = (
        states[CallResolutionState.RESOLVED],
        states[CallResolutionState.POLYMORPHIC],
        states[CallResolutionState.AMBIGUOUS],
        states[CallResolutionState.UNRESOLVED],
        states[CallResolutionState.EXTERNAL],
        states[CallResolutionState.UNSUPPORTED],
    )
    actual = (
        coverage.resolved_call_sites,
        coverage.polymorphic_call_sites,
        coverage.ambiguous_call_sites,
        coverage.unresolved_call_sites,
        coverage.external_call_sites,
        coverage.unsupported_call_sites,
    )
    if actual != expected or sum(actual) != len(sites):
        raise ValueError('call-site state accounting is inconsistent')
    if any(
        item.state is CallResolutionState.AMBIGUOUS
        and not item.candidate_target_ids
        for item in sites
    ):
        raise ValueError('ambiguous site has no represented candidate')


def _edges(sites: Iterable[CallSiteEvidence]) -> tuple[CodeGraphEdge, ...]:
    result: list[CodeGraphEdge] = []
    for site in sites:
        request = site.request
        if site.state is CallResolutionState.RESOLVED:
            kind = (
                CodeGraphEdgeKind.CONSTRUCTOR_CALL
                if request.invocation_kind
                is InvocationKind.CONSTRUCTOR_INVOCATION
                else CodeGraphEdgeKind.METHOD_REFERENCE
                if request.invocation_kind is InvocationKind.METHOD_REFERENCE
                else CodeGraphEdgeKind.RESOLVED_DIRECT_CALL
            )
            result.append(CodeGraphEdge(
                request.caller_subject_id,
                site.target_subject_id or '',
                site.evidence_id,
                kind,
            ))
            continue
        possible = tuple(sorted(set((
            *((site.declared_target_id,) if site.declared_target_id else ()),
            *site.candidate_target_ids,
        ))))
        for target in possible:
            result.append(CodeGraphEdge(
                request.caller_subject_id,
                target,
                site.evidence_id,
                (
                    CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET
                    if site.state is CallResolutionState.POLYMORPHIC
                    else CodeGraphEdgeKind.POSSIBLE_CALL_TARGET
                ),
            ))
    return tuple(sorted(set(result), key=_edge_sort_key))


def _site_sort_key(item: CallSiteEvidence) -> tuple[object, ...]:
    request = item.request
    return (
        request.source_path,
        request.source_range.start,
        request.source_range.end,
        request.caller_subject_id,
        request.invocation_kind.value,
        request.member_name,
        item.evidence_id,
    )


def _edge_sort_key(item: CodeGraphEdge) -> tuple[str, ...]:
    return (
        item.caller_subject_id,
        item.target_subject_id,
        item.evidence_id,
        item.kind.value,
    )


def _diagnostic_sort_key(item: CodeGraphDiagnostic) -> tuple[object, ...]:
    span = item.source_range
    return (
        0 if item.mandatory else 1,
        item.project_id,
        item.source_path or '',
        span.start.line if span is not None else 0,
        span.start.column if span is not None else 0,
        span.end.line if span is not None else 0,
        span.end.column if span is not None else 0,
        item.caller_subject_id or '',
        item.evidence_id or '',
        item.code,
        item.message,
    )


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    ).encode('utf-8')).hexdigest()


def _canonical_row(value: Sequence[object]) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
    )


def _row(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, str):
        raise TypeError(f'{label} must be a compact JSON string')
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(f'{label} is malformed') from error
    if not isinstance(decoded, list):
        raise TypeError(f'{label} must decode to an array')
    if _canonical_row(decoded) != value:
        raise ValueError(f'{label} is not canonical')
    return tuple(decoded)


def _references(values: Sequence[str]) -> dict[str, int]:
    return {item: index for index, item in enumerate(values)}


def _table(value: object, label: str) -> tuple[str, ...]:
    result = tuple(_string(item, label) for item in _array(value, label))
    if result != tuple(sorted(set(result))):
        raise ValueError(f'{label} must be unique and deterministically sorted')
    return result


def _validate_relative_path(value: str) -> None:
    CallSiteRequest(
        'method:path-validation',
        'java-callable:v1:path.Validation#validate()',
        'path-validation',
        value,
        SourceRange(SourcePosition(1, 1), SourcePosition(1, 1)),
        InvocationKind.METHOD_INVOCATION,
        ReceiverKind.UNKNOWN,
        '<path>',
        None,
        (),
        (),
    )


def _non_negative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f'{label} must be a non-negative integer')
    return value


def _positive(value: object, label: str) -> int:
    result = _non_negative(value, label)
    if result == 0:
        raise ValueError(f'{label} must be positive')
    return result


def _ref(value: object, table: Sequence[object], label: str) -> int:
    result = _non_negative(value, label)
    if result >= len(table):
        raise ValueError(f'{label} is out of bounds')
    return result


def _nullable_ref(
    value: object,
    table: Sequence[object],
    label: str,
) -> int | None:
    if value == -1 and not isinstance(value, bool):
        return None
    return _ref(value, table, label)


def _nullable_table_value(
    value: object,
    table: Sequence[str],
    label: str,
) -> str | None:
    index = _nullable_ref(value, table, label)
    return table[index] if index is not None else None


def _refs(
    value: object,
    table: Sequence[object],
    label: str,
) -> tuple[int, ...]:
    return tuple(
        _ref(item, table, label) for item in _array(value, label)
    )


def _enum_ref(value: object, table: Sequence[object], label: str):
    return table[_ref(value, table, label)]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f'{label} keys must be strings')
    return value


def _array(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f'{label} must be an array')
    return tuple(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f'{label} must be a non-empty string')
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f'{label} contains missing or unknown fields')
