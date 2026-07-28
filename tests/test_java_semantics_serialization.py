from moughorai.java_semantics import JavaSemanticParser, semantic_to_dict

def test_serialization_is_stable_and_typed():
    expr, _ = JavaSemanticParser.parse_expression_text("a + 1")
    data = semantic_to_dict(expr)
    assert data["kind"] == "BinaryExpression"
    assert data["operator"] == "+"
    assert data["left"]["kind"] == "UnresolvedNameExpression"

def test_tuple_serializes_as_list():
    expr, _ = JavaSemanticParser.parse_expression_text("save(a, b)")
    data = semantic_to_dict(expr)
    assert isinstance(data["arguments"], list)
