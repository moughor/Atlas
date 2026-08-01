from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from benchmarks.benchmark_pr133_repository_report import benchmark
from moughorai.ai_context import (
    SemanticContextCollector,
    SemanticProjectAnalyzer,
    WorkspaceSemanticContext,
)
from moughorai.ai_explain import ExplainEngine, ExplainRequest
from moughorai.ai_memory import ConversationMemoryStore
from moughorai.llm import LlmClient, LlmResponse, ScriptedLlmProvider
from moughorai.repository_report import (
    ReportCapabilityState,
    ReportContextBudgetError,
    ReportObservationState,
    ReportSectionKind,
    RepositoryReport,
    RepositoryReportContextSelector,
    RepositoryReportService,
)
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import (
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
)


class _CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


class _OscillatingEstimator:
    def estimate(self, text: str) -> int:
        value = json.loads(text)
        selection = value.get("selection", {})
        return 2 if selection.get("estimated_tokens") == 1 else 1


def _base_context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "workspace": {
            "root": "C:/Users/alice/checkouts/atlas-demo",
            "projects": [
                {"name": "atlas-demo", "path": "."},
                {"name": "api", "path": "api"},
            ],
        },
        "repository_summary": {
            "schema_version": 1,
            "root": "C:/Users/alice/checkouts/atlas-demo",
            "project_count": 2,
            "projects": [
                {"name": "atlas-demo", "path": "."},
                {"name": "api", "path": "api"},
            ],
            "inventoried_file_count": 20,
            "inventoried_file_bytes": 2_000,
            "inventoried_file_size_error_count": 0,
            "classified_non_test_source_files": 12,
            "classified_test_source_files": 6,
            "classified_generated_files": 2,
            "language_file_counts": {"Java": 16, "Python": 4},
            "build_systems": ["Maven", "Gradle"],
            "frameworks": ["JUnit"],
            "framework_evidence": [
                {
                    "framework": "JUnit",
                    "project": "api",
                    "scope": "production",
                    "reference": "org.junit:junit-bom",
                }
            ],
            "module_hierarchy": [
                {"project": "atlas-demo", "parent": None},
                {"project": "api", "parent": "atlas-demo"},
            ],
            "entry_points": ["api:src/main/java/demo/App.java"],
            "declared_dependency_count_by_ecosystem": {"maven": 7},
            "dependency_manifest_count_by_ecosystem": {"maven": 2},
        },
        "architecture": {
            "schema_version": 1,
            "findings": [],
            "dependency_cycles": [],
            "classification_conflicts": [],
            "dependency_analysis": {"executed": False, "evidence_edge_count": 0},
        },
        "semantic_graph": {
            "schema_version": 1,
            "nodes": [
                {
                    "id": "project:atlas-demo",
                    "kind": "project",
                    "qualified_name": "atlas-demo",
                    "project_id": "atlas-demo",
                    "language": "unknown",
                },
                {
                    "id": "project:api",
                    "kind": "project",
                    "qualified_name": "api",
                    "project_id": "api",
                    "language": "unknown",
                },
            ],
            "edges": [
                {
                    "source": "project:api",
                    "target": "project:atlas-demo",
                    "kind": "belongs_to",
                    "evidence": ["workspace-project:api"],
                }
            ],
        },
    }


def _snapshot(context: dict[str, object]) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="workspace-fingerprint",
        analyzer_version="test",
    )


def _section(report: RepositoryReport, kind: ReportSectionKind):
    return next(section for section in report.sections if section.kind is kind)


def _item(report: RepositoryReport, title: str):
    return next(item for item in report.items if item.title == title)


def _attribute(report_item, key: str):
    return next(attribute.value for attribute in report_item.attributes if attribute.key == key)


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


def _evidence(subject: str, producer: str) -> EvidenceRecord:
    return EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        subject,
        producer,
        "snapshot:test",
        source_refs=(subject,),
        detail={"verified": "true"},
        reliability=0.9,
        specificity=1.0,
    )


