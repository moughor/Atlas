from pathlib import Path
from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.semantic_search import *

def gs(kind,name,q,source=None,owner=None): return GlobalSymbol.create(kind,name,q,source=source,owner_id=owner)
def setup():
 t=gs(GlobalSymbolKind.TYPE,'CustomerService','com.acme.CustomerService',Path('src/main/CustomerService.java'))
 m=gs(GlobalSymbolKind.METHOD,'createCustomer','com.acme.CustomerService#createCustomer',Path('src/main/CustomerService.java'),t.id)
 r=gs(GlobalSymbolKind.TYPE,'CustomerRepository','com.acme.CustomerRepository',Path('src/main/CustomerRepository.java'))
 x=gs(GlobalSymbolKind.TYPE,'Other','com.other.Other',Path('other/Other.java'))
 db=GlobalSymbolDatabase([t,m,r,x]); g=DependencyGraph([DependencyEdge(m.id,r.id,DependencyKind.CALLS),DependencyEdge(x.id,r.id,DependencyKind.USES)])
 return db,g,t,m,r,x

def test_exact_name_scores_highest():
 db,g,*_=setup(); h=SemanticSearchService(db,g).search(SemanticSearchQuery(text='CustomerService')); assert h[0].score==100
def test_case_insensitive():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery(text='customerservice')))>=1
def test_prefix_search():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery(text='Customer')))==3
def test_qualified_contains():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery(text='acme')))==3
def test_kind_filter():
 db,g,*_=setup(); h=SemanticSearchService(db,g).search(SemanticSearchQuery(kinds=frozenset({GlobalSymbolKind.METHOD}))); assert len(h)==1
def test_owner_filter():
 db,g,t,m,*_=setup(); assert SemanticSearchService(db,g).search(SemanticSearchQuery(owner_id=t.id))[0].symbol==m
def test_source_prefix():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery(source_prefix=Path('src/main'))))==3
def test_limit():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery(text='Customer',limit=1)))==1
def test_direct_relation():
 db,g,t,m,r,x=setup(); h=SemanticSearchService(db,g).search(SemanticSearchQuery(related_to=m.id)); assert h[0].symbol==r
def test_reverse_relation():
 db,g,t,m,r,x=setup(); h=SemanticSearchService(db,g).search(SemanticSearchQuery(related_to=r.id,reverse_relation=True)); assert {z.symbol for z in h}=={m,x}
def test_relation_kind_filter():
 db,g,t,m,r,x=setup(); h=SemanticSearchService(db,g).search(SemanticSearchQuery(related_to=r.id,reverse_relation=True,relation_kinds=frozenset({DependencyKind.CALLS}))); assert [z.symbol for z in h]==[m]
def test_transitive_relation():
 db,g,t,m,r,x=setup(); g.add(DependencyEdge(t.id,m.id,DependencyKind.USES)); h=SemanticSearchService(db,g).search(SemanticSearchQuery(related_to=t.id,transitive=True)); assert {z.symbol for z in h}=={m,r}
def test_missing_graph_returns_empty():
 db,g,t,*_=setup(); assert SemanticSearchService(db).search(SemanticSearchQuery(related_to=t.id))==()
def test_empty_query_returns_all():
 db,g,*_=setup(); assert len(SemanticSearchService(db,g).search(SemanticSearchQuery()))==4
def test_stable_order():
 db,g,*_=setup(); names=[x.symbol.qualified_name for x in SemanticSearchService(db,g).search(SemanticSearchQuery())]; assert names==sorted(names)
def test_reason_recorded():
 db,g,*_=setup(); assert 'exact-name' in SemanticSearchService(db,g).search(SemanticSearchQuery(text='CustomerService'))[0].reasons
