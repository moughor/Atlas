from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import PurePath
from typing import Any

from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    REPOSITORY_METADATA_RELIABILITY,
    REPRODUCIBLE_HEURISTIC_RELIABILITY,
    RESOLVED_SEMANTIC_FACT_RELIABILITY,
    STRUCTURED_ANALYZER_RELIABILITY,
)

from .models import (
    SECTION_ORDER,
    ReportAttribute,
    ReportCapabilityState,
    ReportConfidenceBasis,
    ReportItemKind,
    ReportObservationState,
    ReportSectionKind,
    RepositoryReport,
    RepositoryReportItem,
    RepositoryReportSection,
)
from .safety import contains_absolute_path_text


@dataclass(frozen=True, slots=True)
class _SectionDraft:
    item_ids: tuple[str, ...]
    total_item_count: int
    capability_state: ReportCapabilityState
    observation_state: ReportObservationState
    producer_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class RepositoryReportService:
    """Compose a bounded PR133 report from existing semantic producers."""

    PRODUCER_VERSION = "atlas-pr133/1"
    MAX_LANGUAGES = 10
    MAX_BUILD_SYSTEMS = 10
    MAX_DEPENDENCY_ECOSYSTEMS = 10
    MAX_FRAMEWORKS = 12
    MAX_MAJOR_AREAS = 12
    MAX_IMPORTANT_COMPONENTS = 10
    MAX_ENTRY_POINTS = 12
    MAX_ARCHITECTURE_FINDINGS = 12
    MAX_PATTERN_TYPES = 11
    MAX_CYCLES = 5
    MAX_CYCLE_MEMBERS = 12
    MAX_HOTSPOTS = 10
    MAX_DEBT_FINDINGS = 10
    MAX_RECOMMENDATIONS = 10
    MAX_EVIDENCE_REFS = 3
    MAX_ITEM_LIMITATIONS = 4
    MAX_SECTION_LIMITATIONS = 5

    _STRONG_ARCHITECTURE_EVIDENCE = frozenset({
        "architecture-contract",
        "deployment-boundary",
        "dependency-edge",
        "graph-edge",
        "semantic-relationship",
    })

    def build(
        self,
        semantic_context: Mapping[str, object],
        *,
        graph_digest: str | None = None,
        knowledge_graph: KnowledgeGraph | None = None,
    ) -> RepositoryReport:
        if not isinstance(semantic_context, Mapping):
            raise TypeError("repository report input must be a semantic-context mapping")
        return _ReportAssembler(
            self,
            semantic_context,
            graph_digest,
            knowledge_graph,
        ).build()


