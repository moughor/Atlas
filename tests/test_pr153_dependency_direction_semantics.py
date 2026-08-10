from __future__ import annotations

import json
from pathlib import Path

from moughorai import public_api
from moughorai.ai_ask import EngineeringChatContextBuilder
from moughorai.ai_ask.models import ChatContext
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.impact_analysis import ImpactPredictionRequest, ImpactPredictionService
from moughorai.impact_analysis.models import ImpactPredictionAnalysis
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.structured_explanation import (
    ExplanationRequest,
    StructuredExplanationService,
)
from moughorai.subject_resolution import SubjectQuery


DEPENDENT = "project:a"
DEPENDENCY = "project:b"
EDGE_EVIDENCE = "workspace.projects:a:dependencies:b"
SNAPSHOT_ID = "77c4d03bdf2e002644dda847167553730483a40dbaa5978db5597e64f45d473b"
GRAPH_DIGEST = "4d2f04e143efb62047dc3080ab989484d9d8d435f2b2cfe1758e2e8a8324ddd7"

OUTGOING_FACT_ID = (
    "explanation-fact:5dc582e0d2632a7d83b69d13582f1a3621cf47f582a02652217148fe8f4caf9f"
)
OUTGOING_EVIDENCE_ID = (
    "evidence:3773d94a5b1a33369b262eeefdd13850c70fab13d38b3600b64b7826ee920234"
)
INCOMING_FACT_ID = (
    "explanation-fact:be0d5486d162cfd7a66f07700fa3bf4aa09c2a1484f2189a9073eeef10618beb"
)
INCOMING_EVIDENCE_ID = (
    "evidence:66700d9044b6512c6420466c267a45605ff670f43ea2fe006eeade024eeb7a91"
)
EDGE_SOURCE_REFS = (
    "semantic-graph-edge:0dba29e422df403a55853af05f81f497dd39f8d1d7919426d49bdd05def068c2",
    EDGE_EVIDENCE,
)


def _snapshot(
    *,
    reverse: bool = False,
    relation: KnowledgeRelation = KnowledgeRelation.DEPENDS_ON,
) -> AtlasSemanticSnapshot:
    nodes = (
        KnowledgeNode(
            DEPENDENT,
            KnowledgeKind.PROJECT,
            "a",
            qualified_name="a",
            project_id="a",
        ),
        KnowledgeNode(
            DEPENDENCY,
            KnowledgeKind.PROJECT,
            "b",
            qualified_name="b",
            project_id="b",
        ),
    )
    edge = KnowledgeEdge(
        DEPENDENT,
        DEPENDENCY,
        relation,
        (EDGE_EVIDENCE,),
    )
    graph = KnowledgeGraph(
        tuple(reversed(nodes)) if reverse else nodes,
        (edge,),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": ".",
                "projects": [
                    {"name": "a", "path": "a", "dependencies": ["b"]},
                    {"name": "b", "path": "b", "dependencies": []},
                ],
            },
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr153-dependency-direction",
        analyzer_version="test-pr153/1",
    )


def _relationship(snapshot: AtlasSemanticSnapshot, subject: str):
    explanation = StructuredExplanationService(snapshot).explain(
        ExplanationRequest(subject, kind="project")
    )
    fact = next(
        item for item in explanation.facts if item.kind.value == "relationship"
    )
    record = explanation.evidence_index.get(fact.evidence_ids[0])
    assert record is not None
    return explanation, fact, record


def _attributes(fact) -> dict[str, object]:
    return {item.key: item.value for item in fact.attributes}


def _section(context: ChatContext, section_id: str):
    return next(
        item for item in context.sections if item.section_id == section_id
    )


