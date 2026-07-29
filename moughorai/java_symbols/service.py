"""High-level Java source parsing and symbol indexing service."""

from __future__ import annotations

from pathlib import Path

from moughorai.java_ast.parser import JavaParser
from moughorai.java_symbols.builder import JavaSymbolIndexBuilder
from moughorai.java_symbols.index import JavaSymbolIndex


class JavaSymbolService:
    def __init__(
        self,
        parser: JavaParser | None = None,
        builder: JavaSymbolIndexBuilder | None = None,
    ) -> None:
        self._parser = parser or JavaParser()
        self._builder = builder or JavaSymbolIndexBuilder()

    def index_sources(self, sources: dict[Path, str]) -> JavaSymbolIndex:
        paths = tuple(sources)
        units = tuple(self._parser.parse_source(sources[path]) for path in paths)
        return self._builder.build(units, paths)
