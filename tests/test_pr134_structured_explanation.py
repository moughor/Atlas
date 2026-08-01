from __future__ import annotations

from copy import deepcopy
import json

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.design_patterns import PatternDetectionService
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeRelation
from moughorai.repository_report import RepositoryReportService
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.structured_explanation import (
    ExplanationAvailability,
    ExplanationCapability,
    ExplanationContextBudgetError,
    ExplanationRequest,
    ExplanationSelection,
    StructuredExplanation,
    StructuredExplanationRenderer,
    StructuredExplanationSelector,
    StructuredExplanationService,
)
from moughorai.subject_resolution import CanonicalSubjectResolver


_ENCODED_REPOSITORY_ID = (
    "repository:C%3A%2FUsers%2Falice%2Fprivate%2Fcheckout"
)
_ENCODED_WORKSPACE_ID = (
    "workspace:C%3A%2FUsers%2Falice%2Fprivate%2Fcheckout"
)
_SOURCE_MARKER = "SECRET_SOURCE: public class Service { return this; }"


class _CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _node(
    node_id: str,
    kind: KnowledgeKind,
    qualified_name: str,
    *,
    name: str | None = None,
    project: str | None = None,
    language: str = "unknown",
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": node_id,
        "kind": kind.value,
        "qualified_name": qualified_name,
        "project_id": project,
        "language": language,
    }
    if name is not None:
        value["name"] = name
    return value


def _edge(
    source: str,
    target: str,
    kind: str,
    *evidence: str,
) -> dict[str, object]:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "evidence": list(evidence),
    }


def _base_context() -> dict[str, object]:
    nodes = [
        _node(
            _ENCODED_REPOSITORY_ID,
            KnowledgeKind.REPOSITORY,
            "C:/Users/alice/private/checkout",
        ),
        _node(
            _ENCODED_WORKSPACE_ID,
            KnowledgeKind.WORKSPACE,
            "C:/Users/alice/private/checkout",
        ),
        _node("project:app", KnowledgeKind.PROJECT, "app", project="app"),
        _node("module:app.main", KnowledgeKind.MODULE, "app.main", project="app"),
        _node("package:demo", KnowledgeKind.PACKAGE, "demo", project="app", language="java"),
        _node("type:base", KnowledgeKind.TYPE, "demo.Base", project="app", language="java"),
        _node("type:service", KnowledgeKind.TYPE, "demo.Service", project="app", language="java"),
        _node("type:helper", KnowledgeKind.TYPE, "demo.Helper", project="app", language="java"),
        _node("method:run", KnowledgeKind.METHOD, "demo.Service#run()", project="app", language="java"),
        _node("method:helper", KnowledgeKind.METHOD, "demo.Helper#help()", project="app", language="java"),
        _node("method:base-run", KnowledgeKind.METHOD, "demo.Base#run()", project="app", language="java"),
        _node("field:dependency", KnowledgeKind.FIELD, "demo.Service#dependency", project="app", language="java"),
        _node(
            "dependency:maven:org.demo%3Alib:1.0:compile",
            KnowledgeKind.DEPENDENCY,
            "org.demo:lib",
            project="app",
        ),
        _node("framework:JUnit", KnowledgeKind.FRAMEWORK, "JUnit", project="app"),
        _node("build_system:app:Maven", KnowledgeKind.BUILD_SYSTEM, "Maven", project="app"),
        _node("build_target:app:compileJava", KnowledgeKind.BUILD_TARGET, "compileJava", project="app"),
        _node("symbol:generic", KnowledgeKind.SYMBOL, "demo.Generic", project="app", language="java"),
    ]
    edges = [
        _edge(_ENCODED_REPOSITORY_ID, _ENCODED_WORKSPACE_ID, "ownership", "workspace-metadata:root"),
        _edge(_ENCODED_WORKSPACE_ID, "project:app", "ownership", "workspace-project:app"),
        _edge("project:app", "module:app.main", "ownership", "workspace-module:app.main"),
        _edge("module:app.main", "package:demo", "ownership", "semantic-package:demo"),
        _edge("package:demo", "type:service", "ownership", "global-symbol:demo.Service"),
        _edge("method:run", "type:service", "member_of", "global_symbol.owner_id"),
        _edge("field:dependency", "type:service", "member_of", "global_symbol.owner_id"),
        _edge("type:service", "type:base", "inheritance", "java-architecture:extends"),
        _edge("type:service", "type:helper", "imports", "java-architecture:import"),
        _edge("type:service", "field:dependency", "composition", "java-architecture:field-type"),
        _edge("method:run", "method:helper", "calls", "call-graph:resolved-call"),
        _edge("method:run", "method:helper", "calls", "cross-reference:resolved-call"),
        _edge("method:run", "method:base-run", "overrides", "java-semantics:override"),
        _edge(
            "project:app",
            "dependency:maven:org.demo%3Alib:1.0:compile",
            "depends_on",
            "declared_dependency.source:pom.xml",
        ),
        _edge("project:app", "framework:JUnit", "depends_on", "dependency:org.junit:junit-bom"),
        _edge("project:app", "build_system:app:Maven", "belongs_to", "build-descriptor:pom.xml"),
        _edge("build_target:app:compileJava", "project:app", "belongs_to", "build-task:compileJava"),
        _edge("symbol:generic", "type:service", "related_to", "semantic-symbol:generic"),
    ]
    return {
        "schema_version": 1,
        "workspace": {"root": ".", "projects": [{"name": "app", "path": "."}]},
        "repository_summary": {
            "schema_version": 1,
            "project_count": 1,
            "projects": [{"name": "app", "path": "."}],
            "language_file_counts": {"Java": 4},
            "build_systems": [{"name": "Maven"}],
            "frameworks": [{"name": "JUnit"}],
            "entry_points": [{"project": "app", "symbol": "method:run"}],
        },
        "semantic_graph": {
            "schema_version": 1,
            "nodes": nodes,
            "edges": edges,
        },
        "symbols": [
            {
                "id": "type:service",
                "name": "Service",
                "qualified_name": "demo.Service",
                "source": "src/main/java/demo/Service.java",
                "source_code": _SOURCE_MARKER,
            }
        ],
    }


