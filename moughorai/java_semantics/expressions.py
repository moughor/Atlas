from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .source import SourceSpan

@dataclass(frozen=True, slots=True)
class JavaExpression:
    span: SourceSpan | None = None

@dataclass(frozen=True, slots=True)
class UnknownExpression(JavaExpression):
    text: str = ""

@dataclass(frozen=True, slots=True)
class LiteralExpression(JavaExpression):
    value: Any = None
    literal_kind: str = "unknown"
    source_text: str = ""

@dataclass(frozen=True, slots=True)
class UnresolvedNameExpression(JavaExpression):
    name: str = ""

@dataclass(frozen=True, slots=True)
class VariableExpression(JavaExpression):
    name: str = ""
    symbol_id: str | None = None

@dataclass(frozen=True, slots=True)
class ThisExpression(JavaExpression):
    pass

@dataclass(frozen=True, slots=True)
class SuperExpression(JavaExpression):
    pass

@dataclass(frozen=True, slots=True)
class ParenthesizedExpression(JavaExpression):
    expression: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class FieldAccessExpression(JavaExpression):
    target: JavaExpression | None = None
    field_name: str = ""

@dataclass(frozen=True, slots=True)
class ArrayAccessExpression(JavaExpression):
    target: JavaExpression | None = None
    index: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class MethodCallExpression(JavaExpression):
    target: JavaExpression | None = None
    method_name: str = ""
    arguments: tuple[JavaExpression, ...] = ()

@dataclass(frozen=True, slots=True)
class ObjectCreationExpression(JavaExpression):
    type_name: str = ""
    arguments: tuple[JavaExpression, ...] = ()

@dataclass(frozen=True, slots=True)
class UnaryExpression(JavaExpression):
    operator: str = ""
    operand: JavaExpression | None = None
    postfix: bool = False

@dataclass(frozen=True, slots=True)
class BinaryExpression(JavaExpression):
    left: JavaExpression | None = None
    operator: str = ""
    right: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class AssignmentExpression(JavaExpression):
    target: JavaExpression | None = None
    operator: str = "="
    value: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class ConditionalExpression(JavaExpression):
    condition: JavaExpression | None = None
    when_true: JavaExpression | None = None
    when_false: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class CastExpression(JavaExpression):
    type_name: str = ""
    expression: JavaExpression | None = None
