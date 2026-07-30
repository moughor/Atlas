from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolDatabase
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_symbols import JavaSymbolService
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable
from moughorai.workspace import WorkspaceRunReport, WorkspaceService
from moughorai.workspace.files import project_files
from moughorai.dependency_intelligence import DeclaredDependency
from moughorai.repository_summary import RepositorySummaryService

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

    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def collect(self, report: WorkspaceRunReport) -> CollectedSemanticContext:
        if not report.succeeded:
            raise ValueError("semantic context requires a successful workspace analysis")
        diagnostics: dict[str, list[Diagnostic]] = {}
        types: dict[str, TypeTable] = {}
        symbols = GlobalSymbolDatabase()
        projects_with_symbols: set[str] = set()
        declared_dependencies: list[DeclaredDependency] = []
        for run in report.runs:
            if isinstance(run.value, SemanticDocument):
                declared_dependencies.extend(
                    item for item in run.value.get_artifact("declared_dependencies", ())
                    if isinstance(item, DeclaredDependency)
                )
            if self._collect_result(run.project, run.value, diagnostics, types, symbols):
                projects_with_symbols.add(run.project)
        self._collect_java_sources(diagnostics, symbols, skip=projects_with_symbols)
        snapshot = symbols.snapshot()
        context = WorkspaceContextBuilder().build(
            self.service.workspace,
            diagnostics=diagnostics,
            symbols=snapshot.symbols,
            types=types,
            declared_dependencies=declared_dependencies,
            repository_summary=RepositorySummaryService(self.service).build(),
        )
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
    ) -> bool:
        if isinstance(value, SemanticDocument):
            diagnostics.setdefault(project, []).extend(value.diagnostics)
            if len(value.types):
                types[project] = value.types
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
            for path in self._java_files(project.path, project.include, project.exclude):
                try:
                    index = service.index_sources({path: path.read_text(encoding="utf-8-sig")})
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

    @staticmethod
    def _java_files(
        root: Path,
        include: tuple[str, ...],
        exclude: tuple[str, ...],
    ) -> tuple[Path, ...]:
        return tuple(path for path in project_files(root, include, exclude) if path.suffix.lower() == ".java")

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
                and database.by_qualified_name(symbol.qualified_name, symbol.project_id) is None
            ):
                database.add(symbol)
