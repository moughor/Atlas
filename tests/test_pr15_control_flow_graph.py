import pytest
from moughorai.java_semantics.control_flow_graph import *
from moughorai.java_semantics.cfg_builder import *

def test_empty_cfg():
 g=CFGBuilder().build(()); assert g.successors(0)==(1,)
def test_sequence():
 g=CFGBuilder().build((ExprStmt('a'),ExprStmt('b'))); assert len(g.blocks)==4
def test_return():
 g=CFGBuilder().build((ReturnStmt('x'),)); assert any(e.kind is FlowKind.RETURN for e in g.edges)
def test_throw():
 g=CFGBuilder().build((ThrowStmt('e'),)); assert any(e.kind is FlowKind.THROW for e in g.edges)
def test_if_edges():
 g=CFGBuilder().build((IfStmt('c',(ExprStmt('a'),),(ExprStmt('b'),)),)); kinds={e.kind for e in g.edges}; assert FlowKind.TRUE_BRANCH in kinds and FlowKind.FALSE_BRANCH in kinds
def test_if_without_else():
 g=CFGBuilder().build((IfStmt('c',(ExprStmt('a'),)),)); assert g.exit_id in g.reachable()
def test_while_edges():
 g=CFGBuilder().build((WhileStmt('c',(ExprStmt('a'),)),)); assert any(e.kind is FlowKind.LOOP_BACK for e in g.edges)
def test_break():
 g=CFGBuilder().build((WhileStmt('c',(BreakStmt(),)),)); assert any(e.kind is FlowKind.BREAK for e in g.edges)
def test_continue():
 g=CFGBuilder().build((WhileStmt('c',(ContinueStmt(),)),)); assert any(e.kind is FlowKind.CONTINUE for e in g.edges)
def test_nested():
 g=CFGBuilder().build((WhileStmt('x',(IfStmt('y',(BreakStmt(),),(ContinueStmt(),)),)),)); assert g.exit_id in g.reachable()
def test_successors():
 g=CFGBuilder().build(()); assert g.successors(0)==(1,)
def test_predecessors():
 g=CFGBuilder().build(()); assert g.predecessors(1)==(0,)
def test_reachable():
 g=CFGBuilder().build(()); assert g.reachable()=={0,1}
def test_unreachable():
 g=CFGBuilder().build(()); b=g.add_block('dead'); assert g.unreachable_blocks()==(b.id,)
def test_rpo():
 g=CFGBuilder().build((ExprStmt('a'),)); assert g.reverse_post_order()[0]==0
def test_dominators_entry():
 g=CFGBuilder().build((ExprStmt('a'),)); assert g.dominators()[0]=={0}
def test_dominators_exit():
 g=CFGBuilder().build((ExprStmt('a'),)); assert 0 in g.dominators()[1]
def test_duplicate_edge():
 g=CFGBuilder().build(()); assert not g.add_edge(0,1)
def test_invalid_edge_rejected():
 g=CFGBuilder().build(()); assert not g.add_edge(99,1)
def test_add_block_statement():
 g=CFGBuilder().build(()); b=g.add_block('x',['a']); assert b.statements==['a']
def test_block_add():
 b=BasicBlock(3,'x'); b.add('a'); assert b.statements==['a']
def test_flow_edge_label():
 assert FlowEdge(0,1,label='x').label=='x'
def test_diagnostic_conversion():
 d=CFGDiagnostic(CFGDiagnosticCode.UNREACHABLE,'dead').to_diagnostic(); assert d.code=='ATLAS-CFG-001'
def test_validate_clean():
 assert CFGBuilder().build(()).validate()==()
def test_validate_dead():
 g=CFGBuilder().build(()); g.add_block('dead'); assert g.validate()[0].code is CFGDiagnosticCode.UNREACHABLE
def test_disconnected_exit():
 g=ControlFlowGraph(); g.blocks[0]=BasicBlock(0,'entry'); g.blocks[1]=BasicBlock(1,'exit'); assert any(d.code is CFGDiagnosticCode.DISCONNECTED for d in g.validate())
def test_enum_values():
 assert FlowKind.FINALLY.value=='finally'
def test_expr_immutable():
 with pytest.raises(Exception): ExprStmt('a').text='b'
def test_unknown_stmt():
 class X(Stmt): pass
 with pytest.raises(TypeError): CFGBuilder().build((X(),))
def test_return_stops_sequence():
 g=CFGBuilder().build((ReturnStmt(),ExprStmt('dead'))); assert all('dead' not in b.statements for b in g.blocks.values())
def test_throw_stops_sequence():
 g=CFGBuilder().build((ThrowStmt(),ExprStmt('dead'))); assert len(g.blocks)==3
@pytest.mark.parametrize('kind', list(FlowKind))
def test_flow_kinds_roundtrip(kind):
 assert FlowKind(kind.value) is kind