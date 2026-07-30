from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_ast import JavaParser
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.workspace import Project
from moughorai.workspace.files import project_files


class SemanticProjectAnalyzer:
    """Analyze one configured project into an immutable semantic document."""

    def __init__(
        self,
        parser: JavaParser | None = None,
        symbol_builder: JavaSymbolIndexBuilder | None = None,
        global_builder: GlobalSymbolDatabaseBuilder | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._global_builder = global_builder or GlobalSymbolDatabaseBuilder()

    def __call__(
        self,
        project: Project,
        dependencies: Mapping[str, Any],
    ) -> SemanticDocument:
        files = self._files(project)
        units: list[object] = []
        java_paths: list[Path] = []
        diagnostics: list[Diagnostic] = []
        for path in files:
            if path.suffix.lower() != ".java":
                continue
            try:
                units.append(self._parser.parse_source(path.read_text(encoding="utf-8-sig")))
                java_paths.append(path)
            except (OSError, UnicodeError, ValueError) as exc:
                diagnostics.append(
                    Diagnostic(
                        "ATLAS-JAVA-PARSE",
                        str(exc),
                        DiagnosticSeverity.ERROR,
                        location=path,
                        pass_name="semantic-project-analyzer",
                    )
                )

        index = self._symbol_builder.build(tuple(units), tuple(java_paths))
        symbols = self._global_builder.build(index).snapshot().symbols
        document = SemanticDocument(
            language="java" if java_paths else "workspace",
            source="",
            syntax_tree=tuple(units),
            metadata={
                "project": project.name,
                "files": len(files),
                "dependencies": tuple(sorted(dependencies)),
                "semantic_pipeline": "atlas",
            },
        )
        document = document.with_artifact("global_symbols", symbols)
        return document.with_diagnostics(diagnostics)

    @staticmethod
    def _files(project: Project) -> tuple[Path, ...]:
        return project_files(project.path, project.include, project.exclude)
