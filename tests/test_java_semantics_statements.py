import pytest
from moughorai.java_semantics import JavaSemanticParser
from moughorai.java_semantics.statements import *
from moughorai.java_semantics.expressions import *

@pytest.mark.parametrize("source,kind", [
    ("{ return value; }", ReturnStatement),
    ("{ throw error; }", ThrowStatement),
    ("{ break; }", BreakStatement),
    ("{ continue; }", ContinueStatement),
    ("{ int count = 1; }", LocalVariableDeclaration),
    ("{ save(value); }", ExpressionStatement),
    ("{ if (ok) return a; else return b; }", IfStatement),
    ("{ while (ok) { save(); } }", WhileStatement),
])
def test_statement_kinds(source, kind):
    block, diagnostics = JavaSemanticParser.parse_block_text(source)
    assert isinstance(block.statements[0], kind)
    assert diagnostics == ()

def test_nested_block():
    block, _ = JavaSemanticParser.parse_block_text("{ { int x = 1; } }")
    assert isinstance(block.statements[0], BlockStatement)

def test_local_initializer_is_expression():
    block, _ = JavaSemanticParser.parse_block_text("{ User user = repo.find(id); }")
    declaration = block.statements[0]
    assert isinstance(declaration.initializer, MethodCallExpression)

def test_missing_semicolon_reports_diagnostic():
    block, diagnostics = JavaSemanticParser.parse_block_text("{ return value }")
    assert diagnostics