def _snapshot(
    context: dict[str, object],
    *,
    fixed_id: str | None = None,
) -> AtlasSemanticSnapshot:
    if fixed_id is not None:
        return AtlasSemanticSnapshot(
            1,
            "pr134-structured-explanation",
            "test",
            None,
            context,
            fixed_id,
        )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr134-structured-explanation",
        analyzer_version="test",
    )


def _record(
    subject_id: str,
    producer: str,
    lineage: str = "snapshot:upstream",
) -> EvidenceRecord:
    return EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        subject_id,
        producer,
        lineage,
        source_refs=(f"semantic-fact:{subject_id}",),
        detail={"verified": True},
        reliability=0.9,
        specificity=1.0,
    )


def _confidence() -> dict[str, object]:
    return {
        "score": 0.9,
        "tier": "high",
        "support": 0.9,
        "coverage": 1.0,
        "agreement": 1.0,
        "contradiction_penalty": 0.0,
        "ambiguity_penalty": 0.0,
        "missing_roles": [],
        "model_version": 1,
    }


def _context_with_verified_findings() -> dict[str, object]:
    context = _base_context()
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    graph_digest = KnowledgeGraph.from_dict(graph).stable_digest()
    pattern = EvidenceRecord.create(
        EvidenceKind.GRAPH_EDGE,
        "type:service|inheritance|type:base",
        "knowledge-graph/1",
        "semantic-graph:patterns",
        source_refs=("java-architecture:extends",),
        scope="project:app",
        language="java",
        detail={
            "source": "type:service",
            "target": "type:base",
            "relation": "inheritance",
        },
        reliability=1.0,
        specificity=0.9,
    )
    reachability_coverage = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "project:app",
        "atlas-pr131/1",
        "snapshot:upstream",
        source_refs=("project:app",),
        scope="project:app",
        detail={"roots": "partial", "calls": "partial", "cfg": "unavailable"},
        reliability=1.0,
        specificity=0.8,
    )
    reachability_root = EvidenceRecord.create(
        EvidenceKind.REPOSITORY_METADATA,
        "type:service",
        "explicit-reachability-root",
        "snapshot:upstream",
        source_refs=("type:service",),
        scope="repository",
        language="java",
        detail={"root_category": "application"},
        reliability=1.0,
        specificity=1.0,
    )
    risk = _record("type:service", "test-risk-metric.v1")
    context["design_patterns"] = {
        "schema_version": 1,
        "producer_version": "atlas-pr130/1",
        "input_fingerprint": "patterns",
        "findings": [
            {
                "pattern": "strategy",
                "participants": [
                    {
                        "symbol_id": "type:service",
                        "qualified_name": "demo.Service",
                        "role": "context",
                    },
                    {
                        "symbol_id": "type:base",
                        "qualified_name": "demo.Base",
                        "role": "abstraction",
                    },
                ],
                "confidence": 0.9,
                "confidence_tier": "high",
                "evidence_ids": [pattern.evidence_id],
                "explanation": "Verified structural relations support this candidate.",
                "limitations": ["Runtime selection is not observed."],
            }
        ],
        "capabilities": [],
        "evidence_index": EvidenceIndex((pattern,)).to_dict(),
    }
    context["reachability"] = {
        "schema_version": 1,
        "producer_version": "atlas-pr131/1",
        "input_fingerprint": "reachability",
        "configuration_fingerprint": "configuration",
        "snapshot_lineage": "snapshot:upstream",
        "graph_digest": graph_digest,
        "serialization": "grouped-findings-v1",
        "finding_groups": [
            {
                "subject_id_prefix": "type:",
                "subject_ids": ["service"],
                "symbol_kind": "type",
                "language": "java",
                "project": "app",
                "source_classification": "production",
                "state": "reachable",
                "confidence": 0.9,
                "confidence_tier": "high",
                "evidence_ids": [
                    reachability_coverage.evidence_id,
                    reachability_root.evidence_id,
                ],
                "root_categories": ["application"],
                "production_reachable": True,
                "test_reachable": False,
                "limitations": [],
            }
        ],
        "roots": [{
            "subject_id": "type:service",
            "category": "application",
            "project": "app",
            "scope": "repository",
            "confidence": 1.0,
            "confidence_tier": "high",
            "evidence_ids": [reachability_root.evidence_id],
            "limitations": [],
            "producer_version": "atlas-pr131/1",
        }],
        "paths": [{
            "root_subject_id": "type:service",
            "target_subject_id": "type:service",
            "relationship_sequence": [],
            "evidence_ids": [],
            "scope": "production",
            "truncated": False,
            "limitations": [],
        }],
        "coverage": {
            "status": "partial",
            "projects": [{
                "project": "app",
                "evidence_ids": [reachability_coverage.evidence_id],
            }],
            "limitations": [],
        },
        "evidence_index": EvidenceIndex(
            (reachability_coverage, reachability_root)
        ).to_dict(),
        "limitations": [],
    }
    context["risk_analysis"] = {
        "schema_version": 1,
        "producer_version": "atlas-pr132/1",
        "input_fingerprint": "risk",
        "configuration_fingerprint": "configuration",
        "lineage": "snapshot:upstream",
        "graph_digest": graph_digest,
        "hotspots": [
            {
                "rank": 1,
                "subject_id": "type:service",
                "display_name": "demo.Service",
                "project": "app",
                "kind": "type",
                "language": "java",
                "scope": "production",
                "score": 0.8,
                "confidence": _confidence(),
                "factors": [
                    {
                        "metric": {
                            "metric": "complexity",
                            "status": "available",
                            "raw_value": 12.0,
                            "normalized_value": 0.8,
                            "unit": "cyclomatic_complexity",
                            "window": "current-snapshot",
                            "cohort": "app:java:type:production",
                            "producer": "test-risk-metric.v1",
                            "coverage": 1.0,
                            "normalization": "percentile-rank-v1",
                            "evidence_ids": [risk.evidence_id],
                            "limitations": [],
                        },
                        "configured_weight": 1.0,
                        "effective_weight": 1.0,
                        "contribution": 0.8,
                    }
                ],
                "evidence_ids": [risk.evidence_id],
                "limitations": ["History evidence is unavailable."],
            }
        ],
        "capabilities": [],
        "evidence_index": EvidenceIndex((risk,)).to_dict(),
        "limitations": [],
    }
    return context


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("repository", KnowledgeKind.REPOSITORY),
        ("workspace", KnowledgeKind.WORKSPACE),
        ("app", KnowledgeKind.PROJECT),
        ("app.main", KnowledgeKind.MODULE),
        ("demo", KnowledgeKind.PACKAGE),
        ("demo.Service", KnowledgeKind.TYPE),
        ("demo.Service#run()", KnowledgeKind.METHOD),
        ("demo.Service#dependency", KnowledgeKind.FIELD),
        ("org.demo:lib", KnowledgeKind.DEPENDENCY),
        ("JUnit", KnowledgeKind.FRAMEWORK),
        ("Maven", KnowledgeKind.BUILD_SYSTEM),
        ("compileJava", KnowledgeKind.BUILD_TARGET),
        ("demo.Generic", KnowledgeKind.SYMBOL),
    ],
)
def test_every_authoritative_canonical_subject_kind_is_explainable(
    subject: str,
    kind: KnowledgeKind,
) -> None:
    result = StructuredExplanationService(_snapshot(_base_context())).explain(
        ExplanationRequest(subject, kind.value)
    )

    assert result.availability is ExplanationAvailability.AVAILABLE
    assert result.subject is not None
    assert result.subject.kind == kind.value
    assert any(fact.title == "Canonical subject identity" for fact in result.facts)
    assert result.citations
    assert result.citations == tuple(
        sorted(record.evidence_id for record in result.evidence_index.records)
    )
    assert not contains_absolute_path(result.to_dict())


