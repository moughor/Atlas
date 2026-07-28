import pytest
from moughorai.java_semantics.control_flow_graph import *
from moughorai.java_semantics.cfg_builder import *
from moughorai.java_semantics.nullability import *

def linear(): return CFGBuilder().build((ExprStmt('x'),))
def statement_block(g): return next(i for i,b in g.blocks.items() if b.label=='statement')

def test_states_values(): assert NullState.NULL.value=='null'
def test_merge_same(): assert merge_state(NullState.NULL,NullState.NULL) is NullState.NULL
def test_merge_null_nonnull(): assert merge_state(NullState.NULL,NullState.NON_NULL) is NullState.MAYBE_NULL
def test_merge_bottom(): assert merge_state(NullState.BOTTOM,NullState.NON_NULL) is NullState.NON_NULL
def test_merge_unknown(): assert merge_state(NullState.UNKNOWN,NullState.NON_NULL) is NullState.UNKNOWN
def test_merge_env_empty(): assert merge_environments([])=={}
def test_assign_null():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignNull('x'),)}); assert r.out_states[b]['x'] is NullState.NULL
def test_assign_nonnull():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignNonNull('x'),)}); assert r.out_states[b]['x'] is NullState.NON_NULL
def test_assign_unknown():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignUnknown('x'),)}); assert r.out_states[b]['x'] is NullState.UNKNOWN
def test_copy():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignNonNull('x'),CopyValue('y','x'))}); assert r.out_states[b]['y'] is NullState.NON_NULL
def test_copy_missing_unknown():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(CopyValue('y','x'),)}); assert r.out_states[b]['y'] is NullState.UNKNOWN
def test_safe_deref():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignNonNull('x'),Dereference('x'))}); assert not r.diagnostics
def test_definite_deref():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(AssignNull('x'),Dereference('x'))}); assert r.diagnostics[0].code is NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE
def test_possible_deref_unknown():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(Dereference('x'),)}); assert r.diagnostics[0].code is NullabilityDiagnosticCode.POSSIBLE_NULL_DEREFERENCE
def test_initial_state():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(Dereference('x'),)},initial={'x':NullState.NON_NULL}); assert not r.diagnostics
def branch_graph(): return CFGBuilder().build((IfStmt('x==null',(ExprStmt('t'),),(ExprStmt('f'),)),))
def blocks(g,label): return [i for i,b in g.blocks.items() if b.label==label]
def test_true_refinement_equals_null():
 g=branch_graph(); c=blocks(g,'if')[0]; t=blocks(g,'if.true')[0]; r=NullabilityAnalyzer().analyze(g,conditions={c:NullCondition('x')}); assert r.in_states[t]['x'] is NullState.NULL
def test_false_refinement_equals_null():
 g=branch_graph(); c=blocks(g,'if')[0]; f=blocks(g,'if.false')[0]; r=NullabilityAnalyzer().analyze(g,conditions={c:NullCondition('x')}); assert r.in_states[f]['x'] is NullState.NON_NULL
def test_not_equals_true_nonnull():
 g=branch_graph(); c=blocks(g,'if')[0]; t=blocks(g,'if.true')[0]; r=NullabilityAnalyzer().analyze(g,conditions={c:NullCondition('x',False)}); assert r.in_states[t]['x'] is NullState.NON_NULL
def test_not_equals_false_null():
 g=branch_graph(); c=blocks(g,'if')[0]; f=blocks(g,'if.false')[0]; r=NullabilityAnalyzer().analyze(g,conditions={c:NullCondition('x',False)}); assert r.in_states[f]['x'] is NullState.NULL
def test_branch_safe_false_deref():
 g=branch_graph(); c=blocks(g,'if')[0]; fstmt=blocks(g,'statement')[1]; r=NullabilityAnalyzer().analyze(g,{fstmt:(Dereference('x'),)},{c:NullCondition('x')}); assert not r.diagnostics
def test_branch_bad_true_deref():
 g=branch_graph(); c=blocks(g,'if')[0]; tstmt=blocks(g,'statement')[0]; r=NullabilityAnalyzer().analyze(g,{tstmt:(Dereference('x'),)},{c:NullCondition('x')}); assert r.diagnostics[0].code is NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE
def test_join_merge():
 g=branch_graph(); c=blocks(g,'if')[0]; join=blocks(g,'if.join')[0]; r=NullabilityAnalyzer().analyze(g,conditions={c:NullCondition('x')}); assert r.in_states[join]['x'] is NullState.MAYBE_NULL
def test_assignment_branch_merge():
 g=branch_graph(); stmts=blocks(g,'statement'); join=blocks(g,'if.join')[0]; r=NullabilityAnalyzer().analyze(g,{stmts[0]:(AssignNull('y'),),stmts[1]:(AssignNonNull('y'),)}); assert r.in_states[join]['y'] is NullState.MAYBE_NULL
def test_loop_fixpoint():
 g=CFGBuilder().build((WhileStmt('c',(ExprStmt('body'),)),)); body=blocks(g,'statement')[0]; r=NullabilityAnalyzer().analyze(g,{body:(AssignNull('x'),)},initial={'x':NullState.NON_NULL}); assert r.iterations>len(g.blocks)
def test_loop_after_maybe():
 g=CFGBuilder().build((WhileStmt('c',(ExprStmt('body'),)),)); body=blocks(g,'statement')[0]; after=blocks(g,'while.after')[0]; r=NullabilityAnalyzer().analyze(g,{body:(AssignNull('x'),)},initial={'x':NullState.NON_NULL}); assert r.in_states[after]['x'] in (NullState.NON_NULL,NullState.MAYBE_NULL)
def test_result_maps_all_blocks():
 g=linear(); r=NullabilityAnalyzer().analyze(g); assert set(r.in_states)==set(g.blocks)
def test_diagnostic_conversion_definite():
 d=NullabilityDiagnostic(NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE,'x').to_diagnostic(); assert d.code=='ATLAS-NULL-001'
def test_diagnostic_conversion_possible():
 d=NullabilityDiagnostic(NullabilityDiagnosticCode.POSSIBLE_NULL_DEREFERENCE,'x').to_diagnostic(); assert d.code=='ATLAS-NULL-002'
def test_definite_severity_error():
 d=NullabilityDiagnostic(NullabilityDiagnosticCode.DEFINITE_NULL_DEREFERENCE,'x').to_diagnostic(); assert d.severity.value=='ERROR'
def test_possible_severity_warning():
 d=NullabilityDiagnostic(NullabilityDiagnosticCode.POSSIBLE_NULL_DEREFERENCE,'x').to_diagnostic(); assert d.severity.value=='WARNING'
def test_duplicate_diagnostics_deduped():
 g=linear(); b=statement_block(g); r=NullabilityAnalyzer().analyze(g,{b:(Dereference('x'),Dereference('x'))}); assert len(r.diagnostics)==1
def test_unknown_instruction():
 g=linear(); b=statement_block(g)
 with pytest.raises(TypeError): NullabilityAnalyzer().analyze(g,{b:(object(),)})
def test_empty_graph_program():
 g=CFGBuilder().build(()); r=NullabilityAnalyzer().analyze(g); assert not r.diagnostics
def test_return_graph():
 g=CFGBuilder().build((ReturnStmt(),)); r=NullabilityAnalyzer().analyze(g); assert g.exit_id in r.in_states
def test_throw_graph():
 g=CFGBuilder().build((ThrowStmt(),)); r=NullabilityAnalyzer().analyze(g); assert g.exit_id in r.in_states
@pytest.mark.parametrize('state',list(NullState))
def test_state_roundtrip(state): assert NullState(state.value) is state
