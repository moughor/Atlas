from __future__ import annotations
from moughorai.java_spring import InjectionKind,SpringAnalysisReport
from moughorai.bean_resolution import BeanResolver,BeanResolutionRequest,BeanResolutionStatus
from .models import InjectionEdge,InjectionEdgeKind,UnresolvedInjection
from .graph import InjectionGraph
_KIND={InjectionKind.CONSTRUCTOR:InjectionEdgeKind.CONSTRUCTOR,InjectionKind.FIELD:InjectionEdgeKind.FIELD}
class InjectionGraphBuilder:
    def build(self,report:SpringAnalysisReport,resolver:BeanResolver)->InjectionGraph:
        edges=[];unresolved=[]
        for point in report.injections:
            result=resolver.resolve(BeanResolutionRequest(point.target_qualified_name or point.target_name,injection_name=point.member_name,required=point.required))
            if result.status is BeanResolutionStatus.RESOLVED:
                edges.append(InjectionEdge(point.owner,result.bean.qualified_name,_KIND[point.kind],point.member_name))
            else: unresolved.append(UnresolvedInjection(point.owner,point.target_name,point.member_name,result.status))
        return InjectionGraph(edges,unresolved)