def test_production_pattern_report_evidence_is_accepted_for_participant() -> None:
    context = _base_context()
    graph_payload = context["semantic_graph"]
    assert isinstance(graph_payload, dict)
    nodes = graph_payload["nodes"]
    edges = graph_payload["edges"]
    assert isinstance(nodes, list) and isinstance(edges, list)
    nodes.append(
        _node(
            "type:other-service",
            KnowledgeKind.TYPE,
            "demo.OtherService",
            project="app",
            language="java",
        )
    )
    edges.extend((
        _edge(
            "type:other-service",
            "type:base",
            KnowledgeRelation.INHERITS.value,
            "java-architecture:implements",
        ),
        _edge(
            "type:helper",
            "type:base",
            KnowledgeRelation.COMPOSES.value,
            "java-architecture:field-type",
        ),
    ))
    graph = KnowledgeGraph.from_dict(graph_payload)
    report = PatternDetectionService().detect(graph)
    assert any(
        finding.pattern.value == "strategy"
        for finding in report.findings
    )
    context["semantic_graph"] = graph.to_dict()
    context["design_patterns"] = report.to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Helper", KnowledgeKind.TYPE.value)
    )

    pattern_fact = next(
        fact for fact in result.facts
        if fact.title == "strategy pattern finding"
    )
    assert pattern_fact.evidence_ids
    assert {
        attribute.key: attribute.value
        for attribute in pattern_fact.attributes
    }["participant_count"] == 4


def test_relationship_explanation_uses_only_matching_canonical_edges() -> None:
    service = StructuredExplanationService(_snapshot(_base_context()))
    result = service.explain(ExplanationRequest(
        "demo.Service#run()",
        KnowledgeKind.METHOD.value,
        relationship_source="demo.Service#run()",
        relationship_target="demo.Helper#help()",
        relationship_kind="calls",
    ))

    relationships = [
        fact for fact in result.facts if fact.title == "Canonical calls relationship"
    ]
    assert result.availability is ExplanationAvailability.AVAILABLE
    assert len(relationships) == 2
    assert all(fact.references == ("method:helper", "method:run") for fact in relationships)
    assert all(fact.evidence_ids for fact in relationships)
    assert any(
        "call-graph:resolved-call" in record.source_refs
        for record in result.evidence_index.records
    )

    absent = service.explain(ExplanationRequest(
        "demo.Helper#help()",
        KnowledgeKind.METHOD.value,
        relationship_source="demo.Helper#help()",
        relationship_target="demo.Service#run()",
        relationship_kind="calls",
    ))
    assert absent.availability is ExplanationAvailability.NOT_FOUND
    assert any("Absence is not proof" in item for item in absent.limitations)
    assert not absent.facts


def test_relationship_evidence_bound_is_disclosed_exactly() -> None:
    context = _base_context()
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    edges = graph["edges"]
    assert isinstance(edges, list)
    imports = next(
        edge for edge in edges
        if edge["source"] == "type:service"
        and edge["target"] == "type:helper"
        and edge["kind"] == "imports"
    )
    imports["evidence"] = [f"producer-evidence:{index:02d}" for index in range(20)]

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    fact = next(
        item for item in result.facts
        if item.title == "Canonical imports relationship"
    )
    attributes = {item.key: item.value for item in fact.attributes}

    assert attributes["producer_evidence_count"] == 20
    assert attributes["retained_producer_evidence_count"] == 16
    assert fact.limitations == (
        "4 safe producer evidence reference(s) were omitted by the 16-reference explanation bound.",
    )


