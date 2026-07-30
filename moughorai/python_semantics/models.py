from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moughorai.global_symbols import GlobalSymbol
from moughorai.semantic import Diagnostic
from moughorai.semantic.types import TypeTable


@dataclass(frozen=True, slots=True)
class PythonModule:
    name: str
    source: Path
    imports: tuple[str, ...]
    docstring: str


@dataclass(frozen=True, slots=True)
class PythonAnalysisResult:
    modules: tuple[PythonModule, ...]
    symbols: tuple[GlobalSymbol, ...]
    types: TypeTable
    diagnostics: tuple[Diagnostic, ...]
