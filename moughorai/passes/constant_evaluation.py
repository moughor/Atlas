from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class ConstantKind(str, Enum):
    BYTE = "byte"
    SHORT = "short"
    INT = "int"
    LONG = "long"
    FLOAT = "float"
    DOUBLE = "double"
    CHAR = "char"
    BOOLEAN = "boolean"
    STRING = "String"
    NULL = "null"


_INTEGRAL = {ConstantKind.BYTE, ConstantKind.SHORT, ConstantKind.INT, ConstantKind.LONG, ConstantKind.CHAR}
_NUMERIC = _INTEGRAL | {ConstantKind.FLOAT, ConstantKind.DOUBLE}


@dataclass(frozen=True, slots=True)
class ConstantValue:
    kind: ConstantKind
    value: object

    @property
    def is_numeric(self) -> bool:
        return self.kind in _NUMERIC

    @property
    def is_integral(self) -> bool:
        return self.kind in _INTEGRAL


@dataclass(frozen=True, slots=True)
class Literal:
    value: ConstantValue


@dataclass(frozen=True, slots=True)
class Name:
    identifier: str


@dataclass(frozen=True, slots=True)
class Unary:
    operator: str
    operand: object


@dataclass(frozen=True, slots=True)
class Binary:
    operator: str
    left: object
    right: object


@dataclass(frozen=True, slots=True)
class Cast:
    target: ConstantKind
    operand: object


class ConstantEvaluationError(ValueError):
    pass


class NonConstantExpression(ConstantEvaluationError):
    pass


class ConstantArithmeticError(ConstantEvaluationError):
    pass


