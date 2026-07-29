from __future__ import annotations
from collections import deque
from moughorai.global_symbols import GlobalSymbolDatabase, SymbolId
from moughorai.dependency_graph import DependencyGraph, DependencyKind
from .models import CrossReference, ReferencePath

class CrossReferenceService:
    def __init__(self, symbols: GlobalSymbolDatabase, graph: DependencyGraph):
        self._symbols = symbols
        self._graph = graph

    def outgoing(self, symbol_id: SymbolId, kind: DependencyKind | None = None) -> tuple[CrossReference, ...]:
        return self._materialize(self._graph.outgoing(symbol_id, kind))

    def incoming(self, symbol_id: SymbolId, kind: DependencyKind | None = None) -> tuple[CrossReference, ...]:
        return self._materialize(self._graph.incoming(symbol_id, kind))

    def callers(self, symbol_id: SymbolId, transitive: bool = False):
        return self._related(symbol_id, DependencyKind.CALLS, reverse=True, transitive=transitive)

    def callees(self, symbol_id: SymbolId, transitive: bool = False):
        return self._related(symbol_id, DependencyKind.CALLS, reverse=False, transitive=transitive)

    def implementations(self, symbol_id: SymbolId, transitive: bool = False):
        return self._related(symbol_id, DependencyKind.IMPLEMENTS, reverse=True, transitive=transitive)

    def subclasses(self, symbol_id: SymbolId, transitive: bool = False):
        return self._related(symbol_id, DependencyKind.EXTENDS, reverse=True, transitive=transitive)

    def shortest_path(self, source: SymbolId, target: SymbolId, kinds: set[DependencyKind] | None = None) -> ReferencePath | None:
        if source == target:
            symbol = self._symbols.get(source)
            return ReferencePath((symbol,), ()) if symbol else None
        queue = deque([source]); previous: dict[SymbolId, tuple[SymbolId, DependencyKind]] = {}; seen={source}
        while queue:
            current=queue.popleft()
            for edge in self._graph.outgoing(current):
                if kinds is not None and edge.kind not in kinds: continue
                if edge.target in seen: continue
                seen.add(edge.target); previous[edge.target]=(current, edge.kind)
                if edge.target == target:
                    ids=[target]; rel=[]; cursor=target
                    while cursor != source:
                        parent, kind=previous[cursor]; rel.append(kind); ids.append(parent); cursor=parent
                    ids.reverse(); rel.reverse()
                    symbols=tuple(self._symbols.get(x) for x in ids)
                    if any(x is None for x in symbols): return None
                    return ReferencePath(symbols, tuple(rel))
                queue.append(edge.target)
        return None

    def _related(self, symbol_id, kind, reverse, transitive):
        frontier=[symbol_id]; seen=set()
        while frontier:
            current=frontier.pop(0)
            edges=self._graph.incoming(current,kind) if reverse else self._graph.outgoing(current,kind)
            for edge in edges:
                nxt=edge.source if reverse else edge.target
                if nxt in seen: continue
                seen.add(nxt)
                if transitive: frontier.append(nxt)
        return tuple(x for x in (self._symbols.get(i) for i in sorted(seen,key=str)) if x is not None)

    def _materialize(self, edges):
        out=[]
        for edge in edges:
            source=self._symbols.get(edge.source); target=self._symbols.get(edge.target)
            if source is not None and target is not None: out.append(CrossReference(source,target,edge.kind))
        return tuple(out)
