from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
from moughorai.data_flow import ControlFlowGraph, EdgeKind, Instruction, InstructionKind
from .models import *
from .solver import constraint_truth,evaluate,is_feasible,UNKNOWN

@dataclass(frozen=True,slots=True)
class ExecutionOptions:
    max_states:int=1000; max_depth:int=64; max_states_per_block:int=32
    def __post_init__(self):
        if min(self.max_states,self.max_depth,self.max_states_per_block)<1:raise ValueError('execution limits must be positive')

def _meta(i:Instruction)->dict[str,str]: return dict(i.metadata)
def _atom(token:str,state:SymbolicState)->SymbolicValue:
    token=token.strip()
    if token in {'true','false'}:return SymbolicValue.constant(token=='true')
    if token in {'null','None'}:return SymbolicValue.constant(None)
    if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):return SymbolicValue.constant(token[1:-1])
    try:return SymbolicValue.constant(float(token) if '.' in token else int(token))
    except ValueError:return state.get(token)
def _condition(i:Instruction,state:SymbolicState)->Constraint:
    m=_meta(i); op=m.get('operator',m.get('op','==')); lhs=m.get('left') or (i.uses[0] if i.uses else 'condition'); rhs=m.get('right','true')
    return Constraint(_atom(lhs,state),op,_atom(rhs,state))
def _value(i:Instruction,state:SymbolicState)->SymbolicValue:
    m=_meta(i)
    if i.has_constant:return SymbolicValue.constant(i.constant)
    if 'operator' in m and len(i.uses)>=2:return SymbolicValue.binary(m['operator'],state.get(i.uses[0]),state.get(i.uses[1]))
    if len(i.uses)==1:return state.get(i.uses[0])
    if i.uses:
        value=state.get(i.uses[0])
        for name in i.uses[1:]:value=SymbolicValue.binary('+',value,state.get(name))
        return value
    return SymbolicValue.unknown(i.defines)

class SymbolicExecutor:
    def __init__(self,options:ExecutionOptions|None=None):self.options=options or ExecutionOptions()
    def execute(self,cfg:ControlFlowGraph,initial:SymbolicState|None=None)->SymbolicExecutionReport:
        queue=deque([(cfg.entry,initial or SymbolicState(path=(cfg.entry,)),0)])
        seen:dict[str,set[SymbolicState]]=defaultdict(set); at:dict[object,list[SymbolicState]]=defaultdict(list); terminals=[]; assertions=[]
        explored=pruned=merged=0; depth_hit=False; warnings=[]
        edge_map=defaultdict(list)
        for e in cfg.edges:edge_map[e.source].append(e)
        while queue and explored<self.options.max_states:
            block_name,state,depth=queue.popleft(); explored+=1
            if depth>self.options.max_depth:depth_hit=True;pruned+=1;continue
            if not is_feasible(state):pruned+=1;continue
            if state in seen[block_name]:merged+=1;continue
            if len(seen[block_name])>=self.options.max_states_per_block:pruned+=1;warnings.append(f'state limit reached at {block_name}');continue
            seen[block_name].add(state); block=cfg.block(block_name); current=state; branch=None
            if block is None:continue
            for ins in block.instructions:
                at[ins.id].append(current)
                if ins.kind in {InstructionKind.ASSIGN,InstructionKind.PHI,InstructionKind.CALL} and ins.defines:current=current.set(ins.defines,_value(ins,current))
                if ins.kind is InstructionKind.BRANCH:branch=_condition(ins,current)
                if _meta(ins).get('assert','').lower()=='true':
                    c=_condition(ins,current); truth=constraint_truth(c,current)
                    assertions.append(AssertionResult(ins.id,'proved' if truth is True else 'violated' if truth is False else 'unknown',c,current.path))
                if ins.kind in {InstructionKind.RETURN,InstructionKind.THROW}:terminals.append(current)
            edges=edge_map.get(block_name,[])
            if not edges:
                if current not in terminals:terminals.append(current)
                continue
            for edge in edges:
                nxt=current
                if branch and edge.kind in {EdgeKind.TRUE,EdgeKind.FALSE}:nxt=current.assume(branch if edge.kind is EdgeKind.TRUE else branch.negate(),edge.target)
                else:nxt=SymbolicState(current.values,current.constraints,current.path+(edge.target,))
                if is_feasible(nxt):queue.append((edge.target,nxt,depth+1))
                else:pruned+=1
        if queue:warnings.append('global state limit reached')
        reachable=set(at); all_ids={i.id for i in cfg.instructions}
        states_at=tuple(sorted(((k,tuple(v)) for k,v in at.items()),key=lambda x:x[0].qualified_name))
        stats=ExecutionStatistics(explored,len(set(terminals)),pruned,merged,depth_hit)
        return SymbolicExecutionReport(states_at,tuple(terminals),tuple(sorted(all_ids-reachable)),tuple(assertions),stats,tuple(sorted(set(warnings))))
