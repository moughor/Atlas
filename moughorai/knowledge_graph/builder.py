from __future__ import annotations
from moughorai.global_symbols import GlobalSymbolDatabase
from moughorai.dependency_graph import DependencyGraph
from .models import KnowledgeNode, KnowledgeEdge, KnowledgeKind, KnowledgeRelation
from .graph import KnowledgeGraph

class KnowledgeGraphBuilder:
    def build(self, symbols:GlobalSymbolDatabase, dependencies:DependencyGraph)->KnowledgeGraph:
        g=KnowledgeGraph()
        for s in symbols.symbols:
            g.add_node(KnowledgeNode(str(s.id),KnowledgeKind.SYMBOL,s.qualified_name,s.id,s.metadata))
            for key,value in s.metadata:
                if key in {'domain','capability'}:
                    kind=KnowledgeKind.DOMAIN if key=='domain' else KnowledgeKind.CAPABILITY
                    nid=f'{key}:{value.casefold()}'
                    g.add_node(KnowledgeNode(nid,kind,value))
                    rel=KnowledgeRelation.BELONGS_TO if key=='domain' else KnowledgeRelation.PROVIDES
                    g.add_edge(KnowledgeEdge(str(s.id),nid,rel,(f'metadata:{key}',)))
        for e in dependencies.edges:
            if g.get(str(e.source)) and g.get(str(e.target)):
                g.add_edge(KnowledgeEdge(str(e.source),str(e.target),KnowledgeRelation.DEPENDS_ON,(e.kind.value,)))
        return g
