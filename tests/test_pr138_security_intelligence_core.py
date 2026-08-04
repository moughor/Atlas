from __future__ import annotations

import json
from dataclasses import replace
from itertools import repeat
from types import SimpleNamespace

import pytest

import moughorai.security_intelligence.models as security_models
import moughorai.security_intelligence.service as security_service
from moughorai.security_analysis import (
    Confidence,
    SecurityFinding,
    Severity,
    SourceLocation,
    TraceStep,
)
from moughorai.security_intelligence import (
    SecurityCapability,
    SecurityCapabilityState,
    SecurityCategory,
    SecurityIntelligenceReport,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityLocation,
    SecurityPriority,
    SecurityPriorityComponent,
    SecurityPriorityTier,
    SecurityProducerReport,
    SecurityScope,
    SecuritySeverity,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeNode
from moughorai.semantic_evidence import (
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver
from moughorai.security_intelligence.models import (
    security_intelligence_finding_id,
)


def _legacy(
    *,
    rule: str = "ATLAS-SQL-001",
    path: str = "src/main/java/demo/App.java",
    line: int = 3,
    severity: Severity = Severity.HIGH,
) -> SecurityFinding:
    return SecurityFinding(
        rule,
        "legacy title",
        "legacy message with sensitive prose",
        severity,
        Confidence.HIGH,
        "CWE-89",
        "A03:2021",
        SourceLocation(path, line, 2),
        properties=(("literal", "must-not-escape"),),
    )


def _producer(
    *findings: SecurityFinding,
    project: str = "demo",
    version: str = "atlas-java-security/1",
    limitations: tuple[str, ...] = (),
    warning_count: int = 0,
) -> SecurityProducerReport:
    return SecurityProducerReport.from_findings(
        findings,
        project_id=project,
        source_files=2,
        producer_version=version,
        limitations=limitations,
        warning_count=warning_count,
    )


def test_producer_boundary_drops_legacy_prose_and_rejects_absolute_paths() -> None:
    legacy = _legacy()
    report = _producer(legacy)
    serialized = report.to_json()
    assert "legacy title" not in serialized
    assert "legacy message" not in serialized
    assert "must-not-escape" not in serialized
    assert legacy.fingerprint not in serialized
    assert report.findings[0].legacy_fingerprint.startswith(
        "legacy-fingerprint:"
    )
    assert report.to_dict() == SecurityProducerReport.from_dict(report.to_dict()).to_dict()
    with pytest.raises(ValueError, match="workspace-relative"):
        _producer(_legacy(path="C:/private/App.java"))


def test_service_deduplicates_only_exact_sink_identity_and_is_reproducible() -> None:
    first = _producer(_legacy(), version="producer-a/1")
    second = _producer(_legacy(), version="producer-b/1")
    request = SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
        limit=10,
    )
    forward = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (first, second)
    )
    reverse = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (second, first)
    )
    assert len(forward.findings) == 1
    assert forward.to_dict() == reverse.to_dict()
    assert forward.to_json() == reverse.to_json()
    assert (
        forward.to_dict()
        == SecurityIntelligenceReport.from_dict(forward.to_dict()).to_dict()
    )


def test_direct_report_constructor_normalizes_before_evidence_replay() -> None:
    report = SecurityIntelligenceService(
        None, snapshot_id="snapshot"
    ).analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
            limit=10,
        ),
        (_producer(_legacy()),),
    )
    assert len(report.limitations) > 1

    reordered = replace(
        report,
        limitations=tuple(reversed(report.limitations)),
    )

    assert reordered.limitations == report.limitations
    assert (
        SecurityIntelligenceReport.from_dict(reordered.to_dict()).to_dict()
        == reordered.to_dict()
    )


def test_nested_project_relative_path_maps_only_unique_canonical_suffix() -> None:
    candidate = SimpleNamespace(
        canonical_id="type:demo.App",
        kind=SimpleNamespace(value="type"),
        qualified_name="demo.App",
        project="demo",
        project_scopes=("demo",),
        language="java",
        path="modules/app/src/main/java/demo/App.java",
    )
    graph = SimpleNamespace(nodes=(SimpleNamespace(id="graph-node"),), edges=())

    class Resolver:
        graph_digest = "a" * 64
        limitations = ()

        def __init__(self) -> None:
            self.graph = graph

        @staticmethod
        def candidate_for_graph_id(node_id: str):
            assert node_id == "graph-node"
            return candidate

    result = SecurityIntelligenceService(
        Resolver(), snapshot_id="snapshot"
    ).analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()), _producer(project="other")),
    )
    assert result.findings[0].canonical_subject_id == "type:demo.App"
    assert result.findings[0].canonical_subject_name == "demo.App"
    for change in (
        {"canonical_subject_kind": "module"},
        {"canonical_subject_name": "forged.Name"},
    ):
        with pytest.raises(
            ValueError,
            match="canonical security finding evidence is inconsistent",
        ):
            replace(
                result,
                findings=(replace(result.findings[0], **change),),
            )

    finding = result.findings[0]
    forged_project = replace(
        finding,
        project_id="other",
        finding_id=security_intelligence_finding_id(
            project_id="other",
            language=finding.language,
            category=finding.category,
            rule_id=finding.rule_id,
            location=finding.location,
            producer_versions=finding.producer_versions,
            snapshot_id=result.snapshot_id,
            canonical_subject_id=finding.canonical_subject_id,
            evidence_ids=finding.evidence_ids,
        ),
    )
    with pytest.raises(
        ValueError,
        match="security finding evidence is inconsistent",
    ):
        replace(result, findings=(forged_project,))

    graph_record = next(
        record
        for record in result.evidence_index.records
        if record.kind is EvidenceKind.GRAPH_NODE
    )
    forged_graph_record = EvidenceRecord.create(
        graph_record.kind,
        graph_record.subject_id,
        graph_record.producer,
        graph_record.snapshot_id,
        source_refs=("semantic_graph.node_ref:" + "b" * 64,),
        scope=graph_record.scope,
        language=graph_record.language,
        detail=graph_record.detail,
        limitations=graph_record.limitations,
        reliability=graph_record.reliability,
        specificity=graph_record.specificity,
    )
    forged_graph_index = EvidenceIndex(
        (
            forged_graph_record
            if record.evidence_id == graph_record.evidence_id
            else record
            for record in result.evidence_index.records
        ),
        frozen=True,
    )
    with pytest.raises(ValueError, match="graph evidence shape"):
        replace(result, evidence_index=forged_graph_index)


