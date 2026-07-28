from moughorai.java_semantics import JavaSemanticParser
from moughorai.passes import (
    STATEMENT_DECLARATION_TYPE_MISMATCH,
    STATEMENT_INVALID_THROW_TYPE,
    STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP,
    STATEMENT_MISSING_RETURN_VALUE,
    STATEMENT_NON_BOOLEAN_CONDITION,
    STATEMENT_RETURN_TYPE_MISMATCH,
    STATEMENT_UNEXPECTED_RETURN_VALUE,
    STATEMENT_UNREACHABLE,
    StatementTypeCheckingPass,
    check_statement_types,
)
from moughorai.semantic import PassContext, SemanticDocument


def parse_block(source):
    node, diagnostics = JavaSemanticParser.parse_block_text(source)
    assert diagnostics == ()
    return node


def codes(result):
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_if_and_while_conditions_must_be_boolean():
    result = check_statement_types(parse_block("{ if (1) return; while (2L) break; }"))
    assert [d.code for d in result.diagnostics].count(STATEMENT_NON_BOOLEAN_CONDITION) == 2


def test_declaration_checks_full_expression_type():
    result = check_statement_types(parse_block('{ int total = "Atlas" + 5; }'))
    assert STATEMENT_DECLARATION_TYPE_MISMATCH in codes(result)


def test_return_type_validation():
    mismatch = check_statement_types(parse_block('{ return "wrong"; }'), expected_return_type="int")
    missing = check_statement_types(parse_block("{ return; }"), expected_return_type="long")
    unexpected = check_statement_types(parse_block("{ return 1; }"), expected_return_type="void")
    assert STATEMENT_RETURN_TYPE_MISMATCH in codes(mismatch)
    assert STATEMENT_MISSING_RETURN_VALUE in codes(missing)
    assert STATEMENT_UNEXPECTED_RETURN_VALUE in codes(unexpected)


def test_throw_rejects_primitive_values():
    result = check_statement_types(parse_block("{ throw 42; }"))
    assert STATEMENT_INVALID_THROW_TYPE in codes(result)


def test_break_and_continue_require_loop_context():
    outside = check_statement_types(parse_block("{ break; continue; }"))
    inside = check_statement_types(parse_block("{ while (true) { continue; break; } }"))
    assert [d.code for d in outside.diagnostics].count(STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP) == 2
    assert STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP not in codes(inside)


def test_unreachable_statement_is_reported_as_warning():
    result = check_statement_types(parse_block("{ return; int after = 1; }"), expected_return_type="void")
    diagnostic = next(d for d in result.diagnostics if d.code == STATEMENT_UNREACHABLE)
    assert diagnostic.severity.value == "WARNING"


def test_pass_reads_expected_return_type_from_document_metadata():
    tree = parse_block('{ return "wrong"; }')
    document = SemanticDocument(
        language="java",
        source="",
        syntax_tree=tree,
        metadata={"expected_return_type": "int"},
    )
    result = StatementTypeCheckingPass().run(document, PassContext())
    assert STATEMENT_RETURN_TYPE_MISMATCH in {d.code for d in result.diagnostics}