from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind, SymbolId
from moughorai.dependency_graph import DependencyKind

@dataclass(frozen=True)
class SemanticSearchQuery:
    text: str | None = None
    kinds: frozenset[GlobalSymbolKind] = frozenset()
    source_prefix: Path | None = None
    owner_id: SymbolId | None = None
    related_to: SymbolId | None = None
    relation_kinds: frozenset[DependencyKind] = frozenset()
    reverse_relation: bool = False
    transitive: bool = False
    limit: int | None = None

@dataclass(frozen=True)
class SemanticSearchHit:
    symbol: GlobalSymbol
    score: int
    reasons: tuple[str, ...]