def test_filters_and_explicit_unavailable_categories_are_deterministic() -> None:
    report = _producer(
        _legacy(severity=Severity.HIGH),
        _legacy(rule="ATLAS-PATH-001", line=9, severity=Severity.MEDIUM),
    )
    request = SecurityIntelligenceRequest(
        projects=("demo",),
        categories=(SecurityCategory.SQL_INJECTION, SecurityCategory.XSS),
        severities=(SecuritySeverity.HIGH,),
        limit=10,
    )
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (report,)
    )
    assert [item.category for item in result.findings] == [
        SecurityCategory.SQL_INJECTION
    ]
    capabilities = {item.category: item for item in result.capabilities}
    assert capabilities[SecurityCategory.SQL_INJECTION].state is SecurityCapabilityState.ANALYZED
    assert capabilities[SecurityCategory.XSS].state is SecurityCapabilityState.NOT_ANALYZED
    assert any("XSS" in item for item in capabilities[SecurityCategory.XSS].limitations)


def test_published_scoped_query_does_not_reuse_aggregate_coverage() -> None:
    builder = SecurityIntelligenceService(None, snapshot_id="snapshot")
    published = builder.build_published_report((_producer(_legacy()),))
    service = SecurityIntelligenceService(
        None, snapshot_id="snapshot", published_report=published
    )
    unfiltered = service.analyze(SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,), limit=10
    ))
    assert unfiltered.capabilities[0].state is SecurityCapabilityState.ANALYZED
    assert unfiltered.capabilities[0].source_files == 2
    assert unfiltered.capabilities[0].coverage == 1.0

    scoped = service.analyze(SecurityIntelligenceRequest(
        projects=("demo",),
        categories=(SecurityCategory.SQL_INJECTION,),
        limit=10,
    ))
    assert scoped.capabilities[0].state is SecurityCapabilityState.PARTIAL
    assert scoped.capabilities[0].source_files == 0
    assert scoped.capabilities[0].coverage is None
    assert any(
        "cannot be recalculated" in item
        for item in scoped.capabilities[0].limitations
    )


def test_warnings_limitations_and_incomplete_coverage_are_partial() -> None:
    complete = _producer(_legacy(), project="one")
    partial = _producer(
        project="two",
        limitations=("Producer analysis was isolated by source set.",),
        warning_count=1,
    )
    request = SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
        limit=10,
    )
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (complete, partial)
    )
    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.PARTIAL
    assert any("warning" in item for item in capability.limitations)


def test_capability_supports_large_validated_repository_project_count() -> None:
    capability = SecurityCapability(
        SecurityCategory.SQL_INJECTION,
        SecurityCapabilityState.ANALYZED,
        languages=("java",),
        project_ids=tuple(f"module-{index:04d}" for index in range(1_442)),
        source_files=1_442,
        coverage=1.0,
        producer_versions=("atlas-java-security/1",),
    )
    assert len(capability.project_ids) == 1_442
    assert SecurityCapability.from_dict(capability.to_dict()).to_dict() == capability.to_dict()


def test_large_workspace_capability_deduplicates_shared_producer_metadata() -> None:
    reports = tuple(
        _producer(project=f"module-{index:03d}")
        for index in range(65)
    )

    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
            limit=10,
        ),
        reports,
    )

    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.ANALYZED
    assert len(capability.project_ids) == 65
    assert capability.languages == ("java",)
    assert capability.producer_versions == ("atlas-java-security/1",)
    assert len(capability.evidence_ids) == 1
    assert result.evidence_index.get(capability.evidence_ids[0]) is not None
    assert len(result.evidence_index.records) == 1

    with pytest.raises(ValueError, match="capability evidence is inconsistent"):
        replace(
            result,
            capabilities=(replace(capability, source_files=999),),
        )


