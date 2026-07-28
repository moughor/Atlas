from __future__ import annotations
from dataclasses import dataclass
from moughorai.global_symbols import GlobalSymbol, SymbolId
from moughorai.dependency_graph import DependencyKind

@dataclass(frozen=True)
class CrossReference:
    source: GlobalSymbol
    target: GlobalSymbol
    kind: DependencyKind

@dataclass(frozen=True)
class ReferencePath:
    symbols: tuple[GlobalSymbol, ...]
    kinds: tuple[DependencyKind, ...]

    @property
    def length(self) -> int:
        return len(self.kinds)
