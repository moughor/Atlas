from __future__ import annotations
from moughorai.global_symbols import GlobalSymbolDatabase
from moughorai.dependency_graph import DependencyGraph
from .models import SemanticSearchHit, SemanticSearchQuery

class SemanticSearchService:
    def __init__(self, symbols: GlobalSymbolDatabase, graph: DependencyGraph | None = None): self._symbols=symbols; self._graph=graph
    def search(self, query: SemanticSearchQuery) -> tuple[SemanticSearchHit, ...]:
        allowed=None
        if query.related_to is not None:
            if self._graph is None: return ()
            allowed=self._related(query)
        hits=[]; needle=(query.text or '').casefold().strip()
        for symbol in self._symbols.symbols:
            if query.kinds and symbol.kind not in query.kinds: continue
            if query.owner_id is not None and symbol.owner_id != query.owner_id: continue
            if query.source_prefix is not None and (symbol.source is None or not self._under(symbol.source,query.source_prefix)): continue
            if allowed is not None and symbol.id not in allowed: continue
            score=0; reasons=[]
            if needle:
                simple=symbol.name.casefold(); qualified=symbol.qualified_name.casefold()
                if simple==needle: score+=100; reasons.append('exact-name')
                elif qualified==needle: score+=95; reasons.append('exact-qualified-name')
                elif simple.startswith(needle): score+=70; reasons.append('name-prefix')
                elif needle in simple: score+=50; reasons.append('name-contains')
                elif needle in qualified: score+=30; reasons.append('qualified-name-contains')
                else: continue
            else: reasons.append('filters')
            hits.append(SemanticSearchHit(symbol,score,tuple(reasons)))
        hits.sort(key=lambda h:(-h.score,h.symbol.qualified_name,h.symbol.kind.value))
        return tuple(hits[:query.limit] if query.limit is not None else hits)
    def _related(self,q):
        if not q.relation_kinds:
            return set(self._graph.dependents(q.related_to,q.transitive) if q.reverse_relation else self._graph.dependencies(q.related_to,q.transitive))
        found=set(); frontier=[q.related_to]
        while frontier:
            cur=frontier.pop(0)
            edges=self._graph.incoming(cur) if q.reverse_relation else self._graph.outgoing(cur)
            for e in edges:
                if e.kind not in q.relation_kinds: continue
                nxt=e.source if q.reverse_relation else e.target
                if nxt not in found:
                    found.add(nxt)
                    if q.transitive: frontier.append(nxt)
        return found
    @staticmethod
    def _under(path,prefix):
        try: path.relative_to(prefix); return True
        except ValueError: return False
