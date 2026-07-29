from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.global_symbols import SymbolId

class KnowledgeKind(str, Enum):
    SYMBOL='symbol'; CONCEPT='concept'; DOMAIN='domain'; CAPABILITY='capability'

class KnowledgeRelation(str, Enum):
    REPRESENTS='represents'; BELONGS_TO='belongs_to'; PROVIDES='provides'; DEPENDS_ON='depends_on'; RELATED_TO='related_to'

@dataclass(frozen=True, order=True)
class KnowledgeNode:
    id: str
    kind: KnowledgeKind
    name: str
    symbol_id: SymbolId | None = None
    metadata: tuple[tuple[str,str], ...] = ()

@dataclass(frozen=True, order=True)
class KnowledgeEdge:
    source: str
    target: str
    relation: KnowledgeRelation
    evidence: tuple[str, ...] = ()
