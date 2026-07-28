"""Parser-independent control-flow graph infrastructure for Atlas."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable
from moughorai.semantic import Diagnostic, DiagnosticSeverity

class FlowKind(str, Enum):
    NORMAL='normal'; TRUE_BRANCH='true'; FALSE_BRANCH='false'; LOOP_BACK='loop_back'; BREAK='break'; CONTINUE='continue'; RETURN='return'; THROW='throw'; FINALLY='finally'; CASE='case'

class CFGDiagnosticCode(str, Enum):
    UNREACHABLE='ATLAS-CFG-001'; INVALID_EDGE='ATLAS-CFG-002'; DISCONNECTED='ATLAS-CFG-003'; INFINITE_LOOP='ATLAS-CFG-004'; INVALID_TRANSFER='ATLAS-CFG-005'

@dataclass(frozen=True, slots=True)
class CFGDiagnostic:
    code: CFGDiagnosticCode; message: str; block_id: int|None=None
    def to_diagnostic(self)->Diagnostic:
        return Diagnostic(code=self.code.value,message=self.message,severity=DiagnosticSeverity.ERROR,location=None,pass_name='control_flow_graph')

@dataclass(frozen=True, slots=True)
class FlowEdge:
    source:int; target:int; kind:FlowKind=FlowKind.NORMAL; label:str|None=None

@dataclass(slots=True)
class BasicBlock:
    id:int; label:str; statements:list[str]=field(default_factory=list); terminal:bool=False
    def add(self, statement:str)->None:
        if statement: self.statements.append(statement)

@dataclass(slots=True)
class ControlFlowGraph:
    blocks:dict[int,BasicBlock]=field(default_factory=dict)
    edges:list[FlowEdge]=field(default_factory=list)
    entry_id:int=0; exit_id:int=1
    def add_block(self,label:str,statements:Iterable[str]=(),terminal:bool=False)->BasicBlock:
        block=BasicBlock(max(self.blocks,default=-1)+1,label,list(statements),terminal); self.blocks[block.id]=block; return block
    def add_edge(self,source:int,target:int,kind:FlowKind=FlowKind.NORMAL,label:str|None=None)->bool:
        if source not in self.blocks or target not in self.blocks: return False
        edge=FlowEdge(source,target,kind,label)
        if edge in self.edges:return False
        self.edges.append(edge); return True
    def successors(self,block_id:int)->tuple[int,...]:
        return tuple(e.target for e in self.edges if e.source==block_id)
    def predecessors(self,block_id:int)->tuple[int,...]:
        return tuple(e.source for e in self.edges if e.target==block_id)
    def reachable(self)->set[int]:
        seen=set(); stack=[self.entry_id]
        while stack:
            n=stack.pop()
            if n in seen or n not in self.blocks: continue
            seen.add(n); stack.extend(reversed(self.successors(n)))
        return seen
    def unreachable_blocks(self)->tuple[int,...]: return tuple(sorted(set(self.blocks)-self.reachable()))
    def reverse_post_order(self)->tuple[int,...]:
        seen=set(); post=[]
        def dfs(n:int):
            if n in seen:return
            seen.add(n)
            for s in self.successors(n): dfs(s)
            post.append(n)
        dfs(self.entry_id); return tuple(reversed(post))
    def dominators(self)->dict[int,set[int]]:
        reachable=self.reachable(); alln=set(reachable); dom={n:({n} if n==self.entry_id else set(alln)) for n in reachable}
        changed=True
        while changed:
            changed=False
            for n in reachable-{self.entry_id}:
                preds=[p for p in self.predecessors(n) if p in reachable]
                new={n}| (set.intersection(*(dom[p] for p in preds)) if preds else set())
                if new!=dom[n]: dom[n]=new; changed=True
        return dom
    def validate(self)->tuple[CFGDiagnostic,...]:
        ds=[]
        for e in self.edges:
            if e.source not in self.blocks or e.target not in self.blocks: ds.append(CFGDiagnostic(CFGDiagnosticCode.INVALID_EDGE,'Edge references an unknown block'))
        for b in self.unreachable_blocks():
            if b!=self.exit_id: ds.append(CFGDiagnostic(CFGDiagnosticCode.UNREACHABLE,f"Block {b} is unreachable",b))
        if self.exit_id not in self.reachable(): ds.append(CFGDiagnostic(CFGDiagnosticCode.DISCONNECTED,'CFG exit is disconnected',self.exit_id))
        return tuple(ds)