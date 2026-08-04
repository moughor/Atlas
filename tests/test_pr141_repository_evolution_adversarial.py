from __future__ import annotations

from copy import deepcopy

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.repository_evolution import (
    EvolutionCapabilityKind,
    EvolutionSnapshotReference,
    EvolutionState,
    RepositoryEvolutionResponse,
    RepositoryEvolutionService,
)
from moughorai.repository_evolution.models import repository_evolution_result_digest
from moughorai.risk_analysis import RiskAnalysisReport, RiskMetricKind
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from test_pr141_repository_evolution import _mixed_pair, _snapshot_with_pr132_head


def _payload() -> dict[str, object]:
    return deepcopy(RepositoryEvolutionService().compare(*_mixed_pair()).to_dict())


def _resign(payload: dict[str, object]) -> None:
    unsigned = deepcopy(payload)
    unsigned.pop("result_digest", None)
    payload["result_digest"] = repository_evolution_result_digest(unsigned)


def _with_risk_payload(
    snapshot: AtlasSemanticSnapshot,
    risk_payload: dict[str, object],
    *,
    fingerprint: str,
) -> AtlasSemanticSnapshot:
    context = deepcopy(snapshot.to_dict()["semantic_context"])
    context["risk_analysis"] = risk_payload
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint=fingerprint,
        analyzer_version=snapshot.analyzer_version,
    )


def _replace_change_frequency_capability_record(
    risk_payload: dict[str, object],
    *,
    snapshot_id: str | None = None,
    producer: str | None = None,
) -> None:
    records = risk_payload["evidence_index"]["records"]
    selected_index = next(
        index
        for index, item in enumerate(records)
        if item["subject_id"] == "risk-capability:change_frequency"
    )
    original = EvidenceRecord.from_dict(records[selected_index])
    replacement = EvidenceRecord.create(
        original.kind,
        original.subject_id,
        producer or original.producer,
        snapshot_id or original.snapshot_id,
        source_refs=original.source_refs,
        scope=original.scope,
        language=original.language,
        detail=original.detail,
        limitations=original.limitations,
        reliability=original.reliability,
        specificity=original.specificity,
    )
    records[selected_index] = replacement.to_dict()
    capability = next(
        item
        for item in risk_payload["capabilities"]
        if item["metric"] == RiskMetricKind.CHANGE_FREQUENCY.value
    )
    capability["evidence_ids"] = [
        replacement.evidence_id if item == original.evidence_id else item
        for item in capability["evidence_ids"]
    ]


def test_snapshot_nested_integrity_mutation_is_rejected_before_comparison() -> None:
    base, head = _mixed_pair()
    base.semantic_context["semantic_graph"]["nodes"][0]["qualified_name"] = "forged.A"

    with pytest.raises(ValueError, match="snapshot failed integrity validation"):
        RepositoryEvolutionService().compare(base, head)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["evidence_index"]["records"][0].__setitem__(
                "reliability", 0.2
            ),
            "non-canonical evolution evidence",
        ),
        (
            lambda value: value["node_changes"][0]["confidence"].update(
                {"score": 0.5, "tier": "low"}
            ),
            "confidence is not reproducible",
        ),
        (
            lambda value: value.__setitem__(
                "input_fingerprint", "repository-evolution:" + "0" * 64
            ),
            "input fingerprint mismatch",
        ),
        (
            lambda value: value.__setitem__(
                "result_digest", "repository-evolution-result:" + "0" * 64
            ),
            "result digest mismatch",
        ),
    ],
)
def test_forged_evidence_confidence_fingerprint_and_result_digest_are_rejected(
    mutation,
    message: str,
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ValueError, match=message):
        RepositoryEvolutionResponse.from_dict(payload)


