from __future__ import annotations

from copy import deepcopy

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.impact_analysis import (
    BreakingChangeState,
    ImpactCapability,
    ImpactChangeKind,
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
from moughorai.reachability import (
    CoverageStatus,
    ProjectEvidence,
    ReachabilityAnalysisService,
    ReachabilityEvidenceBundle,
    ReachabilitySeed,
    RootCategory,
)
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import ResolutionStatus, SubjectQuery


TARGET = "type:target"
CALLER = "type:caller"
OTHER = "type:other"
OTHER_CALLER = "type:other-caller"
CALL_EVIDENCE = ("moughorai.call_graph.v1:calls",)


def _node(
    identifier: str,
    *,
    visibility: str = "public",
) -> KnowledgeNode:
    name = identifier.rsplit(":", 1)[-1]
    return KnowledgeNode(
        identifier,
        KnowledgeKind.TYPE,
        name,
        qualified_name=f"demo.{name}",
        project_id="demo",
        language="java",
        metadata=(("visibility", visibility),),
    )


def _snapshot(*, include_additional_root: bool = False) -> AtlasSemanticSnapshot:
    nodes = [_node(TARGET), _node(CALLER)]
    edges = [
        KnowledgeEdge(CALLER, TARGET, KnowledgeRelation.CALLS, CALL_EVIDENCE),
    ]
    if include_additional_root:
        nodes.extend((_node(OTHER), _node(OTHER_CALLER)))
        edges.append(KnowledgeEdge(
            OTHER_CALLER,
            OTHER,
            KnowledgeRelation.CALLS,
            CALL_EVIDENCE,
        ))
    graph = KnowledgeGraph(tuple(nodes), tuple(edges))
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr136-strict-model-fixture",
        analyzer_version="test-analyzer/1",
    )


def _graph_snapshot(
    graph: KnowledgeGraph,
    **extra_context: object,
) -> AtlasSemanticSnapshot:
    context: dict[str, object] = {
        "schema_version": 1,
        "semantic_graph": graph.to_dict(),
        "symbols": [],
    }
    context.update(extra_context)
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr136-strict-model-custom-fixture",
        analyzer_version="test-analyzer/1",
    )


def _response(
    *,
    request: ImpactPredictionRequest | None = None,
    include_additional_root: bool = False,
) -> ImpactPredictionResponse:
    service = ImpactPredictionService.from_snapshot(
        _snapshot(include_additional_root=include_additional_root)
    )
    return service.predict(request or ImpactPredictionRequest(SubjectQuery(TARGET)))


def _replace(value: object, old: str, new: str) -> object:
    if isinstance(value, dict):
        return {key: _replace(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, old, new) for item in value]
    return new if value == old else value


def test_request_rejects_source_shaped_queries_and_non_enum_objects() -> None:
    with pytest.raises(ValueError, match="semantic identity text"):
        ImpactPredictionRequest(SubjectQuery(
            'class PrivateSecret { String token = "do-not-copy"; }'
        ))
    with pytest.raises(ValueError, match="one line"):
        ImpactPredictionRequest(SubjectQuery("demo.Target\nprivate body"))
    with pytest.raises(ValueError, match="source-shaped text"):
        ImpactPredictionRequest(SubjectQuery("password = secret"))
    with pytest.raises(ValueError, match="source-shaped text"):
        ImpactPredictionRequest(SubjectQuery("def private_token()"))
    with pytest.raises(ValueError, match="bounded semantic identifiers"):
        ImpactPredictionRequest(
            SubjectQuery(TARGET), changed_members=("token=secret",)
        )
    with pytest.raises(TypeError, match="ImpactChangeKind"):
        ImpactPredictionRequest(
            SubjectQuery(TARGET), change_kind=object()  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="ImpactCapabilityState"):
        ImpactCapability("calls", object())  # type: ignore[arg-type]


