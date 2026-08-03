from __future__ import annotations

from copy import deepcopy

import pytest

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.refactoring_advisor.models import (
    RefactoringFamily,
    RefactoringRequest,
    RefactoringResponse,
    RefactoringCapabilityState as RefactoringState,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import SubjectQuery

from test_pr137_refactoring_advisor import (
    _advise,
    _architecture,
    _capability,
    _cycle_edges,
    _graph,
    _request,
    _snapshot,
)


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(architecture=_architecture(executed=False)),
        _snapshot(architecture=_architecture(evidence_edge_count=0)),
        _snapshot(graph=_graph(edges=_cycle_edges(authoritative=False))),
        _snapshot(
            graph=_graph(edges=_cycle_edges()[:-1]),
            architecture=_architecture(),
        ),
        _snapshot(
            architecture=_architecture((("alpha", "beta", "fabricated"),)),
        ),
    ),
)
def test_unexecuted_uncovered_fabricated_or_missing_hop_never_creates_advice(
    snapshot: AtlasSemanticSnapshot,
) -> None:
    response = _advise(snapshot=snapshot)

    assert response.advice == ()
    assert response.total_candidate_count == 0
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state in {
        RefactoringState.INSUFFICIENT,
        RefactoringState.PARTIAL,
    }


def test_graph_cycle_is_not_rediscovered_when_pr128_reported_none() -> None:
    snapshot = _snapshot(architecture=_architecture(()))
    response = _advise(snapshot=snapshot)

    assert response.advice == ()
    assert response.total_candidate_count == 0
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.AVAILABLE
    assert any(
        "unrepresented relationships remain unknown" in item
        for item in _capability(
            response, RefactoringFamily.CYCLE_BREAKING
        ).limitations
    )


def test_unsafe_authority_tokens_cannot_create_cycle_advice() -> None:
    unsafe = tuple(
        KnowledgeEdge(
            f"project:{source}",
            f"project:{target}",
            KnowledgeRelation.IMPORTS,
            (
                "calls",
                "global_symbol.metadata:imports:C:\\private\\Secret.java",
            ),
        )
        for source, target in (
            ("alpha", "beta"),
            ("beta", "gamma"),
            ("gamma", "alpha"),
        )
    )

    response = _advise(snapshot=_snapshot(graph=_graph(edges=unsafe)))

    assert response.advice == ()
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.INSUFFICIENT


def test_source_shaped_canonical_subject_is_sanitized_as_unavailable() -> None:
    secret = "class Secret { token(); }"
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                "project:alpha",
                KnowledgeKind.PROJECT,
                secret,
                qualified_name=secret,
                project_id="alpha",
            ),
            KnowledgeNode(
                "project:beta",
                KnowledgeKind.PROJECT,
                "beta",
                qualified_name="beta",
                project_id="beta",
            ),
        ),
        (
            KnowledgeEdge(
                "project:alpha",
                "project:beta",
                KnowledgeRelation.DEPENDS_ON,
                ("workspace.projects:alpha:dependencies:beta",),
            ),
            KnowledgeEdge(
                "project:beta",
                "project:alpha",
                KnowledgeRelation.DEPENDS_ON,
                ("workspace.projects:beta:dependencies:alpha",),
            ),
        ),
    )

    response = _advise(
        snapshot=_snapshot(
            graph=graph,
            architecture=_architecture(((secret, "beta"),), evidence_edge_count=2),
        ),
        request=RefactoringRequest(
            SubjectQuery("project:alpha", KnowledgeKind.PROJECT),
            include_impact=False,
        ),
    )

    assert response.resolution.status.value == "unavailable"
    assert response.advice == ()
    assert secret not in response.to_json()
    assert any(
        "source-free boundary" in item
        for item in response.resolution.limitations
    )


