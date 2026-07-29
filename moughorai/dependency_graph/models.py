from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.global_symbols import SymbolId
class DependencyKind(str,Enum):
    CALLS='calls'; EXTENDS='extends'; IMPLEMENTS='implements'; USES='uses'; IMPORTS='imports'; ANNOTATED_BY='annotated_by'
@dataclass(frozen=True,order=True)
class DependencyEdge:
    source:SymbolId; target:SymbolId; kind:DependencyKind
