from __future__ import annotations
from collections import defaultdict, deque
from collections.abc import Mapping
from moughorai.global_symbols import SymbolId
from .models import KnowledgeEdge, KnowledgeNode, KnowledgeRelation
from .models import KnowledgeKind

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
    def by_kind(self,kind): return tuple(node for node in self.nodes if node.kind is kind)
    def find(self,name): return tuple(node for node in self.nodes if node.name==name)
    def neighborhood(self,node_id,depth=1):
        seen={node_id}; q=deque([(node_id,0)])
        while q:
            cur,d=q.popleft()
            if d>=depth: continue
            for e in (*self._out.get(cur,()),*self._in.get(cur,())):
                nxt=e.target if e.source==cur else e.source
                if nxt not in seen: seen.add(nxt); q.append((nxt,d+1))
        return tuple(self._nodes[x] for x in sorted(seen) if x in self._nodes)
    def to_dict(self):
        return {
            'schema_version': 1,
            'nodes': [self._node_to_dict(node) for node in self.nodes],
            'edges': [
                {
                    'source': edge.source,
                    'target': edge.target,
                    'kind': edge.relation.value,
                    'evidence': list(edge.evidence),
                }
                for edge in self.edges
            ],
        }
    @staticmethod
    def _node_to_dict(node):
        metadata=dict(node.metadata)
        qualified_name=node.qualified_name or node.name
        payload={
            'id':node.id,
            'kind':node.kind.value,
            'qualified_name':qualified_name,
            'project_id':node.project_id,
            'language':node.language,
        }
        if node.name != qualified_name:
            payload['name']=node.name
        if node.symbol_id is not None and str(node.symbol_id) != node.id:
            payload['symbol_id']=str(node.symbol_id)
        if metadata:
            payload['metadata']=metadata
        return payload
    @classmethod
    def from_dict(cls,payload):
        if not isinstance(payload,Mapping): raise TypeError('graph payload must be a mapping')
        nodes=[]
        for item in payload.get('nodes',()):
            if not isinstance(item,Mapping): continue
            metadata=dict(item.get('metadata',{})) if isinstance(item.get('metadata'),Mapping) else {}
            raw_symbol=item.get('symbol_id')
            kind=KnowledgeKind(str(item.get('kind','symbol')))
            inferred_symbol=(
                kind in {
                    KnowledgeKind.SYMBOL,
                    KnowledgeKind.PACKAGE,
                    KnowledgeKind.TYPE,
                    KnowledgeKind.METHOD,
                    KnowledgeKind.FIELD,
                }
            )
            nodes.append(KnowledgeNode(
                str(item.get('id','')),
                kind,
                str(item.get('name') or item.get('qualified_name') or item.get('id','')),
                (
                    SymbolId(str(raw_symbol))
                    if raw_symbol is not None
                    else SymbolId(str(item.get('id',''))) if inferred_symbol
                    else None
                ),
                tuple(sorted((str(key),str(value)) for key,value in metadata.items())),
                str(item.get('qualified_name')) if item.get('qualified_name') is not None else None,
                str(item.get('project_id')) if item.get('project_id') is not None else None,
                str(item.get('language') or 'unknown'),
            ))
        edges=[]
        for item in payload.get('edges',()):
            if not isinstance(item,Mapping): continue
            edges.append(KnowledgeEdge(
                str(item.get('source','')),
                str(item.get('target','')),
                KnowledgeRelation(str(item.get('kind','related_to'))),
                tuple(map(str,item.get('evidence',()))),
            ))
        return cls(nodes,edges)
