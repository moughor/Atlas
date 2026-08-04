from __future__ import annotations

from dataclasses import replace
import json
import hashlib

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_explain import ExplainEngine
from moughorai.ai_explain.repository_projection import RepositoryExplanationProjector
from moughorai.ai_explain.repository_report import RepositoryReportRenderer
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.prompts.semantic import SemanticPromptBuilder
from moughorai.security_intelligence import (
    LegacyConfidence,
    SecurityCategory,
    SecurityIntelligenceReport,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityLocation,
    SecurityProducerFinding,
    SecurityProducerReport,
    SecuritySeverity,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver


_RAW_RULE_ID = "ATLAS-SECRET-RAW-999"
_RAW_LITERAL = "password=hunter2"
_RAW_PATH_PREFIX = "src/private/SecretLiteral"
_PROJECT_ID = "private-project-id"
_GRAPH_FINDING_CAPACITY = 20


def _base_snapshot(*, graph_variant: str = "canonical") -> AtlasSemanticSnapshot:
    project_id = f"project:{_PROJECT_ID}"
    type_nodes = tuple(
        KnowledgeNode(
            f"type:secret-{index}",
            KnowledgeKind.TYPE,
            f"SecretLiteral{index}",
            metadata=(("path", f"{_RAW_PATH_PREFIX}{index}.java"),),
            qualified_name=f"private.SecretLiteral{index}",
            project_id=_PROJECT_ID,
            language="java",
        )
        for index in range(_GRAPH_FINDING_CAPACITY)
    )
    extra_nodes = (
        KnowledgeNode(
            f"concept:{graph_variant}",
            KnowledgeKind.CONCEPT,
            graph_variant,
        ),
    ) if graph_variant != "canonical" else ()
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                project_id,
                KnowledgeKind.PROJECT,
                _PROJECT_ID,
                qualified_name=_PROJECT_ID,
            ),
            *type_nodes,
            *extra_nodes,
        ),
        tuple(
            KnowledgeEdge(
                project_id,
                node.id,
                KnowledgeRelation.OWNS,
                (
                    "semantic_graph.project_id:z",
                    "semantic_graph.project_id:a",
                ),
            )
            for node in type_nodes
        ),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {"root": "demo"},
            "semantic_graph": graph.to_dict(),
        }),
        workspace_fingerprint="security-ai-test",
        analyzer_version="test",
        history_reference=1,
    )


def _producer_findings(count: int) -> tuple[SecurityProducerFinding, ...]:
    return tuple(
        SecurityProducerFinding(
            SecurityCategory.SECRETS,
            _RAW_RULE_ID,
            "legacy-fingerprint:" + hashlib.sha256(
                f"finding-{index}".encode("utf-8")
            ).hexdigest(),
            SecuritySeverity.HIGH,
            LegacyConfidence.HIGH,
            "CWE-798",
            "OWASP-A07",
            SecurityLocation(f"{_RAW_PATH_PREFIX}{index}.java", index + 1, 1),
        )
        for index in range(count)
    )


def _report(
    findings: tuple[SecurityProducerFinding, ...],
    *,
    limitations: tuple[str, ...] = (),
) -> SecurityIntelligenceReport:
    producer = SecurityProducerReport(
        project_id=_PROJECT_ID,
        language="java",
        analyzed_categories=(SecurityCategory.SECRETS,),
        findings=findings,
        source_files=max(1, len(findings)),
        warning_count=0,
        producer_version="test-security-producer/1",
        limitations=limitations,
    )
    return SecurityIntelligenceService(
        None,
        snapshot_id="security-ai-test",
    ).analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SECRETS,),
            limit=100,
        ),
        (producer,),
    )


def _published_report(
    findings: tuple[SecurityProducerFinding, ...],
    *,
    resolver: object | None = None,
) -> SecurityIntelligenceReport:
    base = _base_snapshot()
    raw_graph = base.semantic_context["semantic_graph"]
    assert isinstance(raw_graph, dict)
    selected_resolver = resolver or CanonicalSubjectResolver.from_graph(
        KnowledgeGraph.from_dict(raw_graph)
    )
    producer = SecurityProducerReport(
        project_id=_PROJECT_ID,
        language="java",
        analyzed_categories=(SecurityCategory.SECRETS,),
        findings=findings,
        source_files=max(1, len(findings)),
        warning_count=0,
        producer_version="test-security-producer/1",
    )
    return SecurityIntelligenceService(
        selected_resolver,
        snapshot_id=f"semantic-graph:{selected_resolver.graph_digest}",
    ).build_published_report((producer,))


def _snapshot(
    security: object = None,
    *,
    include_security: bool = True,
    graph_variant: str = "canonical",
) -> AtlasSemanticSnapshot:
    base = _base_snapshot(graph_variant=graph_variant)
    context = dict(base.semantic_context)
    if include_security:
        context["security_intelligence"] = security
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="security-ai-test",
        analyzer_version="test",
        history_reference=1,
    )


def _prompt_text(context: dict[str, object]) -> str:
    result = SemanticPromptBuilder().build(
        "Explain this repository",
        WorkspaceSemanticContext(context),
        template="atlas-repository-explanation-v1",
        variables={"subject": "repository"},
    )
    return "\n".join(message.content for message in result.request.messages)


