from moughorai.java_spring import SpringAnalysisReport,InjectionPoint,InjectionKind
from moughorai.spring_components import *
from moughorai.bean_resolution import *
from moughorai.injection_graph import *
def catalog():return ComponentCatalog((ComponentDefinition('app.A',ComponentKind.SERVICE,'a',('app.A',)),ComponentDefinition('app.B',ComponentKind.SERVICE,'b',('app.B',)),ComponentDefinition('app.C',ComponentKind.SERVICE,'c',('app.C',))))
def graph():
 report=SpringAnalysisReport(injections=(InjectionPoint('app.A','B','app.B',InjectionKind.CONSTRUCTOR,'A'),InjectionPoint('app.B','C','app.C',InjectionKind.FIELD,'c')))
 return InjectionGraphBuilder().build(report,BeanResolver(catalog()))
def test_edges():assert len(graph().edges)==2
def test_dependency():assert graph().dependencies('app.A')==('app.B',)
def test_transitive_dependencies():assert graph().dependencies('app.A',True)==('app.B','app.C')
def test_dependent():assert graph().dependents('app.C')==('app.B',)
def test_transitive_dependents():assert graph().dependents('app.C',True)==('app.A','app.B')
def test_constructor_kind():assert graph().edges[0].kind is InjectionEdgeKind.CONSTRUCTOR
def test_field_kind():assert graph().edges[1].kind is InjectionEdgeKind.FIELD
def test_member_name():assert graph().edges[1].member_name=='c'
def test_no_unresolved():assert graph().unresolved==()
def test_missing_unresolved():
 r=SpringAnalysisReport(injections=(InjectionPoint('app.A','Missing',None,InjectionKind.FIELD,'missing'),));g=InjectionGraphBuilder().build(r,BeanResolver(catalog()));assert len(g.unresolved)==1
def test_missing_status():
 r=SpringAnalysisReport(injections=(InjectionPoint('app.A','Missing',None,InjectionKind.FIELD,'missing'),));g=InjectionGraphBuilder().build(r,BeanResolver(catalog()));assert g.unresolved[0].status is BeanResolutionStatus.MISSING
def test_empty_graph():assert InjectionGraph().edges==()
def test_cycle():
 g=InjectionGraph((InjectionEdge('a','b',InjectionEdgeKind.FIELD,'b'),InjectionEdge('b','a',InjectionEdgeKind.FIELD,'a')));assert g.cycles()==(('a','b'),)
def test_acyclic():assert graph().cycles()==()
def test_edges_deterministic():assert graph().edges==graph().edges
