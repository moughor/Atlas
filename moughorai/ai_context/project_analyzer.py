from __future__ import annotations

from moughorai.global_symbols.builder import GlobalSymbolDatabaseBuilder
from moughorai.java_ast import JavaParser
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.python_semantics import PythonSemanticAnalyzer
from .analyzer_registry import AnalyzerRegistry, JavaLanguageAnalyzer, PythonLanguageAnalyzer


class SemanticProjectAnalyzer(AnalyzerRegistry):
    """Backward-compatible facade for the PR124 analyzer registry."""

    def __init__(
        self,
        parser: JavaParser | None = None,
        symbol_builder: JavaSymbolIndexBuilder | None = None,
        global_builder: GlobalSymbolDatabaseBuilder | None = None,
        python_analyzer: PythonSemanticAnalyzer | None = None,
    ) -> None:
        super().__init__(
            (
                JavaLanguageAnalyzer(parser, symbol_builder, global_builder),
                PythonLanguageAnalyzer(python_analyzer),
            )
        )