def test_default_security_projection_uses_only_bounded_aggregate_metadata() -> None:
    report = _report(
        _producer_findings(15),
        limitations=(
            f"Affected path {_RAW_PATH_PREFIX}0.java",
            f"Rule {_RAW_RULE_ID}",
            "x" * 511,
        ),
    )

    projected = RepositoryExplanationProjector.compact_security_intelligence(
        report.to_dict()
    )
    serialized = json.dumps(projected, sort_keys=True)

    assert projected["status"] == "partial"
    assert projected["finding_count"] == 15
    assert projected["included_finding_count"] == 12
    assert projected["omitted_finding_count"] == 3
    assert "findings" not in projected
    category = projected["categories"][0]
    assert category["category"] == "secrets"
    assert category["state"] == "partial"
    assert category["finding_count"] == 15
    assert category["included_finding_count"] == 12
    assert category["included_severity_counts"] == {"high": 12}
    assert category["included_evidence_count"] >= 12
    assert category["included_confidence"]["status"] == "available"
    for forbidden in (
        _RAW_RULE_ID,
        _RAW_LITERAL,
        _RAW_PATH_PREFIX,
        "private-project-id",
        '"finding_id"',
        '"location"',
        '"rule_id"',
    ):
        assert forbidden not in serialized
    assert len(serialized.encode("utf-8")) < 10_000

    rendered = RepositoryReportRenderer().render({
        "workspace": {"repository_name": "demo"},
        "repository_report": {"status": "available"},
        "security_intelligence": projected,
    })
    prompt = _prompt_text({"security_intelligence": projected})
    assert "## Security Intelligence" in rendered
    assert "secrets" in rendered
    for forbidden in (
        _RAW_RULE_ID,
        _RAW_LITERAL,
        _RAW_PATH_PREFIX,
        '"finding_id"',
        '"location"',
        '"project_id"',
        '"rule_id"',
    ):
        assert forbidden not in rendered
        assert forbidden not in prompt


def test_security_producer_rejects_secret_shaped_limitation_text() -> None:
    with pytest.raises(ValueError, match="source-free semantic text"):
        _report(_producer_findings(1), limitations=(_RAW_LITERAL,))


def test_legacy_absence_is_compatible_and_malformed_context_is_unavailable() -> None:
    legacy = RepositoryExplanationProjector().project(
        _snapshot(include_security=False)
    ).to_dict()
    malformed = RepositoryExplanationProjector().project(
        _snapshot({"schema_version": 999})
    ).to_dict()["security_intelligence"]

    assert "security_intelligence" not in legacy
    assert malformed["status"] == "unavailable"
    assert malformed["categories"]
    assert {
        item["state"] for item in malformed["categories"]
    } == {"incompatible"}


def test_zero_security_findings_never_claim_repository_is_secure() -> None:
    projected = RepositoryExplanationProjector.compact_security_intelligence(
        _report(()).to_dict()
    )
    rendered = RepositoryReportRenderer().render({
        "workspace": {"repository_name": "demo"},
        "repository_report": {"status": "available"},
        "security_intelligence": projected,
    })
    prompt = _prompt_text({"security_intelligence": projected})

    assert projected["status"] == "available"
    assert projected["finding_count"] == 0
    assert (
        "No structured findings were reported within the analyzed scope; "
        "this does not establish that the repository is secure."
    ) in rendered
    assert "never establishes that a repository is secure" in prompt


def test_default_security_projection_is_deterministic_for_reversed_findings() -> None:
    findings = _producer_findings(15)
    forward = RepositoryExplanationProjector.compact_security_intelligence(
        _report(findings).to_dict()
    )
    reverse = RepositoryExplanationProjector.compact_security_intelligence(
        _report(tuple(reversed(findings))).to_dict()
    )

    assert forward == reverse
    assert RepositoryReportRenderer().render({
        "security_intelligence": forward,
    }) == RepositoryReportRenderer().render({
        "security_intelligence": reverse,
    })


def test_default_explain_engine_renders_available_security_intelligence() -> None:
    report = _published_report(_producer_findings(1))

    result = ExplainEngine().explain(_snapshot(report.to_dict()))

    assert "## Security Intelligence" in result.markdown
    assert "secrets" in result.markdown
    assert "- **Finding count:** 1" in result.markdown
    for forbidden in (
        _RAW_RULE_ID,
        _RAW_LITERAL,
        _RAW_PATH_PREFIX,
        "private-project-id",
    ):
        assert forbidden not in result.markdown


def test_default_projection_rejects_stale_security_graph_lineage() -> None:
    report = _published_report(_producer_findings(1))

    projected = RepositoryExplanationProjector().project(
        _snapshot(report.to_dict(), graph_variant="changed-graph")
    ).to_dict()["security_intelligence"]

    assert projected["status"] == "unavailable"
    assert projected["finding_count"] == 0
    assert {
        item["state"] for item in projected["categories"]
    } == {"incompatible"}


def test_default_projection_revalidates_canonical_security_subjects() -> None:
    base = _base_snapshot()
    canonical = CanonicalSubjectResolver.from_snapshot(base)

    class StaleSubjectResolver:
        graph = canonical.graph
        graph_digest = canonical.graph_digest
        limitations = canonical.limitations

        @staticmethod
        def candidate_for_graph_id(node_id: str):
            candidate = canonical.candidate_for_graph_id(node_id)
            if candidate is not None and candidate.path == (
                f"{_RAW_PATH_PREFIX}0.java"
            ):
                return replace(
                    candidate,
                    qualified_name="stale.SecretLiteral0",
                )
            return candidate

    report = _published_report(
        _producer_findings(1),
        resolver=StaleSubjectResolver(),
    )

    projected = RepositoryExplanationProjector().project(
        _snapshot(report.to_dict())
    ).to_dict()["security_intelligence"]

    assert projected["status"] == "unavailable"
    assert projected["finding_count"] == 0
    assert {
        item["state"] for item in projected["categories"]
    } == {"incompatible"}
