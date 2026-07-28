from moughorai.passes.functional_interface_typing import (
    FunctionalInterface, LambdaExpression, MethodReference,
    LAMBDA_ARITY_MISMATCH, LAMBDA_PARAMETER_MISMATCH, LAMBDA_RETURN_MISMATCH,
    METHOD_REFERENCE_AMBIGUOUS, METHOD_REFERENCE_STATIC_MISMATCH,
    check_lambda, resolve_method_reference,
)
from moughorai.passes.method_resolution import MethodSignature
from moughorai.semantic.types import TypeRegistry

R = TypeRegistry()
INT = R.primitive("int")
LONG = R.primitive("long")
STRING = R.class_type("String")
VOID = R.void


def fi(name="Fn", params=(INT,), result=INT):
    return FunctionalInterface(name, tuple(params), result)


def sig(name, params, result=INT, *, static=False, constructor=False):
    return MethodSignature("Example", name, tuple(params), result,
                           is_static=static, is_constructor=constructor)


def codes(result):
    return {d.code for d in result.diagnostics}


def test_implicitly_typed_lambda_uses_target_parameters():
    assert check_lambda(LambdaExpression((None,), (INT,)), fi()).compatible


def test_explicit_lambda_parameter_must_match_target():
    result = check_lambda(LambdaExpression((LONG,), (INT,)), fi())
    assert LAMBDA_PARAMETER_MISMATCH in codes(result)


def test_lambda_arity_is_validated():
    result = check_lambda(LambdaExpression((), (INT,)), fi())
    assert LAMBDA_ARITY_MISMATCH in codes(result)


def test_lambda_return_supports_primitive_widening():
    assert check_lambda(LambdaExpression((None,), (INT,)), fi(result=LONG)).compatible


def test_missing_lambda_return_is_reported():
    result = check_lambda(LambdaExpression((None,), ()), fi())
    assert LAMBDA_RETURN_MISMATCH in codes(result)


def test_void_lambda_rejects_value_return():
    result = check_lambda(LambdaExpression((None,), (INT,)), fi(result=VOID))
    assert LAMBDA_RETURN_MISMATCH in codes(result)


def test_static_method_reference_resolves():
    candidate = sig("parse", (STRING,), INT, static=True)
    target = fi(params=(STRING,), result=INT)
    result = resolve_method_reference(MethodReference("Example", "parse", "static"), target, [candidate])
    assert result.compatible and result.selected == candidate


def test_bound_reference_rejects_static_method():
    candidate = sig("size", (), INT, static=True)
    result = resolve_method_reference(MethodReference("Example", "size", "bound"), fi(params=()), [candidate])
    assert METHOD_REFERENCE_STATIC_MISMATCH in codes(result)


def test_unbound_reference_consumes_receiver_parameter():
    candidate = sig("compare", (STRING,), INT)
    target = fi(params=(R.class_type("Example"), STRING), result=INT)
    result = resolve_method_reference(MethodReference("Example", "compare", "unbound"), target, [candidate])
    assert result.compatible


def test_ambiguous_method_reference_is_reported():
    a = sig("convert", (INT,), INT, static=True)
    b = sig("convert", (INT,), INT, static=True)
    result = resolve_method_reference(MethodReference("Example", "convert", "static"), fi(), [a, b])
    assert METHOD_REFERENCE_AMBIGUOUS in codes(result)
