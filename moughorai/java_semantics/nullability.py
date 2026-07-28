"""Flow-sensitive nullability analysis over Atlas control-flow graphs."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from collections import deque
from .control_flow_graph import ControlFlowGraph, FlowKind
from moughorai.semantic import Diagnostic, DiagnosticSeverity

class NullState(str, Enum):
    BOTTOM='bottom'; NULL='null'; NON_NULL='non_null'; MAYBE_NULL='maybe_null'; UNKNOWN='unknown'

class NullabilityDiagnosticCode(str, Enum):
    DEFINITE_NULL_DEREFERENCE='ATLAS-NULL-001'
    POSSIBLE_NULL_DEREFERENCE='ATLAS-NULL-002'
    INVALID_CONDITION='ATLAS-NULL-003'

@dataclass(frozen=True, slots=True)
class NullabilityDiagnostic:
    code: NullabilityDiagnosticCode
    message: str
    block_id: int|None=None
    variable: str|None=None
    def to_diagnostic(self)->Diagnostic:
        return Diagnostic(code=self.code.value,message=self.message,severity=DiagnosticSeverity.ERROR if self.code is NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE else DiagnosticSeverity.WARNING,location=None,pass_name='nullability')

@dataclass(frozen=True, slots=True)
class AssignNull: variable:str
@dataclass(frozen=True, slots=True)
class AssignNonNull: variable:str
@dataclass(frozen=True, slots=True)
class AssignUnknown: variable:str
@dataclass(frozen=True, slots=True)
class CopyValue: target:str; source:str
@dataclass(frozen=True, slots=True)
class Dereference: variable:str
@dataclass(frozen=True, slots=True)
class NullCondition: variable:str; equals_null:bool=True

Instruction=AssignNull|AssignNonNull|AssignUnknown|CopyValue|Dereference
Environment=dict[str,NullState]

def merge_state(a:NullState,b:NullState)->NullState:
    if a is NullState.BOTTOM:return b
    if b is NullState.BOTTOM:return a
    if a is b:return a
    if NullState.UNKNOWN in (a,b):return NullState.UNKNOWN
    return NullState.MAYBE_NULL

def merge_environments(items:list[Environment])->Environment:
    if not items:return {}
    keys=set().union(*(x.keys() for x in items)); out={}
    for key in keys:
        state=NullState.BOTTOM
        for env in items: state=merge_state(state,env.get(key,NullState.UNKNOWN))
        out[key]=state
    return out

@dataclass(frozen=True, slots=True)
class NullabilityResult:
    in_states:dict[int,Environment]
    out_states:dict[int,Environment]
    diagnostics:tuple[NullabilityDiagnostic,...]
    iterations:int

class NullabilityAnalyzer:
    def analyze(self, graph:ControlFlowGraph, instructions:dict[int,tuple[Instruction,...]]|None=None, conditions:dict[int,NullCondition]|None=None, initial:Environment|None=None)->NullabilityResult:
        instructions=instructions or {}; conditions=conditions or {}; initial=dict(initial or {})
        ins={bid:{} for bid in graph.blocks}; outs={bid:{} for bid in graph.blocks}; ins[graph.entry_id]=initial
        queue=deque(graph.reverse_post_order() or (graph.entry_id,)); queued=set(queue); diagnostics={}; iterations=0
        while queue:
            bid=queue.popleft(); queued.discard(bid); iterations+=1
            if bid!=graph.entry_id:
                incoming=[]
                for edge in graph.edges:
                    if edge.target!=bid:continue
                    env=dict(outs.get(edge.source,{})); cond=conditions.get(edge.source)
                    if cond and edge.kind in (FlowKind.TRUE_BRANCH,FlowKind.FALSE_BRANCH):
                        true_edge=edge.kind is FlowKind.TRUE_BRANCH
                        is_null=true_edge if cond.equals_null else not true_edge
                        env[cond.variable]=NullState.NULL if is_null else NullState.NON_NULL
                    incoming.append(env)
                new_in=merge_environments(incoming)
                if new_in!=ins[bid]:ins[bid]=new_in
            env=dict(ins[bid])
            for op in instructions.get(bid,()):
                if isinstance(op,AssignNull):env[op.variable]=NullState.NULL
                elif isinstance(op,AssignNonNull):env[op.variable]=NullState.NON_NULL
                elif isinstance(op,AssignUnknown):env[op.variable]=NullState.UNKNOWN
                elif isinstance(op,CopyValue):env[op.target]=env.get(op.source,NullState.UNKNOWN)
                elif isinstance(op,Dereference):
                    state=env.get(op.variable,NullState.UNKNOWN)
                    if state is NullState.NULL:
                        d=NullabilityDiagnostic(NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE,f"Definite null dereference of '{op.variable}'",bid,op.variable); diagnostics[(d.code,bid,op.variable)]=d
                    elif state in (NullState.MAYBE_NULL,NullState.UNKNOWN):
                        d=NullabilityDiagnostic(NullabilityDiagnosticCode.POSSIBLE_NULL_DEREFERENCE,f"Possible null dereference of '{op.variable}'",bid,op.variable); diagnostics[(d.code,bid,op.variable)]=d
                else: raise TypeError(type(op).__name__)
            if env!=outs[bid]:
                outs[bid]=env
                for succ in graph.successors(bid):
                    if succ not in queued: queue.append(succ); queued.add(succ)
        return NullabilityResult(ins,outs,tuple(diagnostics.values()),iterations)
