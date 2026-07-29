from __future__ import annotations
from collections import deque
from pathlib import Path
from moughorai.global_symbols import GlobalSymbolDatabase, SymbolId
from moughorai.dependency_graph import DependencyGraph, DependencyKind
from .models import ImpactAnalysisReport, ImpactedSymbol, ImpactPath

class ImpactAnalysisService:
    def __init__(self, symbols: GlobalSymbolDatabase, graph: DependencyGraph): self._symbols=symbols; self._graph=graph
    def analyze(self, roots, *, kinds: set[DependencyKind] | None=None, max_depth: int | None=None, include_roots: bool=False) -> ImpactAnalysisReport:
        root_ids=tuple(dict.fromkeys(roots)); resolved=[]; unresolved=[]
        for sid in root_ids:
            symbol=self._symbols.get(sid)
            (resolved if symbol is not None else unresolved).append(symbol if symbol is not None else sid)
        root_set={s.id for s in resolved}; queue=deque((s.id,0) for s in resolved); previous={}; distance={s.id:0 for s in resolved}
        while queue:
            current,depth=queue.popleft()
            if max_depth is not None and depth>=max_depth: continue
            for edge in self._graph.incoming(current):
                if kinds is not None and edge.kind not in kinds: continue
                nxt=edge.source
                if nxt in distance: continue
                distance[nxt]=depth+1; previous[nxt]=(current,edge.kind); queue.append((nxt,depth+1))
        impacted=[]
        for sid,dist in sorted(distance.items(),key=lambda x:(x[1],str(x[0]))):
            if sid in root_set and not include_roots: continue
            symbol=self._symbols.get(sid)
            if symbol is None: unresolved.append(sid); continue
            ids=[sid]; kinds_path=[]; cursor=sid
            while cursor not in root_set:
                parent,kind=previous[cursor]; kinds_path.append(kind); ids.append(parent); cursor=parent
            impacted.append(ImpactedSymbol(symbol,dist,ImpactPath(tuple(ids),tuple(kinds_path))))
        file_set={s.source for s in resolved if s.source is not None}
        file_set.update(x.symbol.source for x in impacted if x.symbol.source is not None)
        files=tuple(sorted(file_set,key=lambda p:p.as_posix().casefold()))
        return ImpactAnalysisReport(tuple(resolved),tuple(impacted),files,tuple(sorted(set(unresolved),key=str)))
