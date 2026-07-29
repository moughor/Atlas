from __future__ import annotations
from moughorai.global_symbols import GlobalSymbolDatabase
from moughorai.semantic_search import SemanticSearchService, SemanticSearchQuery
from moughorai.knowledge_graph import KnowledgeGraph
from .models import ContextRequest, ContextItem, BuiltContext

class ContextBuilder:
    def __init__(self,symbols:GlobalSymbolDatabase,search:SemanticSearchService,knowledge:KnowledgeGraph): self._symbols=symbols; self._search=search; self._knowledge=knowledge
    def build(self,request:ContextRequest)->BuiltContext:
        hits=list(self._search.search(SemanticSearchQuery(text=request.query,limit=request.max_symbols)))
        candidate={h.symbol.id:(h.symbol,h.score,h.reasons) for h in hits}
        for h in hits:
            for node in self._knowledge.neighborhood(str(h.symbol.id),request.neighborhood_depth):
                if node.symbol_id is None or node.symbol_id in candidate: continue
                s=self._symbols.get(node.symbol_id)
                if s: candidate[s.id]=(s,max(1,h.score-20),('knowledge-neighbor',))
        ranked=sorted(candidate.values(),key=lambda x:(-x[1],x[0].qualified_name))[:request.max_symbols]
        items=[]; chunks=[]; used=0; truncated=False
        for symbol,score,reasons in ranked:
            meta='; '.join(f'{k}={v}' for k,v in symbol.metadata)
            text=f'[{symbol.kind.value}] {symbol.qualified_name}' + (f' ({meta})' if meta else '')
            if used+len(text)+1>request.max_chars: truncated=True; break
            used+=len(text)+1; chunks.append(text); items.append(ContextItem(symbol,score,reasons,text))
        return BuiltContext(request.query,tuple(items),'\n'.join(chunks),truncated)