def test_names_duplicates_risk_patterns_search_and_git_cannot_create_advice() -> None:
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                "project:duplicate-service",
                KnowledgeKind.PROJECT,
                "DuplicateService",
                qualified_name="duplicate.service",
                project_id="DuplicateService",
            ),
            KnowledgeNode(
                "project:extract-hotspot",
                KnowledgeKind.PROJECT,
                "ExtractHotspot",
                qualified_name="extract.hotspot",
                project_id="ExtractHotspot",
            ),
        ),
        (),
    )
    snapshot = _snapshot(
        graph=graph,
        architecture=_architecture(()),
        additions={
            "design_patterns": {
                "findings": [{"pattern": "strategy", "participants": []}],
            },
            "risk_analysis": {
                "hotspots": [{"subject_id": "project:extract-hotspot", "score": 1.0}],
            },
            "semantic_search": {
                "hits": [{"subject_id": "project:duplicate-service", "score": 1.0}],
            },
            "git": {"co_changes": [["duplicate.service", "extract.hotspot"]]},
        },
    )
    request = RefactoringRequest(
        SubjectQuery("project:duplicate-service", KnowledgeKind.PROJECT),
        include_impact=False,
    )
    response = _advise(snapshot=snapshot, request=request)

    assert response.advice == ()
    assert all(
        item.state in {
            RefactoringState.UNAVAILABLE,
            RefactoringState.INSUFFICIENT,
            RefactoringState.AVAILABLE,
        }
        for item in response.capabilities
    )
    assert _capability(
        response, RefactoringFamily.DUPLICATE_CONSOLIDATION
    ).candidate_count == 0
    assert _capability(
        response, RefactoringFamily.EXTRACTION
    ).candidate_count == 0


def test_impact_enrichment_changes_context_not_candidate_membership() -> None:
    snapshot = _snapshot()
    without_impact = _advise(
        snapshot=snapshot,
        request=_request(include_impact=False),
    )
    with_impact = _advise(
        snapshot=snapshot,
        request=_request(include_impact=True),
    )

    def candidate_pairs(response: RefactoringResponse) -> set[frozenset[str]]:
        return {
            frozenset(item.canonical_id for item in advice.subjects)
            for advice in response.advice
        }

    assert with_impact.total_candidate_count == without_impact.total_candidate_count
    assert candidate_pairs(with_impact) == candidate_pairs(without_impact)
    assert all(
        item.impact.state is RefactoringState.UNAVAILABLE
        for item in without_impact.advice
    )
    assert all(
        item.impact.state in {
            RefactoringState.PARTIAL,
            RefactoringState.UNAVAILABLE,
            RefactoringState.INCOMPATIBLE,
        }
        for item in with_impact.advice
    )


def test_two_project_cycle_preserves_both_directed_seams() -> None:
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                "project:alpha", KnowledgeKind.PROJECT, "alpha",
                qualified_name="alpha", project_id="alpha",
            ),
            KnowledgeNode(
                "project:beta", KnowledgeKind.PROJECT, "beta",
                qualified_name="beta", project_id="beta",
            ),
        ),
        (
            KnowledgeEdge(
                "project:alpha", "project:beta", KnowledgeRelation.DEPENDS_ON,
                ("workspace.projects:alpha:dependencies:beta",),
            ),
            KnowledgeEdge(
                "project:beta", "project:alpha", KnowledgeRelation.DEPENDS_ON,
                ("workspace.projects:beta:dependencies:alpha",),
            ),
        ),
    )
    response = _advise(snapshot=_snapshot(
        graph=graph,
        architecture=_architecture((("alpha", "beta"),), evidence_edge_count=2),
    ))

    assert response.total_candidate_count == 2
    assert len(response.advice) == 2
    assert len({item.advice_id for item in response.advice}) == 2
    assert {
        (dict(item.attributes)["source"], dict(item.attributes)["target"])
        for item in response.advice
    } == {
        ("project:alpha", "project:beta"),
        ("project:beta", "project:alpha"),
    }