def test_repository_inventory_never_fabricates_missing_counts_as_zero() -> None:
    context = _base_context()
    context["repository_summary"] = {
        "schema_version": 1,
        "project_count": "unknown",
        "language_file_counts": {"Java": 4},
    }

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("repository", KnowledgeKind.REPOSITORY.value)
    )
    fact = next(item for item in result.facts if item.title == "Repository inventory")
    attributes = {item.key: item.value for item in fact.attributes}

    assert attributes == {"language_count": 1}
    assert "0 project" not in fact.statement
    assert "unavailable" in fact.limitations[0]


def test_high_degree_relationship_projection_is_bounded_and_deterministic() -> None:
    first_context = _base_context()
    first_graph = first_context["semantic_graph"]
    assert isinstance(first_graph, dict)
    nodes = first_graph["nodes"]
    edges = first_graph["edges"]
    assert isinstance(nodes, list) and isinstance(edges, list)
    nodes.extend(
        _node(
            f"type:neighbor:{index:04d}",
            KnowledgeKind.TYPE,
            f"demo.Neighbor{index}",
            project="app",
            language="java",
        )
        for index in reversed(range(200))
    )
    edges.extend(
        _edge(
            "type:service",
            f"type:neighbor:{index:04d}",
            KnowledgeRelation.IMPORTS.value,
            f"import:{index:04d}",
        )
        for index in reversed(range(200))
    )
    second_context = deepcopy(first_context)
    second_graph = second_context["semantic_graph"]
    assert isinstance(second_graph, dict)
    second_nodes = second_graph["nodes"]
    second_edges = second_graph["edges"]
    assert isinstance(second_nodes, list) and isinstance(second_edges, list)
    second_nodes.reverse()
    second_edges.reverse()

    request = ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    first = StructuredExplanationService(
        _snapshot(first_context, fixed_id="fixed-high-degree-snapshot")
    ).explain(request)
    second = StructuredExplanationService(
        _snapshot(second_context, fixed_id="fixed-high-degree-snapshot")
    ).explain(request)

    relation_facts = [
        fact for fact in first.facts
        if fact.kind.value == "relationship"
    ]
    # The base fixture contributes seven incident relationships for Service;
    # the deterministic global prefix retains 41 of the 200 added imports.
    assert len(relation_facts) == StructuredExplanationService.MAXIMUM_RELATION_FACTS
    assert any(
        item == "159 direct canonical relationship(s) were omitted by the deterministic bound."
        for item in first.limitations
    )
    assert first.to_dict() == second.to_dict()
    assert first.availability is ExplanationAvailability.PARTIAL

    selected = StructuredExplanationService(
        _snapshot(first_context, fixed_id="fixed-high-degree-snapshot")
    ).explain(request, token_budget=1_000_000)
    assert selected.selection.applied
    assert selected.selection.omitted_fact_count == 159
    assert selected.selection.omitted_evidence_count == 159
    assert selected.selection.total_fact_count == (
        selected.selection.included_fact_count + 159
    )
    assert selected.selection.total_evidence_count == (
        selected.selection.included_evidence_count + 159
    )


def test_verified_pr130_pr131_and_pr132_findings_enrich_the_subject() -> None:
    result = StructuredExplanationService(
        _snapshot(_context_with_verified_findings())
    ).explain(ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value))

    titles = {fact.title for fact in result.facts}
    assert "strategy pattern finding" in titles
    assert "Reachability finding" in titles
    assert "Risk hotspot finding" in titles
    reachability = next(
        fact for fact in result.facts if fact.title == "Reachability finding"
    )
    assert next(
        item.value for item in reachability.attributes
        if item.key == "production_reachable"
    ) is True
    assert all(
        record.producer == StructuredExplanationService.PRODUCER_VERSION
        for record in result.evidence_index.records
    )
    assert all(
        record.snapshot_id == result.lineage
        for record in result.evidence_index.records
    )
    capabilities = {item.name: item for item in result.capabilities}
    assert capabilities["design_patterns"].availability is ExplanationAvailability.PARTIAL
    assert capabilities["reachability"].availability is ExplanationAvailability.PARTIAL
    assert capabilities["risk_analysis"].availability is ExplanationAvailability.PARTIAL
    assert capabilities["design_patterns"].coverage is None
    assert any(
        "does not publish a standalone canonical graph digest" in limitation
        for limitation in capabilities["design_patterns"].limitations
    )
    assert capabilities["reachability"].coverage is None
    assert capabilities["risk_analysis"].coverage is None


def test_pr131_relation_evidence_must_belong_to_the_subject_path() -> None:
    context = _context_with_verified_findings()
    reachability = context["reachability"]
    assert isinstance(reachability, dict)
    groups = reachability["finding_groups"]
    paths = reachability["paths"]
    raw_index = reachability["evidence_index"]
    assert isinstance(groups, list) and isinstance(paths, list)
    assert isinstance(raw_index, dict)
    foreign = EvidenceRecord.create(
        EvidenceKind.GRAPH_EDGE,
        "type:helper",
        "knowledge-graph.v1",
        "snapshot:upstream",
        source_refs=("type:foreign-root", "type:helper"),
        scope="project:app",
        language="java",
        detail={"relation": "calls"},
        reliability=1.0,
        specificity=1.0,
    )
    paths.append({
        "root_subject_id": "type:foreign-root",
        "target_subject_id": "type:helper",
        "relationship_sequence": ["calls"],
        "evidence_ids": [foreign.evidence_id],
        "scope": "production",
        "truncated": False,
        "limitations": [],
    })
    group = groups[0]
    assert isinstance(group, dict)
    evidence_ids = group["evidence_ids"]
    assert isinstance(evidence_ids, list)
    evidence_ids.append(foreign.evidence_id)
    existing = EvidenceIndex.from_dict(raw_index)
    reachability["evidence_index"] = EvidenceIndex(
        (*existing.records, foreign)
    ).to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert not any(fact.title == "Reachability finding" for fact in result.facts)
    assert any(
        "upstream finding(s) were omitted" in limitation
        for limitation in result.limitations
    )


