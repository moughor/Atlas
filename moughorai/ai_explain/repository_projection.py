from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
import math
from pathlib import PurePath
from typing import Any

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.project_inventory.classifier import GENERATED_DIRECTORY_NAMES
from moughorai.repository_report import (
    RepositoryReport,
    RepositoryReportContextSelector,
)
from moughorai.repository_report.safety import contains_absolute_path_text
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


class RepositoryExplanationProjector:
    """Build a bounded, source-free repository report from persisted Atlas facts."""

    MAX_FRAMEWORKS = 30
    MAX_FRAMEWORK_REFERENCES = 3
    MAX_ENTRY_POINTS = 20
    MAX_HIERARCHY_RELATIONSHIPS = 25
    MAX_ARCHITECTURE_FINDINGS = 12
    MAX_ARCHITECTURE_RELATIONSHIPS = 20
    MAX_PATTERN_TYPES = 20
    MAX_REACHABILITY_FINDINGS = 8
    MAX_RISK_HOTSPOTS = 10
    MAX_RISK_FACTORS = 7
    MAX_RISK_EVIDENCE_RECORDS = 30
    MAX_EVIDENCE_IDS = 3

    _WEAK_ARCHITECTURE_EVIDENCE = frozenset({
        "module-hierarchy",
        "project-entry-point",
        "semantic-name",
    })
    _STRONG_ARCHITECTURE_EVIDENCE = frozenset({
        "architecture-contract",
        "deployment-boundary",
        "dependency-edge",
        "graph-edge",
        "semantic-relationship",
    })
    _TEST_PARTS = frozenset({
        "test", "tests", "testing", "__tests__", "spec", "specs",
    })
    _RESOURCE_PARTS = frozenset({
        "fixture", "fixtures", "resource", "resources", "template", "templates",
    })
    _GENERATED_PARTS = GENERATED_DIRECTORY_NAMES

    def project(self, snapshot: AtlasSemanticSnapshot) -> WorkspaceSemanticContext:
        source = snapshot.semantic_context
        summary = source.get("repository_summary")
        summary_mapping = summary if isinstance(summary, Mapping) else {}
        workspace = source.get("workspace")
        workspace_mapping = workspace if isinstance(workspace, Mapping) else {}
        workspace_projects_value = workspace_mapping.get("projects")
        root = str(summary_mapping.get("root") or workspace_mapping.get("root") or "")
        project_count = self._optional_int(summary_mapping.get("project_count"))
        project_count_basis: str | None = None
        if project_count is not None:
            project_count_basis = "repository_summary.project_count"
        elif isinstance(summary_mapping.get("projects"), (list, tuple)):
            project_count = len(summary_mapping["projects"])
            project_count_basis = "repository_summary.projects"
        elif isinstance(workspace_projects_value, (list, tuple)):
            project_count = len(workspace_projects_value)
            project_count_basis = "workspace.projects"

        graph = source.get("semantic_graph")
        graph_mapping = graph if isinstance(graph, Mapping) else {}
        graph_nodes_value = graph_mapping.get("nodes")
        graph_edges_value = graph_mapping.get("edges")
        symbols_value = source.get("symbols")
        symbol_count = (
            len(symbols_value)
            if isinstance(symbols_value, (list, tuple))
            else None
        )

        limitations = [
            "This report is source-free; it contains persisted semantic metadata, not raw source code.",
            "LLMs do not create, replace, or alter facts in the default repository report.",
        ]
        if symbol_count is None:
            limitations.append("Detailed symbol count is unavailable in this snapshot.")
        else:
            limitations.append(
                f"Detailed symbols are omitted ({symbol_count} available in the snapshot)."
            )
        if not (
            isinstance(graph_nodes_value, (list, tuple))
            and isinstance(graph_edges_value, (list, tuple))
        ):
            limitations.append("Canonical semantic graph counts are unavailable in this snapshot.")
        else:
            limitations.append(
                "The canonical semantic graph is summarized by counts only "
                f"({len(graph_nodes_value)} nodes, {len(graph_edges_value)} edges)."
            )
        if not summary_mapping:
            limitations.append(
                "Repository summary data is unavailable in this snapshot; inventory facts are unknown."
            )

        raw_report = source.get("repository_report")
        if isinstance(raw_report, Mapping):
            try:
                repository_report: dict[str, object] = (
                    RepositoryReportContextSelector().select(
                        RepositoryReport.from_dict(raw_report),
                        token_budget=RepositoryReportContextSelector.DEFAULT_TOKEN_BUDGET,
                    ).to_dict()
                )
                repository_report["status"] = "available"
            except (KeyError, TypeError, ValueError, OverflowError):
                repository_report = {
                    "status": "unavailable",
                    "limitations": [
                        "The persisted PR133 repository report is incompatible or invalid; compatible legacy facts are shown instead."
                    ],
                }
        else:
            repository_report = {
                "status": "unavailable",
                "limitations": [
                    "This snapshot predates PR133; compatible PR127-PR132 repository facts are shown instead."
                ],
            }

        projected = {
            "report_schema_version": 2,
            "snapshot_schema_version": source.get("schema_version"),
            "workspace": {
                "repository_name": self._repository_name(root),
                "root": (
                    root
                    if root and not contains_absolute_path_text(root)
                    else None
                ),
                "discovered_project_count": project_count,
                "evidence_basis": project_count_basis,
            },
            "repository_summary": self.compact_summary(summary),
            "architecture": self.compact_architecture(source.get("architecture")),
            "design_patterns": self.compact_design_patterns(source.get("design_patterns")),
            "reachability": self.compact_reachability(source.get("reachability")),
            "risk_analysis": self.compact_risk_analysis(source.get("risk_analysis")),
            "repository_report": repository_report,
            "limitations": limitations,
        }
        return WorkspaceSemanticContext(self._source_free_projection(projected))

    def compact_summary(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping) or not value:
            return {
                "status": "unavailable",
                "inventory": {"status": "unavailable", "measurements": {}},
                "language_distribution": {"status": "unavailable", "items": []},
                "build_systems": {"status": "unavailable", "items": []},
                "frameworks_and_related_technologies": {
                    "status": "unavailable", "items": [],
                },
                "entry_point_candidates": {"status": "unavailable", "items": []},
                "filesystem_project_hierarchy": {"status": "unavailable"},
                "dependencies": {"status": "unavailable"},
            }

        projects = self._mapping_records(value.get("projects"))
        inventory = self._inventory(value, projects)
        language_counts = self._count_mapping(
            value.get("language_file_counts", value.get("languages"))
        )
        return {
            "status": "available",
            "schema_version": value.get("schema_version", 1),
            "inventory": inventory,
            "language_distribution": self._language_distribution(language_counts),
            "build_systems": self._build_systems(value, projects),
            "frameworks_and_related_technologies": self._frameworks(value),
            "entry_point_candidates": self._entry_points(value),
            "filesystem_project_hierarchy": self._hierarchy(value),
            "dependencies": self._dependencies(value),
        }

    def compact_architecture(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {
                "status": "unavailable",
                "findings": [],
                "limitations": [
                    "Structured architecture analysis is unavailable in this snapshot."
                ],
            }

        findings: list[dict[str, object]] = []
        for item in self._mapping_records(value.get("findings")):
            evidence = self._mapping_records(item.get("evidence"))
            evidence_kinds = sorted({
                str(record.get("kind")) for record in evidence if record.get("kind")
            })
            evidence_references = sorted({
                str(record.get("reference"))
                for record in evidence if record.get("reference")
            })
            has_required_evidence = bool(
                set(evidence_kinds) & self._STRONG_ARCHITECTURE_EVIDENCE
            )
            producer_confidence = self._optional_float(item.get("confidence"))
            limitations: list[str] = []
            if not has_required_evidence:
                status = "insufficient"
                limitations.append(
                    "Available evidence is naming, filesystem hierarchy, or entry-point "
                    "candidate metadata; it does not establish an architecture pattern."
                )
            else:
                status = self._confidence_tier(producer_confidence)
            findings.append({
                "architecture": item.get("architecture"),
                "status": status,
                "producer_confidence": producer_confidence,
                "evidence_count": len(evidence),
                "evidence_kinds": evidence_kinds,
                "representative_evidence_references": evidence_references[
                    : self.MAX_EVIDENCE_IDS
                ],
                "omitted_evidence_reference_count": max(
                    0, len(evidence_references) - self.MAX_EVIDENCE_IDS
                ),
                "required_evidence_available": has_required_evidence,
                "limitations": limitations,
            })
        findings.sort(key=lambda item: (
            str(item.get("architecture", "")),
            str(item.get("status", "")),
        ))

        dependency_analysis = value.get("dependency_analysis")
        dependency_mapping = (
            dependency_analysis if isinstance(dependency_analysis, Mapping) else {}
        )
        executed = bool(dependency_mapping.get("executed", False))
        evidence_edges = self._optional_int(dependency_mapping.get("evidence_edge_count")) or 0
        dependency_supported = executed and evidence_edges > 0
        directions = tuple(sorted(
            self._mapping_records(value.get("dependency_directions")),
            key=lambda item: tuple(
                sorted((str(key), str(detail)) for key, detail in item.items())
            ),
        ))
        cycles = tuple(sorted(
            self._sequence(value.get("dependency_cycles")),
            key=lambda item: tuple(map(str, self._sequence(item))),
        ))
        dependency_result: dict[str, object] = {
            "status": "available" if dependency_supported else "unavailable",
            "executed": executed,
            "evidence_edge_count": evidence_edges,
            "direction_count": len(directions) if dependency_supported else None,
            "cycle_count": len(cycles) if dependency_supported else None,
            "representative_directions": (
                list(directions[: self.MAX_ARCHITECTURE_RELATIONSHIPS])
                if dependency_supported else []
            ),
            "representative_cycles": (
                list(cycles[: self.MAX_ARCHITECTURE_RELATIONSHIPS])
                if dependency_supported else []
            ),
            "limitations": [],
        }
        if not dependency_supported:
            dependency_result["limitations"] = [
                "No executed dependency check with positive edge coverage is recorded; "
                "cycle and directionality conclusions are unavailable."
            ]

        areas = self._strings(value.get("bounded_contexts"))
        ports = self._strings(value.get("ports"))
        adapters = self._strings(value.get("adapters"))
        infrastructure = self._strings(value.get("infrastructure_layers"))
        included = findings[: self.MAX_ARCHITECTURE_FINDINGS]
        return {
            "status": "available",
            "schema_version": value.get("schema_version"),
            "finding_count": len(findings),
            "included_finding_count": len(included),
            "omitted_finding_count": len(findings) - len(included),
            "findings": included,
            "dependency_analysis": dependency_result,
            "filesystem_or_name_candidates": {
                "analyzed_project_identifier_count": len(areas),
                "port_name_candidate_count": len(ports),
                "adapter_name_candidate_count": len(adapters),
                "infrastructure_name_candidate_count": len(infrastructure),
                "status": "insufficient",
            },
            "classification_conflicts": self._strings(
                value.get("classification_conflicts")
            )[:10],
            "limitations": [
                "Name-derived architecture candidates are not promoted to facts.",
                "Deployment topology is unknown unless explicit deployment-boundary evidence exists.",
            ],
        }

    def compact_design_patterns(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {
                "status": "unavailable",
                "pattern_types": [],
                "limitations": [
                    "Structured design-pattern analysis is unavailable in this snapshot."
                ],
            }
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in self._mapping_records(value.get("findings")):
            grouped[str(item.get("pattern") or "unknown")].append(item)
        pattern_types: list[dict[str, object]] = []
        for pattern in sorted(grouped):
            records = grouped[pattern]
            parsed_confidences = [
                self._optional_float(item.get("confidence")) for item in records
            ]
            confidences = [
                number for number in parsed_confidences if number is not None
            ]
            statuses = Counter(
                (
                    str(item.get("confidence_tier", "unknown"))
                    if confidence is not None
                    else "insufficient"
                )
                for item, confidence in zip(records, parsed_confidences, strict=True)
            )
            limitations = sorted({
                str(limitation)
                for item in records
                for limitation in self._sequence(item.get("limitations"))
            })
            evidence_ids = sorted({
                str(evidence_id)
                for item in records
                for evidence_id in self._sequence(item.get("evidence_ids"))
            })
            pattern_types.append({
                "pattern": pattern,
                "finding_count": len(records),
                "status_counts": dict(sorted(statuses.items())),
                "minimum_confidence": min(confidences) if confidences else None,
                "maximum_confidence": max(confidences) if confidences else None,
                "participating_symbols_count": sum(
                    len(self._sequence(item.get("participants"))) for item in records
                ),
                "evidence_count": sum(
                    len(self._sequence(item.get("evidence_ids"))) for item in records
                ),
                "representative_evidence_ids": evidence_ids[: self.MAX_EVIDENCE_IDS],
                "omitted_evidence_id_count": max(
                    0, len(evidence_ids) - self.MAX_EVIDENCE_IDS
                ),
                "limitations": limitations[:4],
            })
        included = pattern_types[: self.MAX_PATTERN_TYPES]
        limitations = []
        if not pattern_types:
            limitations.append(
                "No evidence-backed pattern finding matched; this does not prove that "
                "the repository contains no design patterns."
            )
        return {
            "status": "available",
            "schema_version": value.get("schema_version"),
            "producer_version": value.get("producer_version"),
            "finding_count": sum(item["finding_count"] for item in pattern_types),
            "pattern_type_count": len(pattern_types),
            "included_pattern_type_count": len(included),
            "omitted_pattern_type_count": len(pattern_types) - len(included),
            "pattern_types": included,
            "limitations": limitations,
        }

    def compact_reachability(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {
                "status": "unavailable",
                "statistics": {},
                "representative_findings": [],
                "limitations": [
                    "Structured reachability analysis is unavailable in this snapshot."
                ],
            }
        coverage_value = value.get("coverage")
        coverage = coverage_value if isinstance(coverage_value, Mapping) else {}
        statistics_value = value.get("statistics")
        statistics = statistics_value if isinstance(statistics_value, Mapping) else {}
        states_value = statistics.get("states")
        states = states_value if isinstance(states_value, Mapping) else {}
        projects = self._mapping_records(coverage.get("projects"))
        project_statuses = Counter(str(item.get("status", "unknown")) for item in projects)
        call_statuses = Counter(str(item.get("calls", "unknown")) for item in projects)

        raw_findings = list(self._mapping_records(value.get("findings")))
        if raw_findings:
            candidate_records = [
                item for item in raw_findings
                if item.get("state") in {
                    "likely_dead", "unreachable", "reachable_test_only",
                }
            ]
            candidate_count = len(candidate_records)
        else:
            candidate_records, candidate_count = self._finding_group_candidates(
                value.get("finding_groups")
            )
        candidates = sorted(
            candidate_records,
            key=lambda item: (
                str(item.get("state", "")),
                -(self._optional_float(item.get("confidence")) or 0.0),
                str(item.get("subject_id", "")),
            ),
        )
        selected = candidates[: self.MAX_REACHABILITY_FINDINGS]
        limitations = sorted({
            str(item) for item in self._sequence(coverage.get("limitations"))
        })[:10]
        representative_findings: list[dict[str, object]] = []
        for item in selected:
            confidence = self._optional_float(item.get("confidence"))
            evidence_ids = sorted({
                str(evidence_id)
                for evidence_id in self._sequence(item.get("evidence_ids"))
            })
            representative_findings.append({
                "subject_id": item.get("subject_id"),
                "state": item.get("state"),
                "confidence": confidence,
                "confidence_tier": (
                    item.get("confidence_tier")
                    if confidence is not None
                    else "insufficient"
                ),
                "project": item.get("project"),
                "evidence_count": len(evidence_ids),
                "representative_evidence_ids": evidence_ids[
                    : self.MAX_EVIDENCE_IDS
                ],
                "omitted_evidence_id_count": max(
                    0, len(evidence_ids) - self.MAX_EVIDENCE_IDS
                ),
                "limitations": sorted({
                    str(limitation)
                    for limitation in self._sequence(item.get("limitations"))
                })[:3],
            })
        return {
            "status": str(coverage.get("status", "unknown")),
            "schema_version": value.get("schema_version"),
            "producer_version": value.get("producer_version"),
            "statistics": {
                "analyzed_symbols": self._optional_int(statistics.get("analyzed_symbols")) or 0,
                "states": {
                    str(key): self._optional_int(item) or 0
                    for key, item in sorted(states.items(), key=lambda pair: str(pair[0]))
                },
            },
            "project_coverage": {
                "project_count": len(projects),
                "status_counts": dict(sorted(project_statuses.items())),
                "call_evidence_status_counts": dict(sorted(call_statuses.items())),
                "closed_world_project_count": sum(
                    bool(item.get("closed_world")) for item in projects
                ),
            },
            "candidate_finding_count": candidate_count,
            "included_candidate_finding_count": len(selected),
            "omitted_candidate_finding_count": candidate_count - len(selected),
            "representative_findings": representative_findings,
            "limitations": limitations,
        }

    def compact_risk_analysis(self, value: object) -> dict[str, object]:
        """Select bounded PR132 risk facts without copying source or graph data."""

        if not isinstance(value, Mapping):
            return {
                "status": "unavailable",
                "interpretation": "Structured risk analysis is unavailable; no risk conclusion is inferred.",
                "hotspots": [],
                "evidence_records": [],
                "capabilities": [],
                "limitations": [
                    "PR132 risk and hotspot analysis is unavailable in this snapshot."
                ],
            }
        raw_hotspots = sorted(
            self._mapping_records(value.get("hotspots")),
            key=lambda item: (
                self._optional_int(item.get("rank")) or 2**31,
                str(item.get("subject_id", "")),
            ),
        )
        selected = raw_hotspots[: self.MAX_RISK_HOTSPOTS]
        hotspots = []
        for item in selected:
            raw_confidence = item.get("confidence")
            confidence = raw_confidence if isinstance(raw_confidence, Mapping) else {}
            evidence_ids = sorted({
                str(evidence_id)
                for evidence_id in self._sequence(item.get("evidence_ids"))
            })
            factors = []
            for factor in sorted(
                self._mapping_records(item.get("factors")),
                key=lambda record: str(
                    record.get("metric", {}).get("metric", "")
                    if isinstance(record.get("metric"), Mapping)
                    else ""
                ),
            )[: self.MAX_RISK_FACTORS]:
                raw_metric = factor.get("metric")
                metric = raw_metric if isinstance(raw_metric, Mapping) else {}
                factors.append({
                    "metric": metric.get("metric"),
                    "status": metric.get("status"),
                    "raw_value": self._optional_float(metric.get("raw_value")),
                    "unit": metric.get("unit"),
                    "normalized_value": self._optional_float(
                        metric.get("normalized_value")
                    ),
                    "configured_weight": self._optional_float(
                        factor.get("configured_weight")
                    ),
                    "contribution": self._optional_float(factor.get("contribution")),
                    "coverage": self._optional_float(metric.get("coverage")),
                    "window": metric.get("window"),
                    "producer": metric.get("producer"),
                    "normalization": metric.get("normalization"),
                    "cohort": metric.get("cohort"),
                })
            hotspots.append({
                "rank": self._optional_int(item.get("rank")),
                "subject_id": item.get("subject_id"),
                "display_name": item.get("display_name"),
                "project": item.get("project"),
                "kind": item.get("kind"),
                "language": item.get("language"),
                "scope": item.get("scope"),
                "cohort": item.get("cohort"),
                "score": self._optional_float(item.get("score")),
                "confidence": self._optional_float(confidence.get("score")),
                "confidence_tier": confidence.get("tier", "insufficient"),
                "trend": item.get("trend", "unavailable"),
                "factors": factors,
                "missing_signals": self._strings(item.get("missing_signals")),
                "evidence_count": len(evidence_ids),
                "representative_evidence_ids": evidence_ids[: self.MAX_EVIDENCE_IDS],
                "omitted_evidence_id_count": max(
                    0, len(evidence_ids) - self.MAX_EVIDENCE_IDS
                ),
                "limitations": self._strings(item.get("limitations"))[:5],
            })
        capabilities = [
            {
                "metric": item.get("metric"),
                "status": item.get("status", "unavailable"),
                "observation_count": self._optional_int(item.get("observation_count")) or 0,
                "scored_subject_count": self._optional_int(item.get("scored_subject_count")) or 0,
                "units": self._strings(item.get("units")),
                "omitted_producer_count": (
                    self._optional_int(item.get("omitted_producer_count")) or 0
                ),
                "limitations": self._strings(item.get("limitations"))[:3],
            }
            for item in sorted(
                self._mapping_records(value.get("capabilities")),
                key=lambda record: str(record.get("metric", "")),
            )
        ]
        limitations = list(self._strings(value.get("limitations"))[:10])
        if not raw_hotspots:
            limitations.append(
                "No subject had enough available structured metrics for a ranked risk indicator."
            )
        raw_index = value.get("evidence_index")
        index = raw_index if isinstance(raw_index, Mapping) else {}
        records_by_id = {
            str(item.get("evidence_id")): item
            for item in self._mapping_records(index.get("records"))
            if item.get("evidence_id") is not None
        }
        selected_evidence_ids = sorted({
            evidence_id
            for hotspot in hotspots
            for evidence_id in hotspot["representative_evidence_ids"]
        })[: self.MAX_RISK_EVIDENCE_RECORDS]
        evidence_records = []
        for evidence_id in selected_evidence_ids:
            record = records_by_id.get(evidence_id)
            if record is None:
                continue
            detail = record.get("detail")
            detail_mapping = detail if isinstance(detail, Mapping) else {}
            evidence_records.append({
                "evidence_id": evidence_id,
                "kind": record.get("kind"),
                "subject_id": record.get("subject_id"),
                "producer": record.get("producer"),
                "scope": record.get("scope"),
                "language": record.get("language"),
                "detail": {
                    str(key): detail_mapping[key]
                    for key in sorted(detail_mapping, key=lambda key: str(key))[:12]
                },
                "representative_source_refs": self._strings(
                    record.get("source_refs")
                )[: self.MAX_EVIDENCE_IDS],
                "limitations": self._strings(record.get("limitations"))[:3],
            })
        return {
            "status": "available" if raw_hotspots else "insufficient",
            "schema_version": value.get("schema_version"),
            "producer_version": value.get("producer_version"),
            "interpretation": "Ranked values are risk indicators, not bug or defect findings.",
            "hotspot_count": len(raw_hotspots),
            "included_hotspot_count": len(selected),
            "omitted_hotspot_count": len(raw_hotspots) - len(selected),
            "hotspots": hotspots,
            "evidence_records": evidence_records,
            "omitted_selected_evidence_record_count": max(
                0, len(selected_evidence_ids) - len(evidence_records)
            ),
            "capabilities": capabilities,
            "limitations": limitations,
        }

    def _inventory(
        self,
        value: Mapping[str, Any],
        projects: tuple[Mapping[str, Any], ...],
    ) -> dict[str, object]:
        measurements = {
            "inventoried_file_count": self._metric(
                self._metric_value(value, projects, "inventoried_file_count", "files"),
                "files",
                "Files selected by the workspace inventory across discovered projects.",
            ),
            "inventoried_file_bytes": self._metric(
                self._metric_value(value, projects, "inventoried_file_bytes", "size"),
                "bytes",
                "Bytes successfully statted for inventoried files; not lines of code or repository size.",
            ),
            "inventoried_file_size_error_count": self._metric(
                self._metric_value(
                    value,
                    projects,
                    "inventoried_file_size_error_count",
                    "inventoried_file_size_error_count",
                ),
                "files",
                "Inventoried files whose byte size could not be read; nonzero means byte totals are incomplete.",
            ),
            "classified_non_test_source_files": self._metric(
                self._first_int(value, "classified_non_test_source_files", "production_files"),
                "files",
                "Inventory files classified as source without an exact test-path marker; not compiler-proven production units.",
            ),
            "classified_test_source_files": self._metric(
                self._first_int(value, "classified_test_source_files", "test_files"),
                "files",
                "Inventory source files with an exact test-path marker.",
            ),
            "classified_generated_files": self._metric(
                self._first_int(value, "classified_generated_files", "generated_files"),
                "files",
                "Inventory files under configured generated-path markers; not necessarily source files.",
            ),
        }
        available = any(item["value"] is not None for item in measurements.values())
        return {
            "status": "available" if available else "unavailable",
            "measurements": measurements,
            "evidence_basis": "repository inventory classification and file metadata",
            "confidence": {
                "status": "not-applicable",
                "reason": "These are deterministic measurements, not inferred conclusions.",
            },
        }

    def _language_distribution(self, counts: Mapping[str, int]) -> dict[str, object]:
        total = sum(counts.values())
        basis_points = self._allocate_basis_points(counts)
        items = [
            {
                "language": language,
                "file_count": count,
                "basis_points": basis_points.get(language, 0),
                "percentage": f"{basis_points.get(language, 0) / 100:.2f}",
            }
            for language, count in sorted(
                counts.items(), key=lambda pair: (-pair[1], pair[0].casefold(), pair[0])
            )
        ]
        return {
            "status": "available" if counts else "unavailable",
            "measurement": "recognized-extension inventoried file count",
            "total_classified_language_files": total,
            "percentage_unit": "percent",
            "percentage_total_basis_points": sum(item["basis_points"] for item in items),
            "items": items,
            "confidence": {
                "status": "not-applicable",
                "reason": "Percentages are deterministic derivations from exact file counts.",
            },
            "limitations": [
                "Counts include production, test, generated, resource, and template files and do not measure semantic coverage."
            ],
        }

    def _build_systems(
        self,
        value: Mapping[str, Any],
        projects: tuple[Mapping[str, Any], ...],
    ) -> dict[str, object]:
        names = set(self._strings(value.get("build_systems")))
        by_name: dict[str, set[str]] = defaultdict(set)
        root_names: set[str] = set()
        for project in projects:
            name = str(project.get("name") or project.get("path") or "unknown")
            path = str(project.get("path") or "")
            for build in self._strings(project.get("build_systems")):
                names.add(build)
                by_name[build].add(name)
                if path in {"", ".", "./"}:
                    root_names.add(build)
        items = []
        for name in sorted(names, key=lambda item: (item.casefold(), item)):
            detected_projects = by_name.get(name, set())
            if name in root_names:
                role = "detected-in-root-project-inventory"
            elif detected_projects:
                role = "detected-in-projects"
            else:
                role = "unscoped-legacy-detection"
            items.append({
                "name": name,
                "detected_project_count": len(detected_projects) if detected_projects else None,
                "detected_in_root_project_inventory": name in root_names,
                "classification": role,
                "confidence": {
                    "status": "unavailable",
                    "score": None,
                    "reason": "Repository summaries do not persist detector confidence or descriptor role.",
                },
            })
        return {
            "status": "available" if items else "unavailable",
            "items": items,
            "percentages_reported": False,
            "evidence_basis": "build descriptor filenames in project inventories",
            "limitations": [
                "Build-system membership can overlap; percentages would be misleading.",
                "Embedded fixture descriptors may be counted because descriptor role is not persisted.",
                "Detection in the root project's inventory does not prove that the descriptor is at the repository root and is not automatically called primary.",
            ],
        }

    def _frameworks(self, value: Mapping[str, Any]) -> dict[str, object]:
        evidence = self._mapping_records(value.get("framework_evidence"))
        names = set(self._strings(value.get("frameworks")))
        by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for record in evidence:
            name = str(record.get("framework") or "")
            if name:
                names.add(name)
                by_name[name].append(record)
        items: list[dict[str, object]] = []
        for name in sorted(names, key=lambda item: (item.casefold(), item)):
            records = by_name.get(name, [])
            projects = sorted({
                str(item.get("project")) for item in records if item.get("project")
            })
            record_scopes = [
                str(item.get("scope")) for item in records if item.get("scope")
            ]
            scopes = sorted(set(record_scopes))
            fully_scoped = len(record_scopes) == len(records)
            references = sorted({
                str(item.get("reference")) for item in records if item.get("reference")
            })
            if fully_scoped and scopes and set(scopes) <= {"test-only", "test-or-sample"}:
                classification = "test-or-sample-evidence"
            elif fully_scoped and scopes and set(scopes) <= {"documentation"}:
                classification = "documentation-tooling-evidence"
            elif fully_scoped and scopes and set(scopes) <= {"optional"}:
                classification = "optional-integration-evidence"
            elif fully_scoped and scopes and set(scopes) <= {"build-tooling"}:
                classification = "build-tooling-evidence"
            elif records:
                classification = "framework-or-related-technology-evidence"
            else:
                classification = "unscoped-legacy-detection"
            items.append({
                "name": name,
                "classification": classification,
                "adoption_status": "insufficient",
                "project_count": len(projects),
                "evidence_count": len(records),
                "evidence_scopes": scopes,
                "representative_references": references[: self.MAX_FRAMEWORK_REFERENCES],
                "omitted_reference_count": max(
                    0, len(references) - self.MAX_FRAMEWORK_REFERENCES
                ),
                "confidence": {
                    "status": "insufficient",
                    "score": None,
                    "reason": (
                        "The flattened repository summary does not preserve enough "
                        "category, producer, coverage, and role data to score adoption."
                    ),
                },
                "limitations": [
                    "Dependency or plugin presence does not by itself establish primary repository adoption."
                ],
            })
        included = items[: self.MAX_FRAMEWORKS]
        return {
            "status": "partial" if items else "unavailable",
            "primary_framework": {
                "status": "unknown",
                "reason": "No persisted repository-wide adoption conclusion is available.",
            },
            "total_detected_name_count": len(items),
            "included_name_count": len(included),
            "omitted_name_count": len(items) - len(included),
            "items": included,
            "evidence_basis": "detector-matched declared dependencies and build plugins",
            "limitations": [
                "The legacy field combines frameworks, testing tools, databases, logging, APIs, and other technologies.",
                "Supported, compatibility, and primary roles remain unknown without explicit producer evidence.",
            ],
        }

    def _entry_points(self, value: Mapping[str, Any]) -> dict[str, object]:
        entries = self._strings(value.get("entry_points"))
        items = []
        for entry in entries:
            project, separator, relative = entry.partition(":")
            path = relative if separator else entry
            items.append({
                "project": project if separator else None,
                "path": path,
                "candidate_kind": self._entry_kind(path),
                "scope_candidate": self._entry_scope(path),
                "runtime_role": "unknown",
                "confidence": {
                    "status": "insufficient",
                    "score": None,
                    "reason": "The summary records candidates but not a resolved runtime or build role.",
                },
            })
        items.sort(key=lambda item: (
            str(item.get("project") or ""), str(item.get("path") or "")
        ))
        included = items[: self.MAX_ENTRY_POINTS]
        return {
            "status": "partial" if items else "unavailable",
            "candidate_count": len(items),
            "included_candidate_count": len(included),
            "omitted_candidate_count": len(items) - len(included),
            "items": included,
            "resolved_role_categories": [],
            "unavailable_role_categories": [
                "application", "cli", "framework-lifecycle", "build-pipeline",
                "architecturally-important-type",
            ],
            "evidence_basis": "static main scans, Python main conventions, or package manifest entry fields",
            "limitations": [
                "Candidates are not promoted to application entry points without role-specific semantic evidence.",
                "Build items and important type names are not entry-point evidence.",
            ],
        }

    def _hierarchy(self, value: Mapping[str, Any]) -> dict[str, object]:
        raw = value.get("filesystem_project_hierarchy", value.get("module_hierarchy"))
        records = [
            {
                "project": str(item.get("project")),
                "parent": None if item.get("parent") is None else str(item.get("parent")),
            }
            for item in self._mapping_records(raw)
            if item.get("project") is not None
        ]
        records.sort(key=lambda item: (
            "" if item["parent"] is None else str(item["parent"]),
            str(item["project"]),
        ))
        roots = sorted(
            str(item["project"]) for item in records if item["parent"] is None
        )
        top_level = sorted(
            str(item["project"]) for item in records if item["parent"] in roots
        )
        included = records[: self.MAX_HIERARCHY_RELATIONSHIPS]
        return {
            "status": "available" if records else "unavailable",
            "relationship_count": len(records),
            "root_project_count": len(roots),
            "root_projects": roots[:10],
            "omitted_root_project_count": max(0, len(roots) - 10),
            "top_level_filesystem_area_count": len(top_level),
            "top_level_filesystem_areas": top_level[:20],
            "omitted_top_level_filesystem_area_count": max(0, len(top_level) - 20),
            "representative_relationships": included,
            "omitted_relationship_count": len(records) - len(included),
            "evidence_basis": "nearest containing discovered project path",
            "limitations": [
                "This is filesystem containment, not necessarily Maven reactor, Gradle, deployment, or domain hierarchy."
            ],
        }

    def _dependencies(self, value: Mapping[str, Any]) -> dict[str, object]:
        declared = self._count_mapping(value.get(
            "declared_dependency_count_by_ecosystem",
            value.get("dependencies_by_ecosystem"),
        ))
        manifests = self._count_mapping(value.get(
            "dependency_manifest_count_by_ecosystem"
        ))
        declared_total = self._first_int(
            value,
            "total_declared_dependency_records",
            "total_declared_dependencies",
        )
        if declared_total is None and declared:
            declared_total = sum(declared.values())
        manifest_total = self._first_int(value, "total_dependency_manifests")
        if manifest_total is None and manifests:
            manifest_total = sum(manifests.values())
        return {
            "status": "available" if declared or manifests else "unavailable",
            "declared_dependency_record_count": declared_total,
            "declared_dependency_record_count_by_ecosystem": dict(sorted(declared.items())),
            "manifests_contributing_dependency_records_count": manifest_total,
            "manifests_contributing_dependency_records_count_by_ecosystem": dict(
                sorted(manifests.items())
            ),
            "evidence_basis": "parsed dependency manifest records",
            "confidence": {
                "status": "not-applicable",
                "reason": "These are parsed record and manifest counts, not an adoption conclusion.",
            },
            "limitations": [
                "Declared records are not deduplicated resolved external packages.",
                "Managed and direct dependency records may both be included.",
                "Manifest counts include only manifests that contributed at least one dependency record.",
            ],
        }

    def _finding_group_candidates(
        self,
        value: object,
    ) -> tuple[list[Mapping[str, Any]], int]:
        expanded: list[Mapping[str, Any]] = []
        total = 0
        for group in self._mapping_records(value):
            if group.get("state") not in {
                "likely_dead", "unreachable", "reachable_test_only",
            }:
                continue
            subject_ids = tuple(sorted(map(
                str,
                self._sequence(group.get("subject_ids")),
            )))
            total += len(subject_ids)
            for subject_id in subject_ids[: self.MAX_REACHABILITY_FINDINGS]:
                expanded.append({
                    **{
                        key: item for key, item in group.items()
                        if key not in {"subject_ids", "subject_id_prefix"}
                    },
                    "subject_id": f"{group.get('subject_id_prefix', '')}{subject_id}",
                })
            expanded.sort(key=lambda item: (
                str(item.get("state", "")),
                -(self._optional_float(item.get("confidence")) or 0.0),
                str(item.get("subject_id", "")),
            ))
            del expanded[self.MAX_REACHABILITY_FINDINGS:]
        return expanded, total

    @staticmethod
    def _metric(value: int | None, unit: str, definition: str) -> dict[str, object]:
        return {"value": value, "unit": unit, "definition": definition}

    @classmethod
    def _metric_value(
        cls,
        value: Mapping[str, Any],
        projects: tuple[Mapping[str, Any], ...],
        canonical: str,
        legacy: str,
    ) -> int | None:
        direct = cls._first_int(value, canonical)
        if direct is not None:
            return direct
        project_values = [
            number for project in projects
            if (number := cls._first_int(project, canonical, legacy)) is not None
        ]
        return sum(project_values) if project_values else None

    @staticmethod
    def _first_int(value: Mapping[str, Any], *keys: str) -> int | None:
        for key in keys:
            if key in value:
                result = RepositoryExplanationProjector._optional_int(value.get(key))
                if result is not None:
                    return result
        return None

    @staticmethod
    def _count_mapping(value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, int] = {}
        for key, item in value.items():
            number = RepositoryExplanationProjector._optional_int(item)
            if number is not None and number >= 0:
                result[str(key)] = number
        return result

    @staticmethod
    def _allocate_basis_points(counts: Mapping[str, int]) -> dict[str, int]:
        total = sum(counts.values())
        if total <= 0:
            return {language: 0 for language in counts}
        allocated = {
            language: count * 10_000 // total for language, count in counts.items()
        }
        remainder_count = 10_000 - sum(allocated.values())
        order = sorted(
            counts,
            key=lambda language: (
                -(counts[language] * 10_000 % total),
                language.casefold(),
                language,
            ),
        )
        for language in order[:remainder_count]:
            allocated[language] += 1
        return allocated

    @classmethod
    def _entry_scope(cls, path: str) -> str:
        parts = {
            part.casefold()
            for part in PurePath(*(path.replace("\\", "/").split("/"))).parts
        }
        if parts & cls._GENERATED_PARTS:
            return "generated-candidate"
        if parts & cls._TEST_PARTS:
            return "test-candidate"
        if parts & cls._RESOURCE_PARTS:
            return "resource-or-template-candidate"
        return "scope-unknown"

    @staticmethod
    def _entry_kind(path: str) -> str:
        normalized = path.casefold()
        if normalized.endswith(".java"):
            return "java-static-main-candidate"
        if normalized.endswith(".py"):
            return "python-main-candidate"
        return "manifest-or-source-entry-candidate"

    @staticmethod
    def _confidence_tier(score: float | None) -> str:
        if score is None or score < 0.4:
            return "insufficient"
        if score < 0.6:
            return "possible"
        if score < 0.8:
            return "likely"
        return "detected"

    @staticmethod
    def _repository_name(root: str) -> str | None:
        normalized = root.replace("\\", "/").rstrip("/")
        return normalized.rsplit("/", 1)[-1] if normalized else None

    @classmethod
    def _source_free_projection(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return {
                str(key): cls._source_free_projection(item)
                for key, item in value.items()
                if not contains_absolute_path_text(str(key))
            }
        if isinstance(value, (list, tuple)):
            return [cls._source_free_projection(item) for item in value]
        if isinstance(value, str) and contains_absolute_path_text(value):
            return "machine-specific absolute path omitted"
        return value

    @staticmethod
    def _sequence(value: object) -> tuple[Any, ...]:
        return tuple(value) if isinstance(value, (list, tuple)) else ()

    @classmethod
    def _strings(cls, value: object) -> tuple[str, ...]:
        return tuple(sorted({str(item) for item in cls._sequence(value)}))

    @classmethod
    def _mapping_records(cls, value: object) -> tuple[Mapping[str, Any], ...]:
        return tuple(item for item in cls._sequence(value) if isinstance(item, Mapping))

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            if value is None:
                return None
            number = int(value)
            if isinstance(value, float) and (not math.isfinite(value) or value != number):
                return None
            if isinstance(value, str) and str(number) != value.strip():
                return None
            return number if number >= 0 else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            if value is None:
                return None
            score = float(value)
            return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None
        except (TypeError, ValueError, OverflowError):
            return None
