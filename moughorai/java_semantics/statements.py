from __future__ import annotations
from dataclasses import dataclass
from .source import SourceSpan
from .expressions import JavaExpression

@dataclass(frozen=True, slots=True)
class JavaStatement:
    span: SourceSpan | None = None

@dataclass(frozen=True, slots=True)
class UnknownStatement(JavaStatement):
    text: str = ""

@dataclass(frozen=True, slots=True)
class BlockStatement(JavaStatement):
    statements: tuple[JavaStatement, ...] = ()

@dataclass(frozen=True, slots=True)
class ExpressionStatement(JavaStatement):
    expression: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class LocalVariableDeclaration(JavaStatement):
    type_name: str = ""
    name: str = ""
    initializer: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class ReturnStatement(JavaStatement):
    expression: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class ThrowStatement(JavaStatement):
    expression: JavaExpression | None = None

@dataclass(frozen=True, slots=True)
class IfStatement(JavaStatement):
    condition: JavaExpression | None = None
    then_branch: JavaStatement | None = None
    else_branch: JavaStatement | None = None

@dataclass(frozen=True, slots=True)
class WhileStatement(JavaStatement):
    condition: JavaExpression | None = None
    body: JavaStatement | None = None

@dataclass(frozen=True, slots=True)
class BreakStatement(JavaStatement):
    pass

@dataclass(frozen=True, slots=True)
class ContinueStatement(JavaStatement):
    pass