def _risk_context(record: EvidenceRecord) -> dict[str, object]:
    return {
        "schema_version": 1,
        "producer_version": "atlas-pr132/1",
        "input_fingerprint": "risk-input",
        "configuration_fingerprint": "risk-configuration",
        "hotspots": [
            {
                "rank": 1,
                "subject_id": "type:demo.Service",
                "display_name": "demo.Service",
                "project": "api",
                "kind": "type",
                "language": "Java",
                "scope": "production",
                "score": 0.8,
                "confidence": _confidence(),
                "factors": [
                    {
                        "metric": {
                            "metric": "fan_in",
                            "status": "available",
                            "raw_value": 5,
                            "unit": "edges",
                        }
                    }
                ],
                "missing_signals": ["test_density"],
                "trend": "unavailable",
                "evidence_ids": [record.evidence_id],
                "limitations": ["Test-density evidence is unavailable."],
            }
        ],
        "capabilities": [
            {"metric": "fan_in", "status": "available", "observation_count": 1},
            {"metric": "test_density", "status": "unavailable", "observation_count": 0},
        ],
        "evidence_index": EvidenceIndex((record,)).to_dict(),
        "limitations": [],
    }


def _reachability_context(
    record: EvidenceRecord,
    *,
    grouped: bool,
) -> dict[str, object]:
    shared = {
        "symbol_kind": "type",
        "language": "Java",
        "project": "api",
        "source_classification": "production",
        "state": "likely_dead",
        "confidence": 0.9,
        "confidence_tier": "high",
        "evidence_ids": [record.evidence_id],
        "production_reachable": False,
        "test_reachable": False,
        "limitations": [],
    }
    value: dict[str, object] = {
        "schema_version": 1,
        "producer_version": "atlas-pr131/1",
        "input_fingerprint": "reachability-input",
        "configuration_fingerprint": "reachability-configuration",
        "coverage": {
            "status": "partial",
            "projects": [],
            "languages_supported": ["Java"],
            "languages_partial": [],
            "subject_counts": {"likely_dead": 1},
            "traversal_truncated": False,
            "limitations": [],
        },
        "evidence_index": EvidenceIndex((record,)).to_dict(),
        "limitations": [],
    }
    if grouped:
        value["serialization"] = "grouped-findings-v1"
        value["finding_groups"] = [
            {**shared, "subject_id_prefix": "type:", "subject_ids": ["demo.Legacy"]}
        ]
    else:
        value["findings"] = [{**shared, "subject_id": "type:demo.Legacy"}]
    return value


def test_report_round_trip_and_reordered_inputs_are_exact() -> None:
    first_context = _base_context()
    first_context["architecture"] = {
        "schema_version": 1,
        "findings": [
            {
                "architecture": "layered",
                "confidence": 0.8,
                "evidence": [
                    {
                        "kind": "graph-edge",
                        "reference": "project:api->project:atlas-demo",
                        "detail": "resolved dependency",
                    },
                    {
                        "kind": "semantic-relationship",
                        "reference": "project:atlas-demo->project:api",
                        "detail": "resolved ownership",
                    },
                ],
            },
            {
                "architecture": "modular-monolith",
                "confidence": 0.82,
                "evidence": [
                    {
                        "kind": "dependency-edge",
                        "reference": "project:api",
                        "detail": "workspace module",
                    },
                    {
                        "kind": "graph-edge",
                        "reference": "project:atlas-demo",
                        "detail": "workspace root",
                    },
                ],
            },
            {
                "architecture": "layered",
                "confidence": 0.8,
                "evidence": [
                    {
                        "kind": "graph-edge",
                        "reference": "project:atlas-demo->project:engine",
                        "detail": "resolved dependency",
                    }
                ],
            },
        ],
        "dependency_cycles": [["api", "core"], ["engine", "spi"]],
        "classification_conflicts": ["modular-monolith conflicts with microservices", "layering is partial"],
        "dependency_analysis": {"executed": True, "evidence_edge_count": 2},
    }
    reordered = deepcopy(first_context)
    reordered["repository_summary"]["projects"].reverse()  # type: ignore[index]
    reordered["repository_summary"]["build_systems"].reverse()  # type: ignore[index]
    reordered["repository_summary"]["module_hierarchy"].reverse()  # type: ignore[index]
    reordered["semantic_graph"]["nodes"].reverse()  # type: ignore[index]
    reordered["architecture"]["findings"].reverse()  # type: ignore[index]
    for finding in reordered["architecture"]["findings"]:  # type: ignore[index]
        finding["evidence"].reverse()
    reordered["architecture"]["dependency_cycles"].reverse()  # type: ignore[index]
    for cycle in reordered["architecture"]["dependency_cycles"]:  # type: ignore[index]
        cycle.reverse()
    reordered["architecture"]["classification_conflicts"].reverse()  # type: ignore[index]

    first = RepositoryReportService().build(first_context)
    second = RepositoryReportService().build(reordered)

    assert first.to_dict() == second.to_dict()
    assert first.to_dict() == RepositoryReport.from_dict(first.to_dict()).to_dict()
    assert first.stable_digest() == second.stable_digest()


