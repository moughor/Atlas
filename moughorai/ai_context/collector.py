from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolDatabase
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_symbols import JavaSymbolService
from moughorai.java_workspace.source_selection import (
    select_compiled_java_sources,
)
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable
from moughorai.workspace import WorkspaceRunReport, WorkspaceService
from moughorai.workspace.files import project_files
from moughorai.dependency_intelligence import DeclaredDependency
from moughorai.repository_summary import RepositorySummaryService
from moughorai.architecture_detection import ArchitectureDetectionService
from moughorai.ai_git_context import GitContextError, GitContextService
from moughorai.design_patterns import PatternDetectionService
from moughorai.call_graph import CallGraph
from moughorai.java_architecture import JavaArchitectureGraph
from moughorai.knowledge_graph import KnowledgeGraph
from moughorai.reachability import ReachabilityAnalysisService
from moughorai.risk_analysis import RiskAnalysisService
from moughorai.repository_report import RepositoryReportService
from moughorai.measurement import MeasurementPhase, MeasurementSession
from moughorai.security_intelligence import (
    SecurityCapabilityState,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityProducerReport,
)

from .models import WorkspaceSemanticContext
from .service import WorkspaceContextBuilder


@dataclass(frozen=True, slots=True)
class SemanticCollectionReport:
    projects: tuple[str, ...]
    diagnostics: int
    symbols: int
    type_tables: int


@dataclass(frozen=True, slots=True)
class CollectedSemanticContext:
    context: WorkspaceSemanticContext
    report: SemanticCollectionReport


