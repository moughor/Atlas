from __future__ import annotations
from collections import defaultdict,deque
from .models import Propagation,TransactionBoundary,TransactionCall,TransactionFlow
class TransactionGraph:
    def __init__(self,boundaries=(),calls=()):
        self._boundaries={b.symbol:b for b in boundaries}; self._calls=tuple(sorted(set(calls))); self._out=defaultdict(set); self._in=defaultdict(set)
        for c in self._calls:self._out[c.caller].add(c.callee);self._in[c.callee].add(c.caller)
    @property
    def boundaries(self): return tuple(sorted(self._boundaries.values()))
    @property
    def calls(self): return self._calls
    def boundary(self,symbol): return self._boundaries.get(symbol)
    def callees(self,symbol,transitive=False): return self._walk(symbol,self._out,transitive)
    def callers(self,symbol,transitive=False): return self._walk(symbol,self._in,transitive)
    def _walk(self,start,graph,transitive):
        seen=set();q=deque([start])
        while q:
            cur=q.popleft()
            for nxt in graph.get(cur,()):
                if nxt not in seen and nxt!=start:
                    seen.add(nxt)
                    if transitive:q.append(nxt)
        return tuple(sorted(seen))
    def flow(self,root):
        symbols=[root]; suspended=[]; new=[]; seen={root};q=deque([root])
        while q:
            cur=q.popleft()
            for nxt in sorted(self._out.get(cur,())):
                if nxt in seen: continue
                seen.add(nxt);symbols.append(nxt);q.append(nxt)
                b=self._boundaries.get(nxt)
                if b and b.propagation in (Propagation.NOT_SUPPORTED,Propagation.NEVER): suspended.append(nxt)
                if b and b.propagation in (Propagation.REQUIRES_NEW,Propagation.NESTED): new.append(nxt)
        return TransactionFlow(root,tuple(symbols),tuple(suspended),tuple(new))
    def read_only_writes(self,write_symbols):
        writes=set(write_symbols);out=[]
        for boundary in self._boundaries.values():
            if boundary.read_only and (boundary.symbol in writes or any(x in writes for x in self.callees(boundary.symbol,True))): out.append(boundary.symbol)
        return tuple(sorted(out))
    def cycles(self):
        result=set()
        for start in sorted(set(self._out)|set(self._in)):
            stack=[(start,(start,))]
            while stack:
                cur,path=stack.pop()
                for nxt in self._out.get(cur,()):
                    if nxt==start and len(path)>1:
                        result.add(min(tuple(path[i:]+path[:i]) for i in range(len(path))))
                    elif nxt not in path: stack.append((nxt,path+(nxt,)))
        return tuple(sorted(result))
