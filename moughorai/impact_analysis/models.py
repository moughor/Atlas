from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from moughorai.global_symbols import GlobalSymbol, SymbolId
from moughorai.dependency_graph import DependencyKind

@dataclass(frozen=True)
class ImpactPath:
    symbols: tuple[SymbolId, ...]
    kinds: tuple[DependencyKind, ...]

@dataclass(frozen=True)
class ImpactedSymbol:
    symbol: GlobalSymbol
    distance: int
    path: ImpactPath

@dataclass(frozen=True)
class ImpactAnalysisReport:
    roots: tuple[GlobalSymbol, ...]
    impacted: tuple[ImpactedSymbol, ...]
    files: tuple[Path, ...]
    unresolved_ids: tuple[SymbolId, ...] = ()