def test_response_rejects_source_shaped_candidates_and_evidence() -> None:
    payload = _response().to_dict()
    payload["findings"][0]["subject"]["name"] = "class Leaked { }"
    with pytest.raises(ValueError, match="semantic identity text"):
        ImpactPredictionResponse.from_dict(payload)

    payload = _response().to_dict()
    serialized = payload["evidence_index"]["records"][0]
    old_id = serialized["evidence_id"]
    unsafe = EvidenceRecord.create(
        EvidenceKind(str(serialized["kind"])),
        str(serialized["subject_id"]),
        str(serialized["producer"]),
        str(serialized["snapshot_id"]),
        source_refs=("private implementation body:do-not-copy",),
        scope=str(serialized["scope"]),
        language=str(serialized["language"]),
        detail=serialized["detail"],
        limitations=tuple(serialized["limitations"]),
        reliability=float(serialized["reliability"]),
        specificity=float(serialized["specificity"]),
    )
    payload["evidence_index"]["records"][0] = unsafe.to_dict()
    payload = _replace(payload, old_id, unsafe.evidence_id)
    with pytest.raises(ValueError, match="source-shaped evidence"):
        ImpactPredictionResponse.from_dict(payload)  # type: ignore[arg-type]

    payload = _response().to_dict()
    serialized = payload["evidence_index"]["records"][0]
    old_id = serialized["evidence_id"]
    unsafe = EvidenceRecord.create(
        EvidenceKind(str(serialized["kind"])),
        str(serialized["subject_id"]),
        str(serialized["producer"]),
        str(serialized["snapshot_id"]),
        source_refs=tuple(serialized["source_refs"]),
        scope=str(serialized["scope"]),
        language=str(serialized["language"]),
        detail={"relation": "private source body with spaces"},
        limitations=tuple(serialized["limitations"]),
        reliability=float(serialized["reliability"]),
        specificity=float(serialized["specificity"]),
    )
    payload["evidence_index"]["records"][0] = unsafe.to_dict()
    payload = _replace(payload, old_id, unsafe.evidence_id)
    with pytest.raises(ValueError, match="source-free semantic metadata"):
        ImpactPredictionResponse.from_dict(payload)  # type: ignore[arg-type]


def test_response_rejects_source_shaped_prose_and_evidence_identity() -> None:
    payload = _response().to_dict()
    payload["findings"][0]["explanation"] = (
        "private String token = do-not-copy;"
    )
    with pytest.raises(ValueError, match="source-shaped text"):
        ImpactPredictionResponse.from_dict(payload)

    payload = _response().to_dict()
    serialized = payload["evidence_index"]["records"][0]
    old_id = serialized["evidence_id"]
    unsafe = EvidenceRecord.create(
        EvidenceKind(str(serialized["kind"])),
        "class PrivateSecret { token }",
        str(serialized["producer"]),
        str(serialized["snapshot_id"]),
        source_refs=tuple(serialized["source_refs"]),
        scope=str(serialized["scope"]),
        language=str(serialized["language"]),
        detail=serialized["detail"],
        limitations=tuple(serialized["limitations"]),
        reliability=float(serialized["reliability"]),
        specificity=float(serialized["specificity"]),
    )
    payload["evidence_index"]["records"][0] = unsafe.to_dict()
    payload = _replace(payload, old_id, unsafe.evidence_id)
    with pytest.raises(ValueError, match="semantic identity text"):
        ImpactPredictionResponse.from_dict(payload)  # type: ignore[arg-type]


def test_duplicate_evidence_is_rejected_instead_of_silently_normalized() -> None:
    payload = _response().to_dict()
    payload["evidence_index"]["records"].append(deepcopy(
        payload["evidence_index"]["records"][0]
    ))
    with pytest.raises(ValueError, match="duplicate records"):
        ImpactPredictionResponse.from_dict(payload)


def test_lineage_fingerprint_and_evidence_snapshot_are_bound() -> None:
    original = _response().to_dict()

    payload = deepcopy(original)
    payload["lineage"] = "different-snapshot"
    with pytest.raises(ValueError, match="fingerprint is inconsistent"):
        ImpactPredictionResponse.from_dict(payload)

    payload = deepcopy(original)
    payload["input_fingerprint"] = "impact-prediction:" + "0" * 64
    with pytest.raises(ValueError, match="fingerprint is inconsistent"):
        ImpactPredictionResponse.from_dict(payload)

    payload = deepcopy(original)
    serialized = payload["evidence_index"]["records"][0]
    old_id = serialized["evidence_id"]
    foreign = EvidenceRecord.create(
        EvidenceKind(str(serialized["kind"])),
        str(serialized["subject_id"]),
        str(serialized["producer"]),
        "foreign-snapshot",
        source_refs=tuple(serialized["source_refs"]),
        scope=str(serialized["scope"]),
        language=str(serialized["language"]),
        detail=serialized["detail"],
        limitations=tuple(serialized["limitations"]),
        reliability=float(serialized["reliability"]),
        specificity=float(serialized["specificity"]),
    )
    payload["evidence_index"]["records"][0] = foreign.to_dict()
    payload = _replace(payload, old_id, foreign.evidence_id)
    with pytest.raises(ValueError, match="evidence snapshot differs"):
        ImpactPredictionResponse.from_dict(payload)  # type: ignore[arg-type]


