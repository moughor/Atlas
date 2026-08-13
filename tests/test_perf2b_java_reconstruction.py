from __future__ import annotations

from copy import deepcopy
import json

import pytest

from moughorai.ai_context.persistence import (
    decode_analysis_result_bytes,
    encode_analysis_result_bytes,
)
from moughorai.java_code_intelligence import code_graph as graph_module
from moughorai.java_code_intelligence._validation import (
    reconstruction_validation_scope,
    validated_text,
)
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
    InvocationKind,
    ReceiverKind,
)
from moughorai.java_code_intelligence.callable_index import (
    create_callable_index,
)
from moughorai.java_code_intelligence.code_graph import (
    code_graph_from_dict,
    code_graph_to_dict,
    create_code_graph,
)
from moughorai.java_code_intelligence.models import (
    CallableIndexEntry,
    CallableKind,
    CallableSourceReference,
    NormalizedCallableIdentity,
    ParameterResolution,
    PathScope,
    SourceClassification,
    SourcePosition,
    SourceRange,
)
from moughorai.java_code_intelligence.persistence import (
    callable_index_from_dict,
    callable_index_to_dict,
)
from moughorai.semantic import SemanticDocument


class _CountingText(str):
    strip_calls: int

    def __new__(cls, value: str):
        instance = super().__new__(cls, value)
        instance.strip_calls = 0
        return instance

    def strip(self, chars=None):
        self.strip_calls += 1
        return super().strip(chars)


def _span(line: int = 1) -> SourceRange:
    return SourceRange(
        SourcePosition(line, 1),
        SourcePosition(line, 20),
    )


def _identity(owner: str, name: str) -> NormalizedCallableIdentity:
    return NormalizedCallableIdentity(
        owner,
        CallableKind.METHOD,
        name,
        (),
        (),
        f'void {name}()',
        f'java-callable:v1:{owner}#{name}()',
    )


def _artifacts():
    caller_span = _span(2)
    target_span = _span(3)
    entries = (
        CallableIndexEntry(
            'method:caller',
            'demo',
            _identity('demo.App', 'caller'),
            SourceClassification.PRODUCTION,
            CallableSourceReference(
                'src/main/java/demo/App.java',
                caller_span,
                caller_span,
            ),
            'class',
        ),
        CallableIndexEntry(
            'method:target',
            'demo',
            _identity('demo.App', 'target'),
            SourceClassification.PRODUCTION,
            CallableSourceReference(
                'src/main/java/demo/App.java',
                target_span,
                target_span,
            ),
            'class',
        ),
    )
    callable_index = create_callable_index(
        lineage='project:demo',
        path_scope=PathScope.PROJECT,
        entries=entries,
        diagnostics=(),
        selected_source_files=1,
        parsed_source_files=1,
        represented_callables=2,
        unindexed_callables=0,
        represented_methods=2,
        represented_constructors=0,
    )
    request = CallSiteRequest(
        'method:caller',
        entries[0].identity.normalized_key,
        'demo',
        'src/main/java/demo/App.java',
        caller_span,
        InvocationKind.METHOD_INVOCATION,
        ReceiverKind.TYPE,
        'target',
        'demo.App',
        ('demo.App',),
        (),
    )
    evidence = CallSiteEvidence.create(
        request,
        CallResolutionState.RESOLVED,
        target_subject_id='method:target',
        limitations=('Exact represented target.',),
    )
    graph = create_code_graph(
        lineage='project:demo',
        path_scope=PathScope.PROJECT,
        callable_index=callable_index,
        call_sites=(evidence,),
        callable_bodies_examined=1,
        callable_bodies_unavailable=0,
        extraction_failures=0,
    )
    return callable_index, graph


def test_decode_local_text_reuse_is_exact_bounded_to_scope_and_maximum() -> None:
    value = _CountingText('shared immutable value')

    with reconstruction_validation_scope():
        assert validated_text(value, 'first label', 64) == value
        assert validated_text(value, 'second label', 64) == value
        assert value.strip_calls == 1
        with pytest.raises(ValueError, match='oversized'):
            validated_text(value, 'short field', 4)

    with reconstruction_validation_scope():
        assert validated_text(value, 'new decode', 64) == value
    assert value.strip_calls == 3


