from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import socket
import subprocess

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.impact_analysis import ImpactPredictionService
from moughorai.knowledge_graph import (
    KnowledgeGraph,
    KnowledgeKind,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.semantic_snapshot.models import canonical_json
from moughorai.subject_resolution import SubjectQuery
from moughorai.technical_debt import (
    TechnicalDebtCapabilityKind,
    TechnicalDebtRequest,
    TechnicalDebtResponse,
    TechnicalDebtService,
    TechnicalDebtState,
    render_technical_debt,
)

from test_pr142_technical_debt import (
    PROJECTS,
    _analyze,
    _architecture,
    _capability,
    _edge,
    _graph,
    _mixed_risk_report,
    _node,
    _request,
    _risk_report,
    _snapshot,
)


def _overlapping_cycle_snapshot() -> AtlasSemanticSnapshot:
    projects = ("alpha", "beta", "gamma", "delta")
    edges = (
        _edge("alpha", "beta"),
        _edge("beta", "gamma"),
        _edge("gamma", "alpha"),
        _edge("beta", "delta"),
        _edge("delta", "alpha"),
    )
    graph = KnowledgeGraph(tuple(_node(name) for name in projects), edges)
    architecture = _architecture()
    architecture["dependency_directions"] = [
        {
            "source": edge.source.removeprefix("project:"),
            "target": edge.target.removeprefix("project:"),
        }
        for edge in edges
    ]
    architecture["dependency_cycles"] = [
        ["alpha", "beta", "gamma"],
        ["alpha", "beta", "delta"],
    ]
    architecture["dependency_analysis"] = {
        "executed": True,
        "evidence_edge_count": len(edges),
    }
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": ".",
                "projects": [
                    {"name": name, "path": name, "dependencies": []}
                    for name in projects
                ],
            },
            "semantic_graph": graph.to_dict(),
            "architecture": architecture,
            "symbols": [],
        }),
        workspace_fingerprint="pr142-overlapping-cycles",
        analyzer_version="test-pr142/1",
    )


def _many_overlapping_cycle_snapshot(count: int = 10) -> AtlasSemanticSnapshot:
    branches = tuple(f"branch-{index:02d}" for index in range(count))
    projects = ("alpha", "beta", *branches)
    edges = (
        _edge("alpha", "beta"),
        *(
            edge
            for branch in branches
            for edge in (_edge("beta", branch), _edge(branch, "alpha"))
        ),
    )
    graph = KnowledgeGraph(tuple(_node(name) for name in projects), edges)
    architecture = _architecture()
    architecture["dependency_directions"] = [
        {
            "source": edge.source.removeprefix("project:"),
            "target": edge.target.removeprefix("project:"),
        }
        for edge in edges
    ]
    architecture["dependency_cycles"] = [
        ["alpha", "beta", branch] for branch in branches
    ]
    architecture["dependency_analysis"] = {
        "executed": True,
        "evidence_edge_count": len(edges),
    }
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": ".",
                "projects": [
                    {"name": name, "path": name, "dependencies": []}
                    for name in projects
                ],
            },
            "semantic_graph": graph.to_dict(),
            "architecture": architecture,
            "symbols": [],
        }),
        workspace_fingerprint=f"pr142-many-overlaps-{count}",
        analyzer_version="test-pr142/1",
    )


def test_missing_and_legacy_graphs_degrade_without_inventing_candidates() -> None:
    legacy = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {"root": ".", "projects": []},
            "symbols": [],
        }),
        workspace_fingerprint="pr142-legacy",
        analyzer_version="test-pr142/1",
    )
    response = _analyze(legacy)

    assert response.items == ()
    assert response.total_candidate_count == response.evaluated_count == 0
    assert _capability(
        response, TechnicalDebtCapabilityKind.CYCLE_EVIDENCE
    ).state is TechnicalDebtState.UNAVAILABLE


