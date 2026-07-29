from moughorai.java_semantics import JavaSemanticFrontEnd
from moughorai.java_semantics.expressions import VariableExpression, UnresolvedNameExpression
from moughorai.java_semantics.statements import *

def test_local_reference_resolves():
    doc = JavaSemanticFrontEnd().analyze_method_body("{ int x = 1; return x; }")
    ret = doc.root.statements[1]
    assert isinstance(ret.expression, VariableExpression)
    assert ret.expression.symbol_id == "symbol:1"
    assert doc.unresolved_names == ()

def test_unknown_reference_remains_unresolved():
    doc = JavaSemanticFrontEnd().analyze_method_body("{ return missing; }")
    assert isinstance(doc.root.statements[0].expression, UnresolvedNameExpression)
    assert doc.unresolved_names == ("missing",)

def test_shadowing_uses_inner_symbol():
    doc = JavaSemanticFrontEnd().analyze_method_body(
        "{ int x = 1; { int x = 2; return x; } }"
    )
    inner = doc.root.statements[1]
    ret = inner.statements[1]
    assert ret.expression.symbol_id == "symbol:2"

def test_outer_symbol_visible_in_inner_block():
    doc = JavaSemanticFrontEnd().analyze_method_body(
        "{ int x = 1; { return x; } }"
    )
    ret = doc.root.statements[1].statements[0]
    assert ret.expression.symbol_id == "symbol:1"

def test_if_creates_branch_scope():
    doc = JavaSemanticFrontEnd().analyze_method_body(
        "{ int x = 1; if (x > 0) { int y = x; return y; } }"
    )
    assert doc.root_scope.children
    assert doc.unresolved_names == ()

def test_loop_creates_scope():
    doc = JavaSemanticFrontEnd().analyze_method_body(
        "{ boolean ok = true; while (ok) { int x = 1; break; } }"
    )
    assert any(child.kind.value == "LOOP" for child in doc.root_scope.children)

def test_initializer_cannot_see_later_variable():
    doc = JavaSemanticFrontEnd().analyze_method_body(
        "{ int x = y; int y = 1; }"
    )
    assert doc.unresolved_names == ("y",)