def test_pr131_nontrivial_path_requires_relationship_evidence() -> None:
    context = _context_with_verified_findings()
    reachability = context["reachability"]
    assert isinstance(reachability, dict)
    roots = reachability["roots"]
    paths = reachability["paths"]
    groups = reachability["finding_groups"]
    raw_index = reachability["evidence_index"]
    assert all(isinstance(value, list) for value in (roots, paths, groups))
    assert isinstance(raw_index, dict)
    replacement_root = EvidenceRecord.create(
        EvidenceKind.REPOSITORY_METADATA,
        "type:base",
        "explicit-reachability-root",
        "snapshot:upstream",
        source_refs=("type:base",),
        scope="repository",
        language="java",
        detail={"root_category": "application"},
        reliability=1.0,
        specificity=1.0,
    )
    root = roots[0]
    path = paths[0]
    group = groups[0]
    assert isinstance(root, dict) and isinstance(path, dict) and isinstance(group, dict)
    old_root_id = root["evidence_ids"][0]
    root["subject_id"] = "type:base"
    root["evidence_ids"] = [replacement_root.evidence_id]
    path["root_subject_id"] = "type:base"
    path["evidence_ids"] = []
    finding_ids = group["evidence_ids"]
    assert isinstance(finding_ids, list)
    group["evidence_ids"] = [
        replacement_root.evidence_id if item == old_root_id else item
        for item in finding_ids
    ]
    existing = EvidenceIndex.from_dict(raw_index)
    reachability["evidence_index"] = EvidenceIndex((
        *(record for record in existing.records if record.evidence_id != old_root_id),
        replacement_root,
    )).to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert not any(fact.title == "Reachability finding" for fact in result.facts)
    assert any(
        "upstream finding(s) were omitted" in limitation
        for limitation in result.limitations
    )


def test_pr130_evidence_must_reference_only_finding_participants() -> None:
    context = _context_with_verified_findings()
    patterns = context["design_patterns"]
    assert isinstance(patterns, dict)
    findings = patterns["findings"]
    raw_index = patterns["evidence_index"]
    assert isinstance(findings, list) and isinstance(raw_index, dict)
    finding = findings[0]
    assert isinstance(finding, dict)
    foreign = EvidenceRecord.create(
        EvidenceKind.GRAPH_EDGE,
        "type:helper|inheritance|type:base",
        "knowledge-graph/1",
        "semantic-graph:patterns",
        source_refs=("java-architecture:extends",),
        scope="project:app",
        language="java",
        detail={
            "source": "type:helper",
            "target": "type:base",
            "relation": "inheritance",
        },
        reliability=1.0,
        specificity=0.9,
    )
    evidence_ids = finding["evidence_ids"]
    assert isinstance(evidence_ids, list)
    evidence_ids.append(foreign.evidence_id)
    existing = EvidenceIndex.from_dict(raw_index)
    patterns["evidence_index"] = EvidenceIndex(
        (*existing.records, foreign)
    ).to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert not any(fact.title == "strategy pattern finding" for fact in result.facts)
    assert any(
        "upstream finding(s) were omitted" in limitation
        for limitation in result.limitations
    )


