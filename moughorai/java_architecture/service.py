"""High-level service for parsing sources into an architecture graph."""

from __future__ import annotations

from pathlib import Path

from moughorai.java_architecture.builder import JavaArchitectureGraphBuilder
from moughorai.java_architecture.graph import JavaArchitectureGraph
from moughorai.java_ast.parser import JavaParser
from moughorai.java_resolution.resolver import JavaTypeResolver
from moughorai.java_resolution.service import JavaTypeResolutionService
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder


class JavaArchitectureService:
    def __init__(
        self,
        parser: JavaParser | None = None,
        symbol_builder: JavaSymbolIndexBuilder | None = None,
        graph_builder: JavaArchitectureGraphBuilder | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._symbol_builder = symbol_builder or JavaSymbolIndexBuilder()
        self._graph_builder = graph_builder or JavaArchitectureGraphBuilder()

    def analyze_sources(self, sources: dict[Path, str]) -> JavaArchitectureGraph:
        paths = tuple(sources)
        units = tuple(self._parser.parse_source(sources[path]) for path in paths)
        index = self._symbol_builder.build(units, paths)
        resolver = JavaTypeResolver(index)
        resolution_service = JavaTypeResolutionService(resolver)
        references = tuple(
            reference
            for unit in units
            for reference in resolution_service.resolve_unit(unit)
        )
        return self._graph_builder.build(index, references)