def test_dependency_roles_preserve_canonical_orientation_and_identity() -> None:
    snapshot = _snapshot()
    graph = KnowledgeGraph.from_dict(snapshot.semantic_context["semantic_graph"])

    assert snapshot.snapshot_id == SNAPSHOT_ID
    assert graph.stable_digest() == GRAPH_DIGEST
    assert tuple(
        (edge.source, edge.relation, edge.target)
        for edge in graph.outgoing(DEPENDENT)
    ) == ((DEPENDENT, KnowledgeRelation.DEPENDS_ON, DEPENDENCY),)

    outgoing, outgoing_fact, outgoing_record = _relationship(snapshot, DEPENDENT)
    incoming, incoming_fact, incoming_record = _relationship(snapshot, DEPENDENCY)
    outgoing_attributes = _attributes(outgoing_fact)
    incoming_attributes = _attributes(incoming_fact)

    assert outgoing_attributes["direction"] == "outgoing"
    assert outgoing_attributes["canonical_source_subject_id"] == DEPENDENT
    assert outgoing_attributes["canonical_target_subject_id"] == DEPENDENCY
    assert outgoing_attributes["subject_relative_role"] == "DEPENDENCY_OF_SUBJECT"

    assert incoming_attributes["direction"] == "incoming"
    assert incoming_attributes["canonical_source_subject_id"] == DEPENDENT
    assert incoming_attributes["canonical_target_subject_id"] == DEPENDENCY
    assert incoming_attributes["subject_relative_role"] == "DEPENDENT_OF_SUBJECT"
    assert outgoing_attributes["subject_relative_role"] != (
        incoming_attributes["subject_relative_role"]
    )

    assert outgoing_fact.statement == (
        "The canonical graph records a depends_on relationship from a to b."
    )
    assert incoming_fact.statement == outgoing_fact.statement
    assert outgoing_fact.fact_id == OUTGOING_FACT_ID
    assert outgoing_fact.evidence_ids == (OUTGOING_EVIDENCE_ID,)
    assert incoming_fact.fact_id == INCOMING_FACT_ID
    assert incoming_fact.evidence_ids == (INCOMING_EVIDENCE_ID,)
    assert outgoing_record.source_refs == EDGE_SOURCE_REFS
    assert incoming_record.source_refs == EDGE_SOURCE_REFS

    assert outgoing.context_digest != (
        "906d312f502275d6bcf23a4a8ba39845659aed428bc34a10282f47e6ef9ad455"
    )
    assert incoming.context_digest != (
        "378df1d0ed2ca8128a42d77515dcad8edd82fc965fb07045ea39f05a492d80f3"
    )


def test_non_dependency_relationship_does_not_invent_dependency_roles() -> None:
    _, fact, _ = _relationship(
        _snapshot(relation=KnowledgeRelation.RELATED_TO),
        DEPENDENCY,
    )
    attributes = _attributes(fact)

    assert attributes["relation"] == "related_to"
    assert "subject_relative_role" not in attributes
    assert "canonical_source_subject_id" not in attributes
    assert "canonical_target_subject_id" not in attributes


def test_reverse_impact_context_separates_traversal_and_canonical_orientation() -> None:
    snapshot = _snapshot()
    request = ImpactPredictionRequest(
        SubjectQuery(DEPENDENCY, kind=KnowledgeKind.PROJECT),
        max_depth=4,
        limit=1,
    )
    analysis = ImpactPredictionService.from_snapshot(snapshot).analyze(request)
    legacy_response = analysis.response.to_json()
    aggregate_serialization = analysis.aggregate.to_json()
    finding = analysis.response.findings[0]
    step = finding.path.steps[0]

    assert finding.subject.canonical_id == DEPENDENT
    assert finding.category.value == "project_dependent"
    assert finding.direct is True
    assert step.source_subject_id == DEPENDENCY
    assert step.target_subject_id == DEPENDENT
    assert step.relation is KnowledgeRelation.DEPENDS_ON
    assert step.reverse is True

    assert analysis.aggregate.total_impact_count == 1
    assert analysis.aggregate.unique_affected_project_count == 1
    assert analysis.aggregate.direct_affected_project_count == 1
    assert analysis.aggregate.transitive_affected_project_count == 0
    assert analysis.aggregate.depth_histogram == ((1, 1),)
    assert analysis.aggregate.visited_node_count == 2
    assert analysis.aggregate.visited_edge_count == 1
    assert analysis.aggregate.traversal_complete is True

    context = EngineeringChatContextBuilder().build(
        snapshot,
        question="If I modify this project, what parts could be affected?",
        subject=DEPENDENCY,
        kind="project",
        result_limit=1,
        token_budget=7_000,
    )
    representative = _section(context, "impact_prediction")
    aggregate = _section(context, "impact_aggregate")
    compact_finding = representative.content["findings"][0]
    compact_path = compact_finding["path"]
    compact_step = compact_path["steps"][0]

    assert compact_path["source_subject_id"] == DEPENDENCY
    assert compact_path["target_subject_id"] == DEPENDENT
    assert compact_step == {
        "affected_subject_role": "DEPENDENT_OF_CHANGED_SUBJECT",
        "canonical_relation": "depends_on",
        "canonical_source_subject_id": DEPENDENT,
        "canonical_target_subject_id": DEPENDENCY,
        "evidence_ids": step.evidence_ids,
        "strength": step.strength.value,
        "traversal": "reverse",
        "traversal_source_subject_id": DEPENDENCY,
        "traversal_target_subject_id": DEPENDENT,
    }
    assert not (
        compact_step["canonical_source_subject_id"] == DEPENDENCY
        and compact_step["canonical_target_subject_id"] == DEPENDENT
    )
    assert representative.total_item_count == 1
    assert representative.included_item_count == 1
    assert representative.omitted_item_count == 0
    assert aggregate.content["aggregate"]["total_impact_count"] == 1

    assert analysis.response.to_json() == legacy_response
    assert analysis.aggregate.to_json() == aggregate_serialization
    assert ImpactPredictionAnalysis.from_dict(analysis.to_dict()).to_dict() == (
        analysis.to_dict()
    )
    assert ChatContext.from_dict(context.to_dict()).to_dict() == context.to_dict()


