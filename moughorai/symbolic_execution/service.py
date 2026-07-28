from __future__ import annotations
from moughorai.data_flow import ControlFlowGraph
from .engine import ExecutionOptions,SymbolicExecutor
from .models import SymbolicExecutionReport,SymbolicState

def execute_symbolically(cfg:ControlFlowGraph,*,initial:SymbolicState|None=None,options:ExecutionOptions|None=None)->SymbolicExecutionReport:
    return SymbolicExecutor(options).execute(cfg,initial)
