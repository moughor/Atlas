import pytest
from moughorai.java_semantics.control_flow_graph import *
from moughorai.java_semantics.cfg_builder import *
from moughorai.java_semantics.reachability import *
from moughorai.java_semantics.structured_flow import *

def block(g,label): return next(i for i,b in g.blocks.items() if b.label==label)
def diagnostics(result, code): return [d for d in result.diagnostics if d.code is code]

def test_linear_reachable():
 g=CFGBuilder().build((ExprStmt('a'),)); r=ReachabilityAnalyzer().analyze(g); assert r.reachable_blocks==frozenset(g.blocks)
def test_manual_dead_block():
 g=CFGBuilder().build(()); dead=g.add_block('dead'); r=ReachabilityAnalyzer().analyze(g); assert dead.id in r.unreachable_blocks
def test_dead_block_diagnostic():
 g=CFGBuilder().build(()); g.add_block('dead'); r=ReachabilityAnalyzer().analyze(g); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_BLOCK)
def test_void_method_completes():
 g=CFGBuilder().build((ExprStmt('a'),)); assert ReachabilityAnalyzer().analyze(g).can_complete_normally
def test_return_method_not_normal():
 g=CFGBuilder().build((ReturnStmt('x'),)); assert not ReachabilityAnalyzer().analyze(g).can_complete_normally
def test_throw_method_not_normal():
 g=CFGBuilder().build((ThrowStmt('x'),)); assert not ReachabilityAnalyzer().analyze(g).can_complete_normally
def test_return_is_guaranteed():
 g=CFGBuilder().build((ReturnStmt('x'),)); assert ReachabilityAnalyzer().analyze(g).guaranteed_return
def test_throw_counts_as_termination():
 g=CFGBuilder().build((ThrowStmt('x'),)); assert ReachabilityAnalyzer().analyze(g).guaranteed_return
def test_missing_return_cfg():
 g=CFGBuilder().build((ExprStmt('a'),)); r=ReachabilityAnalyzer().analyze(g,requires_return=True); assert diagnostics(r,ReachabilityDiagnosticCode.MISSING_RETURN)
def test_no_missing_return_cfg():
 g=CFGBuilder().build((ReturnStmt('a'),)); r=ReachabilityAnalyzer().analyze(g,requires_return=True); assert not diagnostics(r,ReachabilityDiagnosticCode.MISSING_RETURN)
def test_if_both_return():
 g=CFGBuilder().build((IfStmt('c',(ReturnStmt('a'),),(ReturnStmt('b'),)),)); r=ReachabilityAnalyzer().analyze(g,requires_return=True); assert r.guaranteed_return
def test_if_one_return_can_complete():
 g=CFGBuilder().build((IfStmt('c',(ReturnStmt('a'),),()),)); r=ReachabilityAnalyzer().analyze(g,requires_return=True); assert r.can_complete_normally
def test_constant_true_prunes_false_cfg():
 g=CFGBuilder().build((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),)); c=block(g,'if'); f=block(g,'if.false'); r=ReachabilityAnalyzer().analyze(g,constant_conditions={c:True}); assert f in r.unreachable_blocks
def test_constant_false_prunes_true_cfg():
 g=CFGBuilder().build((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),)); c=block(g,'if'); t=block(g,'if.true'); r=ReachabilityAnalyzer().analyze(g,constant_conditions={c:False}); assert t in r.unreachable_blocks
def test_unknown_condition_keeps_both():
 g=CFGBuilder().build((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),)); r=ReachabilityAnalyzer().analyze(g); assert block(g,'if.true') in r.reachable_blocks and block(g,'if.false') in r.reachable_blocks
def test_true_loop_detected():
 g=CFGBuilder().build((WhileStmt('true',(ExprStmt('x'),)),)); h=block(g,'while'); r=ReachabilityAnalyzer().analyze(g,constant_conditions={h:True}); assert h in r.infinite_loop_headers
def test_unknown_loop_not_infinite():
 g=CFGBuilder().build((WhileStmt('c',(ExprStmt('x'),)),)); r=ReachabilityAnalyzer().analyze(g); assert not r.infinite_loop_headers
def test_false_loop_body_unreachable_cfg():
 g=CFGBuilder().build((WhileStmt('false',(ExprStmt('x'),)),)); h=block(g,'while'); body=block(g,'while.body'); r=ReachabilityAnalyzer().analyze(g,constant_conditions={h:False}); assert body in r.unreachable_blocks
def test_true_loop_with_break_not_flagged():
 g=CFGBuilder().build((WhileStmt('true',(BreakStmt(),)),)); h=block(g,'while'); r=ReachabilityAnalyzer().analyze(g,constant_conditions={h:True}); assert not r.infinite_loop_headers
def test_result_frozen_reachable():
 g=CFGBuilder().build(()); assert isinstance(ReachabilityAnalyzer().analyze(g).reachable_blocks,frozenset)