def test_failed_validation_is_never_memoized() -> None:
    value = _CountingText('invalid\nvalue')

    with reconstruction_validation_scope():
        for _ in range(2):
            with pytest.raises(ValueError, match='control characters'):
                validated_text(value, 'transport text', 64)

    assert value.strip_calls == 2


def test_plain_text_reuse_never_skips_contextual_invariants() -> None:
    span = _span()
    identity = _identity('demo.App', 'run')
    valid_request = CallSiteRequest(
        'method:run',
        identity.normalized_key,
        'demo',
        'src/main/java/demo/App.java',
        span,
        InvocationKind.METHOD_INVOCATION,
        ReceiverKind.UNQUALIFIED,
        'run',
        None,
        (),
        (),
    )

    with reconstruction_validation_scope():
        validated_text('../outside/App.java', 'opaque text', 2_048)
        with pytest.raises(ValueError, match='workspace-relative'):
            CallableSourceReference('../outside/App.java', span, span)

        validated_text('bad receiver', 'opaque text', 1_024)
        with pytest.raises(ValueError, match='structured name'):
            CallSiteRequest(
                'method:run',
                identity.normalized_key,
                'demo',
                'src/main/java/demo/App.java',
                span,
                InvocationKind.METHOD_INVOCATION,
                ReceiverKind.TYPE,
                'run',
                'bad receiver',
                (),
                (),
            )

        validated_text('method:target', 'opaque text', 256)
        with pytest.raises(ValueError, match='unresolved call'):
            CallSiteEvidence.create(
                valid_request,
                CallResolutionState.UNRESOLVED,
                candidate_target_ids=('method:target',),
            )

        validated_text('method:wrong-kind', 'opaque text', 256)
        with pytest.raises(ValueError, match='kind is inconsistent'):
            CallableIndexEntry(
                'method:wrong-kind',
                'demo',
                NormalizedCallableIdentity(
                    'demo.App',
                    CallableKind.CONSTRUCTOR,
                    '<init>',
                    (),
                    (),
                    'App()',
                    'java-callable:v1:demo.App#<init>()',
                ),
                SourceClassification.PRODUCTION,
                CallableSourceReference(
                    'src/main/java/demo/App.java', span, span,
                ),
                'class',
            )

        validated_text(
            'java-callable:v1:demo.App#wrong()',
            'opaque text',
            4_096,
        )
        with pytest.raises(ValueError, match='normalized callable key'):
            NormalizedCallableIdentity(
                'demo.App',
                CallableKind.METHOD,
                'run',
                (),
                (),
                'void run()',
                'java-callable:v1:demo.App#wrong()',
            )

        with pytest.raises(ValueError, match='precedes'):
            SourceRange(SourcePosition(2, 1), SourcePosition(1, 1))


def test_strict_graph_decode_reuses_projection_without_weakening_comparison(
    monkeypatch,
) -> None:
    callable_index, graph = _artifacts()
    encoded = code_graph_to_dict(graph)
    calls = {'projection': 0, 'digest': 0}
    original_projection = graph_module._compact_projection
    original_digest = graph_module._digest

    def counted_projection(**kwargs):
        calls['projection'] += 1
        return original_projection(**kwargs)

    def counted_digest(value):
        calls['digest'] += 1
        return original_digest(value)

    monkeypatch.setattr(
        graph_module, '_compact_projection', counted_projection,
    )
    monkeypatch.setattr(graph_module, '_digest', counted_digest)

    restored = code_graph_from_dict(encoded, callable_index)
    assert restored == graph
    assert calls == {'projection': 1, 'digest': 1}

    corrupt_digest = deepcopy(encoded)
    corrupt_digest['digest'] = '0' * 64
    with pytest.raises(ValueError, match='digest|ordering|coverage'):
        code_graph_from_dict(corrupt_digest, callable_index)

    duplicate_edge = deepcopy(encoded)
    duplicate_edge['edges'].append(duplicate_edge['edges'][0])
    with pytest.raises(ValueError, match='digest|ordering|coverage'):
        code_graph_from_dict(duplicate_edge, callable_index)

    invalid_order = deepcopy(encoded)
    invalid_order['subjects'].reverse()
    with pytest.raises(ValueError, match='deterministically sorted'):
        code_graph_from_dict(invalid_order, callable_index)


