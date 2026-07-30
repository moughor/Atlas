from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from moughorai.global_symbols import GlobalSymbol
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.global_symbols.models import SymbolId
from moughorai.java_ast import JavaParser
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.python_semantics import PythonSemanticAnalyzer
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable
from moughorai.workspace import Project
from moughorai.workspace.files import project_files


class LanguageAnalyzer(Protocol):
    """Plugin contract for one language frontend."""

    language: str
    extensions: tuple[str, ...]

    def analyze(
        self,
        project: Project,
        paths: tuple[Path, ...],
        dependencies: Mapping[str, Any],
    ) -> SemanticDocument: ...


@dataclass(frozen=True, slots=True)
class AnalyzerRegistration:
    language: str
    extensions: tuple[str, ...]
    analyzer: LanguageAnalyzer


class AnalyzerRegistry:
    """Route project files to independently replaceable language analyzers."""

    def __init__(self, analyzers: tuple[LanguageAnalyzer, ...] | None = None) -> None:
        self._lock = RLock()
        self._by_language: dict[str, AnalyzerRegistration] = {}
        self._by_extension: dict[str, str] = {}
        selected = analyzers if analyzers is not None else (JavaLanguageAnalyzer(), PythonLanguageAnalyzer())
        for analyzer in selected:
            self.register(analyzer)

    def register(self, analyzer: LanguageAnalyzer, *, replace: bool = False) -> None:
        language = analyzer.language.strip().lower()
        extensions = tuple(sorted({_normalize_extension(item) for item in analyzer.extensions}))
        if not language:
            raise ValueError("analyzer language must not be empty")
        if not extensions:
            raise ValueError(f"analyzer {language!r} must declare at least one extension")
        with self._lock:
            if language in self._by_language and not replace:
                raise ValueError(f"analyzer already registered: {language}")
            conflicts = {
                extension: owner
                for extension in extensions
                if (owner := self._by_extension.get(extension)) not in (None, language)
            }
            if conflicts and not replace:
                extension, owner = sorted(conflicts.items())[0]
                raise ValueError(f"extension {extension!r} already registered by {owner!r}")
            previous = self._by_language.get(language)
            if previous is not None:
                for extension in previous.extensions:
                    self._by_extension.pop(extension, None)
            registration = AnalyzerRegistration(language, extensions, analyzer)
            self._by_language[language] = registration
            for extension in extensions:
                self._by_extension[extension] = language

    def registrations(self) -> tuple[AnalyzerRegistration, ...]:
        with self._lock:
            return tuple(self._by_language[key] for key in sorted(self._by_language))

    def analyzer_for(self, path: Path | str) -> LanguageAnalyzer | None:
        extension = Path(path).suffix.casefold()
        with self._lock:
            language = self._by_extension.get(extension)
            return self._by_language[language].analyzer if language is not None else None

    def __call__(self, project: Project, dependencies: Mapping[str, Any]) -> SemanticDocument:
        files = project_files(project.path, project.include, project.exclude)
        grouped: dict[str, list[Path]] = {}
        registrations = self.registrations()
        by_extension = {
            extension: registration.language
            for registration in registrations
            for extension in registration.extensions
        }
        for path in files:
            language = by_extension.get(path.suffix.casefold())
            if language is not None:
                grouped.setdefault(language, []).append(path)

        documents = [
            registration.analyzer.analyze(
                project,
                tuple(grouped[registration.language]),
                dependencies,
            )
            for registration in registrations
            if grouped.get(registration.language)
        ]
        return self._merge(project, dependencies, files, documents)

    @staticmethod
    def _merge(
        project: Project,
        dependencies: Mapping[str, Any],
        files: tuple[Path, ...],
        documents: list[SemanticDocument],
    ) -> SemanticDocument:
        languages = tuple(document.language for document in documents)
        symbols = tuple(
            symbol
            for document in documents
            for symbol in document.get_artifact("global_symbols", ())
        )
        type_builder = TypeTable().to_builder()
        for document in documents:
            type_builder.update(document.types.entries)
        merged = SemanticDocument(
            language=languages[0] if len(languages) == 1 else ("mixed" if languages else "workspace"),
            source="",
            syntax_tree=tuple(
                node
                for document in documents
                for node in (
                    document.syntax_tree
                    if isinstance(document.syntax_tree, tuple)
                    else (document.syntax_tree,)
                )
            ),
            metadata={
                "project": project.name,
                "files": len(files),
                "dependencies": tuple(sorted(dependencies)),
                "semantic_pipeline": "atlas",
            },
        )
        merged = merged.with_artifact("global_symbols", symbols)
        merged = merged.with_artifact("types", type_builder.build())
        for document in documents:
            for name, value in document.artifacts.items():
                if name not in ("global_symbols", "types"):
                    merged = merged.with_artifact(name, value)
        return merged.with_diagnostics(
            diagnostic for document in documents for diagnostic in document.diagnostics
        )


class JavaLanguageAnalyzer:
    language = "java"
    extensions = (".java",)

    def __init__(
        self,
        parser: JavaParser | None = None,
        symbol_builder: JavaSymbolIndexBuilder | None = None,
        global_builder: GlobalSymbolDatabaseBuilder | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._global_builder = global_builder or GlobalSymbolDatabaseBuilder()

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        units: list[object] = []
        sources: list[Path] = []
        diagnostics: list[Diagnostic] = []
        for path in paths:
            try:
                units.append(self._parser.parse_source(path.read_text(encoding="utf-8-sig")))
                sources.append(path)
            except (OSError, UnicodeError, ValueError) as exc:
                diagnostics.append(Diagnostic(
                    "ATLAS-JAVA-PARSE", str(exc), DiagnosticSeverity.ERROR,
                    location=path, pass_name="java-language-analyzer",
                ))
        index = self._symbol_builder.build(tuple(units), tuple(sources), project_id=project.name)
        symbols = _scope_symbols(self._global_builder.build(index).snapshot().symbols, project.name)
        document = SemanticDocument("java", "", tuple(units))
        return document.with_artifact("global_symbols", symbols).with_diagnostics(diagnostics)


class PythonLanguageAnalyzer:
    language = "python"
    extensions = (".py", ".pyi")

    def __init__(self, analyzer: PythonSemanticAnalyzer | None = None) -> None:
        self._analyzer = analyzer or PythonSemanticAnalyzer()

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        result = self._analyzer.analyze(project.path, paths)
        document = SemanticDocument("python", "", result.modules)
        document = document.with_artifact(
            "global_symbols", _scope_symbols(result.symbols, project.name),
        )
        document = document.with_artifact("python_modules", result.modules)
        document = document.with_artifact("types", result.types)
        return document.with_diagnostics(result.diagnostics)


def _normalize_extension(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError("analyzer extension must not be empty")
    return normalized if normalized.startswith(".") else f".{normalized}"


def _scope_symbols(symbols: tuple[GlobalSymbol, ...], project_id: str) -> tuple[GlobalSymbol, ...]:
    ids = {
        symbol.id: SymbolId.from_parts(symbol.kind, symbol.qualified_name, project_id)
        for symbol in symbols
    }
    return tuple(
        GlobalSymbol(
            ids[symbol.id], symbol.kind, symbol.name, symbol.qualified_name,
            ids.get(symbol.owner_id), symbol.source, symbol.metadata, project_id,
        )
        for symbol in symbols
    )