def test_diagnostic_conversion_warning():
 d=ReachabilityDiagnostic(ReachabilityDiagnosticCode.UNREACHABLE_BLOCK,'x').to_diagnostic(); assert d.severity.value=='WARNING'
def test_diagnostic_conversion_error():
 d=ReachabilityDiagnostic(ReachabilityDiagnosticCode.MISSING_RETURN,'x').to_diagnostic(); assert d.severity.value=='ERROR'
def test_diagnostic_code():
 d=ReachabilityDiagnostic(ReachabilityDiagnosticCode.MISSING_RETURN,'x').to_diagnostic(); assert d.code=='ATLAS-REACH-003'
def test_structured_empty_completes():
 assert StructuredFlowAnalyzer().analyze(()).can_complete_normally
def test_structured_return_terminates():
 r=StructuredFlowAnalyzer().analyze((ReturnStmt(),)); assert not r.can_complete_normally and r.always_returns_or_throws
def test_structured_throw_terminates():
 r=StructuredFlowAnalyzer().analyze((ThrowStmt(),)); assert r.always_returns_or_throws
def test_dead_after_return():
 r=StructuredFlowAnalyzer().analyze((ReturnStmt(),ExprStmt('dead'))); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT)
def test_dead_after_throw():
 r=StructuredFlowAnalyzer().analyze((ThrowStmt(),ExprStmt('dead'))); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT)
def test_multiple_dead_statements():
 r=StructuredFlowAnalyzer().analyze((ReturnStmt(),ExprStmt('a'),ExprStmt('b'))); assert len(diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT))==2
def test_invalid_break():
 r=StructuredFlowAnalyzer().analyze((BreakStmt(),)); assert diagnostics(r,ReachabilityDiagnosticCode.INVALID_BREAK)
def test_valid_break_in_loop():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(BreakStmt(),)),)); assert not diagnostics(r,ReachabilityDiagnosticCode.INVALID_BREAK)
def test_invalid_continue():
 r=StructuredFlowAnalyzer().analyze((ContinueStmt(),)); assert diagnostics(r,ReachabilityDiagnosticCode.INVALID_CONTINUE)
def test_valid_continue_in_loop():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(ContinueStmt(),)),)); assert not diagnostics(r,ReachabilityDiagnosticCode.INVALID_CONTINUE)
def test_structured_if_both_return():
 r=StructuredFlowAnalyzer().analyze((IfStmt('c',(ReturnStmt(),),(ThrowStmt(),)),)); assert r.always_returns_or_throws
def test_structured_if_one_returns():
 r=StructuredFlowAnalyzer().analyze((IfStmt('c',(ReturnStmt(),),()),)); assert r.can_complete_normally
def test_constant_true_else_dead():
 r=StructuredFlowAnalyzer().analyze((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),),constant_conditions={'c':True}); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT)
def test_constant_false_then_dead():
 r=StructuredFlowAnalyzer().analyze((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),),constant_conditions={'c':False}); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT)
def test_constant_false_loop_dead():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(ExprStmt('a'),)),),constant_conditions={'c':False}); assert diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT)
def test_constant_true_loop_infinite():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(ExprStmt('a'),)),),constant_conditions={'c':True}); assert diagnostics(r,ReachabilityDiagnosticCode.INFINITE_LOOP)
def test_true_loop_with_break_completes():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(BreakStmt(),)),),constant_conditions={'c':True}); assert r.can_complete_normally
def test_missing_return_structured():
 r=StructuredFlowAnalyzer().analyze((ExprStmt('a'),),requires_return=True); assert diagnostics(r,ReachabilityDiagnosticCode.MISSING_RETURN)
def test_no_missing_return_structured():
 r=StructuredFlowAnalyzer().analyze((ReturnStmt('a'),),requires_return=True); assert not diagnostics(r,ReachabilityDiagnosticCode.MISSING_RETURN)
def test_dead_after_infinite_loop():
 r=StructuredFlowAnalyzer().analyze((WhileStmt('c',(ExprStmt('a'),)),ExprStmt('dead')),constant_conditions={'c':True}); assert len(diagnostics(r,ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT))==1
def test_nested_break_does_not_escape_outer_detection():
 inner=WhileStmt('inner',(BreakStmt(),)); outer=WhileStmt('outer',(inner,)); r=StructuredFlowAnalyzer().analyze((outer,),constant_conditions={'outer':True,'inner':True}); assert diagnostics(r,ReachabilityDiagnosticCode.INFINITE_LOOP)
def test_unknown_statement_raises():
 class X(Stmt): pass
 with pytest.raises(TypeError): StructuredFlowAnalyzer().analyze((X(),))
@pytest.mark.parametrize('code',list(ReachabilityDiagnosticCode))
def test_code_roundtrip(code): assert ReachabilityDiagnosticCode(code.value) is code