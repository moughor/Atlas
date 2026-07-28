from __future__ import annotations
import pytest
from moughorai.data_flow import BasicBlock,ControlFlowEdge,ControlFlowGraph,EdgeKind,Instruction,InstructionId,InstructionKind
from moughorai.symbolic_execution import *

def ins(block,index,kind=InstructionKind.NOP,defines=None,uses=(),constant=None,has_constant=False,metadata=()):
    return Instruction(InstructionId(block,index),kind,defines,uses,constant,has_constant,False,None,index+1,metadata)

def branch_cfg(constant=None):
    entry=[]
    if constant is not None:entry.append(ins('entry',0,InstructionKind.ASSIGN,'x',constant=constant,has_constant=True))
    idx=len(entry); entry.append(ins('entry',idx,InstructionKind.BRANCH,uses=('x',),metadata=(('operator','>'),('right','0'))))
    return ControlFlowGraph((BasicBlock('entry',tuple(entry)),BasicBlock('yes',(ins('yes',0,InstructionKind.RETURN),)),BasicBlock('no',(ins('no',0,InstructionKind.RETURN),))),
        (ControlFlowEdge('entry','yes',EdgeKind.TRUE),ControlFlowEdge('entry','no',EdgeKind.FALSE)),entry='entry')

@pytest.mark.parametrize('value',[None,True,False,0,1,-1,3.5,'x'])
def test_constant_roundtrip(value):
    v=SymbolicValue.constant(value); assert v.value==value and v.kind is SymbolicKind.CONSTANT

@pytest.mark.parametrize('op,a,b,expected',[
    ('+',2,3,5),('-',5,2,3),('*',4,3,12),('/',8,2,4),('==',2,2,True),('!=',2,3,True),('<',2,3,True),('<=',2,2,True),('>',3,2,True),('>=',3,3,True),('and',True,False,False),('or',False,True,True)])
def test_evaluate_binary(op,a,b,expected):
    assert evaluate(SymbolicValue.binary(op,SymbolicValue.constant(a),SymbolicValue.constant(b)),SymbolicState())==expected

@pytest.mark.parametrize('op,value,expected',[('not',True,False),('not',False,True),('-',2,-2),('-',-5,5)])
def test_evaluate_unary(op,value,expected):
    assert evaluate(SymbolicValue.unary(op,SymbolicValue.constant(value)),SymbolicState())==expected

@pytest.mark.parametrize('op,a,b,expected',[('==',1,1,True),('!=',1,1,False),('<',1,2,True),('<=',2,2,True),('>',3,2,True),('>=',2,3,False),('is',None,None,True),('is not',None,1,True)])
def test_constraint_truth_constants(op,a,b,expected):
    c=Constraint(SymbolicValue.constant(a),op,SymbolicValue.constant(b)); assert constraint_truth(c,SymbolicState()) is expected

@pytest.mark.parametrize('constraints,expected',[
    ([('==',1),('!=',1)],False),([('==',1),('==',1)],True),([('>',5),('<',3)],False),([('>=',5),('<=',5)],True),([('>',5),('<=',5)],False),([('!=',2),('==',3)],True),([('is',None),('is not',None)],False)])
def test_feasibility(constraints,expected):
    x=SymbolicValue.variable('x'); state=SymbolicState(constraints=tuple(Constraint(x,op,SymbolicValue.constant(v)) for op,v in constraints)); assert is_feasible(state) is expected

def test_state_set_is_immutable():
    a=SymbolicState(); b=a.set('x',SymbolicValue.constant(1)); assert a.values==() and b.get('x').value==1

def test_constraint_negation():
    c=Constraint(SymbolicValue.variable('x'),'<',SymbolicValue.constant(1)); assert c.negate().operator=='>='

def test_invalid_constraint_rejected():
    with pytest.raises(ValueError):Constraint(SymbolicValue.variable('x'),'contains',SymbolicValue.constant(1))