def test_symbol_scope_requires_and_filters_exact_canonical_identity() -> None:
    with pytest.raises(ValueError, match="canonical subject IDs"):
        SecurityIntelligenceRequest(scope=SecurityScope.SYMBOL)
    request = SecurityIntelligenceRequest(
        scope=SecurityScope.SYMBOL,
        canonical_subject_ids=("subject:missing",),
        categories=(SecurityCategory.SQL_INJECTION,),
    )
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (_producer(_legacy()),)
    )
    assert result.findings == ()
    assert result.capabilities[0].state is SecurityCapabilityState.PARTIAL
    assert result.capabilities[0].coverage is None
    assert any(
        "canonical symbol scope" in item
        for item in result.capabilities[0].limitations
    )


def test_ai_projection_is_bounded_source_free_and_uses_approved_remediation() -> None:
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
            limit=10,
        ),
        (_producer(_legacy()),),
    )
    context = result.to_ai_context(maximum_findings=1)
    serialized = json.dumps(context, sort_keys=True)
    assert context["status"] == "available"
    assert context["findings"][0]["cwe"] == ["CWE-89"]
    assert "remediation" in context["findings"][0]
    assert "safe_example" not in serialized
    assert "unsafe_example" not in serialized
    assert "legacy message" not in serialized


def test_missing_and_incompatible_snapshot_data_degrade_explicitly() -> None:
    missing = AtlasSemanticSnapshot(1, "workspace", "analyzer", None, {}, "snapshot")
    missing_report = SecurityIntelligenceService.from_snapshot(missing).analyze(
        SecurityIntelligenceRequest(categories=(SecurityCategory.SSRF,))
    )
    assert missing_report.capabilities[0].state is SecurityCapabilityState.NOT_ANALYZED

    incompatible = AtlasSemanticSnapshot(
        1,
        "workspace",
        "analyzer",
        None,
        {"security_intelligence": {"schema_version": 999}},
        "snapshot",
    )
    incompatible_report = SecurityIntelligenceService.from_snapshot(
        incompatible
    ).analyze(SecurityIntelligenceRequest(categories=(SecurityCategory.SSRF,)))
    assert (
        incompatible_report.capabilities[0].state
        is SecurityCapabilityState.INCOMPATIBLE
    )


def test_stale_security_graph_lineage_is_incompatible_not_reused() -> None:
    published = SecurityIntelligenceService(
        None, snapshot_id="old-snapshot"
    ).build_published_report((_producer(_legacy()),))
    graph = KnowledgeGraph((KnowledgeNode(
        "type:demo",
        KnowledgeKind.TYPE,
        "Demo",
        qualified_name="demo.Demo",
        project_id="demo",
        language="java",
    ),))
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
            "security_intelligence": published.to_dict(),
        }),
        workspace_fingerprint="stale-security-lineage",
        analyzer_version="test/1",
    )

    result = SecurityIntelligenceService.from_snapshot(snapshot).analyze(
        SecurityIntelligenceRequest(categories=(SecurityCategory.SQL_INJECTION,))
    )

    assert result.findings == ()
    assert result.capabilities[0].state is SecurityCapabilityState.INCOMPATIBLE
    assert any("lineage" in item for item in result.limitations)


def test_security_data_without_verifiable_canonical_graph_is_incompatible() -> None:
    resolver = SimpleNamespace(
        graph=None,
        graph_digest="b" * 64,
        limitations=(),
    )
    published = SecurityIntelligenceService(
        resolver, snapshot_id="graph-lineage"
    ).build_published_report((_producer(_legacy()),))
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "security_intelligence": published.to_dict(),
        }),
        workspace_fingerprint="missing-canonical-graph",
        analyzer_version="test/1",
    )

    result = SecurityIntelligenceService.from_snapshot(snapshot).analyze(
        SecurityIntelligenceRequest(categories=(SecurityCategory.SQL_INJECTION,))
    )

    assert result.findings == ()
    assert result.capabilities[0].state is SecurityCapabilityState.INCOMPATIBLE


def test_snapshot_revalidates_every_retained_canonical_subject() -> None:
    graph = KnowledgeGraph((KnowledgeNode(
        "type:demo",
        KnowledgeKind.TYPE,
        "Demo",
        qualified_name="demo.Demo",
        project_id="demo",
        language="java",
    ),))
    forged_candidate = SimpleNamespace(
        canonical_id="type:missing",
        kind=KnowledgeKind.TYPE,
        qualified_name="demo.Missing",
        project="demo",
        project_scopes=("demo",),
        language="java",
        path="src/main/java/demo/App.java",
    )

    class ForgedResolver:
        graph_digest = graph.stable_digest()
        limitations = ()

        def __init__(self) -> None:
            self.graph = graph

        @staticmethod
        def candidate_for_graph_id(node_id: str):
            assert node_id == "type:demo"
            return forged_candidate

    lineage = f"semantic-graph:{graph.stable_digest()}"
    published = SecurityIntelligenceService(
        ForgedResolver(), snapshot_id=lineage
    ).build_published_report((_producer(_legacy()),))
    assert published.findings[0].canonical_subject_id == "type:missing"
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
            "security_intelligence": published.to_dict(),
        }),
        workspace_fingerprint="invalid-security-subject",
        analyzer_version="test/1",
    )

    result = SecurityIntelligenceService.from_snapshot(snapshot).analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
        )
    )

    assert result.findings == ()
    assert result.capabilities[0].state is SecurityCapabilityState.INCOMPATIBLE
    assert any("revalidated" in item for item in result.limitations)


