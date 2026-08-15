from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from moughorai.java_code_intelligence import code_graph as graph_module
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
)
from moughorai.java_code_intelligence.code_graph import (
    code_graph_from_dict,
    code_graph_to_dict,
    create_code_graph,
)
from moughorai.java_code_intelligence.models import SourcePosition, SourceRange
from test_perf2b_java_reconstruction import _artifacts


def _two_site_artifacts():
    callable_index, graph = _artifacts()
    first = graph.call_sites[0]
    request = CallSiteRequest(
        first.request.caller_subject_id,
        first.request.caller_normalized_key,
        first.request.project_id,
        first.request.source_path,
        SourceRange(SourcePosition(4, 1), SourcePosition(4, 20)),
        first.request.invocation_kind,
        first.request.receiver_kind,
        first.request.member_name,
        first.request.receiver,
        first.request.owner_type_hints,
        first.request.argument_hints,
        first.request.limitations,
    )
    second = CallSiteEvidence.create(
        request,
        CallResolutionState.RESOLVED,
        target_subject_id=first.target_subject_id,
        limitations=first.limitations,
    )
    expanded = create_code_graph(
        lineage=graph.lineage,
        path_scope=graph.path_scope,
        callable_index=callable_index,
        call_sites=(first, second),
        callable_bodies_examined=1,
        callable_bodies_unavailable=0,
        extraction_failures=0,
    )
    return callable_index, expanded


def test_repeated_table_references_are_role_validated_once(monkeypatch) -> None:
    callable_index, graph = _two_site_artifacts()
    encoded = code_graph_to_dict(graph)
    calls: list[tuple[object, str, int]] = []
    original = graph_module.validated_text

    def counted(value: object, label: str, maximum: int) -> str:
        calls.append((value, label, maximum))
        return original(value, label, maximum)

    monkeypatch.setattr(graph_module, 'validated_text', counted)
    restored = code_graph_from_dict(encoded, callable_index)

    assert restored == graph
    assert sum(label == 'invoked member' for _, label, _ in calls) == 1
    assert sum(label == 'call-site limitation' for _, label, _ in calls) == 1


def test_validated_row_proof_rejects_arbitrary_callers() -> None:
    with pytest.raises(TypeError, match='decoder proof'):
        graph_module._ValidatedCallSiteRow(*(None,) * 19)


def test_fast_materializer_matches_constructor_and_canonical_row() -> None:
    callable_index, graph = _artifacts()
    encoded = code_graph_to_dict(graph)
    subjects = tuple(encoded['subjects'])
    files = tuple(encoded['files'])
    lexical = tuple(encoded['lexical'])
    reasons = tuple(encoded['reasons'])
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    row = tuple(json.loads(encoded['call_sites'][0]))
    validated = graph_module._validated_call_site_row(
        row,
        subjects,
        files,
        lexical,
        reasons,
        entries,
        graph_module._LexicalTableValidation(lexical),
    )
    rebuilt = graph_module._reconstructed_call_site(validated)

    assert rebuilt == graph.call_sites[0]
    assert tuple(graph_module._site_row(
        rebuilt,
        graph_module._references(subjects),
        graph_module._references(files),
        graph_module._references(lexical),
        graph_module._references(reasons),
    )) == row

    corrupt = replace(validated, evidence_id='evidence:' + ('0' * 64))
    with pytest.raises(ValueError, match='evidence ID'):
        graph_module._reconstructed_call_site(corrupt)
    with pytest.raises(TypeError, match='decoder proof'):
        graph_module._reconstructed_call_site(object())


def test_decoder_does_not_repeat_per_row_model_construction(monkeypatch) -> None:
    callable_index, graph = _two_site_artifacts()
    encoded = code_graph_to_dict(graph)
    calls = {'requests': 0}
    original_request_post_init = CallSiteRequest.__post_init__

    def counted_request(self, cache_transport_validation: bool) -> None:
        calls['requests'] += 1
        original_request_post_init(self, cache_transport_validation)

    def unexpected_evidence(*_args, **_kwargs):
        raise AssertionError('persisted rows repeated evidence model construction')

    monkeypatch.setattr(
        CallSiteRequest, '__post_init__', counted_request,
    )
    monkeypatch.setattr(
        CallSiteEvidence, '__post_init__', unexpected_evidence,
    )
    monkeypatch.setattr(
        CallSiteEvidence, 'create', classmethod(unexpected_evidence),
    )

    assert code_graph_from_dict(encoded, callable_index) == graph
    assert calls == {'requests': len(encoded['files'])}


@pytest.mark.parametrize(('field', 'replacement'), (
    (7, 999),
    (8, 999),
    (10, [0, 0]),
    (16, [1, 1]),
))
def test_primitive_row_corruption_still_fails_closed(
    field: int,
    replacement: object,
) -> None:
    callable_index, graph = _artifacts()
    encoded = deepcopy(code_graph_to_dict(graph))
    row = json.loads(encoded['call_sites'][0])
    row[field] = replacement
    encoded['call_sites'][0] = json.dumps(
        row, ensure_ascii=False, separators=(',', ':'),
    )

    with pytest.raises((TypeError, ValueError)):
        code_graph_from_dict(encoded, callable_index)


def test_request_limitations_cannot_be_omitted_from_evidence() -> None:
    callable_index, graph = _artifacts()
    encoded = deepcopy(code_graph_to_dict(graph))
    row = json.loads(encoded['call_sites'][0])
    assert row[17]
    row[12] = list(row[17])
    row[17] = []
    encoded['call_sites'][0] = json.dumps(
        row, ensure_ascii=False, separators=(',', ':'),
    )

    with pytest.raises(ValueError, match='must include request limitations'):
        code_graph_from_dict(encoded, callable_index)


def test_round_trip_remains_object_and_transport_identical() -> None:
    callable_index, graph = _two_site_artifacts()
    encoded = code_graph_to_dict(graph)
    restored = code_graph_from_dict(encoded, callable_index)

    assert restored == graph
    assert code_graph_to_dict(restored) == encoded
