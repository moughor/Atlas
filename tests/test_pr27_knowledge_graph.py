from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.knowledge_graph import *

def sym(name,meta=None): return GlobalSymbol.create(GlobalSymbolKind.TYPE,name.split('.')[-1],name,metadata=meta)
def test_build_symbol_nodes():
 a=sym('a.A'); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.get(str(a.id)).symbol_id==a.id
def test_metadata_domain_node():
 a=sym('a.A',{'domain':'Sales'}); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.get('domain:sales').name=='Sales'
def test_metadata_capability_node():
 a=sym('a.A',{'capability':'Billing'}); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.get('capability:billing')
def test_dependency_conversion():
 a,b=sym('a.A'),sym('a.B'); d=DependencyGraph([DependencyEdge(a.id,b.id,DependencyKind.CALLS)]); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a,b]),d); assert g.outgoing(str(a.id))[0].evidence==('calls',)
def test_neighborhood_depth_zero():
 a=sym('a.A'); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert len(g.neighborhood(str(a.id),0))==1
def test_neighborhood_depth_one():
 a,b=sym('a.A'),sym('a.B'); d=DependencyGraph([DependencyEdge(a.id,b.id,DependencyKind.USES)]); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a,b]),d); assert len(g.neighborhood(str(a.id),1))==2
def test_incoming():
 a=sym('a.A',{'domain':'Sales'}); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.incoming('domain:sales')[0].source==str(a.id)
def test_edges_deterministic():
 a=sym('a.A',{'domain':'Sales'}); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.edges==tuple(sorted(g.edges))
def test_duplicate_node_replaced():
 g=KnowledgeGraph(); n=KnowledgeNode('x',KnowledgeKind.CONCEPT,'X'); g.add_node(n); g.add_node(n); assert len(g.nodes)==1
def test_duplicate_edge_deduped():
 g=KnowledgeGraph(); e=KnowledgeEdge('a','b',KnowledgeRelation.RELATED_TO); g.add_edge(e); g.add_edge(e); assert len(g.edges)==1
def test_unknown_get_none(): assert KnowledgeGraph().get('missing') is None
def test_relation_filter():
 g=KnowledgeGraph(edges=[KnowledgeEdge('a','b',KnowledgeRelation.RELATED_TO),KnowledgeEdge('a','c',KnowledgeRelation.DEPENDS_ON)]); assert len(g.outgoing('a',KnowledgeRelation.RELATED_TO))==1
def test_symbol_metadata_preserved():
 a=sym('a.A',{'x':'y'}); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),DependencyGraph()); assert g.get(str(a.id)).metadata==( ('x','y'), )
def test_ignores_missing_dependency_endpoint():
 a,b=sym('a.A'),sym('a.B'); d=DependencyGraph([DependencyEdge(a.id,b.id,DependencyKind.USES)]); g=KnowledgeGraphBuilder().build(GlobalSymbolDatabase([a]),d); assert not g.edges
def test_empty_build(): assert KnowledgeGraphBuilder().build(GlobalSymbolDatabase(),DependencyGraph()).nodes==()
