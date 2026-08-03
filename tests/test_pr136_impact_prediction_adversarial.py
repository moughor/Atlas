from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.impact_analysis import (
    ImpactCapabilityState,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
    ImpactPredictionService,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.subject_resolution import SubjectQuery


TARGET = "type:target"
CALLER = "type:caller"
CALL_EVIDENCE = ("moughorai.call_graph.v1:calls",)


def _node(
    identifier: str,
    *,
    qualified_name: str | None = None,
    kind: KnowledgeKind = KnowledgeKind.TYPE,
    metadata: tuple[tuple[str, str], ...] = (),
) -> KnowledgeNode:
    name = identifier.rsplit(":", 1)[-1]
    return KnowledgeNode(
        identifier,
        kind,
        name,
        metadata=metadata,
        qualified_name=qualified_name or f"demo.{name}",
        project_id="demo",
        language="java",
    )


def _snapshot(
    nodes: tuple[KnowledgeNode, ...],
    edges: tuple[KnowledgeEdge, ...] = (),
    *,
    extra_context: dict[str, object] | None = None,
) -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(nodes, edges)
    context: dict[str, object] = {
        "schema_version": 1,
        "semantic_graph": graph.to_dict(),
        "symbols": [],
    }
    context.update(extra_context or {})
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr136-adversarial-fixture",
        analyzer_version="test-analyzer/1",
    )


def _predict(
    snapshot: AtlasSemanticSnapshot,
    subject: str = TARGET,
    **request: object,
) -> ImpactPredictionResponse:
    return ImpactPredictionService.from_snapshot(snapshot).predict(
        ImpactPredictionRequest(SubjectQuery(subject), **request)
    )


def _calls_capability(response: ImpactPredictionResponse):
    return next(item for item in response.capabilities if item.name == "calls")


def _authoritative_call_snapshot() -> AtlasSemanticSnapshot:
    return _snapshot(
        (_node(TARGET), _node(CALLER)),
        (KnowledgeEdge(CALLER, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),),
    )


@pytest.mark.parametrize("evidence", (("semantic_graph:calls",), ("calls",)))
def test_generic_semantic_graph_calls_are_not_authoritative(
    evidence: tuple[str, ...],
) -> None:
    response = _predict(_snapshot(
        (_node(TARGET), _node(CALLER)),
        (KnowledgeEdge(
            CALLER,
            TARGET,
            KnowledgeRelation.CALLS,
            evidence,
        ),),
    ))

    capability = _calls_capability(response)
    assert response.findings == ()
    assert capability.state is ImpactCapabilityState.UNAVAILABLE
    assert capability.coverage is None
    assert any(
        "lacked relation-specific authoritative evidence" in item
        for item in capability.limitations
    )


def test_unsafe_authority_token_cannot_borrow_an_unrelated_safe_reference() -> None:
    response = _predict(_snapshot(
        (_node(TARGET), _node(CALLER)),
        (KnowledgeEdge(
            CALLER,
            TARGET,
            KnowledgeRelation.IMPORTS,
            (
                "calls",
                "global_symbol.metadata:imports:C:\\private\\Secret.java",
            ),
        ),),
    ))

    assert response.findings == ()


def test_missing_call_evidence_is_explicitly_unavailable() -> None:
    response = _predict(_snapshot((_node(TARGET),)))

    capability = _calls_capability(response)
    assert capability.state is ImpactCapabilityState.UNAVAILABLE
    assert capability.coverage is None
    assert capability.limitations == (
        "Call-based impact was not evaluated for this scope.",
    )


