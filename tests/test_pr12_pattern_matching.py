from moughorai.java_semantics.pattern_matching import (
    PatternAnalyzer,
    PatternBinding,
    PatternDiagnosticCode,
    PatternScope,
    TypePattern,
    analyze_and,
    analyze_or,
    analyze_type_pattern,
    empty_condition,
    intersect_scopes,
    is_pattern_compatible,
)
from moughorai.semantic import Diagnostic
from moughorai.semantic.types import (
    ClassType,
    NullType,
    PrimitiveType,
    UnknownType,
)


OBJECT = ClassType("Object")
STRING = ClassType("String")
NUMBER = ClassType("Number")
INTEGER = ClassType("Integer")
SERIALIZABLE = ClassType("Serializable")
INT = PrimitiveType("int")

HIERARCHY = {
    "String": ("Object", "Serializable"),
    "Number": ("Object", "Serializable"),
    "Integer": ("Number", "Object", "Serializable"),
}


def codes(scope):
    return [diagnostic.code for diagnostic in scope.diagnostics]


def test_matching_binding_exists_only_on_true_edge():
    result = analyze_type_pattern(OBJECT, TypePattern(STRING, "text"))
    assert result.when_true.contains("text")
    assert not result.when_false.contains("text")
    assert result.when_true.type_of("text") == STRING


def test_same_reference_type_is_compatible():
    assert is_pattern_compatible(STRING, STRING)


def test_object_and_subtype_are_compatible():
    assert is_pattern_compatible(OBJECT, STRING, HIERARCHY)
    assert is_pattern_compatible(STRING, OBJECT, HIERARCHY)


def test_sibling_reference_types_are_incompatible():
    assert not is_pattern_compatible(STRING, NUMBER, HIERARCHY)


def test_unknown_expression_type_is_conservatively_accepted():
    result = analyze_type_pattern(
        UnknownType(), TypePattern(STRING, "text"), hierarchy=HIERARCHY
    )
    assert result.when_true.contains("text")
    assert result.when_true.diagnostics == []


def test_null_expression_type_is_accepted_but_never_changes_false_scope():
    result = analyze_type_pattern(NullType(), TypePattern(STRING, "text"))
    assert result.when_true.contains("text")
    assert not result.when_false.contains("text")


def test_primitive_target_pattern_is_rejected():
    result = analyze_type_pattern(OBJECT, TypePattern(INT, "value"))
    assert codes(result.when_true) == [PatternDiagnosticCode.PRIMITIVE_PATTERN]
    assert not result.when_true.contains("value")


def test_primitive_expression_is_incompatible():
    result = analyze_type_pattern(INT, TypePattern(STRING, "text"))
    assert codes(result.when_true) == [PatternDiagnosticCode.INCOMPATIBLE_TYPE]


def test_empty_binding_name_is_rejected():
    result = analyze_type_pattern(OBJECT, TypePattern(STRING, "   "))
    assert codes(result.when_true) == [
        PatternDiagnosticCode.INVALID_BINDING_NAME
    ]


def test_duplicate_binding_is_rejected():
    incoming = PatternScope({"text": PatternBinding("text", OBJECT)})
    result = analyze_type_pattern(
        OBJECT, TypePattern(STRING, "text"), incoming
    )
    assert codes(result.when_true) == [
        PatternDiagnosticCode.DUPLICATE_BINDING
    ]
    assert result.when_true.type_of("text") == OBJECT


def test_negation_swaps_pattern_scopes():
    result = analyze_type_pattern(OBJECT, TypePattern(STRING, "text")).negated()
    assert not result.when_true.contains("text")
    assert result.when_false.contains("text")


def test_and_exposes_left_binding_to_right_operand():
    left = analyze_type_pattern(OBJECT, TypePattern(STRING, "text"))
    seen = []

    def right(incoming):
        seen.append(incoming.contains("text"))
        return empty_condition(incoming)

    result = analyze_and(left, right)
    assert seen == [True]
    assert result.when_true.contains("text")


def test_and_binding_is_not_definite_on_false_edge():
    left = analyze_type_pattern(OBJECT, TypePattern(STRING, "text"))
    result = analyze_and(left, empty_condition)
    assert not result.when_false.contains("text")


def test_or_right_operand_does_not_receive_left_true_binding():
    left = analyze_type_pattern(OBJECT, TypePattern(STRING, "text"))
    seen = []

    def right(incoming):
        seen.append(incoming.contains("text"))
        return empty_condition(incoming)

    result = analyze_or(left, right)
    assert seen == [False]
    assert not result.when_true.contains("text")


def test_intersection_keeps_only_identical_bindings():
    left = PatternScope({
        "shared": PatternBinding("shared", STRING),
        "left": PatternBinding("left", OBJECT),
    })
    right = PatternScope({
        "shared": PatternBinding("shared", STRING),
        "right": PatternBinding("right", OBJECT),
    })
    result = intersect_scopes(left, right)
    assert set(result.bindings) == {"shared"}


def test_pattern_diagnostics_convert_to_standard_diagnostics():
    result = analyze_type_pattern(INT, TypePattern(STRING, "text"))
    diagnostic = result.when_true.standard_diagnostics[0]
    assert isinstance(diagnostic, Diagnostic)
    assert diagnostic.code == "ATLAS-PATTERN-001"
    assert diagnostic.pass_name == "pattern_matching"


def test_analyzer_facade_uses_supplied_hierarchy():
    analyzer = PatternAnalyzer(HIERARCHY)
    result = analyzer.type_pattern(INTEGER, NUMBER, "number")
    assert result.when_true.contains("number")
    assert result.when_true.diagnostics == []