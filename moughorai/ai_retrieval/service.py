from __future__ import annotations
from moughorai.context_builder import ContextBuilder, ContextRequest
from .models import RetrievalRequest, RetrievalResult

class AIRetrievalService:
    def __init__(self,builder:ContextBuilder): self._builder=builder
    def retrieve(self,request:RetrievalRequest)->RetrievalResult:
        context=self._builder.build(ContextRequest(request.question,request.max_symbols,request.max_chars))
        citations=tuple(item.symbol.qualified_name for item in context.items)
        confidence=0.0 if not context.items else min(1.0,0.35+0.1*len(context.items))
        if context.truncated: confidence=max(0.0,confidence-0.1)
        return RetrievalResult(request.question,context,citations,round(confidence,2))
