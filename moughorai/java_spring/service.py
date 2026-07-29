"""High-level service for Spring semantic analysis."""
from __future__ import annotations
from pathlib import Path
from moughorai.java_ast.parser import JavaParser
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.java_spring.analyzer import SpringAnalyzer
from moughorai.java_spring.models import SpringAnalysisReport

class SpringAnalysisService:
    def __init__(self, parser=None, symbol_builder=None, analyzer=None):
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._analyzer = analyzer or SpringAnalyzer()

    def analyze_sources(self, sources: dict[Path, str]) -> SpringAnalysisReport:
        paths = tuple(sources)
        units = tuple(self._parser.parse_source(sources[path]) for path in paths)
        index = self._symbol_builder.build(units, paths)
        return self._analyzer.analyze(units, index, paths)