def test_requested_scope_missing_producer_reports_is_partial() -> None:
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            projects=("demo", "missing"),
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        (_producer(_legacy()),),
    )

    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.PARTIAL
    assert capability.coverage == 0.5
    assert result.findings[0].confidence.coverage == 0.5
    assert any("requested project" in item for item in capability.limitations)


def test_same_sink_from_different_languages_is_not_merged() -> None:
    java = _producer(_legacy(), version="java-producer/1")
    python = SecurityProducerReport.from_findings(
        (_legacy(),),
        project_id="demo",
        language="python",
        source_files=1,
        producer_version="python-producer/1",
    )

    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        (python, java),
    )

    assert len(result.findings) == 2
    assert {item.language for item in result.findings} == {"java", "python"}
    assert len({item.finding_id for item in result.findings}) == 2


def test_reversed_equal_priority_findings_have_stable_tie_breaking_and_evidence() -> None:
    findings = (
        _legacy(path="src/main/java/demo/Zeta.java", line=4),
        _legacy(path="src/main/java/demo/Alpha.java", line=4),
    )
    request = SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,), limit=10,
    )
    first = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (_producer(*findings),)
    )
    second = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        request, (_producer(*reversed(findings)),)
    )

    assert first.to_json() == second.to_json()
    assert [item.location.path for item in first.findings] == [
        "src/main/java/demo/Alpha.java",
        "src/main/java/demo/Zeta.java",
    ]
    assert all(
        first.evidence_index.get(evidence_id) is not None
        for finding in first.findings
        for evidence_id in finding.evidence_ids
    )
    assert all(
        any("No unique canonical subject" in item for item in finding.limitations)
        for finding in first.findings
    )


def test_oversized_legacy_input_uses_stable_bound_and_explicit_warning() -> None:
    findings = tuple(_legacy(line=line) for line in range(1, 4_098))
    forward = _producer(*findings)
    reverse = _producer(*reversed(findings))
    assert len(forward.findings) == 4_096
    assert forward.to_dict() == reverse.to_dict()
    assert forward.warning_count == 1
    assert any("omitted 1" in item for item in forward.limitations)


def test_strict_report_rejects_unknown_fields() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    payload = report.to_dict()
    payload["future_guess"] = True
    with pytest.raises(ValueError, match="unknown security intelligence report"):
        SecurityIntelligenceReport.from_dict(payload)


def test_strict_report_rejects_noncanonical_evidence_wire_types() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    boolean_quality = report.to_dict()
    boolean_quality["evidence_index"]["records"][0]["reliability"] = True
    with pytest.raises(TypeError, match="quality values must be floats"):
        SecurityIntelligenceReport.from_dict(boolean_quality)

    numeric_detail = report.to_dict()
    detail = numeric_detail["evidence_index"]["records"][0]["detail"]
    detail[next(iter(detail))] = 1
    with pytest.raises(TypeError, match="detail must contain strings"):
        SecurityIntelligenceReport.from_dict(numeric_detail)


def test_strict_report_rejects_unclosed_or_source_shaped_evidence() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    unclosed = report.to_dict()
    extra = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "project:extra",
        "test/1",
        "snapshot",
        source_refs=("security-finding:" + "a" * 64,),
        scope="project",
        language="java",
        detail={
            "category": "sql_injection",
            "rule_id": "ATLAS-SQL-001",
            "project_id_ref": security_models.stable_security_digest("extra"),
            "location_ref": "b" * 64,
            "trace_location_count": 0,
            "merged_trace_ref": security_models.stable_security_digest([]),
            "finding_limitations_ref": security_models.stable_security_digest([]),
            "severity": "high",
            "legacy_confidence": "high",
            "legacy_fingerprint": "legacy-fingerprint:" + "a" * 64,
            "cwe": "CWE-89",
            "owasp": "A03:2021",
            "coverage_observed": 1,
            "coverage_eligible": 1,
        },
        reliability=0.9,
        specificity=1.0,
    )
    unclosed["evidence_index"]["records"].append(extra.to_dict())
    with pytest.raises(ValueError, match="exactly closed"):
        SecurityIntelligenceReport.from_dict(unclosed)

    leaked = report.to_dict()
    producer_record = leaked["evidence_index"]["records"][0]
    old_id = producer_record["evidence_id"]
    malicious = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        producer_record["subject_id"],
        producer_record["producer"],
        producer_record["snapshot_id"],
        source_refs=tuple(producer_record["source_refs"]),
        scope="project",
        language=producer_record["language"],
        detail={
            "category": "sql_injection",
            "rule_id": "public class LeakedSecret",
            "location_ref": "b" * 64,
            "trace_location_count": 0,
            "merged_trace_ref": security_models.stable_security_digest([]),
            "finding_limitations_ref": security_models.stable_security_digest([]),
        },
        reliability=producer_record["reliability"],
        specificity=producer_record["specificity"],
    )
    leaked["evidence_index"]["records"][0] = malicious.to_dict()
    for finding in leaked["findings"]:
        finding["evidence_ids"] = [
            malicious.evidence_id if item == old_id else item
            for item in finding["evidence_ids"]
        ]
        for component in finding["priority"]["components"]:
            component["evidence_ids"] = [
                malicious.evidence_id if item == old_id else item
                for item in component["evidence_ids"]
            ]
    with pytest.raises(ValueError, match="evidence shape"):
        SecurityIntelligenceReport.from_dict(leaked)


