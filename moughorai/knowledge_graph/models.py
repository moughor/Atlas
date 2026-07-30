from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.global_symbols import SymbolId

class KnowledgeKind(str, Enum):
    SYMBOL='symbol'; CONCEPT='concept'; DOMAIN='domain'; CAPABILITY='capability'
    REPOSITORY='repository'; WORKSPACE='workspace'; PROJECT='project'
    PACKAGE='package'; MODULE='module'; TYPE='type'; METHOD='method'; FIELD='field'
    DEPENDENCY='dependency'; FRAMEWORK='framework'
    BUILD_SYSTEM='build_system'; BUILD_TARGET='build_target'

class KnowledgeRelation(str, Enum):
    REPRESENTS='represents'; BELONGS_TO='belongs_to'; PROVIDES='provides'; DEPENDS_ON='depends_on'; RELATED_TO='related_to'
    IMPORTS='imports'; INHERITS='inheritance'; COMPOSES='composition'; CALLS='calls'
    OVERRIDES='overrides'; MEMBER_OF='member_of'; OWNS='ownership'

@dataclass(frozen=True, order=True)
class KnowledgeNode:
    id: str
    kind: KnowledgeKind
    name: str
    symbol_id: SymbolId | None = None
    metadata: tuple[tuple[str,str], ...] = ()
    qualified_name: str | None = None
    project_id: str | None = None
    language: str = "unknown"

@dataclass(frozen=True, order=True)
class KnowledgeEdge:
    source: str
    target: str
    relation: KnowledgeRelation
    evidence: tuple[str, ...] = ()