def _signed(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    value &= mask
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def _integral_value(value: ConstantValue) -> int:
    if value.kind is ConstantKind.CHAR:
        raw = value.value
        return ord(raw) if isinstance(raw, str) else int(raw)
    return int(value.value)


def _promoted_kind(left: ConstantValue, right: ConstantValue) -> ConstantKind:
    if ConstantKind.DOUBLE in (left.kind, right.kind):
        return ConstantKind.DOUBLE
    if ConstantKind.FLOAT in (left.kind, right.kind):
        return ConstantKind.FLOAT
    if ConstantKind.LONG in (left.kind, right.kind):
        return ConstantKind.LONG
    return ConstantKind.INT


def _wrap(kind: ConstantKind, value: object) -> ConstantValue:
    if kind is ConstantKind.LONG:
        return ConstantValue(kind, _signed(int(value), 64))
    if kind in {ConstantKind.INT, ConstantKind.BYTE, ConstantKind.SHORT, ConstantKind.CHAR}:
        bits = {ConstantKind.BYTE: 8, ConstantKind.SHORT: 16, ConstantKind.CHAR: 16}.get(kind, 32)
        wrapped = int(value) & ((1 << bits) - 1) if kind is ConstantKind.CHAR else _signed(int(value), bits)
        return ConstantValue(kind, chr(wrapped) if kind is ConstantKind.CHAR else wrapped)
    if kind in {ConstantKind.FLOAT, ConstantKind.DOUBLE}:
        return ConstantValue(kind, float(value))
    return ConstantValue(kind, value)


def _java_div(left: int, right: int) -> int:
    if right == 0:
        raise ConstantArithmeticError("Division by zero in constant expression.")
    return abs(left) // abs(right) * (-1 if (left < 0) ^ (right < 0) else 1)


def _java_rem(left: int, right: int) -> int:
    return left - _java_div(left, right) * right


def _string(value: ConstantValue) -> str:
    if value.kind is ConstantKind.NULL:
        return "null"
    if value.kind is ConstantKind.BOOLEAN:
        return "true" if value.value else "false"
    return str(value.value)


def evaluate(expression: object, constants: Mapping[str, ConstantValue] | None = None) -> ConstantValue:
    constants = constants or {}
    if isinstance(expression, ConstantValue):
        return expression
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, Name):
        try:
            return constants[expression.identifier]
        except KeyError as exc:
            raise NonConstantExpression(f"'{expression.identifier}' is not a compile-time constant.") from exc
    if isinstance(expression, Cast):
        return cast_constant(expression.target, evaluate(expression.operand, constants))
    if isinstance(expression, Unary):
        value = evaluate(expression.operand, constants)
        if expression.operator == "!" and value.kind is ConstantKind.BOOLEAN:
            return ConstantValue(ConstantKind.BOOLEAN, not bool(value.value))
        if expression.operator in {"+", "-"} and value.is_numeric:
            kind = ConstantKind.LONG if value.kind is ConstantKind.LONG else (
                value.kind if value.kind in {ConstantKind.FLOAT, ConstantKind.DOUBLE} else ConstantKind.INT
            )
            raw = float(value.value) if kind in {ConstantKind.FLOAT, ConstantKind.DOUBLE} else _integral_value(value)
            return _wrap(kind, raw if expression.operator == "+" else -raw)
        if expression.operator == "~" and value.is_integral:
            kind = ConstantKind.LONG if value.kind is ConstantKind.LONG else ConstantKind.INT
            return _wrap(kind, ~_integral_value(value))
        raise NonConstantExpression(f"Unary operator '{expression.operator}' is not valid for {value.kind.value}.")
    if isinstance(expression, Binary):
        left = evaluate(expression.left, constants)
        op = expression.operator
        if op == "&&" and left.kind is ConstantKind.BOOLEAN and not left.value:
            return ConstantValue(ConstantKind.BOOLEAN, False)
        if op == "||" and left.kind is ConstantKind.BOOLEAN and left.value:
            return ConstantValue(ConstantKind.BOOLEAN, True)
        right = evaluate(expression.right, constants)
        if op == "+" and (left.kind is ConstantKind.STRING or right.kind is ConstantKind.STRING):
            return ConstantValue(ConstantKind.STRING, _string(left) + _string(right))
        if op in {"&&", "||"} and left.kind is right.kind is ConstantKind.BOOLEAN:
            return ConstantValue(ConstantKind.BOOLEAN, bool(left.value and right.value) if op == "&&" else bool(left.value or right.value))
        if op in {"==", "!="}:
            result = left.value == right.value
            return ConstantValue(ConstantKind.BOOLEAN, result if op == "==" else not result)
        if op in {"<", "<=", ">", ">="} and left.is_numeric and right.is_numeric:
            a, b = float(left.value), float(right.value)
            result = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            return ConstantValue(ConstantKind.BOOLEAN, result)
        if op in {"<<", ">>", ">>>"} and left.is_integral and right.is_integral:
            kind = ConstantKind.LONG if left.kind is ConstantKind.LONG else ConstantKind.INT
            bits = 64 if kind is ConstantKind.LONG else 32
            distance = _integral_value(right) & (0x3F if bits == 64 else 0x1F)
            raw = _integral_value(left)
            if op == "<<": result = raw << distance
            elif op == ">>": result = raw >> distance
            else: result = (raw & ((1 << bits) - 1)) >> distance
            return _wrap(kind, result)
        if op in {"&", "|", "^"}:
            if left.kind is right.kind is ConstantKind.BOOLEAN:
                a, b = bool(left.value), bool(right.value)
                return ConstantValue(ConstantKind.BOOLEAN, {"&": a and b, "|": a or b, "^": a ^ b}[op])
            if left.is_integral and right.is_integral:
                kind = _promoted_kind(left, right)
                a, b = _integral_value(left), _integral_value(right)
                return _wrap(kind, {"&": a & b, "|": a | b, "^": a ^ b}[op])
        if op in {"+", "-", "*", "/", "%"} and left.is_numeric and right.is_numeric:
            kind = _promoted_kind(left, right)
            if kind in {ConstantKind.FLOAT, ConstantKind.DOUBLE}:
                a, b = float(left.value), float(right.value)
                if op == "+": result = a + b
                elif op == "-": result = a - b
                elif op == "*": result = a * b
                elif op == "/": result = a / b
                else: result = a % b
            else:
                a, b = _integral_value(left), _integral_value(right)
                if op == "+": result = a + b
                elif op == "-": result = a - b
                elif op == "*": result = a * b
                elif op == "/": result = _java_div(a, b)
                else: result = _java_rem(a, b)
            return _wrap(kind, result)
        raise NonConstantExpression(f"Binary operator '{op}' is not valid for {left.kind.value} and {right.kind.value}.")
    raise NonConstantExpression(f"Unsupported constant-expression node: {type(expression).__name__}.")


def cast_constant(target: ConstantKind, value: ConstantValue) -> ConstantValue:
    if target is value.kind:
        return value
    if target is ConstantKind.STRING:
        raise NonConstantExpression("Java constant expressions do not permit casts to String.")
    if target is ConstantKind.BOOLEAN or value.kind is ConstantKind.BOOLEAN:
        raise NonConstantExpression("Boolean constants cannot be converted to or from numeric types.")
    if target in _NUMERIC and value.kind in _NUMERIC:
        raw = _integral_value(value) if value.is_integral else float(value.value)
        return _wrap(target, raw)
    raise NonConstantExpression(f"Cannot cast constant {value.kind.value} to {target.value}.")


def require_constant(expression: object, constants: Mapping[str, ConstantValue] | None = None) -> ConstantValue:
    return evaluate(expression, constants)


__all__ = [
    "ConstantKind", "ConstantValue", "Literal", "Name", "Unary", "Binary", "Cast",
    "ConstantEvaluationError", "NonConstantExpression", "ConstantArithmeticError",
    "evaluate", "cast_constant", "require_constant",
]