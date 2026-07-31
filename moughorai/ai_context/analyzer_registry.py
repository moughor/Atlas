from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import re
from threading import RLock
from typing import Any, Protocol

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.dependency_intelligence import DependencyIntelligenceService
from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.global_symbols.models import SymbolId
from moughorai.java_ast import JavaParser
from moughorai.java_architecture import (
    ArchitectureEdgeKind,
    JavaArchitectureGraph,
    JavaArchitectureService,
)
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.java_symbols import JavaSymbolIndex, MethodSymbol, SymbolKind
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
        selected = analyzers if analyzers is not None else (
            JavaLanguageAnalyzer(), PythonLanguageAnalyzer(), TypeScriptLanguageAnalyzer(),
        )
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
        merged = self._merge(project, dependencies, files, documents)
        return merged.with_artifact(
            "declared_dependencies",
            DependencyIntelligenceService().analyze(project.path, files),
        )

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
        architecture: JavaArchitectureService | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._global_builder = global_builder or GlobalSymbolDatabaseBuilder()
        self._architecture = architecture or JavaArchitectureService()

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
        architecture = self._architecture.build(index, tuple(units))
        symbols = _with_java_relations(symbols, index, architecture)
        document = SemanticDocument("java", "", tuple(units))
        return (
            document
            .with_artifact("global_symbols", symbols)
            .with_artifact("java_architecture_graph", architecture)
            .with_diagnostics(diagnostics)
        )


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


class TypeScriptLanguageAnalyzer:
    """Conservative declaration frontend for TypeScript/TSX repositories."""

    language = "typescript"
    extensions = (".ts", ".tsx")
    _IMPORT = re.compile(r"""(?m)^\s*import(?:.*?\sfrom\s*)?["']([^"']+)["']\s*;?""")
    _TYPE = re.compile(
        r"""(?m)^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"""
        r"""(class|interface|enum|type)\s+([A-Za-z_$][\w$]*)"""
    )
    _FUNCTION = re.compile(
        r"""(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"""
        r"""function\s+([A-Za-z_$][\w$]*)\s*\("""
    )

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        symbols: list[GlobalSymbol] = []
        diagnostics: list[Diagnostic] = []
        modules: list[str] = []
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(Diagnostic(
                    "ATLAS-TYPESCRIPT-PARSE", str(exc), DiagnosticSeverity.ERROR,
                    location=path, pass_name="typescript-language-analyzer",
                ))
                continue
            module = path.resolve().relative_to(project.path.resolve()).with_suffix("").as_posix()
            module = module.replace("/", ".")
            modules.append(module)
            imports = tuple(sorted(set(self._IMPORT.findall(source))))
            owner = GlobalSymbol.create(
                GlobalSymbolKind.PACKAGE,
                module.rsplit(".", 1)[-1],
                module,
                source=path,
                metadata={"language": "typescript", "imports": ",".join(imports)},
                project_id=project.name,
            )
            symbols.append(owner)
            for _, name in self._TYPE.findall(source):
                symbols.append(GlobalSymbol.create(
                    GlobalSymbolKind.TYPE, name, f"{module}.{name}",
                    owner_id=owner.id, source=path,
                    metadata={"language": "typescript"}, project_id=project.name,
                ))
            for name in self._FUNCTION.findall(source):
                symbols.append(GlobalSymbol.create(
                    GlobalSymbolKind.METHOD, name, f"{module}#{name}()",
                    owner_id=owner.id, source=path,
                    metadata={"language": "typescript"}, project_id=project.name,
                ))
        document = SemanticDocument("typescript", "", tuple(sorted(modules)))
        return document.with_artifact(
            "global_symbols",
            tuple(sorted(symbols, key=lambda item: (item.qualified_name, item.kind.value))),
        ).with_diagnostics(diagnostics)


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


def _with_java_relations(
    symbols: tuple[GlobalSymbol, ...],
    index: JavaSymbolIndex,
    architecture: JavaArchitectureGraph,
) -> tuple[GlobalSymbol, ...]:
    """Persist only resolved Java relations that survive recovery."""
    java_symbols = {
        symbol.qualified_name: symbol
        for symbol in index.symbols
    }
    inheritance: dict[str, set[str]] = {}
    parents: dict[str, set[str]] = {}
    for edge in architecture.edges:
        if edge.kind not in {
            ArchitectureEdgeKind.EXTENDS,
            ArchitectureEdgeKind.IMPLEMENTS,
        }:
            continue
        inheritance.setdefault(edge.source, set()).add(edge.target)
        parents.setdefault(edge.source, set()).add(edge.target)

    methods: dict[tuple[str, str, tuple[str, ...]], MethodSymbol] = {}
    for symbol in index.by_kind(SymbolKind.METHOD):
        if isinstance(symbol, MethodSymbol) and symbol.owner is not None:
            methods[(symbol.owner, symbol.name, symbol.parameter_types)] = symbol

    def ancestors(owner: str) -> tuple[str, ...]:
        seen: set[str] = set()
        pending = list(sorted(parents.get(owner, ())))
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            pending.extend(sorted(parents.get(current, ())))
        return tuple(sorted(seen))

    overrides: dict[str, set[str]] = {}
    for _, method in sorted(
        methods.items(),
        key=lambda item: item[1].qualified_name,
    ):
        if method.owner is None or "Override" not in method.annotations:
            continue
        for parent in ancestors(method.owner):
            target = methods.get((parent, method.name, method.parameter_types))
            if target is not None:
                overrides.setdefault(method.qualified_name, set()).add(
                    target.qualified_name
                )

    enriched = []
    for symbol in symbols:
        metadata = dict(symbol.metadata)
        java_symbol = java_symbols.get(symbol.qualified_name)
        if java_symbol is not None:
            modifiers = tuple(sorted(set(getattr(java_symbol, "modifiers", ()))))
            annotations = tuple(sorted(set(getattr(java_symbol, "annotations", ()))))
            if annotations:
                metadata["annotations"] = ",".join(annotations)
            metadata["visibility"] = next(
                (
                    value
                    for value in ("public", "protected", "private")
                    if value in modifiers
                ),
                "package",
            )
            if (
                isinstance(java_symbol, MethodSymbol)
                and java_symbol.name == "main"
                and java_symbol.return_type == "void"
                and {"public", "static"}.issubset(modifiers)
            ):
                metadata["entry_point"] = "java-main"
        inherited = inheritance.get(symbol.qualified_name)
        overridden = overrides.get(symbol.qualified_name)
        if inherited:
            metadata["inherits"] = ",".join(sorted(inherited))
        if overridden:
            metadata["overrides"] = ",".join(sorted(overridden))
        enriched.append(replace(symbol, metadata=tuple(sorted(metadata.items()))))
    return tuple(enriched)