@pytest.mark.parametrize("tamper", ("producer", "graph", "evidence"))
def test_malformed_or_stale_risk_context_never_creates_or_removes_cycle_items(
    tamper: str,
) -> None:
    graph = _graph()
    risk = _risk_report(graph)
    broken = deepcopy(risk)
    if tamper == "producer":
        broken["producer_version"] = "foreign-risk/1"
    elif tamper == "graph":
        broken["graph_digest"] = "0" * 64
    else:
        broken["evidence_index"]["records"][0]["evidence_id"] = "evidence:" + "0" * 64

    baseline = _analyze(_snapshot(graph))
    response = _analyze(_snapshot(graph, risk_analysis=broken))

    assert response.total_candidate_count == baseline.total_candidate_count == 3
    assert {
        (item.source.canonical_id, item.target.canonical_id)
        for item in response.items
    } == {
        (item.source.canonical_id, item.target.canonical_id)
        for item in baseline.items
    }
    assert all(item.risk_context is None for item in response.items)
    assert all(not item.complexity_observed for item in response.items)
    assert _capability(
        response, TechnicalDebtCapabilityKind.RISK_CONTEXT
    ).state is TechnicalDebtState.INCOMPATIBLE


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("unavailable", TechnicalDebtState.UNAVAILABLE),
        ("incompatible", TechnicalDebtState.INCOMPATIBLE),
    ),
)
def test_unavailable_or_incompatible_impact_retains_explicitly_unranked_candidates(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: TechnicalDebtState,
) -> None:
    def unavailable(*_args: object, **_kwargs: object):
        if mode == "incompatible":
            raise ValueError("deliberately incompatible")
        return None

    monkeypatch.setattr(ImpactPredictionService, "predict", unavailable)
    response = _analyze()

    assert response.total_candidate_count == response.returned_count == 3
    assert response.ranked_count == 0
    assert response.unranked_count == 3
    assert all(
        item.rank is None
        and item.impact.state is expected
        and item.impact.affected_count == 0
        for item in response.items
    )
    assert _capability(
        response, TechnicalDebtCapabilityKind.ENGINEERING_IMPACT
    ).state is expected


def test_item_identity_is_independent_of_impact_fingerprint_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    represented = _analyze()

    monkeypatch.setattr(ImpactPredictionService, "predict", lambda *_args, **_kwargs: None)
    unavailable = _analyze()

    pair_to_id = lambda response: {
        (item.source.canonical_id, item.target.canonical_id): item.item_id
        for item in response.items
    }
    assert pair_to_id(represented) == pair_to_id(unavailable)
    assert all(item.impact_fingerprint is not None for item in represented.items)
    assert all(item.impact_fingerprint is None for item in unavailable.items)


def test_overlapping_cycles_merge_shared_directed_seam_with_plural_lineage() -> None:
    response = _analyze(_overlapping_cycle_snapshot())

    assert response.total_candidate_count == 6
    assert response.evaluated_count == 6
    assert response.unique_evaluated_count == 5
    assert response.equivalent_observation_count == 1
    assert response.unevaluated_count == 0
    assert response.output_omitted_count == 0
    assert response.returned_count == 5
    assert response.omitted_count == 1
    assert response.truncated is False
    shared = next(
        item for item in response.items
        if item.source.canonical_id == "project:alpha"
        and item.target.canonical_id == "project:beta"
    )
    assert len(shared.refactoring_advice_ids) == 2
    cycle_evidence = {
        record.evidence_id
        for record in response.evidence_index.records
        if record.producer == "atlas-pr137-cycle-adapter/1"
        and record.kind.value == "analysis_result"
        and record.subject_id.startswith("dependency-cycle:")
    }
    assert len(cycle_evidence) == 2
    assert cycle_evidence.issubset(shared.evidence_ids)
    assert _capability(
        response, TechnicalDebtCapabilityKind.ENGINEERING_IMPACT
    ).coverage == pytest.approx(5 / 6)


