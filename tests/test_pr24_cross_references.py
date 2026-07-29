from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.cross_references import *

def s(q): return GlobalSymbol.create(GlobalSymbolKind.METHOD,q.rsplit('.',1)[-1],q)
def setup():
 a,b,c,i,impl,sub=map(s,['A.a','B.b','C.c','I.i','Impl.m','Sub.s'])
 db=GlobalSymbolDatabase([a,b,c,i,impl,sub])
 g=DependencyGraph([DependencyEdge(a.id,b.id,DependencyKind.CALLS),DependencyEdge(b.id,c.id,DependencyKind.CALLS),DependencyEdge(impl.id,i.id,DependencyKind.IMPLEMENTS),DependencyEdge(sub.id,impl.id,DependencyKind.EXTENDS)])
 return db,g,a,b,c,i,impl,sub

def test_outgoing():
 db,g,a,b,*_=setup(); assert CrossReferenceService(db,g).outgoing(a.id)[0].target==b
def test_incoming():
 db,g,a,b,*_=setup(); assert CrossReferenceService(db,g).incoming(b.id)[0].source==a
def test_callers_direct():
 db,g,a,b,*_=setup(); assert CrossReferenceService(db,g).callers(b.id)==(a,)
def test_callers_transitive():
 db,g,a,b,c,*_=setup(); assert set(CrossReferenceService(db,g).callers(c.id,True))=={a,b}
def test_callees_direct():
 db,g,a,b,*_=setup(); assert CrossReferenceService(db,g).callees(a.id)==(b,)
def test_callees_transitive():
 db,g,a,b,c,*_=setup(); assert set(CrossReferenceService(db,g).callees(a.id,True))=={b,c}
def test_implementations():
 db,g,a,b,c,i,impl,*_=setup(); assert CrossReferenceService(db,g).implementations(i.id)==(impl,)
def test_subclasses():
 db,g,a,b,c,i,impl,sub=setup(); assert CrossReferenceService(db,g).subclasses(impl.id)==(sub,)
def test_shortest_path():
 db,g,a,b,c,*_=setup(); p=CrossReferenceService(db,g).shortest_path(a.id,c.id); assert [x.qualified_name for x in p.symbols]==['A.a','B.b','C.c']
def test_shortest_path_length():
 db,g,a,b,c,*_=setup(); assert CrossReferenceService(db,g).shortest_path(a.id,c.id).length==2
def test_path_kind_filter():
 db,g,a,b,c,*_=setup(); assert CrossReferenceService(db,g).shortest_path(a.id,c.id,{DependencyKind.EXTENDS}) is None
def test_self_path():
 db,g,a,*_=setup(); assert CrossReferenceService(db,g).shortest_path(a.id,a.id).length==0
def test_missing_path():
 db,g,a,b,c,i,*_=setup(); assert CrossReferenceService(db,g).shortest_path(a.id,i.id) is None
def test_missing_symbols_are_ignored():
 db,g,a,*_=setup(); ghost=SymbolId.from_parts(GlobalSymbolKind.METHOD,'Ghost'); g.add(DependencyEdge(a.id,ghost,DependencyKind.CALLS)); assert CrossReferenceService(db,g).callees(a.id)==(setup()[3],)
def test_reference_kind_preserved():
 db,g,a,b,*_=setup(); assert CrossReferenceService(db,g).outgoing(a.id)[0].kind is DependencyKind.CALLS