def test_confidence_is_bound_to_formula_and_retained_path_evidence() -> None:
    payload = _response().to_dict()
    confidence = payload["findings"][0]["confidence"]
    confidence["score"] = 0.9
    confidence["tier"] = "high"
    with pytest.raises(ValueError, match="score is inconsistent"):
        ImpactPredictionResponse.from_dict(payload)

    payload = _response().to_dict()
    confidence = payload["findings"][0]["confidence"]
    confidence["support"] = 1.0
    confidence["score"] = round(float(confidence["coverage"]), 4)
    confidence["tier"] = "medium"
    with pytest.raises(ValueError, match="path evidence"):
        ImpactPredictionResponse.from_dict(payload)


def test_breaking_change_kind_and_proof_are_evidence_bound() -> None:
    response = _response(request=ImpactPredictionRequest(
        SubjectQuery(TARGET),
        change_kind=ImpactChangeKind.REMOVAL,
        changed_api_surface=("run()",),
    ))
    assert response.breaking_change.state is BreakingChangeState.POTENTIALLY_BREAKING

    payload = response.to_dict()
    payload["breaking_change"]["change_kind"] = "signature"
    with pytest.raises(ValueError, match="differs from its request"):
        ImpactPredictionResponse.from_dict(payload)

    payload = response.to_dict()
    payload["breaking_change"]["state"] = "proven_breaking"
    with pytest.raises(ValueError, match="before/after evidence"):
        ImpactPredictionResponse.from_dict(payload)


def test_finding_capability_and_request_bounds_are_enforced() -> None:
    payload = _response().to_dict()
    payload["findings"][0]["capability_state"] = "unavailable"
    with pytest.raises(ValueError, match="available or partial"):
        ImpactPredictionResponse.from_dict(payload)

    payload = _response(
        request=ImpactPredictionRequest(
            SubjectQuery(TARGET),
            additional_subjects=(SubjectQuery(OTHER),),
        ),
        include_additional_root=True,
    ).to_dict()
    payload["request"]["limit"] = 1
    with pytest.raises(ValueError, match="result limit"):
        ImpactPredictionResponse.from_dict(payload)


def test_multi_root_request_and_response_round_trip_exactly() -> None:
    request = ImpactPredictionRequest(
        SubjectQuery(TARGET),
        additional_subjects=(SubjectQuery(OTHER),),
    )
    response = _response(
        request=request,
        include_additional_root=True,
    )

    assert tuple(item.query for item in response.additional_resolutions) == (
        SubjectQuery(OTHER),
    )
    assert response.additional_resolutions[0].status is ResolutionStatus.RESOLVED
    assert {item.path.source_subject_id for item in response.findings} == {
        TARGET,
        OTHER,
    }
    assert ImpactPredictionResponse.from_dict(response.to_dict()).to_dict() == (
        response.to_dict()
    )

    with pytest.raises(ValueError, match="must not be repeated"):
        ImpactPredictionRequest(
            SubjectQuery(TARGET),
            additional_subjects=(SubjectQuery(TARGET),),
        )


