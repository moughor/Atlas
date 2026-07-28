import pytest

from moughorai.passes.constant_evaluation import (
    Binary, Cast, ConstantArithmeticError, ConstantKind, ConstantValue,
    Literal, Name, NonConstantExpression, Unary, evaluate, require_constant,
)


def c(kind, value):
    return Literal(ConstantValue(kind, value))


def test_integer_arithmetic_is_folded():
    assert evaluate(Binary("+", c(ConstantKind.INT, 2), c(ConstantKind.INT, 3))).value == 5


def test_java_integer_division_truncates_toward_zero():
    assert evaluate(Binary("/", c(ConstantKind.INT, -7), c(ConstantKind.INT, 3))).value == -2


def test_java_remainder_tracks_truncated_quotient():
    assert evaluate(Binary("%", c(ConstantKind.INT, -7), c(ConstantKind.INT, 3))).value == -1


def test_integer_overflow_wraps_like_java():
    result = evaluate(Binary("+", c(ConstantKind.INT, 2147483647), c(ConstantKind.INT, 1)))
    assert result.value == -2147483648


def test_long_promotion_is_preserved():
    result = evaluate(Binary("+", c(ConstantKind.INT, 1), c(ConstantKind.LONG, 2)))
    assert result.kind is ConstantKind.LONG and result.value == 3


def test_unary_and_bitwise_operators_are_folded():
    assert evaluate(Unary("~", c(ConstantKind.INT, 3))).value == -4


def test_unsigned_right_shift_uses_java_width():
    result = evaluate(Binary(">>>", c(ConstantKind.INT, -1), c(ConstantKind.INT, 1)))
    assert result.value == 2147483647


def test_boolean_short_circuit_avoids_invalid_right_operand():
    dangerous = Binary("/", c(ConstantKind.INT, 1), c(ConstantKind.INT, 0))
    assert evaluate(Binary("&&", c(ConstantKind.BOOLEAN, False), dangerous)).value is False


def test_boolean_and_comparison_are_folded():
    comparison = Binary("<", c(ConstantKind.INT, 2), c(ConstantKind.LONG, 5))
    assert evaluate(Binary("&&", comparison, c(ConstantKind.BOOLEAN, True))).value is True


def test_string_concatenation_uses_java_boolean_spelling():
    result = evaluate(Binary("+", c(ConstantKind.STRING, "value="), c(ConstantKind.BOOLEAN, True)))
    assert result.value == "value=true"


def test_named_constants_are_propagated():
    result = evaluate(Binary("*", Name("SIZE"), c(ConstantKind.INT, 2)), {
        "SIZE": ConstantValue(ConstantKind.INT, 4)
    })
    assert result.value == 8


def test_missing_named_value_is_not_constant():
    with pytest.raises(NonConstantExpression):
        require_constant(Name("runtimeValue"))


def test_integral_constant_cast_wraps():
    result = evaluate(Cast(ConstantKind.BYTE, c(ConstantKind.INT, 130)))
    assert result.value == -126


def test_integer_division_by_zero_is_reported():
    with pytest.raises(ConstantArithmeticError):
        evaluate(Binary("/", c(ConstantKind.INT, 10), c(ConstantKind.INT, 0)))