def test_full_transport_remains_byte_identical_after_strict_reconstruction() -> None:
    callable_index, graph = _artifacts()
    original = (
        SemanticDocument('java', '', (), {'project_id': 'demo'})
        .with_artifact('java_callable_index', callable_index)
        .with_artifact('java_code_graph', graph)
    )
    encoded = encode_analysis_result_bytes(original)
    restored = decode_analysis_result_bytes(encoded)

    assert encode_analysis_result_bytes(restored) == encoded
    assert restored.require_artifact('java_callable_index') == callable_index
    assert restored.require_artifact('java_code_graph') == graph


@pytest.mark.parametrize('corruption', (
    'callable_id',
    'owner_identity',
    'normalized_key',
    'source_path',
    'source_range',
    'type_identity',
    'duplicate_entry',
    'entry_order',
))
def test_cache_active_callable_corruption_still_fails_closed(
    corruption: str,
) -> None:
    callable_index, _ = _artifacts()
    encoded = deepcopy(callable_index_to_dict(callable_index))
    first = encoded['entries'][0]
    if corruption == 'callable_id':
        first['canonical_subject_id'] = 'constructor:caller'
    elif corruption == 'owner_identity':
        first['owner_type'] = 'demo.\x01App'
    elif corruption == 'normalized_key':
        first['normalized_key'] = 'java-callable:v1:demo.App#wrong()'
    elif corruption == 'source_path':
        first['source']['path'] = 'C:/private/App.java'
    elif corruption == 'source_range':
        first['source']['declaration']['end']['line'] = 1
    elif corruption == 'type_identity':
        first['type_kind'] = 'trait'
    elif corruption == 'duplicate_entry':
        encoded['entries'].append(deepcopy(first))
        encoded['coverage']['indexed_callables'] += 1
        encoded['coverage']['represented_callables'] += 1
        encoded['coverage']['methods'] += 1
        encoded['coverage']['classifications']['production'] += 1
    else:
        encoded['entries'].reverse()

    with reconstruction_validation_scope():
        with pytest.raises((TypeError, ValueError)):
            callable_index_from_dict(encoded)


@pytest.mark.parametrize('corruption', (
    'evidence_id',
    'graph_node',
    'graph_edge',
    'structured_name',
    'source_path',
    'source_range',
    'candidate_identity',
    'duplicate_node',
    'duplicate_edge',
    'authority_binding',
    'node_order',
    'resolution_metadata',
))
def test_cache_active_code_graph_corruption_still_fails_closed(
    corruption: str,
) -> None:
    callable_index, graph = _artifacts()
    encoded = deepcopy(code_graph_to_dict(graph))
    row = json.loads(encoded['call_sites'][0])
    if corruption == 'evidence_id':
        row[18] = 'evidence:' + ('0' * 64)
    elif corruption == 'graph_node':
        encoded['subjects'][0] = 'method:missing'
    elif corruption == 'graph_edge':
        edge = json.loads(encoded['edges'][0])
        edge[1] = row[0]
        encoded['edges'][0] = json.dumps(
            edge, ensure_ascii=False, separators=(',', ':'),
        )
    elif corruption == 'structured_name':
        encoded['lexical'][
            encoded['lexical'].index('demo.App')
        ] = 'bad receiver'
    elif corruption == 'source_path':
        encoded['files'][0] = 'C:/private/App.java'
    elif corruption == 'source_range':
        row[4] = 1
    elif corruption == 'candidate_identity':
        row[16] = [row[14]]
    elif corruption == 'duplicate_node':
        encoded['subjects'].append(encoded['subjects'][0])
    elif corruption == 'duplicate_edge':
        encoded['edges'].append(encoded['edges'][0])
    elif corruption == 'authority_binding':
        encoded['callable_index_fingerprint'] = (
            'java-callable-index:' + ('0' * 64)
        )
    elif corruption == 'node_order':
        encoded['subjects'].reverse()
    else:
        row[13] = graph_module._RESOLUTION_STATES.index(
            CallResolutionState.UNRESOLVED,
        )
    encoded['call_sites'][0] = json.dumps(
        row, ensure_ascii=False, separators=(',', ':'),
    )

    with reconstruction_validation_scope():
        with pytest.raises((TypeError, ValueError)):
            code_graph_from_dict(encoded, callable_index)
