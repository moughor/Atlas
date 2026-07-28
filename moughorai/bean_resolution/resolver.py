from __future__ import annotations
from moughorai.spring_components import ComponentCatalog
from .models import BeanResolutionRequest,BeanResolutionResult,BeanResolutionStatus
class BeanResolver:
    def __init__(self,catalog:ComponentCatalog): self._catalog=catalog
    def resolve(self,request:BeanResolutionRequest)->BeanResolutionResult:
        candidates=list(self._catalog.by_type(request.required_type))
        if request.qualifier:
            candidates=[c for c in candidates if request.qualifier==c.bean_name or request.qualifier in c.qualifiers]
        if len(candidates)>1:
            primaries=[c for c in candidates if c.primary]
            if len(primaries)==1: candidates=primaries
        if len(candidates)>1 and request.injection_name:
            named=[c for c in candidates if c.bean_name==request.injection_name]
            if len(named)==1: candidates=named
        ordered=tuple(sorted(candidates,key=lambda c:(c.bean_name,c.qualified_name)))
        if len(ordered)==1:return BeanResolutionResult(request,BeanResolutionStatus.RESOLVED,ordered[0],ordered,'unique candidate')
        if not ordered:return BeanResolutionResult(request,BeanResolutionStatus.MISSING,None,(), 'optional missing' if not request.required else 'no candidate')
        return BeanResolutionResult(request,BeanResolutionStatus.AMBIGUOUS,None,ordered,'multiple candidates')
