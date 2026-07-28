from __future__ import annotations
from moughorai.java_spring import SpringAnalysisReport, SpringBeanKind
from .models import ComponentCatalog,ComponentDefinition,ComponentKind

_KIND={
 SpringBeanKind.COMPONENT:ComponentKind.COMPONENT, SpringBeanKind.SERVICE:ComponentKind.SERVICE,
 SpringBeanKind.REPOSITORY:ComponentKind.REPOSITORY, SpringBeanKind.CONTROLLER:ComponentKind.CONTROLLER,
 SpringBeanKind.REST_CONTROLLER:ComponentKind.REST_CONTROLLER, SpringBeanKind.CONFIGURATION:ComponentKind.CONFIGURATION,
}
def default_bean_name(qualified_name:str)->str:
    simple=qualified_name.rsplit('.',1)[-1]
    return simple[:1].lower()+simple[1:] if simple else simple

class SpringComponentAnalyzer:
    def analyze(self,report:SpringAnalysisReport)->ComponentCatalog:
        items=[]
        for bean in report.beans:
            annotations={a.rsplit('.',1)[-1] for a in bean.annotations}
            qualifiers=tuple(sorted(a.split(':',1)[1] for a in annotations if a.startswith('Qualifier:')))
            items.append(ComponentDefinition(bean.qualified_name,_KIND[bean.kind],default_bean_name(bean.qualified_name),(bean.qualified_name,),qualifiers,'Primary' in annotations,bean.source))
        return ComponentCatalog(tuple(sorted(items,key=lambda c:(c.bean_name,c.qualified_name))))