def test_strict_report_rejects_tampered_confidence_and_aggregate_counts() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    confidence = report.to_dict()
    confidence["findings"][0]["confidence"].update({
        "score": 0.9,
        "tier": "high",
        "support": 0.0,
        "coverage": 0.0,
    })
    with pytest.raises(ValueError, match="confidence arithmetic"):
        SecurityIntelligenceReport.from_dict(confidence)

    counts = report.to_dict()
    counts["capabilities"][0]["finding_count"] = 999
    with pytest.raises(ValueError, match="capability totals"):
        SecurityIntelligenceReport.from_dict(counts)


def test_direct_constructors_enforce_confidence_and_evidence_invariants() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    inconsistent = ConfidenceResult(
        0.9,
        ConfidenceTier.HIGH,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
    )
    with pytest.raises(ValueError, match="confidence arithmetic"):
        replace(report.findings[0], confidence=inconsistent)
    boolean_confidence = ConfidenceResult(
        True,
        ConfidenceTier.HIGH,
        True,
        True,
        True,
        False,
        False,
    )
    with pytest.raises(TypeError, match="canonical floating point"):
        replace(report.findings[0], confidence=boolean_confidence)

    tampered_identity = replace(
        report.findings[0],
        finding_id="security-intelligence:" + "0" * 64,
    )
    with pytest.raises(ValueError, match="finding identity"):
        replace(report, findings=(tampered_identity,))

    malicious = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "project:extra",
        "test/1",
        "snapshot",
        source_refs=("security-finding:" + "a" * 64,),
        scope="project",
        language="java",
        detail={
            "category": "sql_injection",
            "rule_id": "public class LeakedSecret",
            "location_ref": "b" * 64,
            "trace_location_count": 0,
            "merged_trace_ref": security_models.stable_security_digest([]),
            "finding_limitations_ref": security_models.stable_security_digest([]),
        },
    )
    with pytest.raises(ValueError, match="evidence shape"):
        replace(
            report,
            evidence_index=EvidenceIndex(
                (*report.evidence_index.records, malicious), frozen=True
            ),
        )


def test_confidence_coverage_is_exact_observed_over_eligible_scope() -> None:
    analyzed = _producer(_legacy(), project="analyzed")
    unavailable = SecurityProducerReport.from_findings(
        (),
        project_id="not-sql",
        analyzed_categories=(SecurityCategory.PATH_TRAVERSAL,),
        source_files=1,
    )
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (unavailable, analyzed),
    )

    assert result.findings[0].confidence.coverage == 0.5
    assert result.capabilities[0].coverage == 0.5


def test_producer_limitation_prose_is_omitted_at_source_free_boundary() -> None:
    raw = 'Observed literal "hunter2".'
    producer = _producer(_legacy(), limitations=(raw,))

    assert raw not in producer.to_json()
    assert producer.limitations == (
        "1 unstructured producer limitation(s) were omitted at the "
        "source-free boundary.",
    )
    assert SecurityProducerReport.from_dict(producer.to_dict()) == producer


def test_report_rejects_request_priority_and_producer_lineage_tampering() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    with pytest.raises(ValueError, match="do not satisfy the request"):
        replace(
            report,
            request=SecurityIntelligenceRequest(
                categories=(SecurityCategory.XSS,), limit=10
            ),
            capabilities=(SecurityCapability(
                SecurityCategory.XSS,
                SecurityCapabilityState.NOT_ANALYZED,
                limitations=("XSS evidence is unavailable.",),
            ),),
        )

    invented_priority = SecurityPriority(
        1.0,
        SecurityPriorityTier.CRITICAL,
        1.0,
        (SecurityPriorityComponent(
            "invented", True, 1.0, 1.0, 1.0,
        ),),
    )
    with pytest.raises(ValueError, match="priority evidence"):
        replace(
            report,
            findings=(replace(
                report.findings[0], priority=invented_priority
            ),),
        )

    finding = report.findings[0]
    claimed_producers = (*finding.producer_versions, "fake-producer/1")
    claimed = replace(
        finding,
        producer_versions=claimed_producers,
        finding_id=security_intelligence_finding_id(
            project_id=finding.project_id,
            language=finding.language,
            category=finding.category,
            rule_id=finding.rule_id,
            location=finding.location,
            producer_versions=claimed_producers,
            snapshot_id=report.snapshot_id,
            canonical_subject_id=finding.canonical_subject_id,
            evidence_ids=finding.evidence_ids,
        ),
    )
    with pytest.raises(ValueError, match="producer lineage"):
        replace(report, findings=(claimed,))