def test_multi_root_breaking_ids_attribute_only_the_evidenced_source() -> None:
    private_root = KnowledgeNode(
        "type:private-root",
        KnowledgeKind.TYPE,
        "PrivateRoot",
        qualified_name="demo.PrivateRoot",
        project_id="demo",
        language="java",
        metadata=(("visibility", "private"),),
    )
    public_root = KnowledgeNode(
        "type:public-root",
        KnowledgeKind.TYPE,
        "PublicRoot",
        qualified_name="demo.PublicRoot",
        project_id="demo",
        language="java",
        metadata=(("visibility", "public"),),
    )
    service = ImpactPredictionService.from_snapshot(_graph_snapshot(
        KnowledgeGraph((private_root, public_root))
    ))

    response = service.predict(ImpactPredictionRequest(
        SubjectQuery(private_root.id),
        change_kind=ImpactChangeKind.REMOVAL,
        additional_subjects=(SubjectQuery(public_root.id),),
    ))

    assert response.breaking_change.state is BreakingChangeState.POTENTIALLY_BREAKING
    assert response.possible_breaking_change_ids == (public_root.id,)
    assert {
        record.subject_id
        for record in response.evidence_index.records
        if record.evidence_id in response.breaking_change.evidence_ids
    } == {public_root.id}


def test_relation_filter_does_not_inject_pr131_call_test_links() -> None:
    root_method = KnowledgeNode(
        "method:root",
        KnowledgeKind.METHOD,
        "run",
        qualified_name="demo.Root#run()",
        project_id="demo",
        language="java",
        metadata=(("visibility", "public"),),
    )
    test_method = KnowledgeNode(
        "method:test",
        KnowledgeKind.METHOD,
        "testRun",
        qualified_name="demo.RootTest#testRun()",
        project_id="demo",
        language="java",
    )
    graph = KnowledgeGraph(
        (root_method, test_method),
        (KnowledgeEdge(
            test_method.id,
            root_method.id,
            KnowledgeRelation.CALLS,
            ("fixture:calls",),
        ),),
    )
    reachability = ReachabilityAnalysisService().analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            roots=(ReachabilitySeed(
                test_method.id,
                RootCategory.TEST,
                "demo",
                source_refs=("test-root",),
            ),),
            projects=(ProjectEvidence(
                "demo",
                ("java",),
                roots=CoverageStatus.COMPLETE,
                calls=CoverageStatus.COMPLETE,
            ),),
        ),
        snapshot_lineage="pr131-strict-model-fixture",
    )
    service = ImpactPredictionService.from_snapshot(_graph_snapshot(
        graph, reachability=reachability.to_dict()
    ))

    response = service.predict(ImpactPredictionRequest(
        SubjectQuery(root_method.id),
        relations=(KnowledgeRelation.IMPORTS,),
        include_tests=True,
    ))

    assert response.affected_test_ids == ()
    assert all(
        KnowledgeRelation.CALLS not in finding.path.relationships
        for finding in response.findings
    )


def test_mixed_override_and_call_confidence_validates_and_round_trips() -> None:
    base = KnowledgeNode(
        "method:base",
        KnowledgeKind.METHOD,
        "run",
        qualified_name="demo.Base#run()",
        project_id="demo",
        language="java",
        metadata=(("visibility", "public"),),
    )
    override = KnowledgeNode(
        "method:override",
        KnowledgeKind.METHOD,
        "run",
        qualified_name="demo.Child#run()",
        project_id="demo",
        language="java",
        metadata=(("visibility", "public"),),
    )
    caller = KnowledgeNode(
        "method:caller",
        KnowledgeKind.METHOD,
        "call",
        qualified_name="demo.Caller#call()",
        project_id="demo",
        language="java",
    )
    graph = KnowledgeGraph(
        (base, override, caller),
        (
            KnowledgeEdge(
                override.id,
                base.id,
                KnowledgeRelation.OVERRIDES,
                ("global_symbol.metadata:overrides:demo.Base#run()",),
            ),
            KnowledgeEdge(
                caller.id,
                override.id,
                KnowledgeRelation.CALLS,
                CALL_EVIDENCE,
            ),
        ),
    )
    service = ImpactPredictionService.from_snapshot(_graph_snapshot(graph))

    response = service.predict(ImpactPredictionRequest(SubjectQuery(base.id)))
    caller_finding = next(
        finding
        for finding in response.findings
        if finding.canonical_subject_id == caller.id
    )

    assert caller_finding.path.relationships == (
        KnowledgeRelation.OVERRIDES,
        KnowledgeRelation.CALLS,
    )
    assert caller_finding.confidence.support == 0.8562
    assert caller_finding.confidence.score == 0.5155
    assert ImpactPredictionResponse.from_dict(response.to_dict()).to_dict() == (
        response.to_dict()
    )