def test_missing_or_noncanonical_upstream_evidence_is_not_promoted() -> None:
    context = _context_with_verified_findings()
    patterns = context["design_patterns"]
    assert isinstance(patterns, dict)
    findings = patterns["findings"]
    assert isinstance(findings, list)
    finding = findings[0]
    assert isinstance(finding, dict)
    finding["evidence_ids"] = ["evidence:missing"]

    risk = context["risk_analysis"]
    assert isinstance(risk, dict)
    risk_index = risk["evidence_index"]
    assert isinstance(risk_index, dict)
    records = risk_index["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    noncanonical_id = "evidence:" + "0" * 64
    record["evidence_id"] = noncanonical_id
    hotspots = risk["hotspots"]
    assert isinstance(hotspots, list)
    hotspot = hotspots[0]
    assert isinstance(hotspot, dict)
    hotspot["evidence_ids"] = [noncanonical_id]

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    titles = {fact.title for fact in result.facts}
    assert "strategy pattern finding" not in titles
    assert "Risk hotspot finding" not in titles
    assert "Reachability finding" in titles
    assert any("evidence could not be verified" in item for item in result.limitations)


def test_cross_subject_upstream_evidence_is_not_promoted() -> None:
    context = _context_with_verified_findings()
    risk = context["risk_analysis"]
    assert isinstance(risk, dict)
    hotspots = risk["hotspots"]
    assert isinstance(hotspots, list) and isinstance(hotspots[0], dict)
    foreign = _record("type:other", "atlas-pr132/1")
    hotspots[0]["evidence_ids"] = [foreign.evidence_id]
    risk["evidence_index"] = EvidenceIndex((foreign,)).to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert "Risk hotspot finding" not in {fact.title for fact in result.facts}
    assert any("evidence could not be verified" in item for item in result.limitations)


def test_risk_finding_without_authoritative_metric_factors_is_not_promoted() -> None:
    context = _context_with_verified_findings()
    risk = context["risk_analysis"]
    assert isinstance(risk, dict)
    hotspots = risk["hotspots"]
    assert isinstance(hotspots, list) and isinstance(hotspots[0], dict)
    hotspots[0]["factors"] = []

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert "Risk hotspot finding" not in {fact.title for fact in result.facts}
    assert any("evidence could not be verified" in item for item in result.limitations)


def test_risk_finding_cannot_append_unrelated_evidence_to_factor_closure() -> None:
    context = _context_with_verified_findings()
    risk = context["risk_analysis"]
    assert isinstance(risk, dict)
    hotspots = risk["hotspots"]
    assert isinstance(hotspots, list) and isinstance(hotspots[0], dict)
    original_id = hotspots[0]["evidence_ids"][0]
    foreign = _record("type:other", "test-risk-metric.v1")
    hotspots[0]["evidence_ids"] = [original_id, foreign.evidence_id]
    risk_index = risk["evidence_index"]
    assert isinstance(risk_index, dict)
    original_record = risk_index["records"][0]
    risk["evidence_index"] = EvidenceIndex((
        EvidenceRecord.from_dict(original_record),
        foreign,
    )).to_dict()

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert "Risk hotspot finding" not in {fact.title for fact in result.facts}
    assert any("evidence could not be verified" in item for item in result.limitations)


def test_upstream_evidence_lineage_must_match_its_report() -> None:
    context = _context_with_verified_findings()
    patterns = context["design_patterns"]
    assert isinstance(patterns, dict)
    foreign_lineage = _record(
        "type:service|inheritance|type:base",
        "knowledge-graph/1",
        "semantic-graph:different-input",
    )
    patterns["evidence_index"] = EvidenceIndex((foreign_lineage,)).to_dict()
    patterns["findings"][0]["evidence_ids"] = [foreign_lineage.evidence_id]

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert "strategy pattern finding" not in {fact.title for fact in result.facts}
    assert any("evidence could not be verified" in item for item in result.limitations)


def test_stale_lineage_and_malformed_numeric_findings_are_not_promoted() -> None:
    context = _context_with_verified_findings()
    patterns = context["design_patterns"]
    reachability = context["reachability"]
    risk = context["risk_analysis"]
    assert isinstance(patterns, dict)
    assert isinstance(reachability, dict)
    assert isinstance(risk, dict)
    patterns["findings"][0]["confidence"] = "missing"
    reachability["finding_groups"][0]["confidence"] = None
    risk["hotspots"][0]["rank"] = 0

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    titles = {fact.title for fact in result.facts}
    assert "strategy pattern finding" not in titles
    assert "Reachability finding" not in titles
    assert "Risk hotspot finding" not in titles
    assert not any(
        attribute.key in {"confidence", "rank", "score"}
        and attribute.value == 0
        for fact in result.facts
        for attribute in fact.attributes
    )

    stale = _context_with_verified_findings()
    stale_reachability = stale["reachability"]
    assert isinstance(stale_reachability, dict)
    stale_reachability["graph_digest"] = "0" * 64
    stale_result = StructuredExplanationService(_snapshot(stale)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    capability = next(
        item for item in stale_result.capabilities if item.name == "reachability"
    )
    assert capability.availability is ExplanationAvailability.UNAVAILABLE
    assert "Reachability finding" not in {
        fact.title for fact in stale_result.facts
    }
    assert any("stale" in item for item in capability.limitations)


def test_boolean_pr132_confidence_number_is_not_promoted() -> None:
    context = _context_with_verified_findings()
    risk = context["risk_analysis"]
    assert isinstance(risk, dict)
    hotspot = risk["hotspots"][0]
    assert isinstance(hotspot, dict)
    confidence = hotspot["confidence"]
    assert isinstance(confidence, dict)
    confidence["score"] = True

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )

    assert "Risk hotspot finding" not in {fact.title for fact in result.facts}
    assert StructuredExplanation.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_pattern_association_uses_canonical_participant_id_not_qualified_name() -> None:
    context = _context_with_verified_findings()
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    graph["nodes"].append(_node(
        "type:other-service",
        KnowledgeKind.TYPE,
        "demo.Service",
        project="other",
        language="java",
    ))
    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("type:other-service", KnowledgeKind.TYPE.value)
    )

    assert "strategy pattern finding" not in {fact.title for fact in result.facts}


def test_duplicate_architecture_findings_are_reorder_deterministic() -> None:
    first_context = _base_context()
    first_context["architecture"] = {
        "schema_version": 1,
        "findings": [
            {
                "architecture": "layered",
                "confidence": 0.7,
                "evidence": [{"kind": "graph", "reference": "edge:b", "detail": "b"}],
            },
            {
                "architecture": "layered",
                "confidence": 0.8,
                "evidence": [{"kind": "graph", "reference": "edge:a", "detail": "a"}],
            },
        ],
    }
    second_context = deepcopy(first_context)
    second_architecture = second_context["architecture"]
    assert isinstance(second_architecture, dict)
    second_architecture["findings"] = list(reversed(second_architecture["findings"]))
    request = ExplanationRequest("repository", KnowledgeKind.REPOSITORY.value)

    first = StructuredExplanationService(
        _snapshot(first_context, fixed_id="architecture-order")
    ).explain(request)
    second = StructuredExplanationService(
        _snapshot(second_context, fixed_id="architecture-order")
    ).explain(request)

    assert first.to_dict() == second.to_dict()


