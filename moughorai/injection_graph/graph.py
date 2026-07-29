from __future__ import annotations
from collections import defaultdict,deque
from .models import InjectionEdge,UnresolvedInjection
class InjectionGraph:
    def __init__(self,edges=(),unresolved=()):
        self._edges=set(edges); self.unresolved=tuple(unresolved); self._out=defaultdict(set); self._in=defaultdict(set)
        for e in self._edges:self._out[e.owner].add(e);self._in[e.target].add(e)
    @property
    def edges(self):return tuple(sorted(self._edges))
    def dependencies(self,owner:str,transitive:bool=False):return self._walk(owner,False,transitive)
    def dependents(self,target:str,transitive:bool=False):return self._walk(target,True,transitive)
    def _walk(self,start,reverse,transitive):
        seen=set();q=deque([start])
        while q:
            cur=q.popleft();edges=self._in.get(cur,()) if reverse else self._out.get(cur,())
            for e in edges:
                nxt=e.owner if reverse else e.target
                if nxt not in seen and nxt!=start:
                    seen.add(nxt)
                    if transitive:q.append(nxt)
        return tuple(sorted(seen))
    def cycles(self):
        nodes={e.owner for e in self._edges}|{e.target for e in self._edges};out=[]
        for start in sorted(nodes):
            stack=[(start,(start,))]
            while stack:
                cur,path=stack.pop()
                for e in self._out.get(cur,()):
                    if e.target==start and len(path)>1: out.append(tuple(path))
                    elif e.target not in path: stack.append((e.target,path+(e.target,)))
        canon={min(tuple(c[i:]+c[:i]) for i in range(len(c))) for c in out}
        return tuple(sorted(canon))
