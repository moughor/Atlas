from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from moughorai.security_analysis.models import SourceLocation

class FlowRole(str, Enum):
    SOURCE='source'; PARAMETER='parameter'; CALL='call'; RETURN='return'; PROPAGATION='propagation'; SINK='sink'

@dataclass(frozen=True, slots=True)
class MethodId:
    owner: str
    name: str
    arity: int
    def __post_init__(self):
        if not self.name.strip(): raise ValueError('method name must not be empty')
        if self.arity < 0: raise ValueError('arity must be non-negative')
    @property
    def qualified_name(self) -> str:
        return f'{self.owner + "." if self.owner else ""}{self.name}/{self.arity}'

@dataclass(frozen=True, slots=True)
class FlowNode:
    method: MethodId
    symbol: str
    role: FlowRole
    location: SourceLocation | None = None
    message: str = ''
    def __post_init__(self):
        if not self.symbol.strip(): raise ValueError('symbol must not be empty')
    @property
    def key(self):
        loc=self.location
        return (self.method.qualified_name,self.symbol,self.role.value,'' if loc is None else loc.path,0 if loc is None else loc.line,0 if loc is None else loc.column,self.message)

@dataclass(frozen=True, slots=True)
class MethodFlow:
    method: MethodId
    parameters: tuple[str,...] = ()
    assignments: tuple[tuple[str,str],...] = ()
    returns: tuple[str,...] = ()
    sources: tuple[str,...] = ()
    sinks: tuple[str,...] = ()
    locations: tuple[tuple[str,SourceLocation],...] = ()
    def __post_init__(self):
        if len(self.parameters) != self.method.arity: raise ValueError('parameter count must match method arity')
    def location_for(self,symbol):
        return dict(self.locations).get(symbol)

@dataclass(frozen=True, slots=True)
class CallSite:
    caller: MethodId
    callee: MethodId
    arguments: tuple[str,...]
    result: str | None = None
    location: SourceLocation | None = None
    def __post_init__(self):
        if len(self.arguments) != self.callee.arity: raise ValueError('argument count must match callee arity')
    @property
    def key(self):
        loc=self.location
        return (self.caller.qualified_name,self.callee.qualified_name,self.arguments,self.result or '', '' if loc is None else loc.path,0 if loc is None else loc.line,0 if loc is None else loc.column)

@dataclass(frozen=True, slots=True)
class DataFlowProgram:
    methods: tuple[MethodFlow,...]
    calls: tuple[CallSite,...] = ()
    def __post_init__(self):
        ids=[m.method for m in self.methods]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate method')
    def method_map(self): return {m.method:m for m in self.methods}

@dataclass(frozen=True, slots=True)
class FlowPath:
    nodes: tuple[FlowNode,...]
    truncated: bool = False
    recursion_detected: bool = False
    @property
    def source(self): return self.nodes[0] if self.nodes else None
    @property
    def sink(self): return self.nodes[-1] if self.nodes else None
    def to_dict(self):
        def loc(x): return None if x is None else {'path':x.path,'line':x.line,'column':x.column}
        return {'nodes':[{'method':n.method.qualified_name,'symbol':n.symbol,'role':n.role.value,'message':n.message,'location':loc(n.location)} for n in self.nodes], 'truncated':self.truncated,'recursion_detected':self.recursion_detected}
