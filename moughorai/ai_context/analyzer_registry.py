from __future__ import annotations

from collections.abc import Mapping, Sized
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
from moughorai.java_symbols import (
    DuplicateTypeError,
    JavaSymbolIndex,
    MethodSymbol,
    SymbolKind,
)
from moughorai.java_workspace import JavaWorkspaceScanner, SourceRootKind
from moughorai.java_workspace.source_selection import (
    select_compiled_java_sources,
)
from moughorai.measurement import MeasurementPhase, MeasurementSession
from moughorai.python_semantics import PythonSemanticAnalyzer
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable
from moughorai.workspace import GRADLE_SETTINGS_MEMBERSHIP_OPTION, Project
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

    def __init__(
        self,
        analyzers: tuple[LanguageAnalyzer, ...] | None = None,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self._lock = RLock()
        self._by_language: dict[str, AnalyzerRegistration] = {}
        self._by_extension: dict[str, str] = {}
        self.measurement = measurement or MeasurementSession()
        selected = analyzers if analyzers is not None else (
            JavaLanguageAnalyzer(measurement=self.measurement),
            PythonLanguageAnalyzer(measurement=self.measurement),
            TypeScriptLanguageAnalyzer(measurement=self.measurement),
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
        files = project_files(
            project.path,
            project.include,
            project.exclude,
            measurement=self.measurement,
            consumer="analyzer-registry",
            sample_key=project.name,
        )
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

        documents = []
        for registration in registrations:
            paths = tuple(grouped.get(registration.language, ()))
            if not paths:
                continue
            with self.measurement.scope(
                self._language_phase(registration.language),
                consumer="analyzer-registry",
                sample_key=project.name,
            ) as scope:
                document = registration.analyzer.analyze(
                    project,
                    paths,
                    dependencies,
                )
                scope.add_units(len(paths))
                global_symbols = document.get_artifact("global_symbols", ())
                scope.add_objects_produced(
                    len(global_symbols) if isinstance(global_symbols, Sized) else 0
                )
                documents.append(document)
        with self.measurement.scope(
            MeasurementPhase.SYMBOL_EXTRACTION,
            consumer="analyzer-registry",
            sample_key=project.name,
        ) as scope:
            merged = self._merge(project, dependencies, files, documents)
            merged_symbols = merged.get_artifact("global_symbols", ())
            scope.add_units(len(documents))
            scope.add_objects_produced(len(merged_symbols))
            scope.set_objects_retained(len(merged_symbols))
        return merged.with_artifact(
            "declared_dependencies",
            DependencyIntelligenceService(measurement=self.measurement).analyze(
                project.path,
                files,
                sample_key=project.name,
            ),
        )

    @staticmethod
    def _language_phase(language: str) -> MeasurementPhase | str:
        return {
            "java": MeasurementPhase.JAVA_PARSING,
            "kotlin": MeasurementPhase.KOTLIN_PARSING,
            "python": MeasurementPhase.PYTHON_PARSING,
            "typescript": "language.typescript.parsing",
        }.get(language, "language.other.parsing")

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
        workspace_scanner: JavaWorkspaceScanner | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._global_builder = global_builder or GlobalSymbolDatabaseBuilder()
        self._architecture = architecture or JavaArchitectureService()
        self._workspace_scanner = workspace_scanner or JavaWorkspaceScanner()
        self.measurement = measurement or MeasurementSession()

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        maven_project = (project.path / "pom.xml").is_file()
        gradle_project = any(
            (project.path / filename).is_file()
            for filename in (
                "build.gradle",
                "build.gradle.kts",
                "settings.gradle",
                "settings.gradle.kts",
            )
        ) or bool(project.option_map.get(GRADLE_SETTINGS_MEMBERSHIP_OPTION))
        diagnostics: list[Diagnostic] = []
        paths, _excluded_data = select_compiled_java_sources(
            project.path,
            paths,
        )
        if maven_project:
            module = self._workspace_scanner.scan_module(project.path)
            source_roots = tuple(
                root.path.resolve()
                for root in module.source_roots
                if root.language == "java" and root.kind is not SourceRootKind.RESOURCE
            )
            selected_paths: list[Path] = []
            for path in paths:
                resolved_path = path.resolve()
                if any(resolved_path.is_relative_to(root) for root in source_roots):
                    selected_paths.append(path)
            paths = tuple(selected_paths)
        elif gradle_project:
            paths, shadowed_variants = _without_shadowed_gradle_variants(
                project.path,
                paths,
            )
            if shadowed_variants:
                location = shadowed_variants[0].resolve().relative_to(
                    project.path.resolve()
                )
                diagnostics.append(Diagnostic(
                    "ATLAS-JAVA-SOURCE-VARIANT",
                    f"{len(shadowed_variants)} version-specific Gradle Java "
                    "source file(s) shadow matching baseline paths; source-set "
                    "variant semantics are not modeled",
                    DiagnosticSeverity.WARNING,
                    location=location,
                    pass_name="java-language-analyzer",
                ))
        units: list[object] = []
        sources: list[Path] = []
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8-sig")
                if self.measurement.filesystem.enabled:
                    self.measurement.filesystem.file_content_read_unknown_size(
                        "java-analyzer",
                        path,
                    )
                    self.measurement.filesystem.language_parsed("java-analyzer")
                try:
                    unit = self._parser.parse_source(source)
                finally:
                    del source
                units.append(unit)
                sources.append(path)
            except (OSError, UnicodeError, ValueError) as exc:
                diagnostics.append(Diagnostic(
                    "ATLAS-JAVA-PARSE", str(exc), DiagnosticSeverity.ERROR,
                    location=path, pass_name="java-language-analyzer",
                ))
        with self.measurement.scope(
            MeasurementPhase.SYMBOL_EXTRACTION,
            consumer="java-analyzer",
            sample_key=project.name,
        ) as scope:
            try:
                index = self._symbol_builder.build(
                    tuple(units), tuple(sources), project_id=project.name,
                )
            except DuplicateTypeError as error:
                isolated = (
                    self._analyze_gradle_source_sets(
                        project,
                        tuple(units),
                        tuple(sources),
                        error,
                    )
                    if gradle_project
                    else None
                )
                if isolated is None:
                    raise
                isolated_units, symbols = isolated
                scope.add_units(len(isolated_units))
                scope.add_objects_produced(len(symbols))
                scope.set_objects_retained(len(symbols))
                diagnostics.append(Diagnostic(
                    "ATLAS-JAVA-SOURCE-SETS-PARTIAL",
                    f"Gradle project {project.name!r} contains conflicting types "
                    "in distinct conventional source sets; source sets were "
                    "analyzed independently and cross-source-set architecture "
                    "relations are unavailable",
                    DiagnosticSeverity.WARNING,
                    location=None,
                    pass_name="java-language-analyzer",
                ))
                return (
                    SemanticDocument("java", "", isolated_units)
                    .with_artifact("global_symbols", symbols)
                    .with_diagnostics(diagnostics)
                )
            symbols = _scope_symbols(
                self._global_builder.build(index).snapshot().symbols,
                project.name,
            )
            scope.add_units(len(units))
            scope.add_objects_produced(len(index.symbols) + len(symbols))
            scope.set_objects_retained(len(symbols))
        with self.measurement.scope(
            MeasurementPhase.ARCHITECTURE,
            consumer="java-analyzer",
            sample_key=project.name,
        ) as scope:
            architecture = self._architecture.build(index, tuple(units))
            scope.add_units(len(units))
            scope.add_objects_produced(len(architecture.nodes) + len(architecture.edges))
            scope.set_objects_retained(len(architecture.nodes) + len(architecture.edges))
        symbols = _with_java_relations(symbols, index, architecture)
        document = SemanticDocument("java", "", tuple(units))
        return (
            document
            .with_artifact("global_symbols", symbols)
            .with_artifact("java_architecture_graph", architecture)
            .with_diagnostics(diagnostics)
        )

    def _analyze_gradle_source_sets(
        self,
        project: Project,
        units: tuple[object, ...],
        sources: tuple[Path, ...],
        error: DuplicateTypeError,
    ) -> tuple[tuple[object, ...], tuple[GlobalSymbol, ...]] | None:
        """Recover only when conventional Gradle source-set evidence is exact."""
        first_scope = _gradle_java_source_set(project.path, error.first_source)
        second_scope = _gradle_java_source_set(project.path, error.second_source)
        if (
            first_scope is None
            or second_scope is None
            or first_scope == second_scope
        ):
            return None

        grouped: dict[str, list[tuple[Path, object]]] = {}
        for unit, source in zip(units, sources, strict=True):
            source_set = _gradle_java_source_set(project.path, source)
            if source_set is None:
                return None
            grouped.setdefault(source_set, []).append((source, unit))

        ordered_units: list[object] = []
        scoped_symbols: list[GlobalSymbol] = []
        for source_set in sorted(grouped):
            entries = sorted(
                grouped[source_set],
                key=lambda item: item[0].resolve().relative_to(
                    project.path.resolve()
                ).as_posix(),
            )
            scoped_sources = tuple(item[0] for item in entries)
            scoped_units = tuple(item[1] for item in entries)
            index = self._symbol_builder.build(
                scoped_units,
                scoped_sources,
                project_id=project.name,
            )
            scope_id = f"gradle-source-set:{source_set}"
            evidence = {
                "analysis_scope": source_set,
                "analysis_status": "partial",
                "architecture_relations": "unavailable",
                "source_scope_evidence": "conventional-gradle-source-set",
            }
            symbols = _scope_symbols(
                self._global_builder.build(index).snapshot().symbols,
                project.name,
                scope_id=scope_id,
                metadata=evidence,
            )
            scoped_symbols.extend(_with_java_relations(
                symbols,
                index,
                JavaArchitectureGraph(),
            ))
            ordered_units.extend(scoped_units)
        return tuple(ordered_units), tuple(scoped_symbols)


_VERSIONED_GRADLE_JAVA_PATH = re.compile(
    r"^src/(?:(?P<source_set_a>main|test)/java[1-9][0-9]*|"
    r"(?P<source_set_b>main|test)[1-9][0-9]*/java)/(?P<tail>.+)$"
)
_CONVENTIONAL_GRADLE_JAVA_PATH = re.compile(
    r"^src/(?P<source_set>[A-Za-z][A-Za-z0-9_-]*)/java/.+$"
)
_VERSIONED_GRADLE_SOURCE_SET = re.compile(r"^(?:main|test)[1-9][0-9]*$")


def _without_shadowed_gradle_variants(
    root: Path,
    paths: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Keep additive source sets while separating versioned path overlays."""
    project_root = root.resolve()
    eligible = {path.resolve() for path in paths}
    selected: list[Path] = []
    shadowed: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(project_root).as_posix()
        except ValueError:
            selected.append(path)
            continue
        match = _VERSIONED_GRADLE_JAVA_PATH.fullmatch(relative)
        if match is None:
            selected.append(path)
            continue
        source_set = match.group("source_set_a") or match.group("source_set_b")
        baseline = project_root / "src" / source_set / "java" / match.group("tail")
        if baseline.resolve() not in eligible:
            selected.append(path)
            continue
        shadowed.append(path)
    return tuple(selected), tuple(shadowed)


def _gradle_java_source_set(root: Path, source: object) -> str | None:
    if not isinstance(source, (str, Path)):
        return None
    try:
        relative = Path(source).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    match = _CONVENTIONAL_GRADLE_JAVA_PATH.fullmatch(relative)
    if match is None:
        return None
    source_set = match.group("source_set")
    if _VERSIONED_GRADLE_SOURCE_SET.fullmatch(source_set):
        return None
    return source_set


class PythonLanguageAnalyzer:
    language = "python"
    extensions = (".py", ".pyi")

    def __init__(
        self,
        analyzer: PythonSemanticAnalyzer | None = None,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.measurement = measurement or MeasurementSession()
        self._analyzer = analyzer or PythonSemanticAnalyzer(
            measurement=self.measurement,
        )

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        result = self._analyzer.analyze(project.path, paths)
        document = SemanticDocument("python", "", result.modules)
        with self.measurement.scope(
            MeasurementPhase.SYMBOL_EXTRACTION,
            consumer="python-analyzer",
            sample_key=project.name,
        ) as scope:
            symbols = _scope_symbols(result.symbols, project.name)
            scope.add_units(len(result.modules))
            scope.add_objects_produced(len(symbols))
            scope.set_objects_retained(len(symbols))
        document = document.with_artifact("global_symbols", symbols)
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

    def __init__(self, *, measurement: MeasurementSession | None = None) -> None:
        self.measurement = measurement or MeasurementSession()

    def analyze(self, project, paths, dependencies) -> SemanticDocument:
        symbols: list[GlobalSymbol] = []
        diagnostics: list[Diagnostic] = []
        modules: list[str] = []
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8-sig")
                if self.measurement.filesystem.enabled:
                    self.measurement.filesystem.file_content_read_unknown_size(
                        "typescript-analyzer",
                        path,
                    )
                    self.measurement.filesystem.language_parsed(
                        "typescript-analyzer"
                    )
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


def _scope_symbols(
    symbols: tuple[GlobalSymbol, ...],
    project_id: str,
    *,
    scope_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> tuple[GlobalSymbol, ...]:
    ids = {
        symbol.id: SymbolId.from_parts(
            symbol.kind,
            symbol.qualified_name,
            project_id,
            scope_id,
        )
        for symbol in symbols
    }
    return tuple(
        GlobalSymbol(
            ids[symbol.id], symbol.kind, symbol.name, symbol.qualified_name,
            ids.get(symbol.owner_id), symbol.source,
            tuple(sorted({**dict(symbol.metadata), **(metadata or {})}.items())),
            project_id, scope_id,
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
        (symbol.kind.value, symbol.qualified_name): symbol
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
        java_symbol = java_symbols.get((symbol.kind.value, symbol.qualified_name))
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
        inherited = (
            inheritance.get(symbol.qualified_name)
            if symbol.kind is GlobalSymbolKind.TYPE
            else None
        )
        overridden = (
            overrides.get(symbol.qualified_name)
            if symbol.kind is GlobalSymbolKind.METHOD
            else None
        )
        if inherited:
            metadata["inherits"] = ",".join(sorted(inherited))
        if overridden:
            metadata["overrides"] = ",".join(sorted(overridden))
        enriched.append(replace(symbol, metadata=tuple(sorted(metadata.items()))))
    return tuple(enriched)