def test_old_snapshot_ambiguity_and_absolute_cycle_data_degrade_explicitly() -> None:
    old = _snapshot(architecture={
        "schema_version": 1,
        "dependency_cycles": [],
    })
    old_response = _advise(snapshot=old)
    assert old_response.advice == ()
    assert _capability(
        old_response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.INSUFFICIENT

    absolute = _snapshot(
        architecture=_architecture((("alpha", "C:\\private\\Secret.java"),)),
    )
    absolute_response = _advise(snapshot=absolute)
    assert absolute_response.advice == ()
    assert "C:\\private" not in absolute_response.to_json()


def test_valid_cycle_outside_requested_project_scope_is_not_misreported() -> None:
    graph = KnowledgeGraph(
        (*_graph().nodes, KnowledgeNode(
            "project:delta",
            KnowledgeKind.PROJECT,
            "delta",
            qualified_name="delta",
            project_id="delta",
        )),
        _cycle_edges(),
    )
    response = _advise(
        snapshot=_snapshot(graph=graph),
        request=RefactoringRequest(
            SubjectQuery("project:delta", KnowledgeKind.PROJECT),
            families=(RefactoringFamily.CYCLE_BREAKING,),
            include_impact=False,
        ),
    )

    capability = _capability(response, RefactoringFamily.CYCLE_BREAKING)
    assert response.advice == ()
    assert capability.state is RefactoringState.AVAILABLE
    assert any("requested canonical scope" in item for item in capability.limitations)


def test_malformed_cycle_record_keeps_valid_advice_explicitly_partial() -> None:
    architecture = _architecture()
    architecture["dependency_cycles"] = [
        ["alpha", "beta", "gamma"],
        42,
    ]

    response = _advise(snapshot=_snapshot(architecture=architecture))

    assert len(response.advice) == 3
    assert _capability(
        response, RefactoringFamily.CYCLE_BREAKING
    ).state is RefactoringState.PARTIAL


def test_response_rejects_tampered_evidence_and_source_shaped_narrative() -> None:
    encoded = _advise().to_dict()
    missing = deepcopy(encoded)
    missing["evidence_index"]["records"].pop()
    with pytest.raises(ValueError, match="evidence|closure|referenced"):
        RefactoringResponse.from_dict(missing)

    source_shaped = deepcopy(encoded)
    source_shaped["advice"][0]["rationale"] = "class Secret { token(); }"
    with pytest.raises(ValueError, match="source-free"):
        RefactoringResponse.from_dict(source_shaped)

    source_shaped_evidence = deepcopy(encoded)
    source_shaped_evidence["evidence_index"]["records"][0]["detail"] = {
        "payload": "class Secret { token(); }",
    }
    with pytest.raises(ValueError, match="source-free"):
        RefactoringResponse.from_dict(source_shaped_evidence)


def test_response_rejects_tampered_direction_roles_and_lineage() -> None:
    encoded = _advise().to_dict()
    direction = deepcopy(encoded)
    direction["advice"][0]["attributes"]["source"] = "project:not-a-subject"
    with pytest.raises(ValueError):
        RefactoringResponse.from_dict(direction)

    lineage = deepcopy(encoded)
    lineage["lineage"] = "tampered-lineage"
    with pytest.raises(ValueError, match="lineage|fingerprint|identity"):
        RefactoringResponse.from_dict(lineage)


def test_nested_contracts_reject_unknown_fields_and_source_shaped_subjects() -> None:
    encoded = _advise().to_dict()
    for path in (
        ("request", "subject"),
        ("resolution", "query"),
        ("resolution", "subject"),
    ):
        tampered = deepcopy(encoded)
        nested = tampered
        for part in path:
            nested = nested[part]
        nested["future_field"] = "silently-lost"
        with pytest.raises(ValueError, match="unknown"):
            RefactoringResponse.from_dict(tampered)

    source_shaped = deepcopy(encoded)
    source_shaped["resolution"]["subject"]["qualified_name"] = (
        "class Secret { token(); }"
    )
    with pytest.raises(ValueError, match="source-free"):
        RefactoringResponse.from_dict(source_shaped)


def test_response_rejects_tampered_estimate_component_contribution() -> None:
    encoded = _advise().to_dict()
    estimate = encoded["advice"][0]["expected_gain"]
    available = next(
        item for item in estimate["components"] if item["available"]
    )
    available["contribution"] = (
        0.0 if available["contribution"] != 0.0 else 0.125
    )

    with pytest.raises(ValueError, match="contribution|score"):
        RefactoringResponse.from_dict(encoded)


def test_response_rejects_numeric_score_for_unknown_effort() -> None:
    encoded = _advise().to_dict()
    effort = encoded["advice"][0]["effort"]
    assert effort["level"] == "unknown"
    assert effort["score"] is None
    effort["score"] = 0.5

    with pytest.raises(ValueError, match="unknown estimates"):
        RefactoringResponse.from_dict(encoded)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("limit", True),
        ("include_impact", 1),
        ("impact_depth", 1.5),
    ),
)
def test_request_deserialization_rejects_boolean_and_fractional_coercions(
    field: str,
    value: object,
) -> None:
    encoded = _request().to_dict()
    encoded[field] = value

    with pytest.raises((TypeError, ValueError)):
        RefactoringRequest.from_dict(encoded)
