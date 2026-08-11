from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
    InvocationKind,
    ReceiverKind,
    CallSiteExtractor,
)
from moughorai.java_code_intelligence.call_resolution import CallResolver
from moughorai.java_code_intelligence.code_graph import (
    MAXIMUM_CODE_GRAPH_DIAGNOSTICS,
    CodeGraphDiagnostic,
    code_graph_from_dict,
    code_graph_to_dict,
    create_code_graph,
)
from moughorai.java_code_intelligence.callable_index import (
    create_callable_index,
)
from moughorai.java_code_intelligence.models import (
    CallableIndexEntry,
    CallableKind,
    CallableSourceReference,
    NormalizedCallableIdentity,
    PathScope,
    SourceClassification,
    SourcePosition,
    SourceRange,
)
from moughorai.java_ast.ast_nodes import (
    CallSiteSyntax,
    CallSyntaxKind,
    CompilationUnit,
    PackageDeclaration,
)
from moughorai.java_ast.models import SourceLocation, SourceSpan


def _request(number: int, *, limitation: str = 'represented source only'):
    return CallSiteRequest(
        f'method:caller{number}',
        f'java-callable:v1:demo.Caller#call{number}()',
        'demo',
        'src/main/java/demo/Caller.java',
        SourceRange(
            SourcePosition(number + 1, 5),
            SourcePosition(number + 1, 12),
        ),
        InvocationKind.METHOD_INVOCATION,
        ReceiverKind.TYPE,
        f'missing{number}',
        'demo.Missing',
        ('demo.Missing',),
        (),
        (limitation,),
    )


def _unresolved(number: int, *, limitation: str = 'represented source only'):
    return CallSiteEvidence.create(
        _request(number, limitation=limitation),
        CallResolutionState.UNRESOLVED,
        limitations=('No represented target matches this call site.',),
    )


def _callable_index(sites):
    callers = {}
    subjects = set()
    for site in sites:
        request = site.request
        callers[request.caller_subject_id] = request
        subjects.add(request.caller_subject_id)
        subjects.update(item for item in (
            site.target_subject_id,
            site.declared_target_id,
            *site.candidate_target_ids,
        ) if item is not None)
    entries = []
    for number, subject in enumerate(sorted(subjects)):
        request = callers.get(subject)
        kind = (
            CallableKind.CONSTRUCTOR
            if subject.startswith('constructor:') else CallableKind.METHOD
        )
        if request is not None:
            key = request.caller_normalized_key
            project = request.project_id
            path = request.source_path
            span = request.source_range
            prefix = 'java-callable:v1:'
            owner, signature = key.removeprefix(prefix).split('#', 1)
            name = signature.split('(', 1)[0]
        else:
            owner = f'demo.Target{number}'
            name = '<init>' if kind is CallableKind.CONSTRUCTOR else 'target'
            key = f'java-callable:v1:{owner}#{name}()'
            project = 'demo'
            path = 'src/main/java/demo/Targets.java'
            span = SourceRange(
                SourcePosition(number + 1, 1),
                SourcePosition(number + 1, 20),
            )
        entries.append(CallableIndexEntry(
            subject,
            project,
            NormalizedCallableIdentity(
                owner,
                kind,
                name,
                (),
                (),
                f'void {name}()',
                key,
            ),
            SourceClassification.PRODUCTION,
            CallableSourceReference(path, span, span),
            'class',
        ))
    methods = sum(
        item.identity.kind is CallableKind.METHOD for item in entries
    )
    return create_callable_index(
        lineage='workspace:test',
        path_scope=PathScope.WORKSPACE,
        entries=entries,
        diagnostics=(),
        selected_source_files=1,
        parsed_source_files=1,
        represented_callables=len(entries),
        unindexed_callables=0,
        represented_methods=methods,
        represented_constructors=len(entries) - methods,
    )


def _graph(sites, diagnostics=()):
    sites = tuple(sites)
    return create_code_graph(
        lineage='workspace:test',
        path_scope=PathScope.WORKSPACE,
        callable_index=_callable_index(sites),
        call_sites=sites,
        diagnostics=diagnostics,
        callable_bodies_examined=8,
        callable_bodies_unavailable=2,
        extraction_failures=0,
    )


def _round_trip(graph):
    return code_graph_from_dict(
        code_graph_to_dict(graph), _callable_index(graph.call_sites),
    )


