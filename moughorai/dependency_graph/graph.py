from __future__ import annotations
from collections import defaultdict,deque
from typing import Iterable
from moughorai.global_symbols import SymbolId
from .models import DependencyEdge,DependencyKind
class DependencyGraph:
    def __init__(self,edges:Iterable[DependencyEdge]=()):
        self._edges=set(edges); self._out=defaultdict(set); self._in=defaultdict(set)
        for e in self._edges: self._out[e.source].add(e); self._in[e.target].add(e)
    @property
    def edges(self): return tuple(sorted(self._edges,key=lambda e:(str(e.source),str(e.target),e.kind.value)))
    def add(self,e:DependencyEdge)->None:
        if e not in self._edges: self._edges.add(e); self._out[e.source].add(e); self._in[e.target].add(e)
    def outgoing(self,s:SymbolId,kind:DependencyKind|None=None): return tuple(sorted((e for e in self._out.get(s,()) if kind is None or e.kind is kind),key=lambda e:(str(e.target),e.kind.value)))
    def incoming(self,s:SymbolId,kind:DependencyKind|None=None): return tuple(sorted((e for e in self._in.get(s,()) if kind is None or e.kind is kind),key=lambda e:(str(e.source),e.kind.value)))
    def dependencies(self,s:SymbolId,transitive:bool=False)->tuple[SymbolId,...]: return self._walk(s,False,transitive)
    def dependents(self,s:SymbolId,transitive:bool=False)->tuple[SymbolId,...]: return self._walk(s,True,transitive)
    def _walk(self,start,reverse,transitive):
        seen=set(); q=deque([start])
        while q:
            cur=q.popleft(); edges=self._in.get(cur,()) if reverse else self._out.get(cur,())
            for e in edges:
                nxt=e.source if reverse else e.target
                if nxt not in seen and nxt!=start:
                    seen.add(nxt)
                    if transitive:q.append(nxt)
        return tuple(sorted(seen,key=str))
    def cycles(self)->tuple[tuple[SymbolId,...],...]:
        nodes={e.source for e in self._edges}|{e.target for e in self._edges}; index=0; stack=[]; on=set(); idx={}; low={}; out=[]
        def visit(v):
            nonlocal index
            idx[v]=low[v]=index; index+=1; stack.append(v); on.add(v)
            for e in self._out.get(v,()):
                w=e.target
                if w not in idx: visit(w); low[v]=min(low[v],low[w])
                elif w in on: low[v]=min(low[v],idx[w])
            if low[v]==idx[v]:
                comp=[]
                while True:
                    w=stack.pop(); on.remove(w); comp.append(w)
                    if w==v: break
                if len(comp)>1 or any(e.target==v for e in self._out.get(v,())): out.append(tuple(sorted(comp,key=str)))
        for n in sorted(nodes,key=str):
            if n not in idx: visit(n)
        return tuple(sorted(out,key=lambda c:tuple(map(str,c))))