def test_many_overlapping_cycles_keep_all_ids_but_bound_retained_evidence() -> None:
    snapshot = _many_overlapping_cycle_snapshot(10)
    request = _request(limit=100, candidate_limit=100)
    first = _analyze(snapshot, request)
    second = _analyze(snapshot, request)

    assert first.to_json() == second.to_json()
    assert TechnicalDebtResponse.from_dict(first.to_dict()).to_dict() == first.to_dict()
    assert first.total_candidate_count == 30
    assert first.evaluated_count == 30
    assert first.unique_evaluated_count == 21
    assert first.equivalent_observation_count == 9
    shared = next(
        item for item in first.items
        if item.source.canonical_id == "project:alpha"
        and item.target.canonical_id == "project:beta"
    )
    assert len(shared.refactoring_advice_ids) == 10
    assert len(set(shared.refactoring_advice_ids)) == 10
    assert 1 <= len(shared.evidence_backed_refactoring_advice_ids) <= 6
    assert set(shared.evidence_backed_refactoring_advice_ids).issubset(
        shared.refactoring_advice_ids
    )
    assert shared.omitted_advice_evidence_count == (
        len(shared.refactoring_advice_ids)
        - len(shared.evidence_backed_refactoring_advice_ids)
    ) == 4
    assert len(shared.evidence_ids) <= 512
    assert any(
        "per-item bound" in limitation
        for limitation in shared.limitations
    )


def test_unranked_candidates_ignore_risk_for_ordering_and_use_only_item_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    snapshot = _snapshot(graph, risk_analysis=_risk_report(graph))
    monkeypatch.setattr(ImpactPredictionService, "predict", lambda *_args, **_kwargs: None)

    response = _analyze(snapshot)

    assert all(item.rank is None and item.risk_context is not None for item in response.items)
    assert len({item.risk_context.score for item in response.items}) > 1
    assert [item.item_id for item in response.items] == sorted(
        item.item_id for item in response.items
    )


def test_unexecuted_or_incomplete_cycle_evidence_never_becomes_debt() -> None:
    unexecuted = _analyze(_snapshot(architecture=_architecture(executed=False)))
    incomplete_graph = KnowledgeGraph(
        tuple(_node(name) for name in PROJECTS),
        _graph().edges[:-1],
    )
    incomplete = _analyze(_snapshot(
        incomplete_graph,
        architecture=_architecture(),
    ))

    assert unexecuted.items == ()
    assert incomplete.items == ()
    assert unexecuted.total_candidate_count == incomplete.total_candidate_count == 0


def test_reordered_equivalent_inputs_and_ties_are_byte_deterministic() -> None:
    first = _analyze(_snapshot(_graph()))
    second = _analyze(_snapshot(_graph(reverse=True)))

    assert _graph().stable_digest() == _graph(reverse=True).stable_digest()
    assert first.to_json() == second.to_json()
    assert [item.rank for item in first.items] == [1, 2, 3]


def test_strict_round_trip_rejects_unknown_fields_and_tampered_closure() -> None:
    payload = _analyze().to_dict()
    unknown = deepcopy(payload)
    unknown["future"] = "silently ignored"
    with pytest.raises(ValueError, match="unknown"):
        TechnicalDebtResponse.from_dict(unknown)

    nested_unknown = deepcopy(payload)
    nested_unknown["items"][0]["impact"]["future"] = 1
    with pytest.raises(ValueError, match="unknown"):
        TechnicalDebtResponse.from_dict(nested_unknown)

    missing = deepcopy(payload)
    missing["evidence_index"]["records"].pop()
    with pytest.raises(ValueError, match="evidence|closure|referenced"):
        TechnicalDebtResponse.from_dict(missing)

    source = deepcopy(payload)
    source["items"][0]["observation"] = "class Secret { token(); }"
    with pytest.raises(ValueError, match="canonical|source-free"):
        TechnicalDebtResponse.from_dict(source)


def test_complexity_subject_cannot_include_a_non_participant() -> None:
    graph = _graph()
    payload = _analyze(_snapshot(
        graph,
        risk_analysis=_mixed_risk_report(graph),
    )).to_dict()
    item = next(
        candidate for candidate in payload["items"]
        if candidate["source"]["canonical_id"] == "project:alpha"
        and candidate["target"]["canonical_id"] == "project:beta"
    )
    item["complexity_subject_ids"].append("project:gamma")

    with pytest.raises(ValueError) as raised:
        TechnicalDebtResponse.from_dict(payload)
    assert str(raised.value) == (
        "technical debt complexity context must belong to cycle participants"
    )


