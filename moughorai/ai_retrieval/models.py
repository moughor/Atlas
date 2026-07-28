from __future__ import annotations
from dataclasses import dataclass
from moughorai.context_builder import BuiltContext

@dataclass(frozen=True)
class RetrievalRequest:
    question:str
    max_symbols:int=20
    max_chars:int=12000

@dataclass(frozen=True)
class RetrievalResult:
    question:str
    context:BuiltContext
    citations:tuple[str,...]
    confidence:float
