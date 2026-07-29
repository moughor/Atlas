"""Structured statement nodes and a reusable CFG builder."""
from __future__ import annotations
from dataclasses import dataclass
from .control_flow_graph import ControlFlowGraph, FlowKind

@dataclass(frozen=True,slots=True)
class Stmt: pass
@dataclass(frozen=True,slots=True)
class ExprStmt(Stmt): text:str
@dataclass(frozen=True,slots=True)
class IfStmt(Stmt): condition:str; then_body:tuple[Stmt,...]; else_body:tuple[Stmt,...]=()
@dataclass(frozen=True,slots=True)
class WhileStmt(Stmt): condition:str; body:tuple[Stmt,...]
@dataclass(frozen=True,slots=True)
class ReturnStmt(Stmt): expression:str|None=None
@dataclass(frozen=True,slots=True)
class ThrowStmt(Stmt): expression:str='exception'
@dataclass(frozen=True,slots=True)
class BreakStmt(Stmt): pass
@dataclass(frozen=True,slots=True)
class ContinueStmt(Stmt): pass

class CFGBuilder:
    def __init__(self): self.graph=ControlFlowGraph(); self.graph.blocks[0]=__import__('moughorai.java_semantics.control_flow_graph',fromlist=['BasicBlock']).BasicBlock(0,'entry'); self.graph.blocks[1]=__import__('moughorai.java_semantics.control_flow_graph',fromlist=['BasicBlock']).BasicBlock(1,'exit',terminal=True)
    def build(self, statements:tuple[Stmt,...])->ControlFlowGraph:
        tails=self._sequence(statements,(0,),None,None)
        for t in tails:self.graph.add_edge(t,1)
        return self.graph
    def _sequence(self,stmts,tails,break_target,continue_target):
        current=tuple(tails)
        for s in stmts:
            if not current: break
            current=self._stmt(s,current,break_target,continue_target)
        return current
    def _stmt(self,s,tails,break_target,continue_target):
        if isinstance(s,ExprStmt):
            b=self.graph.add_block('statement',(s.text,)); [self.graph.add_edge(t,b.id) for t in tails]; return (b.id,)
        if isinstance(s,ReturnStmt):
            b=self.graph.add_block('return',(() if s.expression is None else (s.expression,)),True); [self.graph.add_edge(t,b.id) for t in tails]; self.graph.add_edge(b.id,1,FlowKind.RETURN); return ()
        if isinstance(s,ThrowStmt):
            b=self.graph.add_block('throw',(s.expression,),True); [self.graph.add_edge(t,b.id) for t in tails]; self.graph.add_edge(b.id,1,FlowKind.THROW); return ()
        if isinstance(s,BreakStmt):
            b=self.graph.add_block('break',terminal=True); [self.graph.add_edge(t,b.id) for t in tails]
            if break_target is not None:self.graph.add_edge(b.id,break_target,FlowKind.BREAK)
            return ()
        if isinstance(s,ContinueStmt):
            b=self.graph.add_block('continue',terminal=True); [self.graph.add_edge(t,b.id) for t in tails]
            if continue_target is not None:self.graph.add_edge(b.id,continue_target,FlowKind.CONTINUE)
            return ()
        if isinstance(s,IfStmt):
            c=self.graph.add_block('if',(s.condition,)); [self.graph.add_edge(t,c.id) for t in tails]
            join=self.graph.add_block('if.join')
            tb=self.graph.add_block('if.true'); self.graph.add_edge(c.id,tb.id,FlowKind.TRUE_BRANCH)
            tt=self._sequence(s.then_body,(tb.id,),break_target,continue_target); [self.graph.add_edge(x,join.id) for x in tt]
            fb=self.graph.add_block('if.false'); self.graph.add_edge(c.id,fb.id,FlowKind.FALSE_BRANCH)
            ft=self._sequence(s.else_body,(fb.id,),break_target,continue_target); [self.graph.add_edge(x,join.id) for x in ft]
            return (join.id,) if self.graph.predecessors(join.id) else ()
        if isinstance(s,WhileStmt):
            c=self.graph.add_block('while',(s.condition,)); [self.graph.add_edge(t,c.id) for t in tails]
            after=self.graph.add_block('while.after'); body=self.graph.add_block('while.body')
            self.graph.add_edge(c.id,body.id,FlowKind.TRUE_BRANCH); self.graph.add_edge(c.id,after.id,FlowKind.FALSE_BRANCH)
            bt=self._sequence(s.body,(body.id,),after.id,c.id); [self.graph.add_edge(x,c.id,FlowKind.LOOP_BACK) for x in bt]
            return (after.id,)
        raise TypeError(type(s).__name__)