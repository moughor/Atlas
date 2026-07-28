import pytest
from moughorai.java_semantics import JavaSemanticParser
from moughorai.java_semantics.expressions import *

@pytest.mark.parametrize("source,kind", [
    ("1", LiteralExpression),
    ("true", LiteralExpression),
    ("name", UnresolvedNameExpression),
    ("this", ThisExpression),
    ("super", SuperExpression),
    ("new User()", ObjectCreationExpression),
    ("(a)", ParenthesizedExpression),
    ("(User)value", CastExpression),
    ("!flag", UnaryExpression),
    ("count++", UnaryExpression),
    ("a+b", BinaryExpression),
    ("x=1", AssignmentExpression),
    ("a?b:c", ConditionalExpression),
    ("items[0]", ArrayAccessExpression),
    ("user.name", FieldAccessExpression),
    ("service.save(user)", MethodCallExpression),
])
def test_expression_kinds(source, kind):
    expr, diagnostics = JavaSemanticParser.parse_expression_text(source)
    assert isinstance(expr, kind)
    assert diagnostics == ()

@pytest.mark.parametrize("source,root_op,child_op", [
    ("a+b*c", "+", "*"),
    ("a||b&&c", "||", "&&"),
    ("a==b+c", "==", "+"),
    ("a+b<c", "<", "+"),
])
def test_precedence(source, root_op, child_op):
    expr, _ = JavaSemanticParser.parse_expression_text(source)
    assert expr.operator == root_op
    assert getattr(expr.right, "operator", None) == child_op or getattr(expr.left, "operator", None) == child_op

def test_assignment_is_right_associative():
    expr, _ = JavaSemanticParser.parse_expression_text("a=b=c")
    assert isinstance(expr.value, AssignmentExpression)

def test_chained_calls():
    expr, _ = JavaSemanticParser.parse_expression_text("repo.find(id).getName()")
    assert isinstance(expr, MethodCallExpression)
    assert expr.method_name == "getName"
    assert isinstance(expr.target, MethodCallExpression)

def test_argument_parsing():
    expr, _ = JavaSemanticParser.parse_expression_text("save(a, b + c)")
    assert len(expr.arguments) == 2
    assert isinstance(expr.arguments[1], BinaryExpression)

def test_numeric_values():
    expr, _ = JavaSemanticParser.parse_expression_text("1_000")
    assert expr.value == 1000

def test_string_value():
    expr, _ = JavaSemanticParser.parse_expression_text('"a\\nb"')
    assert expr.value == "a\nb"