def test_report_rejects_taxonomy_and_capability_scope_tampering() -> None:
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (_producer(_legacy()),),
    )
    finding = report.findings[0]
    with pytest.raises(ValueError, match="taxonomy evidence"):
        replace(report, findings=(replace(finding, cwe=("CWE-999",)),))
    with pytest.raises(ValueError, match="taxonomy evidence"):
        replace(report, findings=(replace(finding, owasp=("A99:2099",)),))
    with pytest.raises(ValueError, match="taxonomy evidence"):
        replace(
            report,
            findings=(replace(
                finding,
                legacy_fingerprints=(
                    "legacy-fingerprint:" + "0" * 64,
                ),
            ),),
        )

    capability = report.capabilities[0]
    for change in (
        {"project_ids": ("other-project",)},
        {"languages": ("python",)},
        {"producer_versions": ("other-producer/1",)},
    ):
        with pytest.raises(ValueError, match="capability scope or producer lineage"):
            replace(report, capabilities=(replace(capability, **change),))


def test_producer_bounds_prefer_severity_and_reject_unbounded_work(
    monkeypatch,
) -> None:
    findings = (
        *(_legacy(line=line, severity=Severity.INFO) for line in range(1, 4_097)),
        _legacy(line=5_000, severity=Severity.CRITICAL),
    )
    report = _producer(*findings)
    assert len(report.findings) == 4_096
    assert any(
        item.severity is SecuritySeverity.CRITICAL for item in report.findings
    )
    assert report.warning_count == 1

    monkeypatch.setattr(security_models, "_MAX_PRODUCER_INPUT_FINDINGS", 2)
    with pytest.raises(ValueError, match="work bound"):
        SecurityProducerReport.from_findings(
            repeat(_legacy(), 3),
            project_id="bounded",
            source_files=1,
        )

    trace_step = SimpleNamespace(
        location=SourceLocation("src/main/java/demo/App.java", 1, 1)
    )
    unbounded_trace = SimpleNamespace(
        location=SourceLocation("src/main/java/demo/App.java", 2, 1),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        trace=repeat(trace_step),
        rule_id="ATLAS-SQL-001",
        fingerprint="legacy-fingerprint-value",
        cwe="CWE-89",
        owasp="A03:2021",
    )
    with pytest.raises(ValueError, match="trace is too large"):
        SecurityProducerReport.from_findings(
            (unbounded_trace,),
            project_id="bounded",
            source_files=1,
        )


def test_security_locations_and_requests_are_canonical_and_round_trip() -> None:
    for path in (".", "C:private/App.java", "src/../private/App.java"):
        with pytest.raises(ValueError, match="workspace-relative"):
            SecurityLocation(path, 1)
    request = SecurityIntelligenceRequest(languages=("JAVA", "java"))
    assert request.languages == ("java",)
    assert SecurityIntelligenceRequest.from_dict(request.to_dict()) == request


def test_present_null_snapshot_is_incompatible_and_specific_failures_survive() -> None:
    snapshot = AtlasSemanticSnapshot(
        1,
        "workspace",
        "analyzer",
        None,
        {"security_intelligence": None},
        "snapshot",
    )
    malformed = SecurityIntelligenceService.from_snapshot(snapshot).analyze(
        SecurityIntelligenceRequest(categories=(SecurityCategory.SSRF,))
    )
    assert malformed.capabilities[0].state is SecurityCapabilityState.INCOMPATIBLE

    explicit = SecurityIntelligenceService(
        None,
        limitations=("Security consolidation exceeded its work bound.",),
        unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
    ).analyze(SecurityIntelligenceRequest(categories=(SecurityCategory.SSRF,)))
    serialized = explicit.to_json()
    assert "exceeded its work bound" in serialized
    assert "No security producer report" not in serialized


def test_published_combined_project_language_scope_never_invents_pairing() -> None:
    java = _producer(project="p1")
    python = SecurityProducerReport.from_findings(
        (),
        project_id="p2",
        language="python",
        analyzed_categories=(SecurityCategory.SQL_INJECTION,),
        source_files=1,
    )
    published = SecurityIntelligenceService(
        None, snapshot_id="snapshot"
    ).build_published_report((java, python))
    result = SecurityIntelligenceService(
        None,
        snapshot_id="snapshot",
        published_report=published,
    ).analyze(SecurityIntelligenceRequest(
        projects=("p1",),
        languages=("python",),
        categories=(SecurityCategory.SQL_INJECTION,),
    ))

    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.NOT_ANALYZED
    assert capability.project_ids == ()
    assert capability.languages == ()
    assert capability.producer_versions == ()
    assert any("pairing" in item for item in capability.limitations)


def test_duplicate_and_conflicting_producer_evidence_replays_exactly() -> None:
    high = _producer(
        _legacy(severity=Severity.HIGH), version="producer-high/1"
    )
    duplicate = _producer(
        _legacy(severity=Severity.HIGH), version="producer-high/1"
    )
    low = _producer(
        _legacy(severity=Severity.LOW), version="producer-low/1"
    )
    report = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,), limit=10
        ),
        (duplicate, low, high),
    )

    assert report.findings[0].severity is SecuritySeverity.HIGH
    assert report.findings[0].confidence.agreement == 0.5
    assert (
        SecurityIntelligenceReport.from_dict(report.to_dict()).to_dict()
        == report.to_dict()
    )