def test_serialized_collection_order_is_canonical_and_evidence_is_report_owned() -> None:
    report = RepositoryReportService().build(_base_context())
    canonical = report.to_dict()
    reordered = deepcopy(canonical)
    reordered["items"].reverse()  # type: ignore[index]
    reordered["sections"].reverse()  # type: ignore[index]
    for section in reordered["sections"]:  # type: ignore[index]
        section["item_ids"].reverse()
    reordered["evidence_index"]["records"].reverse()  # type: ignore[index]

    assert RepositoryReport.from_dict(reordered).to_dict() == canonical

    cross_subject = deepcopy(canonical)
    cross_subject["items"][0]["evidence_ids"] = (  # type: ignore[index]
        cross_subject["items"][1]["evidence_ids"]  # type: ignore[index]
    )
    with pytest.raises(ValueError, match="foreign or cross-subject"):
        RepositoryReport.from_dict(cross_subject)

    unreferenced = deepcopy(canonical)
    extra = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "report-item:" + "f" * 64,
        report.producer_version,
        report.lineage,
        source_refs=("repository_summary.extra",),
    )
    unreferenced["evidence_index"]["records"].append(extra.to_dict())  # type: ignore[index]
    with pytest.raises(ValueError, match="exactly cited evidence"):
        RepositoryReport.from_dict(unreferenced)


def test_persisted_count_metadata_is_validated() -> None:
    report = RepositoryReportService().build(_base_context())
    selected = RepositoryReportContextSelector().select(
        report,
        token_budget=100_000,
    ).to_dict()

    wrong_section_count = deepcopy(selected)
    wrong_section_count["sections"][0]["included_item_count"] = 999  # type: ignore[index]
    with pytest.raises(ValueError, match="section included item count"):
        RepositoryReport.from_dict(wrong_section_count)

    wrong_selection_count = deepcopy(selected)
    wrong_selection_count["selection"]["included_item_count"] = 999  # type: ignore[index]
    with pytest.raises(ValueError, match="selection included item count"):
        RepositoryReport.from_dict(wrong_selection_count)

    over_budget = deepcopy(selected)
    over_budget["selection"]["estimated_tokens"] = (  # type: ignore[index]
        over_budget["selection"]["token_budget"] + 1  # type: ignore[index]
    )
    with pytest.raises(ValueError, match="estimate exceeds"):
        RepositoryReport.from_dict(over_budget)


def test_pr127_to_pr129_only_builds_a_truthful_partial_report() -> None:
    report = RepositoryReportService().build(_base_context())

    assert _section(report, ReportSectionKind.EXECUTIVE_SUMMARY).capability_state is ReportCapabilityState.AVAILABLE
    architecture = _section(report, ReportSectionKind.ARCHITECTURE)
    assert architecture.capability_state is ReportCapabilityState.PARTIAL
    assert architecture.observation_state is ReportObservationState.UNKNOWN
    assert _section(report, ReportSectionKind.RISKS).capability_state is ReportCapabilityState.UNAVAILABLE
    assert _section(report, ReportSectionKind.STRENGTHS).item_ids == ()
    assert _section(report, ReportSectionKind.WEAKNESSES).item_ids == ()