def _resolved_states_fixture():
    resolved = CallSiteEvidence.create(
        replace(
            _request(10),
            argument_hints=('type:java.lang.String', 'primitive:int'),
        ),
        CallResolutionState.RESOLVED,
        target_subject_id='method:resolved-target',
        limitations=('Exact represented target; execution is not proven.',),
    )
    polymorphic = CallSiteEvidence.create(
        _request(11),
        CallResolutionState.POLYMORPHIC,
        declared_target_id='method:declared-target',
        candidate_target_ids=(
            'method:override-b', 'method:override-a',
        ),
        limitations=('Represented dispatch candidates only.',),
    )
    ambiguous = CallSiteEvidence.create(
        _request(12),
        CallResolutionState.AMBIGUOUS,
        candidate_target_ids=(
            'method:ambiguous-b', 'method:ambiguous-a',
        ),
        limitations=('More than one represented target remains.',),
    )
    unresolved = _unresolved(13)
    external = CallSiteEvidence.create(
        _request(14),
        CallResolutionState.EXTERNAL,
        limitations=('Requested owner is outside represented source.',),
    )
    unsupported = CallSiteEvidence.create(
        replace(
            _request(15), receiver=None, receiver_kind=ReceiverKind.UNKNOWN,
        ),
        CallResolutionState.UNSUPPORTED,
        limitations=('Receiver syntax is outside the represented model.',),
    )
    constructor = CallSiteEvidence.create(
        replace(
            _request(16),
            invocation_kind=InvocationKind.CONSTRUCTOR_INVOCATION,
            receiver_kind=ReceiverKind.CONSTRUCTOR,
            member_name='<init>',
            receiver='demo.Widget',
            owner_type_hints=('demo.Widget',),
            argument_hints=('primitive:int',),
        ),
        CallResolutionState.RESOLVED,
        target_subject_id='constructor:widget',
        limitations=('Exact represented constructor target.',),
    )
    method_reference = CallSiteEvidence.create(
        replace(
            _request(17),
            invocation_kind=InvocationKind.METHOD_REFERENCE,
            member_name='reference',
            argument_hints=(),
        ),
        CallResolutionState.RESOLVED,
        target_subject_id='method:reference-target',
        limitations=('Represented method reference; execution is not proven.',),
    )
    return (
        resolved, polymorphic, ambiguous, unresolved, external, unsupported,
        constructor, method_reference,
    )


def test_uncertain_sites_are_structurally_accounted_and_diagnostics_bounded() -> None:
    sites = tuple(_unresolved(number) for number in range(3))
    noisy = tuple(
        CodeGraphDiagnostic(
            'generic_extraction_note',
            f'Bounded structured diagnostic {number:05d}.',
            'demo',
        )
        for number in range(MAXIMUM_CODE_GRAPH_DIAGNOSTICS + 37)
    )

    graph = _graph(reversed(sites), reversed(noisy))
    assert len(graph.diagnostics) == MAXIMUM_CODE_GRAPH_DIAGNOSTICS
    assert not any(item.mandatory for item in graph.diagnostics)
    assert graph.coverage.omitted_diagnostic_count == 37
    assert graph.coverage.total_call_sites == 3
    assert graph.coverage.unresolved_call_sites == 3
    assert graph.coverage.diagnostic_count == len(graph.diagnostics)
    assert all(item.state is CallResolutionState.UNRESOLVED for item in sites)
    assert all(item.evidence_id for item in sites)
    assert not graph.edges


