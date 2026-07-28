from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any
from moughorai.data_flow import InstructionId

class SymbolicKind(str, Enum):
    UNKNOWN='unknown'; CONSTANT='constant'; VARIABLE='variable'; BINARY='binary'; UNARY='unary'

@dataclass(frozen=True, slots=True)
class SymbolicValue:
    kind: SymbolicKind
    value: Any=None
    operator: str|None=None
    operands: tuple['SymbolicValue', ...]=()
    @classmethod
    def unknown(cls, name: str|None=None): return cls(SymbolicKind.UNKNOWN, name)
    @classmethod
    def constant(cls, value: Any): return cls(SymbolicKind.CONSTANT, value)
    @classmethod
    def variable(cls, name: str):
        if not name.strip(): raise ValueError('variable name must not be empty')
        return cls(SymbolicKind.VARIABLE, name.strip())
    @classmethod
    def binary(cls, op: str, left: 'SymbolicValue', right: 'SymbolicValue'):
        return cls(SymbolicKind.BINARY, None, op.strip(), (left,right))
    @classmethod
    def unary(cls, op: str, operand: 'SymbolicValue'):
        return cls(SymbolicKind.UNARY, None, op.strip(), (operand,))

@dataclass(frozen=True, slots=True)
class Constraint:
    left: SymbolicValue
    operator: str
    right: SymbolicValue
    def __post_init__(self):
        if self.operator not in {'==','!=','<','<=','>','>=','is','is not'}: raise ValueError('unsupported constraint operator')
    def negate(self)->'Constraint':
        return Constraint(self.left, {'==':'!=','!=':'==','<':'>=','<=':'>','>':'<=','>=':'<','is':'is not','is not':'is'}[self.operator], self.right)

@dataclass(frozen=True, slots=True)
class SymbolicState:
    values: tuple[tuple[str,SymbolicValue], ...]=()
    constraints: tuple[Constraint,...]=()
    path: tuple[str,...]=()
    def get(self,name:str)->SymbolicValue: return dict(self.values).get(name,SymbolicValue.variable(name))
    def set(self,name:str,value:SymbolicValue)->'SymbolicState':
        d=dict(self.values); d[name]=value
        return SymbolicState(tuple(sorted(d.items())),self.constraints,self.path)
    def assume(self,c:Constraint,block:str|None=None)->'SymbolicState':
        path=self.path+((block,) if block else ())
        return SymbolicState(self.values,self.constraints+(c,),path)

@dataclass(frozen=True, slots=True)
class AssertionResult:
    instruction: InstructionId
    status: str
    condition: Constraint
    path: tuple[str,...]=()

@dataclass(frozen=True, slots=True)
class ExecutionStatistics:
    explored_states:int; feasible_states:int; pruned_states:int; merged_states:int; max_depth_reached:bool

@dataclass(frozen=True, slots=True)
class SymbolicExecutionReport:
    states_at: tuple[tuple[InstructionId,tuple[SymbolicState,...]],...]
    terminal_states: tuple[SymbolicState,...]
    unreachable_instructions: tuple[InstructionId,...]
    assertions: tuple[AssertionResult,...]
    statistics: ExecutionStatistics
    warnings: tuple[str,...]=()
    def states_for(self,i:InstructionId)->tuple[SymbolicState,...]:
        for key,states in self.states_at:
            if key==i:return states
        return ()