def test_pr130_pattern_findings_are_compact_and_traceable() -> None:
    record = _evidence("type:demo.Strategy", "atlas-pr130/1")
    context = _base_context()
    context["design_patterns"] = {
        "schema_version": 1,
        "producer_version": "atlas-pr130/1",
        "input_fingerprint": "patterns-input",
        "findings": [{
            "pattern": "strategy",
            "participants": [
                {"role": "strategy", "symbol_id": "type:demo.Strategy"},
                {"role": "implementation", "symbol_id": "type:demo.FastStrategy"},
            ],
            "confidence": 0.9,
            "confidence_tier": "high",
            "evidence_ids": [record.evidence_id],
            "limitations": ["Resolved calls are unavailable."],
        }],
        "evidence_index": EvidenceIndex((record,)).to_dict(),
    }

    report = RepositoryReportService().build(context)
    item = _item(report, "strategy pattern")
    derived = report.evidence_index.get(item.evidence_ids[0])

    assert item.observation_state is ReportObservationState.OBSERVED
    assert _attribute(item, "finding_count") == 1
    assert _attribute(item, "verified_evidence_count") == 1
    assert derived is not None
    assert record.evidence_id in derived.source_refs
    assert "type:demo.FastStrategy" not in report.to_json()


def test_absent_or_incompatible_producers_are_explicitly_unavailable() -> None:
    context = _base_context()
    context.pop("architecture")
    context["design_patterns"] = {"schema_version": 999, "producer_version": "atlas-pr130/1"}
    context["risk_analysis"] = {"schema_version": 1, "producer_version": "future-risk/2"}

    report = RepositoryReportService().build(context)

    assert _section(report, ReportSectionKind.ARCHITECTURE).capability_state is ReportCapabilityState.UNAVAILABLE
    assert _section(report, ReportSectionKind.RISKS).capability_state is ReportCapabilityState.UNAVAILABLE
    assert any("incompatible" in limitation for limitation in report.limitations)


def test_source_free_report_filters_and_rejects_embedded_absolute_paths() -> None:
    context = _base_context()
    secret_path = "api:C:/Users/alice/private/Main.java"
    raw_source = 'class Secret { String token = "TOP-SECRET"; }'
    context["repository_summary"]["entry_points"] = [secret_path]  # type: ignore[index]
    context["raw_source"] = raw_source

    report = RepositoryReportService().build(context)
    serialized = report.to_json()

    assert secret_path not in serialized
    assert "C:/Users/alice" not in serialized
    assert raw_source not in serialized

    malformed = report.to_dict()
    malformed["items"][0]["statement"] = "Inspect api:C:/Users/alice/private/Main.java"  # type: ignore[index]
    with pytest.raises(ValueError, match="absolute paths"):
        RepositoryReport.from_dict(malformed)