def test_equivalent_reordered_inputs_remain_deterministic() -> None:
    forward = _snapshot()
    reordered = _snapshot(reverse=True)

    assert forward.to_dict() == reordered.to_dict()
    for subject in (DEPENDENT, DEPENDENCY):
        first = StructuredExplanationService(forward).explain(
            ExplanationRequest(subject, kind="project")
        )
        second = StructuredExplanationService(reordered).explain(
            ExplanationRequest(subject, kind="project")
        )
        assert first.to_json() == second.to_json()

    request = ImpactPredictionRequest(SubjectQuery(DEPENDENCY), limit=1)
    first_analysis = ImpactPredictionService.from_snapshot(forward).analyze(request)
    second_analysis = ImpactPredictionService.from_snapshot(reordered).analyze(request)
    assert first_analysis.to_json() == second_analysis.to_json()


def test_prompt_contract_defines_dependency_and_traversal_semantics() -> None:
    for prompt in (
        SemanticPromptBuilder.EXPLAIN_ANYTHING_TEMPLATE.system,
        SemanticPromptBuilder.ENGINEERING_CHAT_TEMPLATE.system,
    ):
        assert "SOURCE --depends_on--> TARGET means SOURCE depends on TARGET" in prompt
        assert "SOURCE is DEPENDENT_OF_SUBJECT" in prompt
        assert "TARGET is DEPENDENCY_OF_SUBJECT" in prompt
        assert "subject_relative_role" in prompt
        assert "depends_on edge in reverse" in prompt
        assert "traversal order" in prompt
        assert "canonical dependency direction" in prompt

    assert "do not prove runtime usage" in (
        SemanticPromptBuilder.ENGINEERING_CHAT_TEMPLATE.system
    )


def test_snapshot_and_public_api_contracts_remain_unchanged() -> None:
    snapshot = _snapshot()
    before = SemanticSnapshotStore._serialize(snapshot)

    StructuredExplanationService(snapshot).explain(
        ExplanationRequest(DEPENDENCY, kind="project")
    )
    ImpactPredictionService.from_snapshot(snapshot).analyze(
        ImpactPredictionRequest(SubjectQuery(DEPENDENCY), limit=1)
    )

    assert snapshot.snapshot_id == SNAPSHOT_ID
    assert SemanticSnapshotStore._serialize(snapshot) == before
    assert AtlasSemanticSnapshot.from_dict(snapshot.to_dict()).to_dict() == (
        snapshot.to_dict()
    )

    fixture = Path(__file__).parent / "fixtures" / "public_api_v1.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    assert expected["public_api_version"] == public_api.PUBLIC_API_VERSION
    assert expected["signatures"] == public_api.public_api_manifest()
    assert public_api.public_api_compatibility_issues() == ()