def test_invalid_variable_rejected():
    with pytest.raises(ValueError):SymbolicValue.variable(' ')

def test_invalid_options_rejected():
    with pytest.raises(ValueError):ExecutionOptions(max_states=0)

def test_unknown_branch_forks_two_paths():
    r=execute_symbolically(branch_cfg()); assert len(r.terminal_states)==2 and r.statistics.pruned_states==0

def test_constant_positive_prunes_false_path():
    r=execute_symbolically(branch_cfg(2)); assert len(r.terminal_states)==1 and any(i.block=='no' for i in r.unreachable_instructions)

def test_constant_negative_prunes_true_path():
    r=execute_symbolically(branch_cfg(-2)); assert len(r.terminal_states)==1 and any(i.block=='yes' for i in r.unreachable_instructions)

def test_zero_takes_false_path():
    r=execute_symbolically(branch_cfg(0)); assert any(i.block=='yes' for i in r.unreachable_instructions)

def test_assignment_propagates_constant():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.ASSIGN,'x',constant=7,has_constant=True),ins('entry',1,InstructionKind.RETURN))),))
    r=execute_symbolically(cfg); assert r.terminal_states[0].get('x').value==7

def test_copy_assignment_propagates_value():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.ASSIGN,'x',constant=7,has_constant=True),ins('entry',1,InstructionKind.ASSIGN,'y',uses=('x',)),ins('entry',2,InstructionKind.RETURN))),))
    assert execute_symbolically(cfg).terminal_states[0].get('y').value==7

def test_binary_assignment_evaluates():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.ASSIGN,'x',constant=2,has_constant=True),ins('entry',1,InstructionKind.ASSIGN,'y',constant=3,has_constant=True),ins('entry',2,InstructionKind.ASSIGN,'z',uses=('x','y'),metadata=(('operator','+'),)),ins('entry',3,InstructionKind.RETURN))),))
    state=execute_symbolically(cfg).terminal_states[0]; assert evaluate(state.get('z'),state)==5

def test_assertion_proved():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.ASSIGN,'x',constant=2,has_constant=True),ins('entry',1,InstructionKind.NOP,uses=('x',),metadata=(('assert','true'),('operator','>'),('right','0'))),)),))
    assert execute_symbolically(cfg).assertions[0].status=='proved'

def test_assertion_violated():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.ASSIGN,'x',constant=-2,has_constant=True),ins('entry',1,InstructionKind.NOP,uses=('x',),metadata=(('assert','true'),('operator','>'),('right','0'))),)),))
    assert execute_symbolically(cfg).assertions[0].status=='violated'

def test_assertion_unknown():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.NOP,uses=('x',),metadata=(('assert','true'),('operator','>'),('right','0'))),)),))
    assert execute_symbolically(cfg).assertions[0].status=='unknown'

def test_depth_limit_sets_flag():
    cfg=ControlFlowGraph((BasicBlock('a'),BasicBlock('b'),BasicBlock('c')),(ControlFlowEdge('a','b'),ControlFlowEdge('b','c')),entry='a')
    assert execute_symbolically(cfg,options=ExecutionOptions(max_depth=1)).statistics.max_depth_reached

def test_state_limit_warning():
    r=execute_symbolically(branch_cfg(),options=ExecutionOptions(max_states=1)); assert 'global state limit reached' in r.warnings

def test_states_for_instruction():
    cfg=branch_cfg(1); r=execute_symbolically(cfg); assert len(r.states_for(InstructionId('entry',0)))==1

def test_terminal_return_recorded():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.RETURN),)),)); assert len(execute_symbolically(cfg).terminal_states)==1

def test_throw_is_terminal():
    cfg=ControlFlowGraph((BasicBlock('entry',(ins('entry',0,InstructionKind.THROW),)),)); assert len(execute_symbolically(cfg).terminal_states)==1

def test_deterministic_report():
    cfg=branch_cfg(); assert execute_symbolically(cfg)==execute_symbolically(cfg)