def test_selector_is_bounded_deterministic_and_finalizes_its_token_estimate() -> None:
    record = _evidence("type:demo.Service", "atlas-pr132/1")
    context = _base_context()
    context["risk_analysis"] = _risk_context(record)
    report = RepositoryReportService().build(context)
    selector = RepositoryReportContextSelector(_CharacterEstimator())
    mandatory_ids = {
        item.item_id
        for item in report.items
        if item.priority <= selector.MANDATORY_PRIORITY
    }
    mandatory = selector._finalize_estimate(  # noqa: SLF001 - fixed-point regression
        selector._materialize(report, mandatory_ids, 9_999)  # noqa: SLF001
    )
    budget = selector._estimate(mandatory) + 32  # noqa: SLF001

    first = selector.select(report, token_budget=budget)
    second = selector.select(report, token_budget=budget)

    assert first.to_dict() == second.to_dict()
    assert set(mandatory_ids) <= {item.item_id for item in first.items}
    assert len(first.items) < len(report.items)
    assert first.selection.omitted_item_count == len(report.items) - len(first.items)
    assert first.selection.estimated_tokens == selector._estimate(first)  # noqa: SLF001
    assert first.selection.estimated_tokens <= budget
    referenced = {evidence_id for item in first.items for evidence_id in item.evidence_ids}
    assert {record.evidence_id for record in first.evidence_index.records} == referenced

    complete = selector.select(report, token_budget=1_000_000)
    recommendation = next(
        item for item in complete.items
        if item.kind.value == "recommendation"
    )
    selected_ids = {item.item_id for item in complete.items}
    assert set(recommendation.related_item_ids) <= selected_ids
    assert complete.to_dict() == RepositoryReport.from_dict(
        complete.to_dict()
    ).to_dict()

    with pytest.raises(ReportContextBudgetError):
        selector.select(report, token_budget=10)


def test_selector_rejects_a_nonconvergent_token_estimator() -> None:
    report = RepositoryReportService().build(_base_context())
    selector = RepositoryReportContextSelector(_OscillatingEstimator())
    mandatory_ids = {
        item.item_id
        for item in report.items
        if item.priority <= selector.MANDATORY_PRIORITY
    }
    materialized = selector._materialize(  # noqa: SLF001
        report,
        mandatory_ids,
        100,
    )

    with pytest.raises(ReportContextBudgetError, match="fixed point"):
        selector._finalize_estimate(materialized)  # noqa: SLF001


def test_upstream_evidence_is_verified_before_a_finding_is_reported() -> None:
    record = _evidence("type:demo.Service", "atlas-pr132/1")
    context = _base_context()
    context["risk_analysis"] = _risk_context(record)

    verified = RepositoryReportService().build(context)
    risk_item = next(item for item in verified.items if item.title.startswith("Risk hotspot"))
    derived = verified.evidence_index.get(risk_item.evidence_ids[0])
    assert derived is not None
    assert record.evidence_id in derived.source_refs

    tampered_context = deepcopy(context)
    tampered_id = "evidence:" + "0" * 64
    tampered_context["risk_analysis"]["hotspots"][0]["evidence_ids"] = [tampered_id]  # type: ignore[index]
    tampered_context["risk_analysis"]["evidence_index"]["records"][0]["evidence_id"] = tampered_id  # type: ignore[index]
    rejected = RepositoryReportService().build(tampered_context)
    assert rejected.input_fingerprint != verified.input_fingerprint
    assert not any(item.title.startswith("Risk hotspot") for item in rejected.items)
    assert any(
        "evidence IDs could not be verified" in limitation
        for limitation in _section(rejected, ReportSectionKind.RISKS).limitations
    )

    mismatched_context = deepcopy(context)
    unrelated = _evidence("type:demo.Unrelated", "atlas-pr132/1")
    mismatched_context["risk_analysis"]["hotspots"][0]["evidence_ids"] = [  # type: ignore[index]
        unrelated.evidence_id
    ]
    mismatched_context["risk_analysis"]["evidence_index"] = (  # type: ignore[index]
        EvidenceIndex((unrelated,)).to_dict()
    )
    mismatched = RepositoryReportService().build(mismatched_context)
    assert not any(item.title.startswith("Risk hotspot") for item in mismatched.items)


def test_dependency_total_falls_back_to_per_ecosystem_counts() -> None:
    context = _base_context()
    summary = context["repository_summary"]
    assert isinstance(summary, dict)
    summary.pop("total_declared_dependency_records", None)
    summary.pop("total_declared_dependencies", None)
    summary["declared_dependency_count_by_ecosystem"] = {"maven": 7, "gradle": 5}

    report = RepositoryReportService().build(context)
    dependency = _item(report, "Dependency overview")

    assert _attribute(dependency, "declared_dependency_records") == 12
    assert "12 declared dependency record(s)" in dependency.statement