def test_order_digest_and_round_trip_are_deterministic() -> None:
    sites = (_unresolved(3), _unresolved(1), _unresolved(2))
    diagnostics = tuple(
        CodeGraphDiagnostic('note', f'Note {number}.', 'demo')
        for number in range(5)
    )
    first = _graph(sites, diagnostics)
    second = _graph(reversed(sites), reversed(diagnostics))

    first_bytes = json.dumps(
        code_graph_to_dict(first),
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    second_bytes = json.dumps(
        code_graph_to_dict(second),
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    assert first_bytes == second_bytes
    assert first.digest == second.digest
    assert _round_trip(first) == first

    changed = _graph((
        _unresolved(3),
        _unresolved(1, limitation='different deterministic limitation'),
        _unresolved(2),
    ), diagnostics)
    assert changed.digest != first.digest
    assert changed.input_fingerprint != first.input_fingerprint


def test_compact_round_trip_preserves_all_logical_evidence_exactly() -> None:
    sites = _resolved_states_fixture()
    diagnostic_site = next(
        item for item in sites
        if item.state is CallResolutionState.UNRESOLVED
    )
    diagnostic = CodeGraphDiagnostic(
        'ordinary_extraction_note',
        'A represented extraction limitation remains explicit.',
        diagnostic_site.request.project_id,
        diagnostic_site.request.caller_subject_id,
        diagnostic_site.evidence_id,
        diagnostic_site.request.source_path,
        diagnostic_site.request.source_range,
    )
    graph = _graph(reversed(sites), (diagnostic,))
    restored = _round_trip(graph)

    assert restored == graph
    assert restored.call_sites == graph.call_sites
    assert restored.edges == graph.edges
    assert restored.diagnostics == (diagnostic,)
    assert {item.state for item in restored.call_sites} == set(
        CallResolutionState
    )
    assert tuple(item.evidence_id for item in restored.call_sites) == tuple(
        item.evidence_id for item in graph.call_sites
    )
    assert any(
        item.request.invocation_kind is InvocationKind.CONSTRUCTOR_INVOCATION
        for item in restored.call_sites
    )
    assert any(
        item.request.invocation_kind is InvocationKind.METHOD_REFERENCE
        for item in restored.call_sites
    )
    assert any(
        item.request.argument_hints
        == ('type:java.lang.String', 'primitive:int')
        for item in restored.call_sites
    )
    assert not any(item.mandatory for item in restored.diagnostics)


def test_compact_state_target_and_evidence_invariants_fail_closed() -> None:
    graph = _graph(_resolved_states_fixture())
    callable_index = _callable_index(graph.call_sites)
    encoded = code_graph_to_dict(graph)
    rows = [json.loads(item) for item in encoded['call_sites']]

    duplicate_evidence = deepcopy(encoded)
    duplicate_rows = [list(item) for item in rows]
    duplicate_rows[1][18] = duplicate_rows[0][18]
    duplicate_evidence['call_sites'] = [
        json.dumps(item, ensure_ascii=False, separators=(',', ':'))
        for item in duplicate_rows
    ]
    with pytest.raises(ValueError, match='evidence'):
        code_graph_from_dict(duplicate_evidence, callable_index)

    resolved_index = next(
        index for index, item in enumerate(graph.call_sites)
        if item.state is CallResolutionState.RESOLVED
    )
    missing_target = deepcopy(encoded)
    changed = json.loads(missing_target['call_sites'][resolved_index])
    changed[14] = -1
    missing_target['call_sites'][resolved_index] = json.dumps(
        changed, ensure_ascii=False, separators=(',', ':'),
    )
    with pytest.raises(ValueError, match='resolved call target'):
        code_graph_from_dict(missing_target, callable_index)

    ambiguous_index = next(
        index for index, item in enumerate(graph.call_sites)
        if item.state is CallResolutionState.AMBIGUOUS
    )
    no_candidates = deepcopy(encoded)
    changed = json.loads(no_candidates['call_sites'][ambiguous_index])
    changed[16] = []
    ambiguous_site = graph.call_sites[ambiguous_index]
    changed[18] = CallSiteEvidence.create(
        ambiguous_site.request,
        CallResolutionState.AMBIGUOUS,
        limitations=ambiguous_site.limitations,
    ).evidence_id
    no_candidates['call_sites'][ambiguous_index] = json.dumps(
        changed, ensure_ascii=False, separators=(',', ':'),
    )
    with pytest.raises(ValueError, match='ambiguous'):
        code_graph_from_dict(no_candidates, callable_index)

    polymorphic_index = next(
        index for index, item in enumerate(graph.call_sites)
        if item.state is CallResolutionState.POLYMORPHIC
    )
    no_dispatch_target = deepcopy(encoded)
    changed = json.loads(
        no_dispatch_target['call_sites'][polymorphic_index]
    )
    changed[15] = -1
    changed[16] = []
    no_dispatch_target['call_sites'][polymorphic_index] = json.dumps(
        changed, ensure_ascii=False, separators=(',', ':'),
    )
    with pytest.raises(ValueError, match='polymorphic'):
        code_graph_from_dict(no_dispatch_target, callable_index)

    wrong_binding = deepcopy(encoded)
    wrong_binding['callable_index_fingerprint'] = (
        'java-callable-index:' + ('0' * 64)
    )
    with pytest.raises(ValueError, match='binding'):
        code_graph_from_dict(wrong_binding, callable_index)


def test_malformed_or_inconsistent_artifacts_fail_closed() -> None:
    graph = _graph((_unresolved(1),))
    callable_index = _callable_index(graph.call_sites)

    absolute = deepcopy(code_graph_to_dict(graph))
    absolute['files'][0] = 'C:/private/Caller.java'
    with pytest.raises(ValueError):
        code_graph_from_dict(absolute, callable_index)

    invalid_reference = deepcopy(code_graph_to_dict(graph))
    row = json.loads(invalid_reference['call_sites'][0])
    row[1] = 999
    invalid_reference['call_sites'][0] = json.dumps(
        row, separators=(',', ':'), ensure_ascii=False,
    )
    with pytest.raises(ValueError, match='reference|bounds'):
        code_graph_from_dict(invalid_reference, callable_index)

    duplicate_subject = deepcopy(code_graph_to_dict(graph))
    duplicate_subject['subjects'].append(duplicate_subject['subjects'][0])
    with pytest.raises(ValueError, match='unique'):
        code_graph_from_dict(duplicate_subject, callable_index)

    wrong_totals = deepcopy(code_graph_to_dict(graph))
    wrong_totals['coverage']['unresolved_call_sites'] = 0
    with pytest.raises(ValueError, match='accounting'):
        code_graph_from_dict(wrong_totals, callable_index)

    extra_field = deepcopy(code_graph_to_dict(graph))
    extra_field['source_text'] = 'private source body'
    with pytest.raises(ValueError, match='fields'):
        code_graph_from_dict(extra_field, callable_index)


def test_artifact_contains_only_source_safe_structured_evidence() -> None:
    graph = _graph((_unresolved(1),))
    serialized = json.dumps(code_graph_to_dict(graph), sort_keys=True)

    assert 'C:\\\\' not in serialized
    assert 'private source body' not in serialized
    assert 'src/main/java/demo/Caller.java' in serialized
    assert 'method:caller1' in serialized
    assert graph.coverage.unresolved_call_sites == 1
    assert not graph.diagnostics


@pytest.mark.parametrize('receiver', (
    'foo',
    'foo.bar',
    'this.field',
    'Owner.member',
    'δοκιμή',
    'élève',
    'δοκιμή.κλάση',
    'demo.κλάση',
    'α9',
))
def test_java_structured_names_accept_lexer_valid_unicode(
    receiver: str,
) -> None:
    request = replace(_request(1), receiver=receiver)

    assert request.receiver == receiver


@pytest.mark.parametrize('receiver', (
    '.foo',
    'foo.',
    'foo..bar',
    'foo bar',
    ' foo',
    'foo ',
    'foo-bar',
    'foo()',
    'foo[0]',
    'foo::bar',
    '9foo',
    '\u0301foo',
))
def test_java_structured_names_reject_non_identifier_syntax(
    receiver: str,
) -> None:
    with pytest.raises(ValueError, match='structured name'):
        replace(_request(1), receiver=receiver)


def test_source_unsupported_receiver_is_accounted_without_leaking_text() -> None:
    span = SourceSpan(
        SourceLocation(10, 2, 3),
        SourceLocation(17, 2, 10),
    )
    syntax = CallSiteSyntax(
        CallSyntaxKind.METHOD_INVOCATION,
        'invoke',
        span,
        receiver='unsafe-receiver',
    )
    request = CallSiteExtractor()._request(
        syntax,
        CompilationUnit(package=PackageDeclaration('demo')),
        'method:caller',
        'java-callable:v1:demo.Caller#call()',
        'demo',
        'src/main/java/demo/Caller.java',
        'demo.Caller',
        {},
        {'demo.Caller'},
        {},
    )
    evidence = CallResolver(()).resolve(request)
    graph = _graph((evidence,))
    serialized = json.dumps(code_graph_to_dict(graph), sort_keys=True)

    assert request.receiver is None
    assert request.receiver_kind is ReceiverKind.UNKNOWN
    assert evidence.state is CallResolutionState.UNSUPPORTED
    assert graph.coverage.unsupported_call_sites == 1
    assert not graph.diagnostics
    assert 'unsafe-receiver' not in serialized
    assert 'Receiver syntax is outside the represented structured-name model.' in serialized


def test_unicode_call_evidence_digest_is_deterministic() -> None:
    request = replace(_request(1), receiver='δοκιμή.κλάση')
    evidence = CallSiteEvidence.create(
        request,
        CallResolutionState.UNRESOLVED,
        limitations=('No represented Unicode target matches this call site.',),
    )

    first = _graph((evidence,))
    second = _graph(reversed((evidence,)))

    assert code_graph_to_dict(first) == code_graph_to_dict(second)
    assert first.digest == second.digest
    assert _round_trip(first) == first