def test_unknown_api_exposure_is_excluded_and_weights_are_renormalized() -> None:
    response = _predict(_authoritative_call_snapshot())
    finding = next(
        item for item in response.findings if item.canonical_subject_id == CALLER
    )

    assert {item.name for item in finding.score.components} == {
        "relation_strength",
        "path_proximity",
    }
    assert math.isclose(
        sum(item.weight for item in finding.score.components),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_search_risk_and_git_context_cannot_create_impact_findings() -> None:
    snapshot = _snapshot(
        (_node(TARGET),),
        extra_context={
            "semantic_search": {"hits": [{"canonical_subject_id": TARGET}]},
            "git_context": {"changed_subject_ids": [TARGET]},
            "risk_analysis": {"findings": [{"subject_id": TARGET}]},
        },
    )
    response = _predict(
        snapshot,
        include_risk=True,
        include_git_context=True,
        include_search_enrichment=True,
    )

    states = {item.name: item.state for item in response.capabilities}
    assert response.findings == ()
    assert states["search"] is ImpactCapabilityState.UNAVAILABLE
    assert states["git"] is ImpactCapabilityState.UNAVAILABLE
    assert states["risk"] is ImpactCapabilityState.INCOMPATIBLE


def test_similarly_named_test_is_not_a_direct_impact() -> None:
    test_id = "method:target-test"
    reachability = {
        "schema_version": 1,
        "producer_version": "atlas-pr131/1",
        "graph_digest": "deliberately-not-the-current-graph",
        "roots": [{"subject_id": test_id, "category": "test"}],
        "paths": [],
    }
    response = _predict(
        _snapshot(
            (_node(TARGET), _node(
                test_id,
                qualified_name="demo.TargetTest#target()",
                kind=KnowledgeKind.METHOD,
            )),
            extra_context={"reachability": reachability},
        ),
        include_tests=True,
    )

    assert response.findings == ()
    assert response.affected_test_ids == ()


def test_cycles_terminate_without_reporting_the_source_as_impacted() -> None:
    other = "type:other"
    response = _predict(_snapshot(
        (_node(TARGET), _node(other)),
        (
            KnowledgeEdge(other, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
            KnowledgeEdge(TARGET, other, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        ),
    ))

    assert {item.canonical_subject_id for item in response.findings} == {other}
    assert TARGET not in {item.canonical_subject_id for item in response.findings}
    assert response.visited_node_count == 2
    assert response.visited_edge_count == 2


def test_diamond_uses_the_same_deterministic_shortest_path_for_reordered_input() -> None:
    left, right, consumer = "type:a", "type:b", "type:c"
    nodes = (_node(TARGET), _node(left), _node(right), _node(consumer))
    edges = (
        KnowledgeEdge(left, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        KnowledgeEdge(right, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        KnowledgeEdge(consumer, left, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        KnowledgeEdge(consumer, right, KnowledgeRelation.CALLS, CALL_EVIDENCE),
    )

    first = _predict(_snapshot(nodes, edges))
    second = _predict(_snapshot(tuple(reversed(nodes)), tuple(reversed(edges))))
    finding = next(
        item for item in first.findings if item.canonical_subject_id == consumer
    )

    assert first.to_json() == second.to_json()
    assert tuple(step.target_subject_id for step in finding.path.steps) == (
        left,
        consumer,
    )


def test_equal_depth_diamond_prefers_the_stronger_complete_path() -> None:
    left, right, consumer = "type:weak", "type:strong", "type:consumer"
    response = _predict(_snapshot(
        (_node(TARGET), _node(left), _node(right), _node(consumer)),
        (
            KnowledgeEdge(left, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
            KnowledgeEdge(right, TARGET, KnowledgeRelation.INHERITS, ("extends",)),
            KnowledgeEdge(consumer, left, KnowledgeRelation.DEPENDS_ON, ("uses",)),
            KnowledgeEdge(consumer, right, KnowledgeRelation.INHERITS, ("extends",)),
        ),
    ))
    finding = next(
        item for item in response.findings if item.canonical_subject_id == consumer
    )

    assert finding.path.relationships == (
        KnowledgeRelation.INHERITS,
        KnowledgeRelation.INHERITS,
    )


def test_module_constraint_narrows_a_pr134_ambiguity() -> None:
    first = _node(
        "type:first",
        qualified_name="demo.Thing",
        metadata=(("scope_id", "module-a"),),
    )
    second = _node(
        "type:second",
        qualified_name="demo.Thing",
        metadata=(("scope_id", "module-b"),),
    )
    response = _predict(
        _snapshot((first, second)),
        subject="demo.Thing",
        module="module-a",
    )

    assert response.resolution.status.value == "resolved"
    assert response.resolution.subject is not None
    assert response.resolution.subject.canonical_id == "type:first"


def test_multi_source_traversal_is_bounded_and_deterministic() -> None:
    second_root = "type:second-root"
    first_caller = "type:first-caller"
    second_caller = "type:second-caller"
    snapshot = _snapshot(
        (
            _node(TARGET),
            _node(second_root),
            _node(first_caller),
            _node(second_caller),
        ),
        (
            KnowledgeEdge(first_caller, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
            KnowledgeEdge(second_caller, second_root, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        ),
    )
    request = ImpactPredictionRequest(
        SubjectQuery(TARGET),
        additional_subjects=(SubjectQuery(second_root),),
        max_depth=1,
    )
    service = ImpactPredictionService.from_snapshot(snapshot)

    first = service.predict(request)
    second = service.predict(ImpactPredictionRequest.from_dict(request.to_dict()))

    assert first.to_json() == second.to_json()
    assert {item.canonical_subject_id for item in first.findings} == {
        first_caller,
        second_caller,
    }
    assert {item.path.source_subject_id for item in first.findings} == {
        TARGET,
        second_root,
    }


def test_high_degree_traversal_is_bounded_and_reports_truncation() -> None:
    caller_ids = tuple(f"type:caller-{index:05d}" for index in range(10_000))
    snapshot = _snapshot(
        (_node(TARGET), *(_node(identifier) for identifier in caller_ids)),
        tuple(
            KnowledgeEdge(identifier, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE)
            for identifier in caller_ids
        ),
    )

    response = _predict(snapshot, max_depth=1, limit=10)

    assert response.truncated is True
    assert len(response.findings) == 10
    assert response.total_candidate_count == 4_096
    assert response.omitted_count == 4_086
    assert response.visited_node_count == 4_097
    assert response.visited_edge_count == 10_000
    assert any("per-node bound" in item for item in response.limitations)


def test_response_rejects_tampered_evidence_ids_and_non_exact_closure() -> None:
    response = _predict(_authoritative_call_snapshot())

    tampered_record = deepcopy(response.to_dict())
    tampered_record["evidence_index"]["records"][0]["detail"]["relation"] = "imports"
    with pytest.raises(ValueError, match="evidence ID is inconsistent"):
        ImpactPredictionResponse.from_dict(tampered_record)

    missing_record = deepcopy(response.to_dict())
    missing_record["evidence_index"]["records"] = []
    with pytest.raises(ValueError, match="unresolvable evidence IDs"):
        ImpactPredictionResponse.from_dict(missing_record)

    unreferenced_record = deepcopy(response.to_dict())
    duplicate = deepcopy(unreferenced_record["evidence_index"]["records"][0])
    duplicate["subject_id"] = TARGET
    # Recomputing the ID would require production evidence helpers.  A duplicate
    # canonical record already proves that the serialized index cannot be loose.
    unreferenced_record["evidence_index"]["records"].append(duplicate)
    with pytest.raises(ValueError):
        ImpactPredictionResponse.from_dict(unreferenced_record)


def test_strict_deserialization_rejects_malformed_arrays_bool_ints_and_nan() -> None:
    request = ImpactPredictionRequest(SubjectQuery(TARGET)).to_dict()
    request["relations"] = "calls"
    with pytest.raises(TypeError, match="array"):
        ImpactPredictionRequest.from_dict(request)

    request = ImpactPredictionRequest(SubjectQuery(TARGET)).to_dict()
    request["max_depth"] = True
    with pytest.raises(TypeError, match="integer"):
        ImpactPredictionRequest.from_dict(request)

    response = _predict(_authoritative_call_snapshot()).to_dict()
    response["findings"] = {"not": "an array"}
    with pytest.raises(TypeError, match="array"):
        ImpactPredictionResponse.from_dict(response)

    response = _predict(_authoritative_call_snapshot()).to_dict()
    response["findings"][0]["score"]["value"] = math.nan
    with pytest.raises(ValueError, match="finite"):
        ImpactPredictionResponse.from_dict(response)


def test_absolute_path_leakage_is_rejected_at_request_and_response_boundaries() -> None:
    with pytest.raises(ValueError, match="absolute paths"):
        ImpactPredictionRequest(SubjectQuery(r"C:\private\Secret.java"))

    response = _predict(_authoritative_call_snapshot()).to_dict()
    response["limitations"].append(r"read C:\private\Secret.java")
    with pytest.raises(ValueError, match="absolute path"):
        ImpactPredictionResponse.from_dict(response)


def test_reordered_graph_input_produces_byte_identical_response() -> None:
    nodes = (_node(TARGET), _node(CALLER), _node("type:upstream"))
    edges = (
        KnowledgeEdge(CALLER, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
        KnowledgeEdge("type:upstream", CALLER, KnowledgeRelation.CALLS, CALL_EVIDENCE),
    )
    first_snapshot = _snapshot(nodes, edges)
    second_snapshot = _snapshot(tuple(reversed(nodes)), tuple(reversed(edges)))

    assert first_snapshot.snapshot_id == second_snapshot.snapshot_id
    assert _predict(first_snapshot).to_json().encode() == _predict(
        second_snapshot
    ).to_json().encode()


def test_warm_and_concurrent_predictions_are_byte_identical() -> None:
    service = ImpactPredictionService.from_snapshot(_authoritative_call_snapshot())
    request = ImpactPredictionRequest(SubjectQuery(TARGET))
    expected = service.predict(request).to_json()

    warm = tuple(service.predict(request).to_json() for _ in range(4))
    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent = tuple(executor.map(lambda _: service.predict(request).to_json(), range(32)))

    assert warm == (expected,) * 4
    assert concurrent == (expected,) * 32


def test_response_is_source_free_even_when_snapshot_contains_private_metadata() -> None:
    secret_path = r"C:\Users\private\src\Caller.java"
    secret_source = "private implementation body: do-not-copy"
    snapshot = _snapshot(
        (
            _node(TARGET),
            _node(CALLER, metadata=(("source", secret_path), ("body", secret_source))),
        ),
        (KnowledgeEdge(
            CALLER,
            TARGET,
            KnowledgeRelation.CALLS,
            CALL_EVIDENCE,
        ),),
    )

    response = _predict(snapshot)
    serialized = response.to_json()

    assert response.findings
    assert secret_path not in serialized
    assert secret_source not in serialized
    assert contains_absolute_path(response.to_dict()) is False


def test_prediction_does_not_mutate_snapshot_bytes_or_identifier() -> None:
    snapshot = _authoritative_call_snapshot()
    identifier = snapshot.snapshot_id
    before = SemanticSnapshotStore._serialize(snapshot)

    _predict(snapshot)

    assert snapshot.snapshot_id == identifier
    assert SemanticSnapshotStore._serialize(snapshot) == before