def test_capabilities_and_old_snapshots_degrade_explicitly() -> None:
    direct = StructuredExplanationService(_snapshot(_base_context())).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    capabilities = {item.name: item.availability for item in direct.capabilities}
    assert capabilities["canonical_graph"] is ExplanationAvailability.AVAILABLE
    assert capabilities["design_patterns"] is ExplanationAvailability.UNAVAILABLE
    assert capabilities["reachability"] is ExplanationAvailability.UNAVAILABLE
    assert capabilities["risk_analysis"] is ExplanationAvailability.UNAVAILABLE
    assert capabilities["repository_report"] is ExplanationAvailability.UNAVAILABLE
    assert capabilities["build_targets"] is ExplanationAvailability.AVAILABLE

    missing_target_context = _base_context()
    graph = missing_target_context["semantic_graph"]
    assert isinstance(graph, dict)
    graph["nodes"] = [
        item for item in graph["nodes"]
        if item["kind"] != KnowledgeKind.BUILD_TARGET.value
    ]
    graph["edges"] = [
        item for item in graph["edges"]
        if not str(item["source"]).startswith("build_target:")
        and not str(item["target"]).startswith("build_target:")
    ]
    target = StructuredExplanationService(_snapshot(missing_target_context)).explain(
        ExplanationRequest("compileJava", KnowledgeKind.BUILD_TARGET.value)
    )
    assert target.availability is ExplanationAvailability.NOT_FOUND
    assert any("build target" in item.casefold() for item in target.limitations)
    assert next(
        item for item in target.capabilities if item.name == "build_targets"
    ).availability is ExplanationAvailability.UNAVAILABLE

    old_snapshot = _snapshot({"schema_version": 1, "symbols": []})
    unavailable = StructuredExplanationService(old_snapshot).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    assert unavailable.availability is ExplanationAvailability.UNAVAILABLE
    assert not unavailable.facts
    assert any("unavailable" in item.casefold() for item in unavailable.limitations)


def test_stale_pr133_report_is_not_attributed_to_a_different_graph() -> None:
    original = _base_context()
    stale_report = RepositoryReportService().build(original).to_dict()
    changed = _base_context()
    graph = changed["semantic_graph"]
    assert isinstance(graph, dict)
    graph["nodes"].append(_node(
        "type:new",
        KnowledgeKind.TYPE,
        "demo.New",
        project="app",
        language="java",
    ))
    changed["repository_report"] = stale_report

    result = StructuredExplanationService(_snapshot(changed)).explain(
        ExplanationRequest("repository", KnowledgeKind.REPOSITORY.value)
    )
    capability = next(
        item for item in result.capabilities if item.name == "repository_report"
    )

    assert capability.availability is ExplanationAvailability.UNAVAILABLE
    assert any("stale" in item or "graph" in item for item in capability.limitations)
    assert "Deterministic repository report" not in {
        fact.title for fact in result.facts
    }


def test_dangling_graph_edges_report_partial_canonical_graph_coverage() -> None:
    context = _base_context()
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    graph["edges"].append(_edge(
        "type:missing",
        "type:service",
        "related_to",
        "malformed:dangling",
    ))

    result = StructuredExplanationService(_snapshot(context)).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    capability = next(
        item for item in result.capabilities if item.name == "canonical_graph"
    )

    assert capability.availability is ExplanationAvailability.PARTIAL
    assert capability.coverage is None
    assert any("dangling" in item for item in capability.limitations)


def test_exact_round_trip_reordered_determinism_and_source_safety() -> None:
    first_context = _context_with_verified_findings()
    second_context = deepcopy(first_context)
    first_graph = first_context["semantic_graph"]
    second_graph = second_context["semantic_graph"]
    assert isinstance(first_graph, dict) and isinstance(second_graph, dict)
    first_graph["edges"][0]["evidence"].append(_SOURCE_MARKER)
    second_graph["edges"][0]["evidence"].append(_SOURCE_MARKER)
    second_graph["nodes"] = list(reversed(second_graph["nodes"]))
    second_graph["edges"] = list(reversed(second_graph["edges"]))
    for key in ("design_patterns", "reachability", "risk_analysis"):
        first_value = first_context[key]
        second_value = second_context[key]
        assert isinstance(first_value, dict) and isinstance(second_value, dict)
        index = second_value["evidence_index"]
        assert isinstance(index, dict)
        index["records"] = list(reversed(index["records"]))

    request = ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    first = StructuredExplanationService(
        _snapshot(first_context, fixed_id="fixed-snapshot")
    ).explain(request)
    second = StructuredExplanationService(
        _snapshot(second_context, fixed_id="fixed-snapshot")
    ).explain(request)
    payload = first.to_dict()

    assert StructuredExplanation.from_dict(payload).to_dict() == payload
    assert first.to_json() == second.to_json()
    assert first.context_digest == second.context_digest
    serialized = first.to_json()
    assert _SOURCE_MARKER not in serialized
    assert "public class Service" not in serialized
    assert "C:/Users/alice" not in serialized
    assert "C%3A%2FUsers%2Falice" not in serialized
    assert not contains_absolute_path(payload)

    with pytest.raises(ValueError, match="workspace-relative|absolute paths"):
        StructuredExplanationService(_snapshot(_base_context())).explain(
            ExplanationRequest(
                "demo.Service",
                KnowledgeKind.TYPE.value,
                path_constraint="C:/Users/alice/private/Service.java",
            )
        )


def test_deserialization_rejects_explanation_evidence_scoped_to_another_subject() -> None:
    result = StructuredExplanationService(_snapshot(_base_context())).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    payload = result.to_dict()
    facts = payload["facts"]
    evidence_index = payload["evidence_index"]
    assert isinstance(facts, list) and isinstance(evidence_index, dict)
    records = evidence_index["records"]
    assert isinstance(records, list)
    fact = facts[0]
    assert isinstance(fact, dict)
    evidence_id = fact["evidence_ids"][0]
    position = next(
        index for index, item in enumerate(records)
        if item["evidence_id"] == evidence_id
    )
    original = EvidenceRecord.from_dict(records[position])
    cross_scoped = EvidenceRecord.create(
        original.kind,
        original.subject_id,
        original.producer,
        original.snapshot_id,
        source_refs=original.source_refs,
        scope="type:other",
        language=original.language,
        detail=original.detail,
        limitations=original.limitations,
        reliability=original.reliability,
        specificity=original.specificity,
    )
    records[position] = cross_scoped.to_dict()
    fact["evidence_ids"] = [cross_scoped.evidence_id]
    payload["citations"] = sorted(
        cross_scoped.evidence_id if item == evidence_id else item
        for item in payload["citations"]
    )
    payload["context_digest"] = ""

    with pytest.raises(ValueError, match="scope|cross-subject"):
        StructuredExplanation.from_dict(payload)