class SemanticContextCollector:
    """Aggregate real analyzer artifacts into the deterministic PR108 model."""

    def __init__(
        self,
        service: WorkspaceService,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.service = service
        self.measurement = (
            measurement
            or getattr(service, "measurement", None)
            or MeasurementSession()
        )

    def collect(self, report: WorkspaceRunReport) -> CollectedSemanticContext:
        if not report.succeeded:
            raise ValueError("semantic context requires a successful workspace analysis")
        diagnostics: dict[str, list[Diagnostic]] = {}
        types: dict[str, TypeTable] = {}
        symbols = GlobalSymbolDatabase()
        projects_with_symbols: set[str] = set()
        declared_dependencies: list[DeclaredDependency] = []
        java_architecture_graphs: dict[str, JavaArchitectureGraph] = {}
        call_graphs: dict[str, CallGraph] = {}
        security_producer_reports: list[SecurityProducerReport] = []
        with self.measurement.scope(
            MeasurementPhase.SYMBOL_EXTRACTION,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            for run in report.runs:
                if isinstance(run.value, SemanticDocument):
                    declared_dependencies.extend(
                        item for item in run.value.get_artifact("declared_dependencies", ())
                        if isinstance(item, DeclaredDependency)
                    )
                if self._collect_result(
                    run.project,
                    run.value,
                    diagnostics,
                    types,
                    symbols,
                    java_architecture_graphs,
                    call_graphs,
                    security_producer_reports,
                ):
                    projects_with_symbols.add(run.project)
            self._collect_java_sources(
                diagnostics,
                symbols,
                skip=projects_with_symbols,
            )
            snapshot = symbols.snapshot()
            scope.add_units(len(report.runs))
            scope.add_objects_produced(len(snapshot))
            scope.set_objects_retained(len(snapshot))
        with self.measurement.scope(
            MeasurementPhase.REPOSITORY_SUMMARY,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            repository_summary = RepositorySummaryService(
                self.service,
                measurement=self.measurement,
            ).build()
            scope.add_units(len(repository_summary.projects))
            scope.add_objects_produced(len(repository_summary.projects))
            scope.set_objects_retained(len(repository_summary.projects))
        context = WorkspaceContextBuilder(measurement=self.measurement).build(
            self.service.workspace,
            diagnostics=diagnostics,
            symbols=snapshot.symbols,
            types=types,
            declared_dependencies=declared_dependencies,
            repository_summary=repository_summary,
        )
        context_data = context.to_dict()
        with self.measurement.scope(
            MeasurementPhase.ARCHITECTURE,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            architecture = ArchitectureDetectionService().detect(
                context_data["repository_summary"],
                context_data["semantic_graph"],
            )
            scope.add_units(len(context_data["semantic_graph"].get("nodes", ())))
            scope.add_objects_produced(len(architecture.findings))
            scope.set_objects_retained(len(architecture.findings))
            context_data["architecture"] = architecture.to_dict()
            del architecture
        with self.measurement.scope(
            MeasurementPhase.KNOWLEDGE_GRAPH,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            knowledge_graph = KnowledgeGraph.from_dict(context_data["semantic_graph"])
            scope.add_units(
                len(knowledge_graph.nodes) + len(knowledge_graph.edges)
            )
            scope.add_objects_produced(
                len(knowledge_graph.nodes) + len(knowledge_graph.edges)
            )
            scope.set_objects_retained(
                len(knowledge_graph.nodes) + len(knowledge_graph.edges)
            )
        graph_digest = knowledge_graph.stable_digest()
        with self.measurement.scope(
            "security_intelligence.consolidation",
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            # Keep semantic-snapshot imports acyclic while the AI context package
            # initializes; the resolver is needed only for this optional phase.
            from moughorai.subject_resolution import CanonicalSubjectResolver

            resolver = CanonicalSubjectResolver(
                knowledge_graph,
                symbols=context_data["symbols"],
                graph_digest=graph_digest,
            )
            security_service = SecurityIntelligenceService(
                resolver,
                snapshot_id=f"semantic-graph:{graph_digest}",
                measurement=self.measurement,
            )
            try:
                security_intelligence = security_service.analyze(
                    SecurityIntelligenceRequest(limit=10_000),
                    producer_reports=tuple(security_producer_reports),
                )
            except (TypeError, ValueError, OverflowError):
                security_intelligence = SecurityIntelligenceService(
                    resolver,
                    snapshot_id=f"semantic-graph:{graph_digest}",
                    measurement=self.measurement,
                    limitations=(
                        "Security producer consolidation was incompatible or "
                        "exceeded its deterministic work bound.",
                    ),
                    unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
                ).analyze(SecurityIntelligenceRequest(limit=10_000))
            scope.add_units(len(security_producer_reports))
            scope.add_objects_produced(len(security_intelligence.findings))
            scope.set_objects_retained(len(security_intelligence.findings))
            context_data["security_intelligence"] = security_intelligence.to_dict()
            del security_intelligence
        with self.measurement.scope(
            "design_patterns.analysis",
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            patterns = PatternDetectionService().detect(
                knowledge_graph,
                java_architecture_graphs=java_architecture_graphs,
                call_graphs=call_graphs,
            )
            scope.add_units(len(knowledge_graph.nodes))
            scope.add_objects_produced(len(patterns.findings))
            scope.set_objects_retained(len(patterns.findings))
            context_data["design_patterns"] = patterns.to_dict()
            del patterns
        with self.measurement.scope(
            MeasurementPhase.REACHABILITY,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            reachability = ReachabilityAnalysisService().analyze(
                knowledge_graph,
                symbol_metadata=context_data["symbols"],
                repository_summary=context_data["repository_summary"],
                call_graphs=call_graphs,
            )
            scope.add_units(len(knowledge_graph.nodes))
            scope.add_objects_produced(
                len(reachability.roots) + len(reachability.findings)
            )
            scope.set_objects_retained(
                len(reachability.roots) + len(reachability.findings)
            )
        context_data["reachability"] = reachability.to_dict(grouped=True)
        with self.measurement.scope(
            MeasurementPhase.RISK,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            risk_service = RiskAnalysisService()
            git_history = None
            try:
                git_history = GitContextService(
                    self.service.workspace.root
                ).collect_history(
                    commit_limit=risk_service.configuration.git_commit_limit
                )
            except (GitContextError, OSError):
                pass
            risk_analysis = risk_service.analyze(
                knowledge_graph,
                symbol_metadata=context_data["symbols"],
                repository_summary=context_data["repository_summary"],
                git_history=git_history,
            )
            scope.add_units(risk_analysis.analyzed_subject_count)
            scope.add_objects_produced(len(risk_analysis.hotspots))
            scope.set_objects_retained(len(risk_analysis.hotspots))
            context_data["risk_analysis"] = risk_analysis.to_dict()
            del risk_analysis
        with self.measurement.scope(
            MeasurementPhase.REPOSITORY_REPORT,
            consumer="semantic-collector",
            sample_key="workspace",
        ) as scope:
            repository_report = RepositoryReportService().build(
                context_data,
                graph_digest=knowledge_graph.stable_digest(),
                knowledge_graph=knowledge_graph,
            )
            scope.add_units(len(repository_report.sections))
            scope.add_objects_produced(
                len(repository_report.sections) + len(repository_report.items)
            )
            scope.set_objects_retained(
                len(repository_report.sections) + len(repository_report.items)
            )
            context_data["repository_report"] = repository_report.to_dict()
            del repository_report
        context = WorkspaceSemanticContext(context_data)
        collection = SemanticCollectionReport(
            tuple(run.project for run in report.runs),
            sum(len(items) for items in diagnostics.values()),
            len(snapshot),
            len(types),
        )
        return CollectedSemanticContext(context, collection)

    def _collect_result(
        self,
        project: str,
        value: object,
        diagnostics: dict[str, list[Diagnostic]],
        types: dict[str, TypeTable],
        symbols: GlobalSymbolDatabase,
        java_architecture_graphs: dict[str, JavaArchitectureGraph],
        call_graphs: dict[str, CallGraph],
        security_producer_reports: list[SecurityProducerReport],
    ) -> bool:
        if isinstance(value, SemanticDocument):
            diagnostics.setdefault(project, []).extend(value.diagnostics)
            if len(value.types):
                types[project] = value.types
            architecture = value.get_artifact("java_architecture_graph")
            if isinstance(architecture, JavaArchitectureGraph):
                java_architecture_graphs[project] = architecture
            call_graph = value.get_artifact("call_graph")
            if isinstance(call_graph, CallGraph):
                call_graphs[project] = call_graph
            security_report = value.get_artifact("security_producer_report")
            if isinstance(security_report, SecurityProducerReport):
                security_producer_reports.append(security_report)
            raw_symbols = value.get_artifact("global_symbols")
            if raw_symbols is not None:
                self._add_unique(symbols, raw_symbols)
                return True
            return False
        raw_diagnostics = self._field(value, "diagnostics")
        if raw_diagnostics is not None:
            for item in raw_diagnostics:
                if isinstance(item, Diagnostic):
                    diagnostics.setdefault(project, []).append(item)
        raw_types = self._field(value, "types")
        if isinstance(raw_types, TypeTable) and len(raw_types):
            types[project] = raw_types
        raw_symbols = self._field(value, "symbols")
        raw_security_report = self._field(value, "security_producer_report")
        if isinstance(raw_security_report, SecurityProducerReport):
            security_producer_reports.append(raw_security_report)
        if raw_symbols is not None:
            self._add_unique(symbols, raw_symbols)
            return True
        return False

    def _collect_java_sources(
        self,
        diagnostics: dict[str, list[Diagnostic]],
        symbols: GlobalSymbolDatabase,
        *,
        skip: set[str],
    ) -> None:
        service = JavaSymbolService()
        builder = GlobalSymbolDatabaseBuilder()
        for project in sorted(self.service.workspace.projects, key=lambda item: item.name):
            if project.name in skip:
                continue
            for path in self._java_files(
                project.path,
                project.include,
                project.exclude,
                sample_key=project.name,
            ):
                try:
                    source = path.read_text(encoding="utf-8-sig")
                    if self.measurement.filesystem.enabled:
                        self.measurement.filesystem.file_content_read_unknown_size(
                            "semantic-collector",
                            path,
                        )
                        self.measurement.filesystem.language_parsed(
                            "semantic-collector"
                        )
                    try:
                        index = service.index_sources({path: source})
                    finally:
                        del source
                    self._add_unique(symbols, builder.build(index).snapshot().symbols)
                except (OSError, UnicodeError, ValueError) as exc:
                    diagnostics.setdefault(project.name, []).append(
                        Diagnostic(
                            "ATLAS-JAVA-PARSE",
                            str(exc),
                            DiagnosticSeverity.ERROR,
                            location=path,
                            pass_name="semantic-context-collector",
                        )
                    )

    def _java_files(
        self,
        root: Path,
        include: tuple[str, ...],
        exclude: tuple[str, ...],
        *,
        sample_key: str = "semantic-collector",
    ) -> tuple[Path, ...]:
        paths = tuple(
            path
            for path in project_files(
                root,
                include,
                exclude,
                measurement=self.measurement,
                consumer="semantic-collector",
                sample_key=sample_key,
            )
            if path.suffix.lower() == ".java"
        )
        selected, _excluded_data = select_compiled_java_sources(root, paths)
        return selected

    @staticmethod
    def _field(value: object, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

    @staticmethod
    def _add_unique(database: GlobalSymbolDatabase, values: Iterable[object]) -> None:
        for symbol in values:
            if (
                isinstance(symbol, GlobalSymbol)
                and database.get(symbol.id) is None
            ):
                database.add(symbol)