def test_grouped_and_ungrouped_reachability_have_identical_report_identity() -> None:
    record = _evidence("type:demo.Legacy", "atlas-pr131/1")
    ungrouped_context = _base_context()
    ungrouped_context["reachability"] = _reachability_context(record, grouped=False)
    grouped_context = _base_context()
    grouped_context["reachability"] = _reachability_context(record, grouped=True)

    ungrouped = RepositoryReportService().build(ungrouped_context)
    grouped = RepositoryReportService().build(grouped_context)

    assert ungrouped.input_fingerprint == grouped.input_fingerprint
    assert ungrouped.to_dict() == grouped.to_dict()


def test_reachability_top_k_total_changes_report_identity() -> None:
    records = tuple(
        _evidence(f"type:demo.Legacy{index}", "atlas-pr131/1")
        for index in range(12)
    )
    reachability = _reachability_context(records[0], grouped=False)
    prototype = reachability["findings"][0]  # type: ignore[index]
    reachability["findings"] = [
        {
            **prototype,
            "subject_id": f"type:demo.Legacy{index}",
            "evidence_ids": [record.evidence_id],
        }
        for index, record in enumerate(records)
    ]
    reachability["evidence_index"] = EvidenceIndex(records).to_dict()
    context = _base_context()
    context["reachability"] = reachability

    report = RepositoryReportService().build(context)
    section = _section(report, ReportSectionKind.TECHNICAL_DEBT)
    assert len(section.item_ids) == 10
    assert section.total_item_count == 12
    assert section.omitted_item_count == 2

    extra = _evidence("type:demo.Legacy12", "atlas-pr131/1")
    extended_context = deepcopy(context)
    extended = extended_context["reachability"]
    extended["findings"].append({  # type: ignore[index]
        **prototype,
        "subject_id": "type:demo.Legacy12",
        "evidence_ids": [extra.evidence_id],
    })
    extended["evidence_index"] = EvidenceIndex((*records, extra)).to_dict()  # type: ignore[index]
    extended_report = RepositoryReportService().build(extended_context)

    assert extended_report.input_fingerprint != report.input_fingerprint
    assert _section(
        extended_report, ReportSectionKind.TECHNICAL_DEBT
    ).total_item_count == 13


def test_cycle_debt_counts_and_recommendations_remain_pr128_scoped() -> None:
    context = _base_context()
    architecture = context["architecture"]
    architecture["dependency_analysis"] = {  # type: ignore[index]
        "executed": True,
        "evidence_edge_count": 14,
    }
    architecture["dependency_cycles"] = [  # type: ignore[index]
        [f"module-{index}", f"module-{index + 1}"]
        for index in range(7)
    ]

    report = RepositoryReportService().build(context)
    debt = _section(report, ReportSectionKind.TECHNICAL_DEBT)
    assert len(debt.item_ids) == 5
    assert debt.total_item_count == 7
    assert debt.omitted_item_count == 2

    cycle_recommendations = [
        item for item in report.items
        if item.title.startswith("Investigation: Dependency cycle")
    ]
    assert cycle_recommendations
    assert all("PR128" in item.statement for item in cycle_recommendations)
    assert all("PR131" not in item.statement for item in cycle_recommendations)
    assert all(
        any("PR128" in prerequisite for prerequisite in item.prerequisites)
        for item in cycle_recommendations
    )


def test_nested_pr132_factor_metadata_uses_precise_labels() -> None:
    record = _evidence("type:demo.Service", "atlas-pr132/1")
    context = _base_context()
    context["risk_analysis"] = _risk_context(record)

    report = RepositoryReportService().build(context)
    hotspot = next(item for item in report.items if item.title.startswith("Risk hotspot"))

    assert _attribute(hotspot, "factor_metrics_and_units") == "fan_in (edges)"
    assert "{'metric'" not in report.to_json()
    assert "risk indicator" in hotspot.statement
    assert "bug, defect, or vulnerability" in hotspot.statement
    assert hotspot.confidence is not None
    assert hotspot.confidence.to_dict() == _confidence()
    recommendation = next(
        item for item in report.items if item.title.startswith("Investigation:")
    )
    assert recommendation.confidence is not None
    assert recommendation.confidence.score <= hotspot.confidence.score


