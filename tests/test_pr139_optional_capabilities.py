from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    ChatCapabilityState,
    EngineeringChatContextBuilder,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.security_intelligence import (
    LegacyConfidence,
    SecurityCategory,
    SecurityIntelligenceService,
    SecurityLocation,
    SecurityProducerFinding,
    SecurityProducerReport,
    SecuritySeverity,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver


def _snapshot() -> AtlasSemanticSnapshot:
    projects = ("alpha", "beta", "gamma")
    graph = KnowledgeGraph(
        tuple(
            KnowledgeNode(
                f"project:{name}",
                KnowledgeKind.PROJECT,
                name,
                qualified_name=name,
                project_id=name,
                language="java",
            )
            for name in projects
        ),
        tuple(
            KnowledgeEdge(
                f"project:{source}",
                f"project:{target}",
                KnowledgeRelation.DEPENDS_ON,
                (f"workspace.projects:{source}:dependencies:{target}",),
            )
            for source, target in (
                ("alpha", "beta"),
                ("beta", "gamma"),
                ("gamma", "alpha"),
            )
        ),
    )
    architecture = {
        "schema_version": 1,
        "findings": [],
        "dependency_directions": [
            {"source": "alpha", "target": "beta"},
            {"source": "beta", "target": "gamma"},
            {"source": "gamma", "target": "alpha"},
        ],
        "dependency_cycles": [["alpha", "beta", "gamma"]],
        "bounded_contexts": [],
        "ports": [],
        "adapters": [],
        "infrastructure_layers": [],
        "dependency_analysis": {
            "executed": True,
            "evidence_edge_count": 3,
        },
        "classification_conflicts": [],
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
        workspace_fingerprint="pr139-optional-capabilities",
        analyzer_version="test-pr139/1",
    )


def test_chat_consumes_real_impact_and_refactoring_services_without_reimplementing_them() -> None:
    context = EngineeringChatContextBuilder().build(
        _snapshot(),
        question="What impact and refactoring should be reviewed for alpha?",
        subject="project:alpha",
        kind="project",
        capabilities=("impact", "refactoring"),
        token_budget=7_000,
    )
    capabilities = {item.name: item for item in context.capabilities}
    sections = {item.section_id: item for item in context.sections}

    assert capabilities["impact_prediction"].state in {
        ChatCapabilityState.AVAILABLE,
        ChatCapabilityState.PARTIAL,
    }
    assert capabilities["refactoring_advisor"].state in {
        ChatCapabilityState.AVAILABLE,
        ChatCapabilityState.PARTIAL,
    }
    assert sections["impact_prediction"].included_item_count > 0
    assert sections["refactoring_advisor"].included_item_count > 0
    selected = {
        evidence_id
        for section in (
            sections["impact_prediction"],
            sections["refactoring_advisor"],
        )
        for evidence_id in section.evidence_ids
    }
    assert selected
    assert selected.issubset({
        item.evidence_id for item in context.evidence_index.records
    })


def test_chat_consumes_a_real_published_pr138_finding_with_canonical_secret_id() -> None:
    project_id = "private-project-id"
    subject_id = "type:secret-0"
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                f"project:{project_id}",
                KnowledgeKind.PROJECT,
                project_id,
                qualified_name=project_id,
            ),
            KnowledgeNode(
                subject_id,
                KnowledgeKind.TYPE,
                "SecretLiteral0",
                metadata=(("path", "src/private/SecretLiteral0.java"),),
                qualified_name="private.SecretLiteral0",
                project_id=project_id,
                language="java",
            ),
        ),
        (
            KnowledgeEdge(
                f"project:{project_id}",
                subject_id,
                KnowledgeRelation.OWNS,
                ("semantic_graph.project_id",),
            ),
        ),
    )
    resolver = CanonicalSubjectResolver.from_graph(graph)
    producer = SecurityProducerReport(
        project_id=project_id,
        language="java",
        analyzed_categories=(SecurityCategory.SECRETS,),
        findings=(SecurityProducerFinding(
            SecurityCategory.SECRETS,
            "ATLAS-SECRET-TEST",
            "legacy-fingerprint:" + hashlib.sha256(b"finding-0").hexdigest(),
            SecuritySeverity.HIGH,
            LegacyConfidence.HIGH,
            "CWE-798",
            "OWASP-A07",
            SecurityLocation("src/private/SecretLiteral0.java", 1, 1),
        ),),
        source_files=1,
        warning_count=0,
        producer_version="test-security-producer/1",
    )
    report = SecurityIntelligenceService(
        resolver,
        snapshot_id=f"semantic-graph:{resolver.graph_digest}",
    ).build_published_report((producer,))
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {"root": ".", "projects": []},
            "semantic_graph": graph.to_dict(),
            "security_intelligence": report.to_dict(),
        }),
        workspace_fingerprint="pr139-security-capability",
        analyzer_version="test-pr139/1",
    )

    evidence_id = report.findings[0].evidence_ids[0]
    result = AskEngine(LlmClient(ScriptedLlmProvider((
        f"One security finding was observed. {evidence_id}",
    )))).ask(
        snapshot,
        AskRequest(
            "Review security for the selected type.",
            subject=subject_id,
            kind="type",
            capabilities=("security",),
        ),
    )

    assert result.context is not None
    context = result.context
    capabilities = {item.name: item for item in context.capabilities}
    sections = {item.section_id: item for item in context.sections}
    assert capabilities["security_intelligence"].state in {
        ChatCapabilityState.AVAILABLE,
        ChatCapabilityState.PARTIAL,
    }
    assert sections["security_intelligence"].included_item_count == 1
    assert sections["security_intelligence"].evidence_ids
    capability_summary = sections["security_intelligence"].content[
        "capabilities"
    ]
    assert capability_summary["total_item_count"] == 9
    assert capability_summary["included_item_count"] == 3
    assert capability_summary["omitted_item_count"] == 6
    exposed_capability_evidence = {
        evidence_id
        for item in capability_summary["items"]
        for evidence_id in item["evidence_ids"]
    }
    assert exposed_capability_evidence
    assert exposed_capability_evidence.issubset(
        set(sections["security_intelligence"].evidence_ids)
    )
    assert result.grounded is True
import hashlib