class _ReportAssembler:
    def __init__(
        self,
        configuration: RepositoryReportService,
        semantic_context: Mapping[str, object],
        graph_digest: str | None,
        knowledge_graph: KnowledgeGraph | None,
    ) -> None:
        self.configuration = configuration
        self.context = semantic_context
        self.source_limitations: list[str] = []
        self.summary = self._compatible_source("repository_summary")
        self.workspace = _mapping(semantic_context.get("workspace"))
        self.architecture = self._compatible_source("architecture")
        self.graph = self._compatible_source("semantic_graph")
        self.patterns = self._compatible_source(
            "design_patterns", producer="atlas-pr130/1"
        )
        self.reachability = self._compatible_source(
            "reachability", producer="atlas-pr131/1"
        )
        self.risk = self._compatible_source(
            "risk_analysis", producer="atlas-pr132/1"
        )
        self.knowledge_graph = knowledge_graph
        if self.knowledge_graph is None and self.graph:
            # Snapshot-only composition reuses PR129 deserialization. The normal
            # collector passes its live graph and never rebuilds it.
            try:
                self.knowledge_graph = KnowledgeGraph.from_dict(self.graph)
            except (KeyError, TypeError, ValueError, OverflowError):
                self.graph = {}
                self.source_limitations.append(
                    "The PR129 canonical graph is incompatible with graph schema 1."
                )
        self.graph_digest = (
            self.knowledge_graph.stable_digest() if self.knowledge_graph is not None else ""
        ) or (
            _safe_identifier(graph_digest)
            or _safe_identifier(self.risk.get("graph_digest"))
            or _safe_identifier(self.reachability.get("graph_digest"))
            or "unavailable"
        )
        self.input_fingerprint = self._input_fingerprint()
        self.lineage = f"repository-report:{self.input_fingerprint}"
        self.evidence = EvidenceIndex()
        self.items: dict[str, RepositoryReportItem] = {}

    def _compatible_source(
        self,
        key: str,
        *,
        producer: str | None = None,
    ) -> Mapping[str, object]:
        value = _mapping(self.context.get(key))
        if not value:
            return {}
        raw_schema = value.get("schema_version")
        schema = _integer(raw_schema) if raw_schema is not None else 1
        if schema != 1:
            self.source_limitations.append(
                f"{key} schema {raw_schema!r} is incompatible; its analysis is unavailable."
            )
            return {}
        if producer is not None:
            actual = str(value.get("producer_version", producer))
            if actual != producer:
                self.source_limitations.append(
                    f"{key} producer {actual!r} is incompatible; its analysis is unavailable."
                )
                return {}
        return value

    def build(self) -> RepositoryReport:
        executive = self._executive_summary()
        architecture, cycles, conflicts = self._architecture_overview()
        health, test_inventory, reachability_coverage = self._repository_health()
        risks = self._risks()
        debt = self._technical_debt(cycles)
        quality = self._quality(test_inventory, reachability_coverage)
        strengths = self._strengths()
        weaknesses = self._weaknesses()
        recommendations = self._recommendations(risks, debt, conflicts, cycles)
        drafts = {
            ReportSectionKind.EXECUTIVE_SUMMARY: executive,
            ReportSectionKind.ARCHITECTURE: architecture,
            ReportSectionKind.REPOSITORY_HEALTH: health,
            ReportSectionKind.STRENGTHS: strengths,
            ReportSectionKind.WEAKNESSES: weaknesses,
            ReportSectionKind.RISKS: self._risk_section(risks),
            ReportSectionKind.TECHNICAL_DEBT: self._debt_section(debt),
            ReportSectionKind.QUALITY: quality,
            ReportSectionKind.RECOMMENDATIONS: recommendations,
        }
        sections = tuple(
            self._materialize_section(kind, drafts[kind]) for kind in SECTION_ORDER
        )
        limitations = [
            "This deterministic report is source-free and contains no raw source code.",
            "Unavailable or incomplete analysis remains explicit and is never converted to a negative finding.",
            "Recommendations are bounded investigation prompts, not autonomous remediation advice.",
            "Machine-specific absolute path values are excluded from persisted and rendered report facts.",
            *self.source_limitations,
        ]
        if not self.graph:
            limitations.append(
                "The PR129 canonical graph is unavailable; graph-backed report coverage is partial."
            )
        return RepositoryReport(
            self.input_fingerprint,
            self.graph_digest,
            self.lineage,
            tuple(self.items.values()),
            sections,
            self.evidence.freeze(),
            tuple(limitations),
        )

    def _executive_summary(self) -> _SectionDraft:
        item_ids: list[str] = []
        omitted_item_count = 0
        limitations: list[str] = []
        producers = ["repository-summary.v1", "knowledge-graph.v1"]
        project_count, project_source = self._project_count()
        repository_name = self._repository_name()
        if repository_name is not None or project_count is not None:
            name = repository_name or "The repository"
            count_text = (
                f" contains {project_count:,} discovered project(s)"
                if project_count is not None
                else " has an unavailable project count"
            )
            item_ids.append(self._add_item(
                logical_key="executive.identity",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository",
                title="Repository identity",
                statement=f"{name}{count_text}.",
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.AVAILABLE,
                scope="repository",
                priority=0,
                attributes=(
                    ReportAttribute("repository_name", repository_name),
                    ReportAttribute("discovered_projects", project_count, "projects"),
                ),
                producer="repository-summary.v1",
                source_refs=(project_source or "workspace.repository_identity",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
            ))
        else:
            limitations.append("Repository identity and discovered-project count are unavailable.")

        inventory_values = {
            "inventoried_files": _integer(self.summary.get("inventoried_file_count")),
            "inventoried_bytes": _integer(self.summary.get("inventoried_file_bytes")),
            "production_files": _integer(self.summary.get("classified_non_test_source_files")),
            "test_files": _integer(self.summary.get("classified_test_source_files")),
            "generated_files": _integer(self.summary.get("classified_generated_files")),
        }
        if any(value is not None for value in inventory_values.values()):
            parts = [
                f"{value:,} {name.replace('_', ' ')}"
                for name, value in inventory_values.items()
                if value is not None
            ]
            item_ids.append(self._add_item(
                logical_key="executive.scale",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository",
                title="Repository scale",
                statement="The inventory records " + ", ".join(parts) + ".",
                observation=ReportObservationState.OBSERVED,
                capability=(
                    ReportCapabilityState.AVAILABLE
                    if "inventoried_file_size_error_count" in self.summary
                    and _integer(self.summary.get("inventoried_file_size_error_count")) == 0
                    else ReportCapabilityState.PARTIAL
                ),
                scope="repository",
                priority=5,
                attributes=tuple(
                    ReportAttribute(name, value, "bytes" if name.endswith("bytes") else "files")
                    for name, value in inventory_values.items()
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.inventory",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "File counts are inventory facts, not semantic coverage or test execution results.",
                ),
            ))

        graph_nodes = self.graph.get("nodes")
        graph_edges = self.graph.get("edges")
        if self.graph and _is_sequence(graph_nodes) and _is_sequence(graph_edges):
            item_ids.append(self._add_item(
                logical_key="executive.graph-scale",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="canonical-knowledge-graph",
                title="Canonical graph scale",
                statement=(
                    f"The PR129 canonical graph contains {len(graph_nodes):,} nodes and "
                    f"{len(graph_edges):,} edges."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.AVAILABLE,
                scope="repository",
                priority=6,
                attributes=(
                    ReportAttribute("nodes", len(graph_nodes), "nodes"),
                    ReportAttribute("edges", len(graph_edges), "edges"),
                ),
                producer="knowledge-graph.v1",
                source_refs=("semantic_graph.nodes", "semantic_graph.edges"),
                evidence_kind=EvidenceKind.GRAPH_NODE,
                reliability=RESOLVED_SEMANTIC_FACT_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
            ))
        else:
            limitations.append("Canonical graph scale is unavailable.")

        if self.knowledge_graph is not None:
            degree_summaries = self.knowledge_graph.degree_summaries(
                subject_kinds=(
                    KnowledgeKind.PROJECT,
                    KnowledgeKind.MODULE,
                    KnowledgeKind.PACKAGE,
                    KnowledgeKind.TYPE,
                ),
                include_zero=False,
            )
            included_degrees = tuple(heapq.nsmallest(
                self.configuration.MAX_IMPORTANT_COMPONENTS,
                (
                    item for item in degree_summaries
                    if item.incoming or item.outgoing
                ),
                key=lambda item: (
                    -(item.incoming + item.outgoing),
                    -item.incoming,
                    -item.outgoing,
                    item.node_id,
                ),
            ))
            omitted_item_count += len(degree_summaries) - len(included_degrees)
            for rank, degree in enumerate(included_degrees, 1):
                subject = _safe_identifier(degree.node_id)
                node = self.knowledge_graph.get(degree.node_id)
                title = _safe_text(
                    (node.qualified_name or node.name) if node is not None else subject
                )
                if not subject or not title:
                    omitted_item_count += 1
                    continue
                edge_refs = tuple(sorted(set(
                    reference
                    for edge in (
                        *self.knowledge_graph.incoming(degree.node_id),
                        *self.knowledge_graph.outgoing(degree.node_id),
                    )
                    for reference in edge.evidence
                    if _safe_source_ref(reference)
                )))
                item_ids.append(self._add_item(
                    logical_key=f"executive.degree:{subject}",
                    kind=ReportItemKind.MEASUREMENT,
                    subject_id=subject,
                    title=f"Canonical degree #{rank}: {title}",
                    statement=(
                        f"{title} has {degree.incoming:,} distinct incoming and "
                        f"{degree.outgoing:,} distinct outgoing canonical neighbor(s)."
                    ),
                    observation=ReportObservationState.OBSERVED,
                    capability=ReportCapabilityState.PARTIAL,
                    scope="repository",
                    priority=515 + rank,
                    attributes=(
                        ReportAttribute("rank", rank),
                        ReportAttribute("in_degree", degree.incoming, "neighbors"),
                        ReportAttribute("out_degree", degree.outgoing, "neighbors"),
                        ReportAttribute("fan_in", degree.incoming, "distinct neighbors"),
                        ReportAttribute("fan_out", degree.outgoing, "distinct neighbors"),
                        ReportAttribute("canonical_edge_evidence_reference_count", len(edge_refs), "references"),
                        ReportAttribute("omitted_canonical_edge_evidence_reference_count", max(0, len(edge_refs) - self.configuration.MAX_EVIDENCE_REFS), "references"),
                    ),
                    producer="knowledge-graph.v1",
                    source_refs=(
                        f"semantic_graph.node:{subject}",
                        *edge_refs[: self.configuration.MAX_EVIDENCE_REFS],
                    ),
                    evidence_kind=EvidenceKind.GRAPH_NODE,
                    reliability=RESOLVED_SEMANTIC_FACT_RELIABILITY,
                    confidence=None,
                    confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                    limitations=(
                        "Degree is deterministic structural connectivity, not business importance or expensive centrality.",
                        "Fan-in and fan-out here mean distinct incoming and outgoing canonical neighbors across populated relations.",
                    ),
                ))
        else:
            limitations.append("Canonical degree summaries are unavailable.")

        language_counts = _count_mapping(
            self.summary.get("language_file_counts") or self.summary.get("languages")
        )
        if language_counts:
            languages = sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))
            included = languages[: self.configuration.MAX_LANGUAGES]
            statement = ", ".join(f"{name} ({count:,})" for name, count in included)
            item_ids.append(self._add_item(
                logical_key="executive.languages",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-languages",
                title="Primary languages",
                statement=f"Recognized file extensions indicate: {statement}.",
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=500,
                attributes=(
                    ReportAttribute("language_count", len(languages), "languages"),
                    ReportAttribute("included_language_count", len(included), "languages"),
                    ReportAttribute("omitted_language_count", len(languages) - len(included), "languages"),
                    ReportAttribute("primary_languages", statement),
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.language_file_counts",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Language counts are recognized-extension inventory counts and may include test or generated files.",
                ),
            ))

        build_systems = sorted(set(_strings(self.summary.get("build_systems"))))
        frameworks = sorted(set(_strings(self.summary.get("frameworks"))))
        if build_systems or frameworks:
            included_builds = build_systems[: self.configuration.MAX_BUILD_SYSTEMS]
            included_frameworks = frameworks[: self.configuration.MAX_FRAMEWORKS]
            item_ids.append(self._add_item(
                logical_key="executive.technologies",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-technologies",
                title="Build systems and detected technologies",
                statement=(
                    f"Detected build systems: {_joined(included_builds)}. "
                    f"Framework or related technology metadata: {_joined(included_frameworks)}."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=510,
                attributes=(
                    ReportAttribute("build_system_count", len(build_systems), "build systems"),
                    ReportAttribute("included_build_system_count", len(included_builds), "build systems"),
                    ReportAttribute("omitted_build_system_count", len(build_systems) - len(included_builds), "build systems"),
                    ReportAttribute("framework_or_technology_count", len(frameworks), "technologies"),
                    ReportAttribute("included_framework_or_technology_count", len(included_frameworks), "technologies"),
                    ReportAttribute("omitted_framework_or_technology_count", len(frameworks) - len(included_frameworks), "technologies"),
                    ReportAttribute("build_systems", ", ".join(included_builds)),
                    ReportAttribute("frameworks_or_technologies", ", ".join(included_frameworks)),
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.build_systems", "repository_summary.framework_evidence"),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Framework metadata may be project-local, test/sample, documentation, optional, or build tooling evidence.",
                    "Build-system detection does not establish a primary build system.",
                ),
            ))

        hierarchy = _mapping_records(self.summary.get("module_hierarchy"))
        if hierarchy:
            areas = list(self._major_areas())
            included = areas[: self.configuration.MAX_MAJOR_AREAS]
            item_ids.append(self._add_item(
                logical_key="executive.hierarchy",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-hierarchy",
                title="Project and module structure",
                statement=(
                    f"The filesystem hierarchy records {len(hierarchy):,} relationship(s); "
                    f"representative top-level areas are {_joined(included)}."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=520,
                attributes=(
                    ReportAttribute("hierarchy_relationships", len(hierarchy), "relationships"),
                    ReportAttribute("major_area_count", len(areas), "areas"),
                    ReportAttribute("included_major_area_count", len(included), "areas"),
                    ReportAttribute("omitted_major_area_count", len(areas) - len(included), "areas"),
                    ReportAttribute("representative_major_areas", ", ".join(included)),
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.module_hierarchy",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "The hierarchy represents filesystem project containment, not deployment or Domain-Driven Design boundaries.",
                ),
            ))

        dependencies = _count_mapping(self.summary.get("declared_dependency_count_by_ecosystem"))
        manifests = _count_mapping(self.summary.get("dependency_manifest_count_by_ecosystem"))
        total_dependencies = _first_integer(
            self.summary,
            "total_declared_dependency_records",
            "total_declared_dependencies",
        )
        if total_dependencies is None and dependencies:
            total_dependencies = sum(dependencies.values())
        if dependencies or manifests or total_dependencies is not None:
            ecosystems = sorted(dependencies)
            included_ecosystems = ecosystems[: self.configuration.MAX_DEPENDENCY_ECOSYSTEMS]
            manifest_total = sum(manifests.values()) if manifests else None
            dependency_total_text = (
                f"{total_dependencies:,}" if total_dependencies is not None else "an unavailable number of"
            )
            item_ids.append(self._add_item(
                logical_key="executive.dependencies",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-dependencies",
                title="Dependency overview",
                statement=(
                    f"The inventory records {dependency_total_text} declared dependency record(s) "
                    f"across {_joined(included_ecosystems)}; "
                    + (
                        f"{manifest_total:,} dependency manifest(s) are reported separately."
                        if manifest_total is not None
                        else "dependency manifest counts are unavailable."
                    )
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=530,
                attributes=(
                    ReportAttribute("declared_dependency_records", total_dependencies, "records"),
                    ReportAttribute("dependency_ecosystem_count", len(ecosystems), "ecosystems"),
                    ReportAttribute("included_dependency_ecosystem_count", len(included_ecosystems), "ecosystems"),
                    ReportAttribute("omitted_dependency_ecosystem_count", len(ecosystems) - len(included_ecosystems), "ecosystems"),
                    ReportAttribute("dependency_ecosystems", ", ".join(included_ecosystems)),
                    ReportAttribute("dependency_manifests", manifest_total, "manifests"),
                ),
                producer="repository-summary.v1",
                source_refs=(
                    "repository_summary.declared_dependency_count_by_ecosystem",
                    "repository_summary.dependency_manifest_count_by_ecosystem",
                ),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Declared dependency records are not counts of unique installed external packages.",
                ),
            ))

        entry_points = sorted(
            item for item in (_safe_relative_reference(value) for value in _strings(
                self.summary.get("entry_points")
            )) if item
        )
        if entry_points:
            included = entry_points[: self.configuration.MAX_ENTRY_POINTS]
            item_ids.append(self._add_item(
                logical_key="executive.entry-points",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-entry-point-candidates",
                title="Entry-point candidates",
                statement=(
                    f"Atlas recorded {len(entry_points):,} entry-point candidate(s); "
                    f"representative candidates: {_joined(included)}."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=540,
                attributes=(
                    ReportAttribute("candidate_count", len(entry_points), "candidates"),
                    ReportAttribute("included_candidate_count", len(included), "candidates"),
                    ReportAttribute("omitted_candidate_count", len(entry_points) - len(included), "candidates"),
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.entry_points",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Repository-summary entry points are candidates; runtime lifecycle roles remain unresolved unless a semantic root producer confirms them.",
                ),
            ))
        if not self.summary:
            limitations.append("PR127 repository summary is unavailable.")
        return self._draft(
            item_ids,
            total=len(item_ids) + omitted_item_count,
            capability=(
                ReportCapabilityState.AVAILABLE if self.summary and self.graph
                else ReportCapabilityState.PARTIAL if self.summary or self.graph
                else ReportCapabilityState.UNAVAILABLE
            ),
            observation=(
                ReportObservationState.OBSERVED if item_ids
                else ReportObservationState.NOT_ANALYZED
            ),
            producers=producers,
            limitations=limitations,
        )

    def _architecture_overview(self) -> tuple[_SectionDraft, tuple[str, ...], tuple[str, ...]]:
        item_ids: list[str] = []
        cycle_ids: list[str] = []
        conflict_ids: list[str] = []
        limitations: list[str] = []
        raw_findings = sorted(
            _mapping_records(self.architecture.get("findings")),
            key=lambda item: (
                _safe_text(item.get("architecture")),
                _safe_number(item.get("confidence")),
                tuple(sorted(
                    (
                        _safe_text(evidence.get("kind")),
                        _safe_source_ref(evidence.get("reference")),
                    )
                    for evidence in _mapping_records(item.get("evidence"))
                )),
            ),
        )
        for finding_index, finding in enumerate(
            raw_findings[: self.configuration.MAX_ARCHITECTURE_FINDINGS]
        ):
            architecture = _safe_text(finding.get("architecture")) or "unknown architecture"
            evidence = _mapping_records(finding.get("evidence"))
            kinds = sorted({_safe_text(item.get("kind")) for item in evidence if item.get("kind")})
            strong = bool(set(kinds) & self.configuration._STRONG_ARCHITECTURE_EVIDENCE)
            producer_score = _number(finding.get("confidence"))
            confidence = _insufficient_confidence(
                "shared_repository_architecture_coverage"
            )
            evidence_references = tuple(sorted({
                reference
                for item in evidence
                if (reference := _safe_source_ref(item.get("reference")))
            }))
            finding_key = _short_digest({
                "architecture": architecture,
                "producer_confidence": producer_score,
                "evidence_kinds": kinds,
                "evidence_references": evidence_references,
            })
            statement = (
                f"PR128 records structured evidence for {architecture}, but shared repository-level coverage is insufficient to establish it."
                if strong
                else f"{architecture} remains an architecture candidate; available evidence is insufficient to establish it."
            )
            item_ids.append(self._add_item(
                logical_key=f"architecture.finding:{finding_key}",
                kind=ReportItemKind.FINDING,
                subject_id=f"architecture:{architecture}",
                title=architecture,
                statement=statement,
                observation=ReportObservationState.UNKNOWN,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=100 + finding_index,
                attributes=(
                    ReportAttribute("producer_confidence", producer_score),
                    ReportAttribute("evidence_count", len(evidence), "records"),
                    ReportAttribute("evidence_kinds", ", ".join(kinds)),
                ),
                producer="architecture-detection.v1",
                source_refs=(
                    f"architecture.findings:{architecture}",
                    *evidence_references,
                ),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY if strong else 0.0,
                confidence=confidence,
                confidence_basis=ReportConfidenceBasis.SHARED_CALCULATOR,
                limitations=(
                    () if strong else (
                        "Name, hierarchy, and entry-point candidate metadata do not establish an architecture pattern.",
                    )
                ),
            ))
        if len(raw_findings) > self.configuration.MAX_ARCHITECTURE_FINDINGS:
            limitations.append(
                f"{len(raw_findings) - self.configuration.MAX_ARCHITECTURE_FINDINGS} architecture finding(s) were omitted."
            )

        dependency = _mapping(self.architecture.get("dependency_analysis"))
        executed = bool(dependency.get("executed", False))
        evidence_edges = _integer(dependency.get("evidence_edge_count")) or 0
        raw_cycles = self._architecture_cycles()
        self._trusted_cycle_total = (
            len(raw_cycles) if executed and evidence_edges > 0 else 0
        )
        if executed and evidence_edges > 0 and raw_cycles:
            for cycle in raw_cycles[: self.configuration.MAX_CYCLES]:
                members = tuple(cycle)
                included_members = members[: self.configuration.MAX_CYCLE_MEMBERS]
                cycle_key = _short_digest(members)
                cycle_id = self._add_item(
                    logical_key=f"architecture.cycle:{cycle_key}",
                    kind=ReportItemKind.FINDING,
                    subject_id=f"dependency-cycle:{cycle_key}",
                    title="Dependency cycle",
                    statement=f"A dependency cycle is recorded among {_joined(included_members)}.",
                    observation=ReportObservationState.OBSERVED,
                    capability=ReportCapabilityState.PARTIAL,
                    scope="repository",
                    priority=110,
                    attributes=(
                        ReportAttribute("cycle_member_count", len(members), "projects"),
                        ReportAttribute("included_cycle_member_count", len(included_members), "projects"),
                        ReportAttribute("omitted_cycle_member_count", len(members) - len(included_members), "projects"),
                        ReportAttribute("cycle_members", ", ".join(included_members)),
                        ReportAttribute("evidence_edges", evidence_edges, "edges"),
                    ),
                    producer="architecture-detection.v1",
                    source_refs=("architecture.dependency_cycles",),
                    evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                    reliability=STRUCTURED_ANALYZER_RELIABILITY,
                    confidence=None,
                    confidence_basis=ReportConfidenceBasis.SHARED_CALCULATOR,
                    limitations=(
                        "Dependency analysis coverage lacks an eligible-edge denominator and is therefore partial.",
                    ),
                )
                item_ids.append(cycle_id)
                cycle_ids.append(cycle_id)
        elif executed and evidence_edges > 0:
            limitations.append(
                "No dependency cycle is listed, but covered negative evidence is insufficient to claim that no cycles exist."
            )
        else:
            limitations.append("Dependency direction and cycle analysis is unavailable or lacks positive edge coverage.")

        conflicts = self._architecture_conflicts()
        for conflict in conflicts[:5]:
            conflict_key = _short_digest(conflict)
            conflict_id = self._add_item(
                logical_key=f"architecture.conflict:{conflict_key}",
                kind=ReportItemKind.FINDING,
                subject_id=f"architecture-conflict:{conflict_key}",
                title="Architecture classification conflict",
                statement=f"The architecture producer recorded a classification conflict: {conflict}.",
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=115,
                attributes=(ReportAttribute("classification_conflict", conflict),),
                producer="architecture-detection.v1",
                source_refs=("architecture.classification_conflicts",),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.SHARED_CALCULATOR,
            )
            item_ids.append(conflict_id)
            conflict_ids.append(conflict_id)

        grouped_patterns: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for finding in _mapping_records(self.patterns.get("findings")):
            grouped_patterns[_safe_text(finding.get("pattern")) or "unknown"].append(finding)
        selected_patterns = tuple(sorted(grouped_patterns)[: self.configuration.MAX_PATTERN_TYPES])
        requested_pattern_evidence = {
            evidence_id
            for pattern in selected_patterns
            for item in grouped_patterns[pattern]
            for evidence_id in _strings(item.get("evidence_ids"))
            if evidence_id.startswith("evidence:")
        }
        verified_pattern_evidence = self._verified_evidence_ids(
            self.patterns,
            requested_pattern_evidence,
        )
        for pattern in selected_patterns:
            findings = grouped_patterns[pattern]
            scores = [score for item in findings if (score := _number(item.get("confidence"))) is not None]
            tiers = {_safe_text(item.get("confidence_tier")) for item in findings}
            upstream_ids = sorted({
                evidence_id
                for item in findings
                for evidence_id in _strings(item.get("evidence_ids"))
                if evidence_id in verified_pattern_evidence
            })
            observed = (
                bool(scores)
                and bool(upstream_ids)
                and any(tier != "insufficient" for tier in tiers)
            )
            confidence = (
                None if observed
                else _insufficient_confidence("complete_pattern_evidence")
            )
            item_ids.append(self._add_item(
                logical_key=f"architecture.pattern:{pattern}",
                kind=(ReportItemKind.MEASUREMENT if observed else ReportItemKind.FINDING),
                subject_id=f"design-pattern:{pattern}",
                title=f"{pattern} pattern",
                statement=(
                    f"The PR130 producer reports {len(findings):,} evidence-backed {pattern} finding(s)."
                    if observed else
                    f"The PR130 producer has insufficient evidence to establish {pattern}."
                ),
                observation=(ReportObservationState.OBSERVED if observed else ReportObservationState.UNKNOWN),
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=120,
                attributes=(
                    ReportAttribute("finding_count", len(findings), "findings"),
                    ReportAttribute("maximum_producer_confidence", max(scores) if scores else None),
                    ReportAttribute("producer_confidence_tiers", ", ".join(sorted(tiers))),
                    ReportAttribute("verified_evidence_count", len(upstream_ids), "records"),
                ),
                producer=_safe_identifier(self.patterns.get("producer_version")) or "atlas-pr130/1",
                source_refs=("design_patterns.findings", *upstream_ids),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=confidence,
                confidence_basis=(
                    ReportConfidenceBasis.NOT_APPLICABLE
                    if observed else ReportConfidenceBasis.SHARED_CALCULATOR
                ),
                limitations=tuple(sorted({
                    _safe_text(limitation)
                    for item in findings
                    for limitation in _strings(item.get("limitations"))
                    if _safe_text(limitation)
                }))[: self.configuration.MAX_ITEM_LIMITATIONS],
            ))
        pattern_type_count = len(grouped_patterns)
        included_total = len(item_ids)
        total = len(raw_findings) + len(raw_cycles) + len(conflicts) + pattern_type_count
        if not self.architecture:
            limitations.append("PR128 architecture analysis is unavailable.")
        if not self.patterns:
            limitations.append("PR130 design-pattern analysis is unavailable.")
        elif not grouped_patterns:
            limitations.append(
                "PR130 produced no retained pattern finding; this does not establish that design patterns are absent."
            )
        if self.architecture and not raw_findings and not raw_cycles and not conflicts:
            limitations.append(
                "PR128 produced no retained architecture finding; this is not covered negative evidence."
            )
        capability = (
            ReportCapabilityState.PARTIAL if self.architecture or self.patterns
            else ReportCapabilityState.UNAVAILABLE
        )
        return (
            self._draft(
                item_ids,
                total=max(total, included_total),
                capability=capability,
                observation=(
                    ReportObservationState.OBSERVED if item_ids
                    else ReportObservationState.UNKNOWN if self.architecture or self.patterns
                    else ReportObservationState.NOT_ANALYZED
                ),
                producers=("architecture-detection.v1", "atlas-pr130/1"),
                limitations=limitations,
            ),
            tuple(cycle_ids),
            tuple(conflict_ids),
        )

    def _repository_health(self) -> tuple[_SectionDraft, str | None, str | None]:
        item_ids: list[str] = []
        limitations: list[str] = [
            "Snapshot presence does not persist per-project completion evidence for replay.",
        ]
        test_inventory_id: str | None = None
        reachability_id: str | None = None
        file_count = _integer(self.summary.get("inventoried_file_count"))
        stat_errors = _integer(self.summary.get("inventoried_file_size_error_count"))
        if file_count is not None and stat_errors is not None:
            item_ids.append(self._add_item(
                logical_key="health.inventory-completeness",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-inventory",
                title="Inventory completeness",
                statement=(
                    f"The inventory records {file_count:,} files and {stat_errors:,} file-size read error(s)."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=(ReportCapabilityState.AVAILABLE if stat_errors == 0 else ReportCapabilityState.PARTIAL),
                scope="repository",
                priority=20,
                attributes=(
                    ReportAttribute("inventoried_files", file_count, "files"),
                    ReportAttribute("file_size_errors", stat_errors, "errors"),
                ),
                producer="repository-summary.v1",
                source_refs=("repository_summary.inventoried_file_size_error_count",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
            ))
        test_files = _first_integer(
            self.summary,
            "classified_test_source_files",
            "test_files",
        )
        if test_files is not None:
            test_inventory_id = self._add_item(
                logical_key="health.test-inventory",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="repository-test-inventory",
                title="Test source inventory",
                statement=(
                    f"The repository inventory contains {test_files:,} classified test source file(s); "
                    "this does not establish test execution or coverage."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=25,
                attributes=(ReportAttribute("classified_test_source_files", test_files, "files"),),
                producer="repository-summary.v1",
                source_refs=("repository_summary.classified_test_source_files",),
                evidence_kind=EvidenceKind.REPOSITORY_METADATA,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Test-file presence is not test execution, test coverage, or resolved production-to-test density.",
                ),
            )
            item_ids.append(test_inventory_id)
        coverage = _mapping(self.reachability.get("coverage"))
        if coverage:
            status = _capability_state(coverage.get("status"))
            subject_counts = _count_mapping(coverage.get("subject_counts"))
            analyzed = sum(subject_counts.values())
            coverage_limitations = _strings(coverage.get("limitations"))
            reachability_id = self._add_item(
                logical_key="health.reachability-coverage",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="reachability-coverage",
                title="Reachability coverage",
                statement=(
                    f"PR131 reachability coverage is {status.value} across {analyzed:,} classified subject(s)."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=status,
                scope="repository",
                priority=30,
                attributes=(
                    ReportAttribute("analyzed_subjects", analyzed, "subjects"),
                    ReportAttribute("coverage_status", status.value),
                ),
                producer=_safe_identifier(self.reachability.get("producer_version")) or "atlas-pr131/1",
                source_refs=("reachability.coverage",),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=coverage_limitations[: self.configuration.MAX_ITEM_LIMITATIONS],
            )
            item_ids.append(reachability_id)
        else:
            limitations.append("PR131 reachability coverage is unavailable.")
        return (
            self._draft(
                item_ids,
                total=len(item_ids),
                capability=(ReportCapabilityState.PARTIAL if item_ids else ReportCapabilityState.UNAVAILABLE),
                observation=(ReportObservationState.OBSERVED if item_ids else ReportObservationState.NOT_ANALYZED),
                producers=("repository-summary.v1", "atlas-pr131/1"),
                limitations=limitations,
            ),
            test_inventory_id,
            reachability_id,
        )

    def _risks(self) -> tuple[str, ...]:
        raw_hotspots = _mapping_records(self.risk.get("hotspots"))
        selected_hotspots = tuple(heapq.nsmallest(
            self.configuration.MAX_HOTSPOTS,
            raw_hotspots,
            key=lambda item: (_integer(item.get("rank")) or 10**9, _safe_text(item.get("subject_id"))),
        ))
        requested_risk_evidence = {
            evidence_id
            for hotspot in selected_hotspots
            for evidence_id in _strings(hotspot.get("evidence_ids"))
            if evidence_id.startswith("evidence:")
        }
        verified_risk_evidence = self._verified_evidence_records(
            self.risk,
            requested_risk_evidence,
        )
        invalid_evidence_count = 0
        item_ids: list[str] = []
        for hotspot in selected_hotspots:
            subject = _safe_identifier(hotspot.get("subject_id")) or "unknown-subject"
            display = _safe_text(hotspot.get("display_name")) or subject
            rank = _integer(hotspot.get("rank")) or len(item_ids) + 1
            score = _number(hotspot.get("score"))
            raw_confidence = hotspot.get("confidence")
            confidence = _full_confidence(raw_confidence) or _insufficient_confidence(
                "valid_risk_confidence"
            )
            upstream_ids = tuple(
                evidence_id for evidence_id in _strings(hotspot.get("evidence_ids"))
                if (
                    evidence_id in verified_risk_evidence
                    and verified_risk_evidence[evidence_id].subject_id == subject
                )
            )
            if not upstream_ids:
                invalid_evidence_count += 1
                continue
            factors = []
            for factor in _mapping_records(hotspot.get("factors")):
                metric = _mapping(factor.get("metric"))
                name = _safe_text(metric.get("metric"))
                unit = _safe_text(metric.get("unit"))
                if name:
                    factors.append(f"{name} ({unit})" if unit else name)
            factors = sorted(set(factors))
            missing_signals = sorted(set(_safe_strings(hotspot.get("missing_signals"))))
            trend = _safe_text(hotspot.get("trend")) or "unavailable"
            item_ids.append(self._add_item(
                logical_key=f"risk.hotspot:{subject}",
                kind=ReportItemKind.FINDING,
                subject_id=subject,
                title=f"Risk hotspot #{rank}: {display}",
                statement=(
                    f"{display} is ranked #{rank} as a deterministic risk indicator"
                    + (f" with score {score:.6f}" if score is not None else "")
                    + "; this is not a bug, defect, or vulnerability finding."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope=_safe_text(hotspot.get("scope")) or "repository",
                priority=130 + rank * 4,
                attributes=(
                    ReportAttribute("rank", rank),
                    ReportAttribute("risk_score", score),
                    ReportAttribute("factor_count", len(factors), "factors"),
                    ReportAttribute("factor_metrics_and_units", ", ".join(factors)),
                    ReportAttribute("missing_signals", ", ".join(missing_signals)),
                    ReportAttribute("trend", trend),
                ),
                producer=_safe_identifier(self.risk.get("producer_version")) or "atlas-pr132/1",
                source_refs=("risk_analysis.hotspots", *upstream_ids),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=confidence,
                confidence_basis=ReportConfidenceBasis.UPSTREAM,
                limitations=_strings(hotspot.get("limitations"))[: self.configuration.MAX_ITEM_LIMITATIONS],
            ))
        self._risk_total = len(raw_hotspots)
        self._risk_invalid_evidence_count = invalid_evidence_count
        return tuple(item_ids)

    def _technical_debt(self, cycle_ids: tuple[str, ...]) -> tuple[str, ...]:
        debt_ids = list(cycle_ids)
        candidate_count = 0

        def candidates():
            nonlocal candidate_count
            for finding, source_ref in _reachability_findings(self.reachability):
                state = _safe_text(finding.get("state"))
                tier = _safe_text(finding.get("confidence_tier"))
                subject = _safe_identifier(finding.get("subject_id"))
                if (
                    state not in {"likely_dead", "unreachable"}
                    or tier == "insufficient"
                    or not subject
                ):
                    continue
                candidate_count += 1
                yield finding, source_ref, subject

        selected = heapq.nsmallest(
            max(0, self.configuration.MAX_DEBT_FINDINGS - len(debt_ids)),
            candidates(),
            key=lambda item: (
                item[2],
                _safe_text(item[0].get("state")),
                _safe_text(item[0].get("project")),
            ),
        )
        requested_reachability_evidence = {
            evidence_id
            for finding, _, _ in selected
            for evidence_id in _strings(finding.get("evidence_ids"))
            if evidence_id.startswith("evidence:")
        }
        verified_reachability_evidence = self._verified_evidence_records(
            self.reachability,
            requested_reachability_evidence,
        )
        invalid_evidence_count = 0
        for finding, source_ref, subject in selected:
            state = _safe_text(finding.get("state"))
            score = _number(finding.get("confidence"))
            tier = _safe_text(finding.get("confidence_tier")) or "unavailable"
            upstream_ids = tuple(
                evidence_id for evidence_id in _strings(finding.get("evidence_ids"))
                if evidence_id in verified_reachability_evidence
            )
            if not upstream_ids or not any(
                verified_reachability_evidence[evidence_id].subject_id == subject
                for evidence_id in upstream_ids
            ):
                invalid_evidence_count += 1
                continue
            project = _safe_text(finding.get("project"))
            source_classification = _safe_text(finding.get("source_classification")) or "unknown"
            debt_ids.append(self._add_item(
                logical_key=f"debt.reachability:{state}:{subject}",
                kind=ReportItemKind.FINDING,
                subject_id=subject,
                title=f"Reachability candidate: {state}",
                statement=(
                    f"PR131 reports {subject} as {state}; removal or remediation still requires review of coverage and cited evidence."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope=f"project:{project}" if project else "repository",
                priority=200,
                attributes=(
                    ReportAttribute("reachability_state", state),
                    ReportAttribute("producer_confidence", score),
                    ReportAttribute("producer_confidence_tier", tier),
                    ReportAttribute("source_classification", source_classification),
                ),
                producer=_safe_identifier(self.reachability.get("producer_version")) or "atlas-pr131/1",
                source_refs=(source_ref, *upstream_ids),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=_insufficient_confidence(
                    "complete_reachability_confidence_components"
                ),
                confidence_basis=ReportConfidenceBasis.SHARED_CALCULATOR,
                limitations=_strings(finding.get("limitations"))[: self.configuration.MAX_ITEM_LIMITATIONS],
            ))
        self._debt_total = getattr(
            self, "_trusted_cycle_total", len(cycle_ids)
        ) + candidate_count
        self._debt_invalid_evidence_count = invalid_evidence_count
        return tuple(debt_ids)

    def _quality(self, test_inventory: str | None, reachability_coverage: str | None) -> _SectionDraft:
        item_ids = [item for item in (test_inventory, reachability_coverage) if item]
        limitations = [
            "Atlas has no persisted runtime test result or coverage percentage in this report.",
        ]
        capabilities = _mapping_records(self.risk.get("capabilities"))
        if capabilities:
            states = Counter(_safe_text(item.get("status")) or "unavailable" for item in capabilities)
            available_metrics = sorted(
                _safe_text(item.get("metric")) for item in capabilities
                if _safe_text(item.get("status")) in {"available", "partial"}
            )
            unavailable_metrics = sorted(
                _safe_text(item.get("metric")) for item in capabilities
                if _safe_text(item.get("status")) == "unavailable"
            )
            item_ids.append(self._add_item(
                logical_key="quality.risk-capabilities",
                kind=ReportItemKind.MEASUREMENT,
                subject_id="risk-capability-coverage",
                title="Quality and risk metric coverage",
                statement=(
                    f"PR132 exposes {_joined(available_metrics)} and reports {_joined(unavailable_metrics)} as unavailable."
                ),
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope="repository",
                priority=400,
                attributes=(
                    ReportAttribute("available_or_partial_metrics", len(available_metrics), "metrics"),
                    ReportAttribute("unavailable_metrics", len(unavailable_metrics), "metrics"),
                    ReportAttribute("capability_states", ", ".join(f"{key}={value}" for key, value in sorted(states.items()))),
                ),
                producer=_safe_identifier(self.risk.get("producer_version")) or "atlas-pr132/1",
                source_refs=("risk_analysis.capabilities",),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=STRUCTURED_ANALYZER_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.NOT_APPLICABLE,
                limitations=(
                    "Unavailable complexity, test-density, change, or call metrics remain unknown rather than zero.",
                ),
            ))
        else:
            limitations.append("PR132 metric capability data is unavailable.")
        return self._draft(
            item_ids,
            total=len(item_ids),
            capability=(ReportCapabilityState.PARTIAL if item_ids else ReportCapabilityState.UNAVAILABLE),
            observation=(ReportObservationState.OBSERVED if item_ids else ReportObservationState.NOT_ANALYZED),
            producers=("repository-summary.v1", "atlas-pr131/1", "atlas-pr132/1"),
            limitations=limitations,
        )

    def _strengths(self) -> _SectionDraft:
        return self._draft(
            (),
            total=0,
            capability=ReportCapabilityState.UNAVAILABLE,
            observation=ReportObservationState.UNKNOWN,
            producers=(),
            limitations=(
                "No authoritative repository-strength producer exists; inventory, pattern, or zero-finding facts are not promoted to strengths.",
            ),
        )

    def _weaknesses(self) -> _SectionDraft:
        return self._draft(
            (),
            total=0,
            capability=ReportCapabilityState.UNAVAILABLE,
            observation=ReportObservationState.UNKNOWN,
            producers=(),
            limitations=(
                "No authoritative repository-weakness producer exists; risks, reachability candidates, and architecture conflicts remain in their own evidence-scoped sections.",
            ),
        )

    def _recommendations(
        self,
        risks: tuple[str, ...],
        debt: tuple[str, ...],
        conflicts: tuple[str, ...],
        cycles: tuple[str, ...],
    ) -> _SectionDraft:
        source_ids = tuple(dict.fromkeys((*risks, *debt, *conflicts)))
        recommendations: list[str] = []
        for source_id in source_ids[: self.configuration.MAX_RECOMMENDATIONS]:
            source = self.items[source_id]
            if source_id in risks:
                statement = (
                    f"Investigate {source.title} by reviewing its cited metric factors, units, missing signals, and domain-specific evidence before taking action."
                )
                prerequisites = (
                    "Review the cited PR132 metric factors and units.",
                    "Validate missing signals with authoritative analyzers before engineering action.",
                )
            elif source_id in conflicts:
                statement = (
                    "Review the recorded architecture classification conflict and its evidence before selecting or enforcing an architecture label."
                )
                prerequisites = (
                    "Inspect the cited PR128 architecture evidence.",
                    "Preserve conflicting classifications until stronger evidence resolves them.",
                )
            elif source_id in cycles:
                statement = (
                    "Review the recorded dependency cycle and its PR128 dependency evidence before changing module boundaries or dependency direction."
                )
                prerequisites = (
                    "Inspect the cited PR128 dependency-cycle evidence and covered edges.",
                    "Confirm the cycle across the authoritative build and dependency models before remediation.",
                )
            else:
                statement = (
                    f"Review {source.title} and its reachability evidence before removal, suppression, or remediation."
                )
                prerequisites = (
                    "Confirm call, root, and closed-world coverage for the affected scope.",
                    "Review the cited PR131 evidence before modifying code.",
                )
            recommendations.append(self._add_item(
                logical_key=f"recommendation:{source_id}",
                kind=ReportItemKind.RECOMMENDATION,
                subject_id=f"recommendation:{source.subject_id}",
                title=f"Investigation: {source.title}",
                statement=statement,
                observation=ReportObservationState.OBSERVED,
                capability=ReportCapabilityState.PARTIAL,
                scope=source.scope,
                priority=source.priority + 1,
                attributes=(),
                producer=self.configuration.PRODUCER_VERSION,
                source_refs=(source.item_id, *source.evidence_ids[: self.configuration.MAX_EVIDENCE_REFS]),
                evidence_kind=EvidenceKind.ANALYSIS_RESULT,
                reliability=REPRODUCIBLE_HEURISTIC_RELIABILITY,
                confidence=None,
                confidence_basis=ReportConfidenceBasis.SHARED_CALCULATOR,
                confidence_ceiling=(
                    source.confidence.score if source.confidence is not None else 0.0
                ),
                limitations=(
                    "This is a deterministic investigation prompt derived from a structured finding, not autonomous remediation advice.",
                ),
                related_item_ids=(source.item_id,),
                prerequisites=prerequisites,
            ))
        return self._draft(
            recommendations,
            total=len(source_ids),
            capability=(ReportCapabilityState.PARTIAL if recommendations else ReportCapabilityState.UNAVAILABLE),
            observation=(ReportObservationState.OBSERVED if recommendations else ReportObservationState.UNKNOWN),
            producers=(self.configuration.PRODUCER_VERSION,),
            limitations=(
                "Recommendations are emitted only for retained structured findings and remain interpretations.",
            ),
        )

    def _risk_section(self, risks: tuple[str, ...]) -> _SectionDraft:
        capabilities = _mapping_records(self.risk.get("capabilities"))
        missing = [
            _safe_text(item.get("metric")) for item in capabilities
            if _safe_text(item.get("status")) == "unavailable"
        ]
        limitations = list(_strings(self.risk.get("limitations")))
        if missing:
            limitations.append(f"Unavailable risk metrics: {', '.join(sorted(missing))}.")
        invalid_evidence = getattr(self, "_risk_invalid_evidence_count", 0)
        if invalid_evidence:
            limitations.append(
                f"{invalid_evidence} retained risk hotspot(s) were omitted because their evidence IDs could not be verified."
            )
        if not self.risk:
            limitations.append("PR132 risk and hotspot analysis is unavailable.")
        elif not risks:
            limitations.append(
                "PR132 produced no traceable retained hotspot; this is not covered evidence of low repository risk."
            )
        limitations.append(
            "Structured impact and blast-radius analysis belongs to PR136 and is unavailable in PR133."
        )
        return self._draft(
            risks,
            total=getattr(self, "_risk_total", len(risks)),
            capability=(ReportCapabilityState.PARTIAL if self.risk else ReportCapabilityState.UNAVAILABLE),
            observation=(ReportObservationState.OBSERVED if risks else ReportObservationState.UNKNOWN),
            producers=(_safe_identifier(self.risk.get("producer_version")) or "atlas-pr132/1",),
            limitations=limitations,
        )

    def _debt_section(self, debt: tuple[str, ...]) -> _SectionDraft:
        limitations = [
            "PR133 reports only evidence-backed reachability or structural candidates; it is not the PR142 technical-debt engine.",
        ]
        if not debt:
            limitations.append(
                "No retained technical-debt candidate is not proof that the repository has no technical debt."
            )
        invalid_evidence = getattr(self, "_debt_invalid_evidence_count", 0)
        if invalid_evidence:
            limitations.append(
                f"{invalid_evidence} reachability candidate(s) were omitted because their evidence IDs could not be verified."
            )
        return self._draft(
            debt,
            total=getattr(self, "_debt_total", len(debt)),
            capability=(ReportCapabilityState.PARTIAL if self.reachability or self.architecture else ReportCapabilityState.UNAVAILABLE),
            observation=(ReportObservationState.OBSERVED if debt else ReportObservationState.UNKNOWN),
            producers=("architecture-detection.v1", "atlas-pr131/1"),
            limitations=limitations,
        )

    def _draft(
        self,
        item_ids: Sequence[str],
        *,
        total: int,
        capability: ReportCapabilityState,
        observation: ReportObservationState,
        producers: Sequence[str],
        limitations: Sequence[str],
    ) -> _SectionDraft:
        included = tuple(dict.fromkeys(item_ids))
        return _SectionDraft(
            included,
            max(total, len(included)),
            capability,
            observation,
            tuple(producers),
            tuple(limitations),
        )

    def _materialize_section(
        self,
        kind: ReportSectionKind,
        draft: _SectionDraft,
    ) -> RepositoryReportSection:
        ordered = tuple(sorted(
            draft.item_ids,
            key=lambda item_id: (self.items[item_id].priority, item_id),
        ))
        limitations = tuple(dict.fromkeys(
            item for item in (_safe_text(value) for value in draft.limitations) if item
        ))
        if len(limitations) > self.configuration.MAX_SECTION_LIMITATIONS:
            retained = limitations[: self.configuration.MAX_SECTION_LIMITATIONS - 1]
            limitations = (
                *retained,
                f"{len(limitations) - len(retained)} additional section limitation(s) omitted.",
            )
        return RepositoryReportSection(
            kind,
            draft.capability_state,
            draft.observation_state,
            ordered,
            draft.total_item_count,
            draft.total_item_count - len(ordered),
            draft.producer_ids,
            limitations,
        )

    def _add_item(
        self,
        *,
        logical_key: str,
        kind: ReportItemKind,
        subject_id: str,
        title: str,
        statement: str,
        observation: ReportObservationState,
        capability: ReportCapabilityState,
        scope: str,
        priority: int,
        attributes: Sequence[ReportAttribute],
        producer: str,
        source_refs: Sequence[str],
        evidence_kind: EvidenceKind,
        reliability: float,
        confidence: ConfidenceResult | None,
        confidence_basis: ReportConfidenceBasis,
        confidence_ceiling: float | None = None,
        limitations: Sequence[str] = (),
        related_item_ids: Sequence[str] = (),
        prerequisites: Sequence[str] = (),
    ) -> str:
        safe_subject = _safe_text(subject_id) or "unknown"
        safe_title = _safe_text(title) or "Unavailable"
        safe_statement = _safe_text(statement) or "Structured report statement is unavailable."
        safe_scope = _safe_text(scope) or "repository"
        safe_producer = _safe_identifier(producer) or "unknown-producer"
        item_id = "report-item:" + hashlib.sha256(
            _canonical_json({
                "logical_key": logical_key,
                "subject_id": safe_subject,
                "producer": safe_producer,
            }).encode("utf-8")
        ).hexdigest()
        all_safe_refs = tuple(dict.fromkeys(
            reference for reference in (
                _safe_source_ref(item) for item in source_refs
            ) if reference
        ))
        safe_refs = all_safe_refs[: 1 + self.configuration.MAX_EVIDENCE_REFS]
        all_safe_limitations = tuple(dict.fromkeys(
            item for item in (_safe_text(value) for value in limitations) if item
        ))
        if len(all_safe_limitations) > self.configuration.MAX_ITEM_LIMITATIONS:
            retained_limitations = all_safe_limitations[: self.configuration.MAX_ITEM_LIMITATIONS - 1]
            safe_limitations = (
                *retained_limitations,
                f"{len(all_safe_limitations) - len(retained_limitations)} additional item limitation(s) omitted.",
            )
        else:
            safe_limitations = all_safe_limitations
        safe_attributes = tuple(
            ReportAttribute(
                attribute.key,
                _safe_text(attribute.value) if isinstance(attribute.value, str) else attribute.value,
                attribute.unit,
            )
            for attribute in attributes
        )
        if len(all_safe_refs) > len(safe_refs):
            safe_attributes = (
                *safe_attributes,
                ReportAttribute(
                    "omitted_evidence_reference_count",
                    len(all_safe_refs) - len(safe_refs),
                    "references",
                ),
            )
        record = EvidenceRecord.create(
            evidence_kind,
            item_id,
            self.configuration.PRODUCER_VERSION,
            self.lineage,
            source_refs=safe_refs,
            scope=safe_scope,
            detail={
                "logical_key": logical_key,
                "statement_digest": _short_digest(safe_statement),
                "observation_state": observation.value,
                "capability_state": capability.value,
                "upstream_producer": safe_producer,
                **{
                    attribute.key: attribute.value
                    for attribute in safe_attributes
                },
            },
            limitations=safe_limitations,
            reliability=reliability,
            specificity=1.0,
        )
        evidence_id = self.evidence.add(record)
        if confidence_basis is ReportConfidenceBasis.SHARED_CALCULATOR:
            if confidence is None:
                roles = (EvidenceRole("report_evidence", (evidence_id,)),)
                calculator = ConfidenceCalculator()
                confidence = calculator.calculate(roles, self.evidence)
                if confidence_ceiling is not None:
                    ceiling = max(0.0, min(1.0, confidence_ceiling))
                    if confidence.score > ceiling:
                        confidence = calculator.calculate(
                            roles,
                            self.evidence,
                            ambiguity_penalty=confidence.score - ceiling,
                        )
        item = RepositoryReportItem(
            item_id,
            kind,
            safe_subject,
            safe_title,
            safe_statement,
            observation,
            capability,
            safe_scope,
            priority,
            safe_attributes,
            confidence,
            confidence_basis,
            (safe_producer, self.configuration.PRODUCER_VERSION),
            (evidence_id,),
            safe_limitations,
            tuple(item for item in (_safe_identifier(value) for value in related_item_ids) if item),
            tuple(item for item in (_safe_text(value) for value in prerequisites) if item),
        )
        existing = self.items.get(item_id)
        if existing is not None and existing != item:
            raise ValueError(f"conflicting repository report item: {item_id}")
        self.items[item_id] = item
        return item_id

    def _project_count(self) -> tuple[int | None, str | None]:
        count = _integer(self.summary.get("project_count"))
        if count is not None:
            return count, "repository_summary.project_count"
        projects = _mapping_records(self.summary.get("projects"))
        if projects:
            return len(projects), "repository_summary.projects"
        workspace_projects = _mapping_records(self.workspace.get("projects"))
        if workspace_projects:
            return len(workspace_projects), "workspace.projects"
        return None, None

    def _major_areas(self) -> tuple[str, ...]:
        roots = {
            _safe_text(item.get("name"))
            for item in _mapping_records(self.summary.get("projects"))
            if _safe_text(item.get("path")) in {".", ""}
        }
        return tuple(sorted({
            project
            for item in _mapping_records(self.summary.get("module_hierarchy"))
            if (project := _safe_text(item.get("project")))
            and (
                item.get("parent") is None
                or _safe_text(item.get("parent")) in roots
            )
        }))

    def _architecture_cycles(self) -> tuple[tuple[str, ...], ...]:
        return tuple(sorted({
            members
            for cycle in _sequence(self.architecture.get("dependency_cycles"))
            if _is_sequence(cycle)
            if (members := tuple(sorted({
                member
                for value in _sequence(cycle)
                if (member := _safe_text(value))
            })))
        }))

    def _architecture_conflicts(self) -> tuple[str, ...]:
        return tuple(sorted({
            conflict
            for raw_conflict in _strings(self.architecture.get("classification_conflicts"))
            if (conflict := _safe_text(raw_conflict))
        }))

    @staticmethod
    def _verified_evidence_ids(
        source: Mapping[str, object],
        requested: set[str],
    ) -> frozenset[str]:
        return frozenset(
            _ReportAssembler._verified_evidence_records(source, requested)
        )

    @staticmethod
    def _verified_evidence_records(
        source: Mapping[str, object],
        requested: set[str],
    ) -> Mapping[str, EvidenceRecord]:
        if not requested:
            return {}
        evidence_index = _mapping(source.get("evidence_index"))
        verified: dict[str, EvidenceRecord] = {}
        for raw_record in _mapping_records(evidence_index.get("records")):
            raw_id = raw_record.get("evidence_id")
            if raw_id not in requested:
                continue
            try:
                record = EvidenceRecord.from_dict(raw_record)
                canonical = EvidenceRecord.create(
                    record.kind,
                    record.subject_id,
                    record.producer,
                    record.snapshot_id,
                    source_refs=record.source_refs,
                    scope=record.scope,
                    language=record.language,
                    detail=record.detail,
                    limitations=record.limitations,
                    reliability=record.reliability,
                    specificity=record.specificity,
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if canonical == record:
                verified[record.evidence_id] = record
        return dict(sorted(verified.items()))

    def _repository_name(self) -> str | None:
        for projects in (
            _mapping_records(self.summary.get("projects")),
            _mapping_records(self.workspace.get("projects")),
        ):
            for project in projects:
                if _safe_text(project.get("path")) in {".", ""}:
                    name = _safe_text(project.get("name"))
                    if name:
                        return name
        raw_root = self.summary.get("root") or self.workspace.get("root")
        if raw_root is None:
            return None
        name = PurePath(str(raw_root).replace("\\", "/")).name
        return _safe_text(name) or None

    def _input_fingerprint(self) -> str:
        architecture_findings = tuple(sorted(
            (
                _safe_text(item.get("architecture")),
                _safe_number(item.get("confidence")),
                tuple(sorted(
                    (
                        _safe_text(evidence.get("kind")),
                        _safe_source_ref(evidence.get("reference")),
                    )
                    for evidence in _mapping_records(item.get("evidence"))
                )),
            )
            for item in _mapping_records(self.architecture.get("findings"))
        ))
        entry_points = tuple(sorted(
            item
            for value in _strings(self.summary.get("entry_points"))
            if (item := _safe_relative_reference(value))
        ))
        pattern_projection = tuple(sorted(
            (
                _safe_text(item.get("pattern")),
                _safe_number(item.get("confidence")),
                _safe_text(item.get("confidence_tier")),
                tuple(sorted(_safe_strings(item.get("evidence_ids")))),
                tuple(sorted(_safe_strings(item.get("limitations")))),
            )
            for item in _mapping_records(self.patterns.get("findings"))
        ))
        pattern_requested_evidence = {
            evidence_id
            for item in pattern_projection
            for evidence_id in item[3]
            if evidence_id.startswith("evidence:")
        }
        pattern_verified_evidence = tuple(sorted(self._verified_evidence_ids(
            self.patterns,
            pattern_requested_evidence,
        )))
        reachability_candidate_count = 0

        def reachability_candidate_projection():
            nonlocal reachability_candidate_count
            for item, _ in _reachability_findings(self.reachability):
                state = _safe_text(item.get("state"))
                tier = _safe_text(item.get("confidence_tier"))
                subject = _safe_identifier(item.get("subject_id"))
                if (
                    state not in {"likely_dead", "unreachable"}
                    or tier == "insufficient"
                    or not subject
                ):
                    continue
                reachability_candidate_count += 1
                yield (
                    subject,
                    state,
                    _safe_number(item.get("confidence")),
                    tier,
                    _safe_text(item.get("project")),
                    _safe_text(item.get("source_classification")),
                    tuple(sorted(_safe_strings(item.get("evidence_ids")))),
                    tuple(sorted(_safe_strings(item.get("limitations")))),
                )

        reachability_candidates = heapq.nsmallest(
            self.configuration.MAX_DEBT_FINDINGS,
            reachability_candidate_projection(),
        )
        reachability_requested_evidence = {
            evidence_id
            for item in reachability_candidates
            for evidence_id in item[6]
            if evidence_id.startswith("evidence:")
        }
        reachability_verified_records = self._verified_evidence_records(
            self.reachability,
            reachability_requested_evidence,
        )
        reachability_verified_projection = tuple(
            (
                item[0],
                tuple(
                    evidence_id for evidence_id in item[6]
                    if evidence_id in reachability_verified_records
                ),
                any(
                    reachability_verified_records[evidence_id].subject_id == item[0]
                    for evidence_id in item[6]
                    if evidence_id in reachability_verified_records
                ),
            )
            for item in reachability_candidates
        )
        raw_risk_hotspots = _mapping_records(self.risk.get("hotspots"))
        selected_risk_hotspots = tuple(heapq.nsmallest(
            self.configuration.MAX_HOTSPOTS,
            raw_risk_hotspots,
            key=lambda value: (
                _integer(value.get("rank")) or 10**9,
                _safe_identifier(value.get("subject_id")),
            ),
        ))
        risk_projection = tuple(
            {
                "rank": _integer(item.get("rank")),
                "subject_id": _safe_identifier(item.get("subject_id")),
                "display_name": _safe_text(item.get("display_name")),
                "score": _number(item.get("score")),
                "scope": _safe_text(item.get("scope")),
                "confidence": item.get("confidence"),
                "factors": tuple(sorted(
                    (
                        _safe_text(_mapping(factor.get("metric")).get("metric")),
                        _safe_text(_mapping(factor.get("metric")).get("unit")),
                    )
                    for factor in _mapping_records(item.get("factors"))
                )),
                "evidence_ids": tuple(sorted(_safe_strings(item.get("evidence_ids")))),
                "missing_signals": tuple(sorted(_safe_strings(item.get("missing_signals")))),
                "trend": _safe_text(item.get("trend")),
                "limitations": tuple(sorted(_safe_strings(item.get("limitations")))),
            }
            for item in selected_risk_hotspots
        )
        risk_requested_evidence = {
            evidence_id
            for item in risk_projection
            for evidence_id in item["evidence_ids"]
            if evidence_id.startswith("evidence:")
        }
        risk_verified_records = self._verified_evidence_records(
            self.risk,
            risk_requested_evidence,
        )
        risk_verified_projection = tuple(
            (
                str(item["subject_id"]),
                tuple(
                    evidence_id for evidence_id in item["evidence_ids"]
                    if (
                        evidence_id in risk_verified_records
                        and risk_verified_records[evidence_id].subject_id
                        == item["subject_id"]
                    )
                ),
            )
            for item in risk_projection
        )
        dependencies = _count_mapping(
            self.summary.get("declared_dependency_count_by_ecosystem")
        )
        manifests = _count_mapping(
            self.summary.get("dependency_manifest_count_by_ecosystem")
        )
        identity = {
            "producer": self.configuration.PRODUCER_VERSION,
            "graph_digest": self.graph_digest,
            "source_limitations": tuple(sorted(self.source_limitations)),
            "summary": {
                "schema": self.summary.get("schema_version"),
                "repository_name": self._repository_name(),
                "project_count": self._project_count()[0],
                "inventory": {
                    key: self.summary.get(key) for key in (
                        "inventoried_file_count",
                        "inventoried_file_bytes",
                        "inventoried_file_size_error_count",
                        "classified_non_test_source_files",
                        "classified_test_source_files",
                        "classified_generated_files",
                    )
                },
                "languages": _count_mapping(self.summary.get("language_file_counts") or self.summary.get("languages")),
                "build_systems": sorted(_strings(self.summary.get("build_systems"))),
                "frameworks": sorted(_strings(self.summary.get("frameworks"))),
                "hierarchy_count": len(_mapping_records(self.summary.get("module_hierarchy"))),
                "major_areas": self._major_areas()[: self.configuration.MAX_MAJOR_AREAS],
                "major_area_count": len(self._major_areas()),
                "entry_points": entry_points[: self.configuration.MAX_ENTRY_POINTS],
                "entry_point_count": len(entry_points),
                "dependencies": dependencies,
                "manifests": manifests,
                "total_dependencies": _first_integer(
                    self.summary,
                    "total_declared_dependency_records",
                    "total_declared_dependencies",
                ),
            },
            "architecture": {
                "schema": self.architecture.get("schema_version"),
                "findings": architecture_findings[: self.configuration.MAX_ARCHITECTURE_FINDINGS],
                "finding_count": len(architecture_findings),
                "dependency_analysis": _mapping(self.architecture.get("dependency_analysis")),
                "cycles": self._architecture_cycles()[: self.configuration.MAX_CYCLES],
                "cycle_count": len(self._architecture_cycles()),
                "conflicts": self._architecture_conflicts()[:5],
                "conflict_count": len(self._architecture_conflicts()),
            },
            "patterns": {
                "producer": self.patterns.get("producer_version"),
                "input": self.patterns.get("input_fingerprint"),
                "finding_count": len(_mapping_records(self.patterns.get("findings"))),
                "selected_finding_digest": _short_digest(pattern_projection),
                "verified_evidence_ids": pattern_verified_evidence,
            },
            "reachability": {
                "producer": self.reachability.get("producer_version"),
                "input": self.reachability.get("input_fingerprint"),
                "configuration": self.reachability.get("configuration_fingerprint"),
                "coverage": {
                    "status": _safe_text(
                        _mapping(self.reachability.get("coverage")).get("status")
                    ),
                    "subject_counts": _count_mapping(
                        _mapping(self.reachability.get("coverage")).get("subject_counts")
                    ),
                    "limitations": tuple(sorted(_safe_strings(
                        _mapping(self.reachability.get("coverage")).get("limitations")
                    ))),
                },
                "candidate_count": reachability_candidate_count,
                "selected_candidate_digest": _short_digest(reachability_candidates),
                "verified_evidence_projection": reachability_verified_projection,
            },
            "risk": {
                "producer": self.risk.get("producer_version"),
                "input": self.risk.get("input_fingerprint"),
                "configuration": self.risk.get("configuration_fingerprint"),
                "capabilities": tuple(sorted(
                    (
                        _safe_text(item.get("metric")),
                        _safe_text(item.get("status")),
                        _integer(item.get("observation_count")),
                    )
                    for item in _mapping_records(self.risk.get("capabilities"))
                )),
                "hotspot_count": len(raw_risk_hotspots),
                "selected_hotspots": risk_projection,
                "verified_evidence_projection": risk_verified_projection,
                "limitations": tuple(sorted(_safe_strings(
                    self.risk.get("limitations")
                ))),
            },
        }
        return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[Any, ...]:
    if not _is_sequence(value):
        return ()
    return tuple(value)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _mapping_records(value: object) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in _sequence(value) if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value))


def _safe_strings(value: object) -> tuple[str, ...]:
    return tuple(
        text for item in _sequence(value) if (text := _safe_text(item))
    )


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.isdecimal():
            return None
        try:
            return int(stripped)
        except (ValueError, OverflowError):
            return None
    return None


def _first_integer(value: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        if key not in value:
            continue
        parsed = _integer(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and 0.0 <= parsed <= 1.0 else None


def _safe_number(value: object) -> float:
    parsed = _number(value)
    return parsed if parsed is not None else -1.0


def _safe_text(value: object, *, maximum: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping) or _is_sequence(value):
        return ""
    text = " ".join(str(value).replace("\x00", "").split())
    if not text:
        return ""
    if contains_absolute_path_text(text):
        return ""
    return text[:maximum]


def _safe_identifier(value: object) -> str:
    return _safe_text(value, maximum=512)


def _safe_source_ref(value: object) -> str:
    text = _safe_text(value, maximum=512)
    if not text:
        return ""
    return text if text.startswith("evidence:") or not contains_absolute_path_text(text) else ""


def _safe_relative_reference(value: object) -> str:
    text = _safe_text(value, maximum=240)
    return text if text and not contains_absolute_path_text(text) else ""


def _count_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for key, raw in value.items():
        count = _integer(raw)
        name = _safe_text(key)
        if name and count is not None:
            result[name] = count
    return dict(sorted(result.items()))


def _joined(values: Sequence[str]) -> str:
    selected = tuple(value for value in values if value)
    return ", ".join(selected) if selected else "unavailable"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _short_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:16]


def _reachability_findings(
    reachability: Mapping[str, object],
):
    for finding in _mapping_records(reachability.get("findings")):
        yield finding, "reachability.findings"
    for group in _mapping_records(reachability.get("finding_groups")):
        shared = {
            key: item
            for key, item in group.items()
            if key not in {"subject_ids", "subject_id_prefix"}
        }
        prefix = str(group.get("subject_id_prefix", ""))
        for subject_id in _sequence(group.get("subject_ids")):
            yield {
                **shared,
                "subject_id": f"{prefix}{subject_id}",
            }, "reachability.findings"


def _insufficient_confidence(role: str) -> ConfidenceResult:
    return ConfidenceResult(
        0.0,
        ConfidenceTier.INSUFFICIENT,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        (role,),
    )


def _full_confidence(value: object) -> ConfidenceResult | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return ConfidenceResult.from_dict(value)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _capability_state(value: object) -> ReportCapabilityState:
    normalized = str(value).strip().casefold()
    if normalized == "complete":
        return ReportCapabilityState.AVAILABLE
    if normalized == "insufficient":
        return ReportCapabilityState.PARTIAL
    try:
        return ReportCapabilityState(normalized)
    except ValueError:
        return ReportCapabilityState.UNAVAILABLE
