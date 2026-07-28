from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.spring_components import ComponentDefinition
class BeanResolutionStatus(str,Enum): RESOLVED='resolved'; MISSING='missing'; AMBIGUOUS='ambiguous'
@dataclass(frozen=True)
class BeanResolutionRequest:
    required_type:str
    qualifier:str|None=None
    injection_name:str|None=None
    required:bool=True
@dataclass(frozen=True)
class BeanResolutionResult:
    request:BeanResolutionRequest
    status:BeanResolutionStatus
    bean:ComponentDefinition|None=None
    candidates:tuple[ComponentDefinition,...]=()
    reason:str=''