def test_complexity_evidence_must_cite_a_pr132_adapter_with_complexity_signal() -> None:
    graph = _graph()
    payload = _analyze(_snapshot(
        graph,
        risk_analysis=_mixed_risk_report(graph),
    )).to_dict()
    item = next(
        candidate for candidate in payload["items"]
        if candidate["source"]["canonical_id"] == "project:alpha"
        and candidate["target"]["canonical_id"] == "project:beta"
    )
    non_complexity_risk_id = item["risk_context"]["evidence_ids"][0]
    item["complexity_subject_ids"] = ["project:alpha"]
    item["complexity_evidence_ids"] = [non_complexity_risk_id]
    item["complexity_observed"] = True

    with pytest.raises(ValueError) as raised:
        TechnicalDebtResponse.from_dict(payload)
    assert str(raised.value) == (
        "technical debt complexity evidence does not match its exact subjects"
    )


def test_advice_ids_cannot_be_replaced_without_matching_adapter_digest() -> None:
    payload = _analyze().to_dict()
    item = payload["items"][0]
    fabricated = "refactoring-advice:" + "f" * 64
    item["refactoring_advice_ids"] = [fabricated]
    item["evidence_backed_refactoring_advice_ids"] = [fabricated]
    item["confidence_advice_id"] = fabricated
    item["omitted_advice_evidence_count"] = 0

    with pytest.raises(ValueError) as raised:
        TechnicalDebtResponse.from_dict(payload)
    assert str(raised.value) == (
        "technical debt item lineage does not match its adapter evidence"
    )


def test_impact_fingerprint_cannot_change_without_matching_adapter_evidence() -> None:
    payload = _analyze().to_dict()
    payload["items"][0]["impact_fingerprint"] = (
        "impact-prediction:" + "f" * 64
    )

    with pytest.raises(ValueError) as raised:
        TechnicalDebtResponse.from_dict(payload)
    assert str(raised.value) == (
        "technical debt item lineage does not match its adapter evidence"
    )


def test_private_paths_are_rejected_and_control_text_is_escaped() -> None:
    with pytest.raises(ValueError, match="source-free|absolute paths"):
        TechnicalDebtRequest(SubjectQuery(
            "C:\\private\\Secret.java",
            KnowledgeKind.TYPE,
        ))

    graph = _graph()
    control_nodes = tuple(
        type(node)(
            node.id,
            node.kind,
            node.name,
            qualified_name=(
                "alpha\x1b[31m" if node.id == "project:alpha" else node.qualified_name
            ),
            project_id=node.project_id,
            language=node.language,
            metadata=node.metadata,
        )
        for node in graph.nodes
    )
    response = _analyze(_snapshot(KnowledgeGraph(control_nodes, graph.edges)))
    rendered = render_technical_debt(response)

    assert "\x1b" not in rendered
    assert response.items
    assert "\\u001b" in rendered
    assert not contains_absolute_path(response.to_dict())
    assert not contains_absolute_path(rendered)


def test_analysis_is_in_memory_source_free_and_does_not_mutate_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    before = canonical_json(snapshot.to_dict())

    def forbidden(*_args: object, **_kwargs: object):
        raise AssertionError("external source/provider/rescan path was invoked")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    response = TechnicalDebtService.from_snapshot(snapshot).analyze(_request())

    assert response.returned_count == 3
    assert canonical_json(snapshot.to_dict()) == before
    assert "technical_debt" not in snapshot.semantic_context


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("limit", True),
        ("candidate_limit", 1.5),
        ("impact_depth", 0),
    ),
)
def test_request_rejects_boolean_fractional_and_out_of_range_bounds(
    field: str,
    value: object,
) -> None:
    payload = _request().to_dict()
    payload[field] = value

    with pytest.raises((TypeError, ValueError)):
        TechnicalDebtRequest.from_dict(payload)
