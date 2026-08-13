from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from moughorai.java_code_intelligence import call_graph_producer
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


def test_validated_source_path_update_is_byte_compatible() -> None:
    sites = _resolved_states_fixture()
    reference_sites = []
    optimized_sites = []

    for site in sites:
        source_path = f'module-a/{site.request.source_path}'
        reference_request = replace(site.request, source_path=source_path)
        optimized_request = site.request.with_source_path(source_path)
        assert optimized_request == reference_request
        assert optimized_request.source_range is site.request.source_range
        assert (
            optimized_request.owner_type_hints
            is site.request.owner_type_hints
        )
        assert optimized_request.argument_hints is site.request.argument_hints
        assert optimized_request.limitations is site.request.limitations

        evidence_arguments = {
            'target_subject_id': site.target_subject_id,
            'declared_target_id': site.declared_target_id,
            'candidate_target_ids': site.candidate_target_ids,
            'limitations': site.limitations,
        }
        reference_sites.append(CallSiteEvidence.create(
            reference_request, site.state, **evidence_arguments,
        ))
        optimized_sites.append(CallSiteEvidence.create(
            optimized_request, site.state, **evidence_arguments,
        ))

    reference = _graph(reference_sites)
    optimized = _graph(reversed(optimized_sites))
    assert tuple(
        item.evidence_id for item in optimized.call_sites
    ) == tuple(item.evidence_id for item in reference.call_sites)
    assert optimized.digest == reference.digest
    assert code_graph_to_dict(optimized) == code_graph_to_dict(reference)
    assert sites[0].request.with_source_path(
        sites[0].request.source_path,
    ) is sites[0].request


@pytest.mark.parametrize('source_path', (
    '/absolute/Caller.java',
    '../outside/Caller.java',
    'module/../outside/Caller.java',
    'C:/absolute/Caller.java',
    r'module\Caller.java',
))
def test_validated_source_path_update_rejects_unsafe_paths(
    source_path: str,
) -> None:
    with pytest.raises(ValueError, match='call-site path'):
        _request(1).with_source_path(source_path)


def test_workspace_merge_reuses_paths_and_is_insertion_order_independent(
    tmp_path,
    monkeypatch,
) -> None:
    requests = tuple(replace(
        _request(number),
        project_id='caller-project',
        member_name='target',
        receiver='demo.Target',
        owner_type_hints=('demo.Target',),
        limitations=(),
    ) for number in (2, 1))

    def entry_for_request(request, path):
        return CallableIndexEntry(
            request.caller_subject_id,
            request.project_id,
            NormalizedCallableIdentity(
                'demo.Caller',
                CallableKind.METHOD,
                request.caller_normalized_key.split('#', 1)[1].split('(', 1)[0],
                (),
                (),
                'void caller()',
                request.caller_normalized_key,
            ),
            SourceClassification.PRODUCTION,
            CallableSourceReference(
                path, request.source_range, request.source_range,
            ),
            'class',
        )

    target_span = SourceRange(
        SourcePosition(1, 1), SourcePosition(1, 20),
    )
    target_entry = CallableIndexEntry(
        'method:target',
        'target-project',
        NormalizedCallableIdentity(
            'demo.Target',
            CallableKind.METHOD,
            'target',
            (),
            (),
            'void target()',
            'java-callable:v1:demo.Target#target()',
        ),
        SourceClassification.PRODUCTION,
        CallableSourceReference(
            'src/main/java/demo/Target.java', target_span, target_span,
        ),
        'class',
    )

    def index(entries, scope, lineage):
        entries = tuple(entries)
        return create_callable_index(
            lineage=lineage,
            path_scope=scope,
            entries=entries,
            diagnostics=(),
            selected_source_files=1,
            parsed_source_files=1,
            represented_callables=len(entries),
            unindexed_callables=0,
            represented_methods=len(entries),
            represented_constructors=0,
        )

    caller_entries = tuple(
        entry_for_request(request, request.source_path)
        for request in requests
    )
    caller_index = index(
        caller_entries, PathScope.PROJECT, 'project:caller-project',
    )
    target_index = index(
        (target_entry,), PathScope.PROJECT, 'project:target-project',
    )
    workspace_index = index(
        (
            *(replace(
                item,
                source=replace(
                    item.source,
                    path=f'module-a/{item.source.path}',
                ),
            ) for item in caller_entries),
            replace(
                target_entry,
                source=replace(
                    target_entry.source,
                    path=f'module-b/{target_entry.source.path}',
                ),
            ),
        ),
        PathScope.WORKSPACE,
        'workspace:test',
    )
    local_sites = tuple(
        CallResolver(caller_index.entries).resolve(request)
        for request in requests
    )
    assert all(
        item.state is CallResolutionState.EXTERNAL for item in local_sites
    )

    def project_graph(call_sites, callable_index, lineage):
        call_sites = tuple(call_sites)
        return create_code_graph(
            lineage=lineage,
            path_scope=PathScope.PROJECT,
            callable_index=callable_index,
            call_sites=call_sites,
            callable_bodies_examined=len(call_sites),
            callable_bodies_unavailable=0,
            extraction_failures=0,
        )

    caller_forward = project_graph(
        local_sites, caller_index, 'project:caller-project',
    )
    caller_reverse = project_graph(
        reversed(local_sites), caller_index, 'project:caller-project',
    )
    target_graph = project_graph(
        (), target_index, 'project:target-project',
    )
    project_paths = {
        'caller-project': tmp_path / 'module-a',
        'target-project': tmp_path / 'module-b',
    }

    original_join = call_graph_producer._join_relative
    joins = []

    def tracked_join(prefix, path):
        joins.append((prefix, path))
        return original_join(prefix, path)

    monkeypatch.setattr(
        call_graph_producer, '_join_relative', tracked_join,
    )
    first = call_graph_producer.merge_code_graphs(
        {
            'caller-project': caller_forward,
            'target-project': target_graph,
        },
        callable_index=workspace_index,
        workspace_root=tmp_path,
        project_paths=project_paths,
        canonical_symbols=(),
        lineage='workspace:test',
    )
    second = call_graph_producer.merge_code_graphs(
        {
            'target-project': target_graph,
            'caller-project': caller_reverse,
        },
        callable_index=workspace_index,
        workspace_root=tmp_path,
        project_paths=dict(reversed(tuple(project_paths.items()))),
        canonical_symbols=(),
        lineage='workspace:test',
    )

    assert joins == [
        ('module-a', requests[0].source_path),
        ('module-a', requests[0].source_path),
    ]
    assert all(
        item.state is CallResolutionState.RESOLVED
        and item.target_subject_id == 'method:target'
        and item.request.source_path.startswith('module-a/')
        for item in first.call_sites
    )
    expected_ids = {
        item.request.caller_subject_id: item.evidence_id
        for item in (
            CallResolver(workspace_index.entries).resolve(
                request.with_source_path(
                    f'module-a/{request.source_path}',
                )
            )
            for request in requests
        )
    }
    assert {
        item.request.caller_subject_id: item.evidence_id
        for item in first.call_sites
    } == expected_ids
    assert code_graph_to_dict(first) == code_graph_to_dict(second)
    assert first.digest == second.digest


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
