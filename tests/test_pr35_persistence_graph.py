from moughorai.java_jpa import JpaAnalysisReport,JpaEntity,JpaRelation,JpaRelationKind
from moughorai.persistence_graph import *
def report(): return JpaAnalysisReport(entities=(JpaEntity('app.Order','orders',()),JpaEntity('app.Customer','customers',()),JpaEntity('app.Line','lines',())),relations=(JpaRelation('app.Order','customer',JpaRelationKind.MANY_TO_ONE,'Customer','app.Customer'),JpaRelation('app.Order','lines',JpaRelationKind.ONE_TO_MANY,'Line','app.Line')))
def graph(): return PersistenceGraphBuilder().build(report(),(('app.OrderRepository','app.Order','java.lang.Long'),),{('app.Order','lines'):{'cascades':(CascadeType.ALL,), 'fetch':FetchType.EAGER}})
def test_entities(): assert len(graph().entities)==3
def test_entity(): assert graph().entity('app.Order').table_name=='orders'
def test_relations(): assert len(graph().relations_for('app.Order'))==2
def test_incoming(): assert graph().incoming('app.Customer')[0].owner=='app.Order'
def test_repository(): assert graph().repositories_for('app.Order')[0].qualified_name=='app.OrderRepository'
def test_related_direct(): assert graph().related('app.Order')==('app.Customer','app.Line')
def test_related_transitive(): assert graph().related('app.Customer',True)==('app.Line','app.Order')
def test_cascade(): assert graph().cascade_targets('app.Order')==('app.Line',)
def test_no_remove_customer(): assert 'app.Customer' not in graph().cascade_targets('app.Order')
def test_impact_related(): assert graph().impact('app.Order').related_entities==('app.Customer','app.Line')
def test_impact_repository(): assert graph().impact('app.Order').repositories==('app.OrderRepository',)
def test_fetch_option(): assert [r for r in graph().relations if r.field_name=='lines'][0].fetch is FetchType.EAGER
def test_no_orphans(): assert graph().orphan_relations()==()
def test_orphan():
 r=PersistenceRelation('Missing','app.Order','x','many_to_one');assert PersistenceGraph(graph().entities,relations=(r,)).orphan_relations()==(r,)
def test_empty(): assert PersistenceGraph().entities==()
