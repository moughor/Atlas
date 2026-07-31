from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
import json

from moughorai.call_graph import CallGraph, CallSiteKind, ResolutionStatus
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)

from .classifier import ReachabilityClassifier

from .models import (
    CoverageStatus,
    DeadCodeReport,
    ProjectEvidence,
    ProjectReachabilityCoverage,
    ReachabilityCapability,
    ReachabilityConfiguration,
    ReachabilityCoverage,
    ReachabilityEvidenceBundle,
    ReachabilityFinding,
    ReachabilityPath,
    ReachabilityProtection,
    ReachabilityRoot,
    ReachabilitySeed,
    ReachabilityState,
    RootCategory,
    SourceClassification,
)
from .traversal import (
    ReachabilityRelation,
    materialize_path,
    select_protections,
    traverse,
)


class ReachabilityAnalysisService:
    """Conservative PR131 analysis over existing canonical and specialized facts."""

    PRODUCER_VERSION = "atlas-pr131/1"
    SCHEMA_VERSION = 1
    _SUBJECT_KINDS = {
        KnowledgeKind.TYPE,
        KnowledgeKind.METHOD,
        KnowledgeKind.FIELD,
    }
    _FRAMEWORK_ANNOTATIONS = {
        "spring": frozenset({
            "Component", "Service", "Repository", "Controller",
            "RestController", "Configuration", "Bean", "EventListener",
            "Scheduled",
        }),
        "jpa": frozenset({"Entity", "Embeddable", "MappedSuperclass", "Converter"}),
        "jakarta persistence": frozenset({
            "Entity", "Embeddable", "MappedSuperclass", "Converter",
        }),
    }
    _GENERATED_ANNOTATIONS = frozenset({
        "Generated", "GeneratedValue", "AutoValue", "DaggerGenerated",
    })

    def __init__(
        self,
        *,
        confidence: ConfidenceCalculator | None = None,
        cache_size: int = 8,
    ) -> None:
        if cache_size < 1:
            raise ValueError("cache_size must be positive")
        self._confidence = confidence or ConfidenceCalculator()
        self._classifier = ReachabilityClassifier(self._confidence)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, DeadCodeReport] = OrderedDict()

    def analyze(
        self,
        graph: KnowledgeGraph,
        *,
        symbol_metadata: Sequence[Mapping[str, object]] = (),
        repository_summary: Mapping[str, object] | None = None,
        call_graphs: Mapping[str, CallGraph] | None = None,
        evidence: ReachabilityEvidenceBundle | None = None,
        failed_projects: Sequence[str] = (),
        snapshot_lineage: str | None = None,
        configuration: ReachabilityConfiguration | None = None,
    ) -> DeadCodeReport:
        calls = dict(call_graphs or {})
        bundle = evidence or ReachabilityEvidenceBundle()
        config = configuration or ReachabilityConfiguration()
        summary = dict(repository_summary or {})
        metadata = self._normalized_metadata(symbol_metadata)
        graph_digest = self._digest(graph.to_dict())
        configuration_fingerprint = self._digest(config.to_dict())
        fingerprint = self._fingerprint(
            graph, metadata, summary, calls, bundle, failed_projects, config,
        )
        cached = self._cache.get(fingerprint)
        if cached is not None:
            self._cache.move_to_end(fingerprint)
            return cached

        lineage = snapshot_lineage or f"reachability-input:{fingerprint}"
        result = self._analyze(
            graph,
            metadata=metadata,
            summary=summary,
            call_graphs=calls,
            bundle=bundle,
            failed_projects=tuple(sorted(set(map(str, failed_projects)))),
            lineage=lineage,
            fingerprint=fingerprint,
            graph_digest=graph_digest,
            configuration_fingerprint=configuration_fingerprint,
            configuration=config,
        )
        self._cache[fingerprint] = result
        self._cache.move_to_end(fingerprint)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    def _analyze(
        self,
        graph: KnowledgeGraph,
        *,
        metadata: Mapping[str, Mapping[str, object]],
        summary: Mapping[str, object],
        call_graphs: Mapping[str, CallGraph],
        bundle: ReachabilityEvidenceBundle,
        failed_projects: tuple[str, ...],
        lineage: str,
        fingerprint: str,
        graph_digest: str,
        configuration_fingerprint: str,
        configuration: ReachabilityConfiguration,
    ) -> DeadCodeReport:
        all_evidence = EvidenceIndex()
        nodes = {node.id: node for node in graph.nodes}
        subjects = tuple(node for node in graph.nodes if node.kind in self._SUBJECT_KINDS)
        projects = self._project_evidence(
            subjects, summary, call_graphs, bundle, failed_projects, graph,
        )
        coverage_evidence = {
            project: all_evidence.add(self._coverage_evidence(item, lineage))
            for project, item in sorted(projects.items())
        }
        relations, relation_limitations = self._relations(
            graph, nodes, call_graphs, all_evidence, lineage,
        )
        adjacency: dict[str, tuple[ReachabilityRelation, ...]] = {}
        outgoing: dict[str, list[ReachabilityRelation]] = defaultdict(list)
        for relation in relations:
            outgoing[relation.source].append(relation)
        for source, values in outgoing.items():
            adjacency[source] = tuple(sorted(values))

        inferred_roots, inferred_protections = self._discover_structured_evidence(
            subjects, metadata, summary,
        )
        seeds = tuple(sorted(set((*bundle.roots, *inferred_roots))))
        protections = select_protections((*bundle.protections, *inferred_protections))
        roots, root_evidence = self._roots(
            seeds, nodes, all_evidence, lineage,
        )
        production_seeds = tuple(
            item for item in roots if item.category is not RootCategory.TEST
        )
        test_seeds = tuple(item for item in roots if item.category is RootCategory.TEST)
        production, production_truncated = traverse(
            production_seeds, root_evidence, adjacency, configuration.max_traversal_nodes,
        )
        tests, test_truncated = traverse(
            test_seeds, root_evidence, adjacency, configuration.max_traversal_nodes,
        )
        truncated = production_truncated or test_truncated

        paths: dict[tuple[str, str], ReachabilityPath] = {}
        findings: list[ReachabilityFinding] = []
        project_findings: dict[str, list[ReachabilityFinding]] = defaultdict(list)
        for node in subjects:
            project = self._project(node)
            project_capability = projects[project]
            if project_capability.failed:
                continue
            source_classification = self._source_classification(metadata.get(node.id, {}))
            protection = protections.get(node.id)
            production_trace = production.get(node.id)
            test_trace = tests.get(node.id)
            state, limitations = self._classifier.classify(
                node,
                metadata.get(node.id, {}),
                source_classification,
                project_capability,
                protection,
                production_trace,
                test_trace,
                truncated,
            )
            evidence_ids = [coverage_evidence[project]]
            root_categories: set[RootCategory] = set()
            relationship_ids: list[str] = []
            root_ids: list[str] = []
            for scope, trace in (("production", production_trace), ("test", test_trace)):
                if trace is None:
                    continue
                root_categories.add(trace.category)
                path = materialize_path(
                    node.id,
                    trace,
                    production if scope == "production" else tests,
                    configuration.max_path_depth,
                    scope,
                )
                paths[(scope, node.id)] = path
                relationship_ids.extend(path.evidence_ids)
                root_ids.append(trace.root_evidence_id)
            protection_ids: list[str] = []
            if protection is not None:
                protection_ids.append(all_evidence.add(
                    self._protection_evidence(protection, lineage)
                ))
            evidence_ids.extend((*root_ids, *relationship_ids, *protection_ids))
            node_id = coverage_evidence[project]
            if state in {
                ReachabilityState.UNUSED,
                ReachabilityState.LIKELY_DEAD,
                ReachabilityState.UNREACHABLE,
            }:
                node_id = all_evidence.add(self._node_evidence(node, lineage))
                evidence_ids.append(node_id)
            score, tier = self._classifier.confidence_for(
                state,
                all_evidence,
                node_id=node_id,
                coverage_id=coverage_evidence[project],
                root_ids=tuple(root_ids),
                relationship_ids=tuple(relationship_ids),
                protection_ids=tuple(protection_ids),
                project=project_capability,
            )
            if state is ReachabilityState.LIKELY_DEAD and (
                tier is not ConfidenceTier.HIGH
                or score < configuration.dead_code_threshold
            ):
                state = ReachabilityState.UNUSED
                limitations = (*limitations, "Dead-code confidence threshold was not met.")
                score, tier = self._classifier.confidence_for(
                    state,
                    all_evidence,
                    node_id=node_id,
                    coverage_id=coverage_evidence[project],
                    root_ids=(), relationship_ids=(), protection_ids=(),
                    project=project_capability,
                )
            finding = ReachabilityFinding(
                node.id,
                node.kind.value,
                node.language,
                project,
                source_classification,
                state,
                score,
                tier,
                tuple(evidence_ids),
                tuple(root_categories),
                production_trace is not None,
                test_trace is not None,
                tuple(limitations),
                self.PRODUCER_VERSION,
            )
            findings.append(finding)
            project_findings[project].append(finding)

        project_coverage = tuple(
            self._project_coverage(
                item,
                project_findings.get(project, ()),
                coverage_evidence[project],
                relation_limitations.get(project, ()),
            )
            for project, item in sorted(projects.items())
        )
        coverage = self._coverage(subjects, project_coverage, truncated)
        capabilities = self._capabilities(project_coverage)
        report_limitations = set(coverage.limitations)
        if not relations:
            report_limitations.add(
                "No reliable call relationships were available; missing calls were not treated as dead-code evidence."
            )
        referenced = {
            evidence_id
            for item in roots
            for evidence_id in item.evidence_ids
        }
        referenced.update(
            evidence_id for item in findings for evidence_id in item.evidence_ids
        )
        referenced.update(
            evidence_id for item in paths.values() for evidence_id in item.evidence_ids
        )
        referenced.update(
            evidence_id for item in project_coverage for evidence_id in item.evidence_ids
        )
        referenced.update(
            evidence_id for item in capabilities for evidence_id in item.evidence_ids
        )
        return DeadCodeReport(
            tuple(roots),
            tuple(findings),
            tuple(paths.values()),
            coverage,
            capabilities,
            EvidenceIndex(record for record in all_evidence.records if record.evidence_id in referenced),
            fingerprint,
            graph_digest,
            configuration_fingerprint,
            lineage,
            tuple(report_limitations),
            self.PRODUCER_VERSION,
            self.SCHEMA_VERSION,
        )

    def _project_evidence(
        self,
        subjects: tuple[KnowledgeNode, ...],
        summary: Mapping[str, object],
        call_graphs: Mapping[str, CallGraph],
        bundle: ReachabilityEvidenceBundle,
        failed_projects: tuple[str, ...],
        graph: KnowledgeGraph,
    ) -> dict[str, ProjectEvidence]:
        languages: dict[str, set[str]] = defaultdict(set)
        for node in subjects:
            languages[self._project(node)].add(node.language)
        summary_projects = {
            str(item.get("name", "")): item
            for item in summary.get("projects", ())
            if isinstance(item, Mapping) and str(item.get("name", ""))
        }
        explicit = {item.project: item for item in bundle.projects}
        names = set(languages) | set(summary_projects) | set(explicit) | set(call_graphs) | set(failed_projects)
        canonical_call_projects = {
            self._project(graph.get(edge.source))
            for edge in graph.edges
            if edge.relation is KnowledgeRelation.CALLS and graph.get(edge.source) is not None
        }
        result: dict[str, ProjectEvidence] = {}
        for name in sorted(names or {"repository"}):
            base = explicit.get(name, ProjectEvidence(name))
            calls = base.calls
            limitations = set(base.limitations)
            if calls is CoverageStatus.UNAVAILABLE and (
                name in call_graphs or name in canonical_call_projects
            ):
                calls = CoverageStatus.PARTIAL
            call_graph = call_graphs.get(name)
            if call_graph is not None and any(
                item.status is ResolutionStatus.UNRESOLVED
                for item in call_graph.resolutions
            ):
                calls = CoverageStatus.PARTIAL
                limitations.add("Unresolved specialized call sites reduce call coverage.")
            project_summary = summary_projects.get(name, {})
            roots = base.roots
            if roots is CoverageStatus.UNAVAILABLE and project_summary.get("entry_points"):
                roots = CoverageStatus.PARTIAL
            frameworks = base.frameworks
            if frameworks is CoverageStatus.UNAVAILABLE and project_summary.get("framework_evidence"):
                frameworks = CoverageStatus.PARTIAL
            failed = base.failed or name in failed_projects
            if calls is CoverageStatus.UNAVAILABLE:
                limitations.add("Reliable call evidence is unavailable.")
            if not base.closed_world:
                limitations.add("The project is not established as a closed world.")
            if failed:
                limitations.add("Project analysis failed; reachability is unavailable for this scope.")
            result[name] = replace(
                base,
                languages=tuple(sorted(set((*base.languages, *languages.get(name, ()))))) or ("unknown",),
                roots=roots,
                calls=calls,
                frameworks=frameworks,
                failed=failed,
                limitations=tuple(limitations),
            )
        return result

    def _relations(
        self,
        graph: KnowledgeGraph,
        nodes: Mapping[str, KnowledgeNode],
        call_graphs: Mapping[str, CallGraph],
        evidence: EvidenceIndex,
        lineage: str,
    ) -> tuple[tuple[ReachabilityRelation, ...], Mapping[str, tuple[str, ...]]]:
        relations: set[ReachabilityRelation] = set()
        limitations: dict[str, set[str]] = defaultdict(set)
        for edge in graph.edges:
            if edge.relation is KnowledgeRelation.CALLS:
                evidence_id = evidence.add(self._edge_evidence(edge, nodes, lineage))
                relations.add(ReachabilityRelation(edge.source, edge.target, "calls", evidence_id))
            elif edge.relation is KnowledgeRelation.MEMBER_OF:
                source = nodes.get(edge.source)
                target = nodes.get(edge.target)
                if source is None or target is None or target.kind is not KnowledgeKind.TYPE:
                    continue
                evidence_id = evidence.add(self._edge_evidence(edge, nodes, lineage))
                relations.add(ReachabilityRelation(edge.source, edge.target, "member_owner", evidence_id))

        lookup = self._method_lookup(graph)
        for project, call_graph in sorted(call_graphs.items()):
            for edge in call_graph.edges:
                if edge.status not in {ResolutionStatus.RESOLVED, ResolutionStatus.POLYMORPHIC}:
                    continue
                source = self._resolve_method(lookup, project, edge.caller.qualified_name)
                target = self._resolve_method(lookup, project, edge.callee.qualified_name)
                if source is None or target is None:
                    limitations[project].add(
                        "Some specialized call subjects could not be mapped uniquely to canonical IDs."
                    )
                    continue
                record = EvidenceRecord.create(
                    EvidenceKind.ANALYSIS_RESULT,
                    target,
                    "moughorai.call_graph.v1",
                    lineage,
                    source_refs=(source, target, edge.caller.qualified_name, edge.callee.qualified_name),
                    scope=f"project:{project}",
                    language="java",
                    detail={
                        "relation": "constructor" if edge.kind is CallSiteKind.CONSTRUCTOR else "calls",
                        "resolution": edge.status.value,
                        "dispatch": edge.dispatch.value,
                    },
                    reliability=0.9,
                    specificity=1.0 if edge.status is ResolutionStatus.RESOLVED else 0.85,
                )
                evidence_id = evidence.add(record)
                relation = "constructor" if edge.kind is CallSiteKind.CONSTRUCTOR else "calls"
                relations.add(ReachabilityRelation(source, target, relation, evidence_id))
        return tuple(sorted(relations)), {
            project: tuple(sorted(values)) for project, values in limitations.items()
        }

    def _discover_structured_evidence(
        self,
        subjects: tuple[KnowledgeNode, ...],
        metadata: Mapping[str, Mapping[str, object]],
        summary: Mapping[str, object],
    ) -> tuple[tuple[ReachabilitySeed, ...], tuple[ReachabilityProtection, ...]]:
        frameworks = self._frameworks_by_project(summary)
        roots: list[ReachabilitySeed] = []
        protections: list[ReachabilityProtection] = []
        for node in subjects:
            values = metadata.get(node.id, {})
            project = self._project(node)
            entry_point = str(values.get("entry_point", ""))
            if entry_point:
                roots.append(ReachabilitySeed(
                    node.id,
                    RootCategory.APPLICATION,
                    project,
                    f"project:{project}",
                    "java-symbol-index",
                    (node.id,),
                    (),
                    1.0,
                    1.0,
                ))
            annotations = self._tokens(values.get("annotations"))
            simple_annotations = {item.rsplit(".", 1)[-1] for item in annotations}
            generated = simple_annotations & self._GENERATED_ANNOTATIONS
            if generated:
                protections.append(ReachabilityProtection(
                    node.id,
                    ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED,
                    "java-symbol-index",
                    project,
                    node.language,
                    f"annotation:{sorted(generated)[0]}",
                    SourceClassification.GENERATED,
                    (node.id,),
                ))
            supported_annotations: set[str] = set()
            for framework in frameworks.get(project, ()):
                folded = framework.casefold()
                for family, allowed in self._FRAMEWORK_ANNOTATIONS.items():
                    if family in folded:
                        supported_annotations.update(simple_annotations & allowed)
            if supported_annotations:
                protections.append(ReachabilityProtection(
                    node.id,
                    ReachabilityState.FRAMEWORK_MANAGED,
                    "repository-summary+java-symbol-index",
                    project,
                    node.language,
                    f"framework-annotation:{sorted(supported_annotations)[0]}",
                    self._source_classification(values),
                    (node.id, f"framework-project:{project}"),
                ))
        return tuple(roots), tuple(protections)

    def _roots(
        self,
        seeds: tuple[ReachabilitySeed, ...],
        nodes: Mapping[str, KnowledgeNode],
        evidence: EvidenceIndex,
        lineage: str,
    ) -> tuple[tuple[ReachabilityRoot, ...], Mapping[tuple[str, RootCategory], str]]:
        roots: list[ReachabilityRoot] = []
        evidence_ids: dict[tuple[str, RootCategory], str] = {}
        for seed in seeds:
            node = nodes.get(seed.subject_id)
            if node is None:
                continue
            record = EvidenceRecord.create(
                EvidenceKind.REPOSITORY_METADATA,
                seed.subject_id,
                seed.producer,
                lineage,
                source_refs=seed.source_refs or (seed.subject_id,),
                scope=seed.scope,
                language=node.language,
                detail={"root_category": seed.category.value},
                limitations=seed.limitations,
                reliability=seed.reliability,
                specificity=seed.specificity,
            )
            evidence_id = evidence.add(record)
            result = self._confidence.calculate(
                (EvidenceRole("root", (evidence_id,)),), evidence,
            )
            roots.append(ReachabilityRoot(
                seed.subject_id,
                seed.category,
                seed.project or self._project(node),
                seed.scope,
                result.score,
                result.tier,
                (evidence_id,),
                seed.limitations,
                self.PRODUCER_VERSION,
            ))
            evidence_ids[(seed.subject_id, seed.category)] = evidence_id
        return tuple(sorted(set(roots))), evidence_ids

    def _project_coverage(
        self,
        project: ProjectEvidence,
        findings: Sequence[ReachabilityFinding],
        evidence_id: str,
        relation_limitations: Sequence[str],
    ) -> ProjectReachabilityCoverage:
        counts = Counter(item.state.value for item in findings)
        limitations = tuple(sorted(set((*project.limitations, *relation_limitations))))
        statuses = (
            project.roots, project.calls, project.cfg, project.frameworks,
            project.reflection, project.service_loader, project.generated,
            project.external_api,
        )
        if project.failed:
            status = CoverageStatus.UNAVAILABLE
        elif all(item is CoverageStatus.COMPLETE for item in statuses):
            status = CoverageStatus.COMPLETE
        elif all(item is CoverageStatus.UNAVAILABLE for item in statuses):
            status = CoverageStatus.UNAVAILABLE
        else:
            status = CoverageStatus.PARTIAL
        return ProjectReachabilityCoverage(
            project.project,
            project.languages,
            status,
            project.roots,
            project.calls,
            project.cfg,
            project.frameworks,
            project.reflection,
            project.service_loader,
            project.generated,
            project.external_api,
            project.closed_world,
            len(findings),
            tuple(sorted(counts.items())),
            (evidence_id,),
            limitations,
        )

    @staticmethod
    def _coverage(
        subjects: tuple[KnowledgeNode, ...],
        projects: tuple[ProjectReachabilityCoverage, ...],
        truncated: bool,
    ) -> ReachabilityCoverage:
        subject_counts = Counter(node.kind.value for node in subjects)
        supported: set[str] = set()
        partial: set[str] = set()
        limitations: set[str] = set()
        for project in projects:
            limitations.update(project.limitations)
            if project.status is CoverageStatus.COMPLETE:
                supported.update(project.languages)
            elif project.status is CoverageStatus.PARTIAL:
                partial.update(project.languages)
        statuses = {project.status for project in projects}
        status = (
            CoverageStatus.COMPLETE
            if statuses == {CoverageStatus.COMPLETE} and not truncated
            else CoverageStatus.UNAVAILABLE
            if statuses <= {CoverageStatus.UNAVAILABLE}
            else CoverageStatus.PARTIAL
        )
        if truncated:
            limitations.add("Traversal was truncated at the configured node bound.")
        return ReachabilityCoverage(
            projects,
            tuple(supported),
            tuple(partial),
            tuple(sorted(subject_counts.items())),
            status,
            truncated,
            tuple(limitations),
        )

    @staticmethod
    def _capabilities(
        projects: tuple[ProjectReachabilityCoverage, ...],
    ) -> tuple[ReachabilityCapability, ...]:
        fields = (
            ("roots", "roots"),
            ("calls", "calls"),
            ("control_flow", "cfg"),
            ("frameworks", "frameworks"),
            ("reflection", "reflection"),
            ("service_loader", "service_loader"),
            ("generated_or_annotation_managed", "generated"),
            ("external_api", "external_api"),
        )
        result = []
        for name, field in fields:
            values = tuple(getattr(project, field) for project in projects)
            distinct = set(values)
            status = (
                CoverageStatus.COMPLETE
                if distinct == {CoverageStatus.COMPLETE}
                else CoverageStatus.UNAVAILABLE
                if not distinct or distinct == {CoverageStatus.UNAVAILABLE}
                else CoverageStatus.PARTIAL
            )
            scopes = tuple(project.project for project in projects if getattr(project, field) is not CoverageStatus.UNAVAILABLE)
            evidence_ids = tuple(evidence_id for project in projects for evidence_id in project.evidence_ids)
            limitations = tuple(
                sorted({
                    limitation
                    for project in projects
                    if getattr(project, field) is not CoverageStatus.COMPLETE
                    for limitation in project.limitations
                })
            )
            result.append(ReachabilityCapability(name, status, scopes, evidence_ids, limitations))
        return tuple(result)

    @staticmethod
    def _project(node: KnowledgeNode | None) -> str:
        return (node.project_id if node is not None else None) or "repository"

    @staticmethod
    def _tokens(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(sorted(filter(None, (item.strip() for item in value.split(",")))))
        if isinstance(value, (list, tuple)):
            return tuple(sorted(map(str, value)))
        return ()

    @staticmethod
    def _source_classification(value: Mapping[str, object]) -> SourceClassification:
        raw = str(value.get("source_classification", "unknown"))
        try:
            return SourceClassification(raw)
        except ValueError:
            return SourceClassification.UNKNOWN

    @staticmethod
    def _frameworks_by_project(summary: Mapping[str, object]) -> Mapping[str, tuple[str, ...]]:
        result: dict[str, set[str]] = defaultdict(set)
        for item in summary.get("framework_evidence", ()):
            if isinstance(item, Mapping):
                result[str(item.get("project", "repository"))].add(str(item.get("framework", "")))
        for project in summary.get("projects", ()):
            if not isinstance(project, Mapping):
                continue
            name = str(project.get("name", "repository"))
            result[name].update(map(str, project.get("frameworks", ())))
        return {key: tuple(sorted(filter(None, values))) for key, values in result.items()}

    @staticmethod
    def _normalized_metadata(
        values: Sequence[Mapping[str, object]],
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        selected = {
            "annotations", "visibility", "entry_point",
            "source_classification", "language",
        }
        for item in values:
            subject_id = str(item.get("id", ""))
            if not subject_id:
                continue
            raw = item.get("metadata", {})
            metadata = dict(raw) if isinstance(raw, Mapping) else {}
            result[subject_id] = {
                key: metadata[key]
                for key in sorted(selected.intersection(metadata))
            }
        return result

    @staticmethod
    def _method_lookup(
        graph: KnowledgeGraph,
    ) -> Mapping[tuple[str | None, str], tuple[str, ...]]:
        values: dict[tuple[str | None, str], list[str]] = defaultdict(list)
        for node in graph.by_kind(KnowledgeKind.METHOD):
            name = node.qualified_name or node.name
            values[(node.project_id, name)].append(node.id)
            values[(None, name)].append(node.id)
        return {key: tuple(sorted(set(items))) for key, items in values.items()}

    @staticmethod
    def _resolve_method(
        lookup: Mapping[tuple[str | None, str], tuple[str, ...]],
        project: str,
        qualified_name: str,
    ) -> str | None:
        scoped = lookup.get((project, qualified_name), ())
        if len(scoped) == 1:
            return scoped[0]
        unscoped = lookup.get((None, qualified_name), ())
        return unscoped[0] if len(unscoped) == 1 else None

    @staticmethod
    def _node_evidence(node: KnowledgeNode, lineage: str) -> EvidenceRecord:
        return EvidenceRecord.create(
            EvidenceKind.GRAPH_NODE,
            node.id,
            "knowledge-graph.v1",
            lineage,
            source_refs=(node.id,),
            scope=f"project:{ReachabilityAnalysisService._project(node)}",
            language=node.language,
            detail={"kind": node.kind.value},
            reliability=1.0,
            specificity=1.0,
        )

    @staticmethod
    def _edge_evidence(
        edge: KnowledgeEdge,
        nodes: Mapping[str, KnowledgeNode],
        lineage: str,
    ) -> EvidenceRecord:
        source = nodes.get(edge.source)
        return EvidenceRecord.create(
            EvidenceKind.GRAPH_EDGE,
            edge.target,
            "knowledge-graph.v1",
            lineage,
            source_refs=(edge.source, edge.target, *edge.evidence),
            scope=f"project:{ReachabilityAnalysisService._project(source)}",
            language=source.language if source is not None else "unknown",
            detail={"relation": edge.relation.value},
            reliability=1.0,
            specificity=1.0,
        )

    @staticmethod
    def _coverage_evidence(project: ProjectEvidence, lineage: str) -> EvidenceRecord:
        return EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            f"project:{project.project}",
            ReachabilityAnalysisService.PRODUCER_VERSION,
            lineage,
            source_refs=(f"project:{project.project}",),
            scope=f"project:{project.project}",
            language=",".join(project.languages) or "unknown",
            detail={
                "roots": project.roots.value,
                "calls": project.calls.value,
                "cfg": project.cfg.value,
                "frameworks": project.frameworks.value,
                "reflection": project.reflection.value,
                "service_loader": project.service_loader.value,
                "generated": project.generated.value,
                "external_api": project.external_api.value,
                "closed_world": str(project.closed_world).lower(),
                "failed": str(project.failed).lower(),
            },
            limitations=project.limitations,
            reliability=1.0,
            specificity=0.95 if project.closed_world else 0.8,
        )

    @staticmethod
    def _protection_evidence(
        protection: ReachabilityProtection,
        lineage: str,
    ) -> EvidenceRecord:
        return EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            protection.subject_id,
            protection.producer,
            lineage,
            source_refs=protection.source_refs or (protection.subject_id,),
            scope=f"project:{protection.project}" if protection.project else "repository",
            language=protection.language,
            detail={
                "state": protection.state.value,
                "mechanism": protection.mechanism,
                "source_classification": protection.source_classification.value,
            },
            limitations=protection.limitations,
            reliability=protection.reliability,
            specificity=protection.specificity,
        )

    @classmethod
    def _fingerprint(
        cls,
        graph: KnowledgeGraph,
        metadata: Mapping[str, Mapping[str, object]],
        summary: Mapping[str, object],
        calls: Mapping[str, CallGraph],
        bundle: ReachabilityEvidenceBundle,
        failed_projects: Sequence[str],
        config: ReachabilityConfiguration,
    ) -> str:
        selected_summary = {
            "projects": summary.get("projects", ()),
            "framework_evidence": summary.get("framework_evidence", ()),
            "entry_points": summary.get("entry_points", ()),
        }
        return cls._digest({
            "producer_version": cls.PRODUCER_VERSION,
            "schema_version": cls.SCHEMA_VERSION,
            "graph": graph.to_dict(),
            "symbol_metadata": metadata,
            "repository_summary": selected_summary,
            "call_graphs": {
                project: value.to_dict() for project, value in sorted(calls.items())
            },
            "evidence": bundle.to_dict(),
            "failed_projects": sorted(set(map(str, failed_projects))),
            "configuration": config.to_dict(),
        })

    @staticmethod
    def _digest(value: object) -> str:
        return hashlib.sha256(json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")).hexdigest()