def _snapshot_for_security_publication(
    *,
    snapshot_lineage: str | None = None,
    scoped: bool = False,
) -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph((KnowledgeNode(
        "type:demo",
        KnowledgeKind.TYPE,
        "Demo",
        qualified_name="demo.Demo",
        project_id="demo",
        language="java",
    ),))
    base = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="security-publication-fixture",
        analyzer_version="test/1",
    )
    resolver = CanonicalSubjectResolver.from_snapshot(base)
    lineage = snapshot_lineage or f"semantic-graph:{resolver.graph_digest}"
    service = SecurityIntelligenceService(resolver, snapshot_id=lineage)
    report = (
        service.analyze(
            SecurityIntelligenceRequest(
                scope=SecurityScope.PROJECT,
                projects=("demo",),
                categories=(SecurityCategory.SQL_INJECTION,),
                limit=10,
            ),
            (_producer(_legacy()),),
        )
        if scoped
        else service.build_published_report((_producer(_legacy()),))
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
            "security_intelligence": report.to_dict(),
        }),
        workspace_fingerprint="security-publication-fixture",
        analyzer_version="test/1",
    )


def test_snapshot_accepts_only_canonical_repository_security_publication() -> None:
    valid = SecurityIntelligenceService.from_snapshot(
        _snapshot_for_security_publication()
    ).analyze(SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
    ))
    forged = SecurityIntelligenceService.from_snapshot(
        _snapshot_for_security_publication(snapshot_lineage="forged-lineage")
    ).analyze(SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
    ))
    scoped = SecurityIntelligenceService.from_snapshot(
        _snapshot_for_security_publication(scoped=True)
    ).analyze(SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
    ))

    assert len(valid.findings) == 1
    for incompatible in (forged, scoped):
        assert incompatible.findings == ()
        assert (
            incompatible.capabilities[0].state
            is SecurityCapabilityState.INCOMPATIBLE
        )
        assert any(
            "publication" in item.lower()
            for item in incompatible.limitations
        )


def test_producer_report_input_work_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(security_service, "_PRODUCER_REPORT_INPUT_LIMIT", 2)

    with pytest.raises(ValueError, match="report input.*work bound"):
        SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
            SecurityIntelligenceRequest(
                categories=(SecurityCategory.SQL_INJECTION,),
            ),
            repeat(_producer(_legacy())),
        )


def test_scoped_report_selection_happens_before_retention(monkeypatch) -> None:
    monkeypatch.setattr(security_service, "_PRODUCER_REPORT_LIMIT", 2)
    reports = tuple(
        _producer(_legacy(), project=project)
        for project in ("a", "b", "z")
    )

    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            projects=("z",),
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        reports,
    )

    assert [item.project_id for item in result.findings] == ["z"]
    assert result.omitted_count == 0


def test_report_retention_never_turns_unknown_category_into_not_analyzed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(security_service, "_PRODUCER_REPORT_LIMIT", 1)
    retained = SecurityProducerReport.from_findings(
        (),
        project_id="a",
        analyzed_categories=(SecurityCategory.PATH_TRAVERSAL,),
        source_files=1,
    )
    omitted = SecurityProducerReport.from_findings(
        (),
        project_id="z",
        analyzed_categories=(SecurityCategory.SQL_INJECTION,),
        source_files=1,
    )

    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        (retained, omitted),
    )

    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.PARTIAL
    assert capability.coverage is None
    assert any("omitted" in item for item in capability.limitations)


def test_matching_combined_published_scope_retains_finding_proven_metadata() -> None:
    published = SecurityIntelligenceService(
        None, snapshot_id="snapshot"
    ).build_published_report((_producer(_legacy(), project="p1"),))
    result = SecurityIntelligenceService(
        None,
        snapshot_id="snapshot",
        published_report=published,
    ).analyze(SecurityIntelligenceRequest(
        projects=("p1",),
        languages=("java",),
        categories=(SecurityCategory.SQL_INJECTION,),
    ))

    assert len(result.findings) == 1
    capability = result.capabilities[0]
    assert capability.state is SecurityCapabilityState.PARTIAL
    assert capability.project_ids == ("p1",)
    assert capability.languages == ("java",)
    assert capability.producer_versions == ("atlas-java-security/1",)
    assert capability.coverage is None


