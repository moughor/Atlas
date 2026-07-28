from moughorai.passes.generic_type_inference import (
    GENERIC_INFERENCE_ARITY,
    GENERIC_INFERENCE_CONFLICT,
    GENERIC_INFERENCE_UNRESOLVED,
    infer_method_type_arguments,
    substitute_type,
)
from moughorai.semantic.types import TypeRegistry


R = TypeRegistry()
T = R.class_type("T")
U = R.class_type("U")


def codes(result):
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_infers_direct_type_variable():
    result = infer_method_type_arguments(["T"], [T], [R.class_type("String")], T)
    assert result.succeeded
    assert result.substitutions["T"] == R.class_type("String")
    assert result.resolved_return_type == R.class_type("String")


def test_infers_nested_generic_argument():
    parameter = R.generic("java.util.List", [T])
    argument = R.generic("java.util.List", [R.class_type("String")])
    result = infer_method_type_arguments(["T"], [parameter], [argument], T)
    assert result.succeeded
    assert result.resolved_return_type == R.class_type("String")


def test_infers_array_element_type():
    result = infer_method_type_arguments(
        ["T"], [R.array(T)], [R.array(R.class_type("Number"))], R.array(T)
    )
    assert result.succeeded
    assert result.resolved_return_type == R.array(R.class_type("Number"))


def test_multiple_variables_are_substituted_in_return_type():
    result = infer_method_type_arguments(
        ["T", "U"],
        [T, U],
        [R.class_type("String"), R.class_type("Integer")],
        R.generic("Pair", [T, U]),
    )
    assert result.succeeded
    assert result.resolved_return_type.display_name == "Pair<String, Integer>"


def test_conflicting_constraints_report_diagnostic():
    result = infer_method_type_arguments(
        ["T"], [T, T], [R.class_type("String"), R.class_type("Integer")], T
    )
    assert GENERIC_INFERENCE_CONFLICT in codes(result)


def test_unresolved_variable_reports_diagnostic():
    result = infer_method_type_arguments(["T"], [], [], T)
    assert GENERIC_INFERENCE_UNRESOLVED in codes(result)


def test_explicit_type_arguments_override_inference_starting_point():
    result = infer_method_type_arguments(
        ["T"], [T], [R.class_type("String")], T,
        explicit_type_arguments=[R.class_type("String")],
    )
    assert result.succeeded
    assert result.resolved_return_type == R.class_type("String")


def test_argument_and_explicit_arity_are_validated():
    result = infer_method_type_arguments(
        ["T", "U"], [T], [], T,
        explicit_type_arguments=[R.class_type("String")],
    )
    assert GENERIC_INFERENCE_ARITY in codes(result)


def test_substitute_type_preserves_non_variables():
    original = R.generic("List", [R.class_type("String")])
    assert substitute_type(original, {"T": R.class_type("Integer")}) == original