from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.bean_resolution import BeanResolutionStatus
class InjectionEdgeKind(str,Enum): CONSTRUCTOR='constructor'; FIELD='field'; METHOD='method'
@dataclass(frozen=True,order=True)
class InjectionEdge:
    owner:str; target:str; kind:InjectionEdgeKind; member_name:str
@dataclass(frozen=True)
class UnresolvedInjection:
    owner:str; required_type:str; member_name:str; status:BeanResolutionStatus