def test_hotspot_top_k_has_exact_omitted_count() -> None:
    records = tuple(
        _evidence(f"type:demo.Service{index}", "atlas-pr132/1")
        for index in range(12)
    )
    risk = _risk_context(records[0])
    prototype = risk["hotspots"][0]  # type: ignore[index]
    risk["hotspots"] = [
        {
            **prototype,
            "rank": index + 1,
            "subject_id": f"type:demo.Service{index}",
            "display_name": f"demo.Service{index}",
            "evidence_ids": [record.evidence_id],
        }
        for index, record in enumerate(records)
    ]
    risk["evidence_index"] = EvidenceIndex(records).to_dict()
    context = _base_context()
    context["risk_analysis"] = risk

    report = RepositoryReportService().build(context)
    section = _section(report, ReportSectionKind.RISKS)

    assert len(section.item_ids) == 10
    assert section.total_item_count == 12
    assert section.omitted_item_count == 2

    extra = _evidence("type:demo.Service12", "atlas-pr132/1")
    extended_context = deepcopy(context)
    extended_risk = extended_context["risk_analysis"]
    extended_risk["hotspots"].append({  # type: ignore[index]
        **prototype,
        "rank": 13,
        "subject_id": "type:demo.Service12",
        "display_name": "demo.Service12",
        "evidence_ids": [extra.evidence_id],
    })
    extended_risk["evidence_index"] = EvidenceIndex((*records, extra)).to_dict()  # type: ignore[index]
    extended = RepositoryReportService().build(extended_context)
    extended_section = _section(extended, ReportSectionKind.RISKS)

    assert extended.input_fingerprint != report.input_fingerprint
    assert extended_section.total_item_count == 13
    assert extended_section.omitted_item_count == 3


def test_missing_findings_do_not_fabricate_strengths_weaknesses_or_negatives() -> None:
    report = RepositoryReportService().build(_base_context())
    strengths = _section(report, ReportSectionKind.STRENGTHS)
    weaknesses = _section(report, ReportSectionKind.WEAKNESSES)

    assert strengths.item_ids == ()
    assert weaknesses.item_ids == ()
    assert strengths.capability_state is ReportCapabilityState.UNAVAILABLE
    assert weaknesses.capability_state is ReportCapabilityState.UNAVAILABLE
    statements = "\n".join(item.statement.casefold() for item in report.items)
    assert "no issues" not in statements
    assert "no risks" not in statements
    assert "no technical debt" not in statements
    assert "safe to delete" not in statements


def test_persisted_default_explain_is_provider_free_source_free_and_deterministic() -> None:
    context = _base_context()
    context["repository_report"] = RepositoryReportService().build(context).to_dict()
    restored = AtlasSemanticSnapshot.from_dict(_snapshot(context).to_dict())

    first = ExplainEngine().explain(restored)
    second = ExplainEngine().explain(restored)

    assert first.markdown == second.markdown
    assert first.estimated_input_tokens == 0
    assert first.structured_explanation is not None
    assert second.structured_explanation is not None
    assert (
        first.structured_explanation.to_json()
        == second.structured_explanation.to_json()
    )
    assert first.context_digest == first.structured_explanation.context_digest
    assert first.citations == first.structured_explanation.citations
    assert "## AI repository report" in first.markdown
    assert first.markdown.count("### Executive summary") == 1
    assert "## Inventory" not in first.markdown
    assert "C:/Users/alice" not in first.markdown