def test_scoped_query_preserves_published_incompatible_capability() -> None:
    published = SecurityIntelligenceService(
        None,
        snapshot_id="snapshot",
        limitations=("Security producer consolidation was incompatible.",),
        unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
    ).analyze(SecurityIntelligenceRequest(limit=10_000))
    service = SecurityIntelligenceService(
        None,
        snapshot_id="snapshot",
        published_report=published,
    )

    for request in (
        SecurityIntelligenceRequest(
            scope=SecurityScope.PROJECT,
            projects=("demo",),
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        SecurityIntelligenceRequest(
            projects=("demo",),
            languages=("java",),
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
    ):
        result = service.analyze(request)
        assert (
            result.capabilities[0].state
            is SecurityCapabilityState.INCOMPATIBLE
        )
        assert any(
            "incompatible" in item.lower() for item in result.limitations
        )


def test_published_selection_preserves_resolver_limitations() -> None:
    resolver = SimpleNamespace(
        graph=None,
        graph_digest="a" * 64,
        limitations=("Ignored 1 dangling canonical graph relationship(s).",),
    )
    builder = SecurityIntelligenceService(
        resolver,
        snapshot_id="semantic-graph:" + "a" * 64,
    )
    published = builder.build_published_report((_producer(_legacy()),))

    result = SecurityIntelligenceService(
        resolver,
        snapshot_id="semantic-graph:" + "a" * 64,
        published_report=published,
    ).analyze(SecurityIntelligenceRequest(
        categories=(SecurityCategory.SQL_INJECTION,),
    ))

    assert "Ignored 1 dangling canonical graph relationship(s)." in result.limitations


def test_duplicate_reports_do_not_overflow_merged_metadata() -> None:
    report = _producer(_legacy())

    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        repeat(report, 65),
    )

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.cwe == ("CWE-89",)
    assert finding.owasp == ("A03:2021",)
    assert finding.producer_versions == ("atlas-java-security/1",)
    assert len(finding.legacy_fingerprints) == 1


def test_merged_traces_are_bounded_and_evidence_bound() -> None:
    first_trace = tuple(
        TraceStep(
            "source-free test step",
            SourceLocation(f"src/main/java/trace/A{index:03d}.java", 1, 1),
        )
        for index in range(130)
    )
    second_trace = tuple(
        TraceStep(
            "source-free test step",
            SourceLocation(f"src/main/java/trace/B{index:03d}.java", 1, 1),
        )
        for index in range(130)
    )
    result = SecurityIntelligenceService(None, snapshot_id="snapshot").analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SQL_INJECTION,),
        ),
        (
            _producer(
                replace(_legacy(), trace=first_trace),
                version="producer-a/1",
            ),
            _producer(
                replace(_legacy(), trace=second_trace),
                version="producer-b/1",
            ),
        ),
    )

    finding = result.findings[0]
    assert len(finding.trace_locations) == 256
    assert any("omitted 4 location" in item for item in finding.limitations)
    assert (
        SecurityIntelligenceReport.from_dict(result.to_dict()).to_dict()
        == result.to_dict()
    )

    forged = replace(
        finding,
        trace_locations=(
            SecurityLocation("src/main/java/trace/Forged.java", 999, 1),
            *finding.trace_locations[1:],
        ),
    )
    with pytest.raises(ValueError, match="finding evidence is inconsistent"):
        replace(result, findings=(forged,))
    with pytest.raises(ValueError, match="finding evidence is inconsistent"):
        replace(
            result,
            findings=(replace(finding, limitations=()),),
        )
    with pytest.raises(ValueError, match="capability evidence is inconsistent"):
        replace(result, limitations=())

    old_record = next(
        record
        for record in result.evidence_index.records
        if record.kind is EvidenceKind.ANALYSIS_RESULT
        and record.evidence_id in finding.evidence_ids
    )
    forged_detail = dict(old_record.detail)
    forged_detail["trace_location_count"] = "0"
    forged_record = EvidenceRecord.create(
        old_record.kind,
        old_record.subject_id,
        old_record.producer,
        old_record.snapshot_id,
        source_refs=old_record.source_refs,
        scope=old_record.scope,
        language=old_record.language,
        detail=forged_detail,
        limitations=old_record.limitations,
        reliability=old_record.reliability,
        specificity=old_record.specificity,
    )
    forged_evidence_ids = tuple(
        forged_record.evidence_id
        if evidence_id == old_record.evidence_id
        else evidence_id
        for evidence_id in finding.evidence_ids
    )
    forged_index = EvidenceIndex(
        (
            forged_record
            if record.evidence_id == old_record.evidence_id
            else record
            for record in result.evidence_index.records
        ),
        frozen=True,
    )
    producer_evidence_ids = tuple(
        evidence_id
        for evidence_id in forged_evidence_ids
        if forged_index.get(evidence_id).kind is EvidenceKind.ANALYSIS_RESULT
    )
    forged_finding = replace(
        finding,
        evidence_ids=forged_evidence_ids,
        priority=security_models.security_priority_for_finding(
            finding.severity,
            producer_evidence_ids,
            finding.trace_locations,
            None,
        ),
        finding_id=security_intelligence_finding_id(
            project_id=finding.project_id,
            language=finding.language,
            category=finding.category,
            rule_id=finding.rule_id,
            location=finding.location,
            producer_versions=finding.producer_versions,
            snapshot_id=result.snapshot_id,
            canonical_subject_id=finding.canonical_subject_id,
            evidence_ids=forged_evidence_ids,
        ),
    )
    with pytest.raises(ValueError, match="finding evidence is inconsistent"):
        replace(
            result,
            findings=(forged_finding,),
            evidence_index=forged_index,
        )
