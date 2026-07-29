from __future__ import annotations
from collections import defaultdict, deque
from .models import KnowledgeEdge, KnowledgeNode, KnowledgeRelation

class KnowledgeGraph:
    def __init__(self, nodes=(), edges=()):
        self._nodes={n.id:n for n in nodes}; self._edges=set(); self._out=defaultdict(set); self._in=defaultdict(set)
        for e in edges: self.add_edge(e)
    @property
    def nodes(self): return tuple(sorted(self._nodes.values()))
    @property
    def edges(self): return tuple(sorted(self._edges))
    def add_node(self,node): self._nodes[node.id]=node
    def get(self,node_id): return self._nodes.get(node_id)
    def add_edge(self,edge):
        self._edges.add(edge); self._out[edge.source].add(edge); self._in[edge.target].add(edge)
    def outgoing(self,node_id,relation=None): return tuple(sorted(e for e in self._out.get(node_id,()) if relation is None or e.relation is relation))
    def incoming(self,node_id,relation=None): return tuple(sorted(e for e in self._in.get(node_id,()) if relation is None or e.relation is relation))
    def neighborhood(self,node_id,depth=1):
        seen={node_id}; q=deque([(node_id,0)])
        while q:
            cur,d=q.popleft()
            if d>=depth: continue
            for e in (*self._out.get(cur,()),*self._in.get(cur,())):
                nxt=e.target if e.source==cur else e.source
                if nxt not in seen: seen.add(nxt); q.append((nxt,d+1))
        return tuple(self._nodes[x] for x in sorted(seen) if x in self._nodes)