def test_deserialization_rejects_statement_that_no_longer_matches_fact_id() -> None:
    result = StructuredExplanationService(_snapshot(_base_context())).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    payload = result.to_dict()
    facts = payload["facts"]
    assert isinstance(facts, list) and isinstance(facts[0], dict)
    facts[0]["statement"] = "A different unsupported statement."
    payload["context_digest"] = ""

    with pytest.raises(ValueError, match="fact ID|identity|trace"):
        StructuredExplanation.from_dict(payload)


def test_injected_resolver_must_belong_to_the_supplied_snapshot_graph() -> None:
    snapshot = _snapshot(_base_context())
    other_context = _base_context()
    graph = other_context["semantic_graph"]
    assert isinstance(graph, dict)
    graph["nodes"].append(_node(
        "type:foreign",
        KnowledgeKind.TYPE,
        "foreign.Subject",
        project="foreign",
        language="java",
    ))
    foreign_resolver = CanonicalSubjectResolver.from_snapshot(
        _snapshot(other_context)
    )

    with pytest.raises(ValueError, match="resolver|graph digest|snapshot"):
        StructuredExplanationService(snapshot, resolver=foreign_resolver)


def test_context_selection_is_bounded_and_keeps_exact_evidence_closure() -> None:
    context = _base_context()
    graph = context["semantic_graph"]
    assert isinstance(graph, dict)
    nodes = graph["nodes"]
    edges = graph["edges"]
    assert isinstance(nodes, list) and isinstance(edges, list)
    for index in range(64):
        node_id = f"type:neighbor-{index:02d}"
        nodes.append(_node(
            node_id,
            KnowledgeKind.TYPE,
            f"demo.Neighbor{index:02d}",
            project="app",
            language="java",
        ))
        edges.append(_edge(
            "type:service",
            node_id,
            "related_to",
            f"semantic-neighbor:{index:02d}",
        ))

    selector = StructuredExplanationSelector(_CharacterEstimator())
    service = StructuredExplanationService(_snapshot(context), selector=selector)
    full = service.explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    selected = None
    for budget in range(4_000, min(len(full.to_json()), 30_000), 1_000):
        try:
            candidate = service.explain(
                ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value),
                token_budget=budget,
            )
        except ExplanationContextBudgetError:
            continue
        if candidate.selection.truncated:
            selected = candidate
            break

    assert selected is not None
    assert selected.availability is ExplanationAvailability.PARTIAL
    assert selected.selection.applied
    assert selected.selection.truncated
    assert selected.selection.estimated_tokens <= selected.selection.token_budget
    assert selected.selection.included_fact_count == len(selected.facts)
    assert selected.selection.included_evidence_count == len(selected.evidence_index)
    assert set(selected.citations) == {
        record.evidence_id for record in selected.evidence_index.records
    }
    assert any(fact.title == "Canonical subject identity" for fact in selected.facts)


def test_selection_constructor_and_deserializer_share_budget_invariants() -> None:
    invalid = {
        "applied": True,
        "token_budget": 10,
        "estimated_tokens": 11,
        "total_fact_count": 0,
        "included_fact_count": 0,
        "omitted_fact_count": 0,
        "total_evidence_count": 0,
        "included_evidence_count": 0,
        "omitted_evidence_count": 0,
        "truncated": False,
        "policy": "structured-explanation-context.v1",
    }

    with pytest.raises(ValueError, match="exceeds its token budget"):
        ExplanationSelection(
            True, 10, 11, 0, 0, 0, 0, 0, 0, False,
        )
    with pytest.raises(ValueError, match="exceeds its token budget"):
        ExplanationSelection.from_dict(invalid)
    with pytest.raises(ValueError, match="positive"):
        ExplanationSelection(True, 0)
    with pytest.raises(ValueError, match="positive"):
        StructuredExplanationService(_snapshot(_base_context())).explain(
            ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value),
            token_budget=0,
        )

    valid = ExplanationSelection(True, 10, 10, 1, 1, 0, 1, 1, 0, False)
    assert ExplanationSelection.from_dict(valid.to_dict()) == valid


def test_public_numeric_contract_rejects_boolean_and_fractional_counts() -> None:
    with pytest.raises((TypeError, ValueError)):
        ExplanationSelection(True, 10.5, 10, 1, 1, 0, 1, 1, 0, False)
    with pytest.raises((TypeError, ValueError)):
        ExplanationSelection(True, 10, 9.5, 1, 1, 0, 1, 1, 0, False)
    with pytest.raises((TypeError, ValueError)):
        ExplanationSelection(True, 10, 10, True, True, 0, 1, 1, 0, False)
    with pytest.raises((TypeError, ValueError)):
        ExplanationCapability(
            "test",
            ExplanationAvailability.AVAILABLE,
            coverage=True,
        )

    service = StructuredExplanationService(_snapshot(_base_context()))
    with pytest.raises((TypeError, ValueError)):
        service.explain(
            ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value),
            token_budget=1_000_000.5,
        )


def test_provider_free_renderer_is_deterministic_and_adds_no_facts() -> None:
    result = StructuredExplanationService(_snapshot(_base_context())).explain(
        ExplanationRequest("demo.Service", KnowledgeKind.TYPE.value)
    )
    renderer = StructuredExplanationRenderer()

    first = renderer.render(result)
    second = renderer.render(
        StructuredExplanation.from_dict(json.loads(result.to_json()))
    )

    assert first == second
    assert "# Atlas Structured Explanation" in first
    assert sum(line.startswith("### ") for line in first.splitlines()) == len(result.facts)
    assert result.facts[0].statement in first
    assert _SOURCE_MARKER not in first
    assert "LLM" not in first
