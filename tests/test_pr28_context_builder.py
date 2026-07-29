from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.semantic_search import *
from moughorai.knowledge_graph import *
from moughorai.context_builder import *

def setup():
 a=GlobalSymbol.create(GlobalSymbolKind.TYPE,'OrderService','app.OrderService',metadata={'domain':'sales'}); b=GlobalSymbol.create(GlobalSymbolKind.TYPE,'Repo','app.Repo'); db=GlobalSymbolDatabase([a,b]); dg=DependencyGraph([DependencyEdge(a.id,b.id,DependencyKind.USES)]); kg=KnowledgeGraphBuilder().build(db,dg); return a,b,ContextBuilder(db,SemanticSearchService(db,dg),kg)
def test_exact_query(): a,b,c=setup(); assert c.build(ContextRequest('OrderService')).items[0].symbol==a
def test_includes_neighbor(): a,b,c=setup(); assert any(x.symbol==b for x in c.build(ContextRequest('OrderService')).items)
def test_depth_zero_excludes_neighbor(): a,b,c=setup(); assert all(x.symbol!=b for x in c.build(ContextRequest('OrderService',neighborhood_depth=0)).items)
def test_limit(): a,b,c=setup(); assert len(c.build(ContextRequest('app',max_symbols=1)).items)==1
def test_char_budget_truncates(): a,b,c=setup(); assert c.build(ContextRequest('app',max_chars=5)).truncated
def test_empty_query_matches_filters(): a,b,c=setup(); assert len(c.build(ContextRequest('')).items)==2
def test_text_contains_kind(): a,b,c=setup(); assert '[type]' in c.build(ContextRequest('OrderService')).text
def test_metadata_rendered(): a,b,c=setup(); assert 'domain=sales' in c.build(ContextRequest('OrderService')).text
def test_deterministic(): a,b,c=setup(); assert c.build(ContextRequest('app')).text==c.build(ContextRequest('app')).text
def test_unknown_query_empty(): a,b,c=setup(); assert c.build(ContextRequest('zzz')).items==()
def test_reasons_kept(): a,b,c=setup(); assert 'exact-name' in c.build(ContextRequest('OrderService')).items[0].reasons
def test_neighbor_reason(): a,b,c=setup(); assert any('knowledge-neighbor' in x.reasons for x in c.build(ContextRequest('OrderService')).items if x.symbol==b)
def test_score_positive(): a,b,c=setup(); assert c.build(ContextRequest('OrderService')).items[0].score>0
def test_query_preserved(): a,b,c=setup(); assert c.build(ContextRequest('abc')).query=='abc'
def test_no_truncation_normal(): a,b,c=setup(); assert not c.build(ContextRequest('OrderService')).truncated
