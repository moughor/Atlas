from __future__ import annotations
from dataclasses import dataclass
from .models import *

@dataclass(frozen=True, slots=True)
class CallGraph:
    edges: tuple[tuple[MethodId,MethodId],...]
    def callees(self,method): return tuple(b for a,b in self.edges if a==method)
    def callers(self,method): return tuple(a for a,b in self.edges if b==method)
    def to_dict(self): return {'edges':[{'caller':a.qualified_name,'callee':b.qualified_name} for a,b in self.edges]}

def build_call_graph(program:DataFlowProgram)->CallGraph:
    return CallGraph(tuple(sorted({(c.caller,c.callee) for c in program.calls},key=lambda e:(e[0].qualified_name,e[1].qualified_name))))
