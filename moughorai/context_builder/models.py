from __future__ import annotations
from dataclasses import dataclass
from moughorai.global_symbols import GlobalSymbol

@dataclass(frozen=True)
class ContextRequest:
    query:str
    max_symbols:int=20
    max_chars:int=12000
    neighborhood_depth:int=1

@dataclass(frozen=True)
class ContextItem:
    symbol:GlobalSymbol
    score:int
    reasons:tuple[str,...]
    text:str

@dataclass(frozen=True)
class BuiltContext:
    query:str
    items:tuple[ContextItem,...]
    text:str
    truncated:bool