def test_pr133_default_skips_provider_while_targeted_explain_remains_compatible() -> None:
    context = _base_context()
    context["repository_report"] = RepositoryReportService().build(context).to_dict()
    snapshot = _snapshot(context)
    provider = ScriptedLlmProvider(
        [LlmResponse("# Targeted\n\nVerified.", "test", "model")],
        name="test",
    )
    engine = ExplainEngine(LlmClient(provider))

    default = engine.explain(snapshot)
    assert "## AI repository report" in default.markdown
    assert default.structured_explanation is not None
    assert provider.calls == []

    targeted = engine.explain(snapshot, ExplainRequest(subject="api"))
    assert targeted.markdown.startswith("# Atlas Structured Explanation")
    assert "## Optional provider narrative" in targeted.markdown
    assert targeted.markdown.endswith("# Targeted\n\nVerified.")
    assert targeted.structured_explanation is not None
    assert len(provider.calls) == 1


def test_malformed_pr133_report_falls_back_to_compatible_legacy_context() -> None:
    context = _base_context()
    context["repository_report"] = {"schema_version": 999, "items": []}

    result = ExplainEngine().explain(_snapshot(context))

    assert "## Inventory" in result.markdown
    assert "incompatible or invalid" in result.markdown
    assert "C:/Users/alice" not in result.markdown


def test_structurally_malformed_pr133_reports_never_break_legacy_explain() -> None:
    base_context = _base_context()
    valid_report = RepositoryReportService().build(base_context).to_dict()
    evidence_index = valid_report["evidence_index"]
    assert isinstance(evidence_index, dict)
    evidence_index["records"] = [{}]

    for malformed_report in (valid_report, {"schema_version": float("inf")}):
        context = deepcopy(base_context)
        context["repository_report"] = malformed_report

        result = ExplainEngine().explain(_snapshot(context))

        assert "## Inventory" in result.markdown
        assert "incompatible or invalid" in result.markdown


def test_old_snapshot_falls_back_without_requiring_a_provider() -> None:
    result = ExplainEngine().explain(_snapshot(_base_context()))

    assert result.estimated_input_tokens == 0
    assert "## Inventory" in result.markdown
    assert "This snapshot predates PR133" in result.markdown
    assert "C:/Users/alice" not in result.markdown


def test_targeted_no_client_error_has_no_conversation_memory_side_effect(
    tmp_path: Path,
) -> None:
    memory = ConversationMemoryStore(tmp_path)

    with pytest.raises(ValueError, match="targeted explanations require an LLM client"):
        ExplainEngine(memory=memory).explain(
            _snapshot(_base_context()),
            ExplainRequest(subject="api"),
        )

    assert not memory.path.exists()


def test_collector_publishes_a_round_trippable_repository_report(
    tmp_path: Path,
) -> None:
    project = tmp_path / "app"
    project.mkdir()
    (project / "App.java").write_text(
        "package demo; public class App {}",
        encoding="utf-8",
    )
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )
    service = WorkspaceService(tmp_path)
    document = SemanticProjectAnalyzer()(service.project("app"), {})
    workspace_report = WorkspaceRunReport(
        (ProjectRun("app", ProjectRunStatus.SUCCEEDED, document),),
        ("app",),
        ("app",),
    )

    collected = SemanticContextCollector(service).collect(workspace_report)
    raw_report = collected.context.to_dict()["repository_report"]
    assert isinstance(raw_report, dict)
    report = RepositoryReport.from_dict(raw_report)
    snapshot = SemanticSnapshotStore(service.workspace).capture(collected.context)
    restored = AtlasSemanticSnapshot.from_dict(snapshot.to_dict())

    assert report.to_dict() == raw_report
    assert restored.semantic_context["repository_report"] == raw_report
    assert report.evidence_index.frozen
    assert "package demo" not in report.to_json()


def test_pr133_benchmark_reports_deterministic_bounded_metrics() -> None:
    result = benchmark(synthetic_projects=25, repeats=2)

    assert result["determinism_verified"] is True
    assert result["canonical_graph_node_count"] == 26
    assert result["canonical_graph_edge_count"] == 49
    assert result["selected_token_count"] <= result["token_budget"]
    assert result["projected_report_snapshot_bytes"] > 0
    assert len(str(result["report_hash"])) == 64
