from moughorai.java_semantics import JavaSemanticParser
from moughorai.passes import ExpressionTypeInferencePass, VariableTypeInferencePass, infer_expression_type
from moughorai.semantic import PassContext, SemanticDocument
from moughorai.semantic.types import ClassType, PrimitiveType


def parse(source):
    node, diagnostics = JavaSemanticParser.parse_expression_text(source)
    assert diagnostics == ()
    return node


def test_arithmetic_numeric_promotion():
    assert infer_expression_type(parse("1 + 2L")).semantic_type == PrimitiveType("long")


def test_string_concatenation():
    assert infer_expression_type(parse('"Atlas" + 5')).semantic_type == ClassType("java.lang.String")


def test_boolean_and_comparison_results():
    assert infer_expression_type(parse("1 < 2")).semantic_type == PrimitiveType("boolean")
    assert infer_expression_type(parse("true && false")).semantic_type == PrimitiveType("boolean")


def test_cast_and_object_creation():
    assert infer_expression_type(parse("(long) 1")).semantic_type == PrimitiveType("long")
    assert infer_expression_type(parse("new Widget()")).semantic_type == ClassType("Widget")


def test_conditional_numeric_promotion():
    assert infer_expression_type(parse("true ? 1 : 2.0")).semantic_type == PrimitiveType("double")


def test_pass_uses_variable_symbols():
    tree, diagnostics = JavaSemanticParser.parse_block_text("{ int count = 1; var total = count + 2L; }")
    assert diagnostics == ()
    document = SemanticDocument(language="java", source="", syntax_tree=tree)
    document = VariableTypeInferencePass().run(document, PassContext())
    result = ExpressionTypeInferencePass().run(document, PassContext())
    assert any(value == PrimitiveType("long") for value in result.types.entries.values())