def test_evidence_cannot_be_reassigned_to_another_change_subject() -> None:
    payload = _payload()
    first, second = payload["node_changes"][:2]
    first["evidence_ids"] = list(second["evidence_ids"])
    first["confidence"] = deepcopy(second["confidence"])

    with pytest.raises(ValueError, match="evidence subject does not match"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_evidence_foreign_lineage_and_unreferenced_records_are_rejected() -> None:
    payload = _payload()
    payload["evidence_index"]["records"][0]["snapshot_id"] = "f" * 64
    payload["result_digest"] = ""

    with pytest.raises(ValueError):
        RepositoryEvolutionResponse.from_dict(payload)

    payload = _payload()
    duplicate = deepcopy(payload["evidence_index"]["records"][0])
    duplicate["evidence_id"] = "evidence:" + "f" * 64
    payload["evidence_index"]["records"].append(duplicate)
    payload["result_digest"] = ""
    with pytest.raises(ValueError):
        RepositoryEvolutionResponse.from_dict(payload)


def test_same_snapshot_object_with_forged_identifier_is_rejected() -> None:
    base, head = _mixed_pair()
    forged = base.to_dict()
    forged["snapshot_id"] = "0" * 64

    with pytest.raises(ValueError, match="identifier mismatch"):
        AtlasSemanticSnapshot.from_dict(forged)
    with pytest.raises(ValueError, match="snapshot failed integrity validation"):
        RepositoryEvolutionService().compare(
            AtlasSemanticSnapshot(
                base.schema_version,
                base.workspace_fingerprint,
                base.analyzer_version,
                base.history_reference,
                base.semantic_context,
                "0" * 64,
            ),
            head,
        )


def test_collection_shape_and_boolean_count_coercions_are_rejected() -> None:
    payload = _payload()
    payload["node_changes"] = {"not": "an array"}
    with pytest.raises(TypeError, match="must contain objects"):
        RepositoryEvolutionResponse.from_dict(payload)

    payload = _payload()
    payload["counts"]["total_node_change_count"] = True
    with pytest.raises(TypeError, match="must be an integer"):
        RepositoryEvolutionResponse.from_dict(payload)


@pytest.mark.parametrize("field", ["before_digest", "after_digest"])
def test_resigned_node_observation_must_match_its_evidence(field: str) -> None:
    payload = _payload()
    modified = next(
        item for item in payload["node_changes"] if item["change"] == "modified"
    )
    modified[field] = "f" * 64
    _resign(payload)

    with pytest.raises(ValueError, match="change evidence is inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_resigned_relation_count_must_match_its_evidence() -> None:
    payload = _payload()
    relation = payload["relation_changes"][0]
    if relation["change"] == "removed":
        relation["before_evidence_count"] += 7
    else:
        relation["after_evidence_count"] += 7
    _resign(payload)

    with pytest.raises(ValueError, match="change evidence is inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_resigned_visible_changed_fields_cannot_be_relabelled_as_metadata() -> None:
    payload = _payload()
    modified = next(
        item for item in payload["node_changes"] if item["change"] == "modified"
    )
    modified["changed_fields"] = ["metadata"]
    _resign(payload)

    with pytest.raises(ValueError, match="changed fields are inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_resigned_nonvisible_changed_field_must_match_change_evidence() -> None:
    payload = _payload()
    modified = next(
        item for item in payload["node_changes"] if item["change"] == "modified"
    )
    modified["changed_fields"] = sorted({*modified["changed_fields"], "metadata"})
    _resign(payload)

    with pytest.raises(ValueError, match="change evidence is inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


@pytest.mark.parametrize(
    "capability_name",
    ["rename_tracking", "api_compatibility", "security_evolution", "architectural_drift"],
)
def test_resigned_future_capability_cannot_be_forged_available(
    capability_name: str,
) -> None:
    payload = _payload()
    capability = next(
        item for item in payload["capabilities"]
        if item["capability"] == capability_name
    )
    capability.update({"state": "available", "limitations": []})
    _resign(payload)

    with pytest.raises(ValueError, match="capability is unsupported"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_resigned_overall_state_must_match_the_capability_contract() -> None:
    payload = _payload()
    payload["state"] = "available"
    _resign(payload)

    with pytest.raises(ValueError, match="overall state is inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_resigned_truncation_counts_cannot_hide_retained_results() -> None:
    payload = _payload()
    payload["counts"]["total_node_change_count"] += 1
    payload["counts"]["omitted_node_change_count"] += 1
    _resign(payload)
    with pytest.raises(ValueError, match="node truncation is inconsistent"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_strict_parsing_rejects_scalar_strings_and_unknown_evidence_fields() -> None:
    payload = _payload()
    payload["limitations"] = "not-an-array"
    with pytest.raises(TypeError, match="must be an array"):
        RepositoryEvolutionResponse.from_dict(payload)

    payload = _payload()
    payload["evidence_index"]["records"][0]["future"] = "field"
    with pytest.raises(ValueError, match="unknown fields"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_evidence_is_bounded_before_record_materialization() -> None:
    payload = _payload()
    payload["evidence_index"]["records"].extend(
        deepcopy(payload["evidence_index"]["records"][0]) for _ in range(50)
    )
    with pytest.raises(ValueError, match="exceeds its maximum count"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_direct_snapshot_reference_enforces_round_trip_text_bounds() -> None:
    with pytest.raises(ValueError, match="analyzer version must not be empty"):
        EvolutionSnapshotReference("a" * 64, "b" * 64, "x" * 4_097)

    reference = EvolutionSnapshotReference("a" * 64, "b" * 64, "  atlas/2  ")
    assert reference.analyzer_version == "atlas/2"
    assert EvolutionSnapshotReference.from_dict(reference.to_dict()) == reference


def test_unreferenced_git_head_evidence_cannot_override_commit_association() -> None:
    original = _snapshot_with_pr132_head("a" * 40, fingerprint="referenced-head")
    risk_payload = deepcopy(original.semantic_context["risk_analysis"])
    report = RiskAnalysisReport.from_dict(risk_payload)
    forged = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "risk-capability:change_frequency",
        report.producer_version,
        report.lineage,
        source_refs=("git-head:" + "f" * 40,),
        detail={
            "metric": RiskMetricKind.CHANGE_FREQUENCY.value,
            "input_fingerprint": report.lineage.removeprefix("risk-analysis:"),
        },
    )
    risk_payload["evidence_index"]["records"].append(forged.to_dict())
    base = _with_risk_payload(
        original,
        risk_payload,
        fingerprint="unreferenced-forged-head",
    )

    response = RepositoryEvolutionService().compare(
        base,
        _snapshot_with_pr132_head("b" * 40, fingerprint="referenced-other-head"),
    )

    assert response.base.git_head == "a" * 40
    assert response.capability(
        EvolutionCapabilityKind.COMMIT_ALIGNMENT
    ).state is EvolutionState.PARTIAL


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: _replace_change_frequency_capability_record(
            payload,
            snapshot_id="risk-analysis:" + "f" * 64,
        ),
        lambda payload: _replace_change_frequency_capability_record(
            payload,
            producer="forged-risk-producer/1",
        ),
    ],
)
def test_referenced_pr132_git_head_requires_exact_lineage_and_producer_contract(
    mutation,
) -> None:
    original = _snapshot_with_pr132_head("a" * 40, fingerprint="contract-source")
    risk_payload = deepcopy(original.semantic_context["risk_analysis"])
    mutation(risk_payload)
    forged = _with_risk_payload(
        original,
        risk_payload,
        fingerprint="forged-contract",
    )

    response = RepositoryEvolutionService().compare(
        forged,
        _snapshot_with_pr132_head("b" * 40, fingerprint="contract-head"),
    )
    capability = response.capability(EvolutionCapabilityKind.COMMIT_ALIGNMENT)

    assert response.base.git_head is None
    assert capability.state is EvolutionState.INCOMPATIBLE
    assert "malformed or conflicting" in " ".join(capability.limitations)
