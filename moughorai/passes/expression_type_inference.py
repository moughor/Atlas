from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

from moughorai.java_semantics.expressions import (
    ArrayAccessExpression,
    AssignmentExpression,
    BinaryExpression,
    CastExpression,
    ConditionalExpression,
    JavaExpression,
    LiteralExpression,
    ObjectCreationExpression,
    ParenthesizedExpression,
    UnaryExpression,
    UnresolvedNameExpression,
    VariableExpression,
)
from moughorai.semantic import Diagnostic, DiagnosticSeverity, PassContext, SemanticDocument
from moughorai.semantic.types import ArrayType, PrimitiveType, Type, TypeRegistry, UnknownType

from .base import PassDescriptor, SemanticPass
from .literal_type_inference import infer_java_literal_type
from .variable_type_inference import is_assignment_compatible, resolve_declared_type

EXPRESSION_INVALID_OPERANDS = "ATLAS-TYPE-004"
EXPRESSION_CONDITIONAL_MISMATCH = "ATLAS-TYPE-005"
EXPRESSION_UNKNOWN_NAME = "ATLAS-TYPE-006"

_NUMERIC_ORDER = {"byte": 0, "short": 1, "char": 1, "int": 2, "long": 3, "float": 4, "double": 5}


@dataclass(frozen=True, slots=True)
class ExpressionTypeInferenceResult:
    expression: JavaExpression
    semantic_type: Type
    diagnostics: tuple[Diagnostic, ...] = ()


def expression_node_key(node: object) -> Hashable:
    span = getattr(node, "span", None)
    return ("expression", node.__class__.__name__, getattr(span, "start", None), getattr(span, "end", None))


def _diagnostic(code: str, message: str, expression: JavaExpression) -> Diagnostic:
    return Diagnostic(code=code, message=message, severity=DiagnosticSeverity.ERROR,
                      location=expression.span, pass_name="expression_type_inference")


def _numeric_promotion(left: Type, right: Type, registry: TypeRegistry) -> Type | None:
    if not isinstance(left, PrimitiveType) or not isinstance(right, PrimitiveType):
        return None
    if left.name not in _NUMERIC_ORDER or right.name not in _NUMERIC_ORDER:
        return None
    rank = max(_NUMERIC_ORDER[left.name], _NUMERIC_ORDER[right.name], _NUMERIC_ORDER["int"])
    name = next(name for name, value in _NUMERIC_ORDER.items() if value == rank and name != "char")
    return registry.primitive(name)


def infer_expression_type(expression: JavaExpression, symbols=None,
                          registry: TypeRegistry | None = None) -> ExpressionTypeInferenceResult:
    if not isinstance(expression, JavaExpression):
        raise TypeError("expression must be a JavaExpression")
    target = registry if registry is not None else TypeRegistry()
    diagnostics: list[Diagnostic] = []

    def infer(node: JavaExpression | None) -> Type:
        if node is None:
            return target.unknown
        if isinstance(node, LiteralExpression):
            return infer_java_literal_type(node.source_text, target).semantic_type
        if isinstance(node, (UnresolvedNameExpression, VariableExpression)):
            name = node.name
            matches = () if symbols is None else symbols.find_by_name(name)
            if matches:
                return matches[-1].semantic_type
            diagnostics.append(_diagnostic(EXPRESSION_UNKNOWN_NAME, f"Cannot resolve expression name '{name}'.", node))
            return target.unknown
        if isinstance(node, ParenthesizedExpression):
            return infer(node.expression)
        if isinstance(node, CastExpression):
            infer(node.expression)
            return resolve_declared_type(node.type_name, target)
        if isinstance(node, ObjectCreationExpression):
            for argument in node.arguments: infer(argument)
            return target.class_type(node.type_name)
        if isinstance(node, ArrayAccessExpression):
            base = infer(node.target); infer(node.index)
            return base.element_type if isinstance(base, ArrayType) else target.unknown
        if isinstance(node, UnaryExpression):
            operand = infer(node.operand)
            if node.operator == "!":
                if operand != target.primitive("boolean") and not isinstance(operand, UnknownType):
                    diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, "Operator ! requires a boolean operand.", node))
                return target.primitive("boolean")
            if node.operator in {"+", "-", "~", "++", "--"}:
                if not isinstance(operand, UnknownType) and not (isinstance(operand, PrimitiveType) and operand.name in _NUMERIC_ORDER):
                    diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, f"Operator {node.operator} requires a numeric operand.", node))
                    return target.unknown
                return target.primitive("int") if isinstance(operand, PrimitiveType) and operand.name in {"byte", "short", "char"} else operand
            return target.unknown
        if isinstance(node, BinaryExpression):
            left, right = infer(node.left), infer(node.right)
            if node.operator in {"&&", "||"}:
                boolean = target.primitive("boolean")
                if not isinstance(left, UnknownType) and left != boolean or not isinstance(right, UnknownType) and right != boolean:
                    diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, f"Operator {node.operator} requires boolean operands.", node))
                return boolean
            if node.operator in {"==", "!=", "<", "<=", ">", ">="}:
                return target.primitive("boolean")
            if node.operator == "+" and (left.display_name == "java.lang.String" or right.display_name == "java.lang.String"):
                return target.class_type("java.lang.String")
            promoted = _numeric_promotion(left, right, target)
            if promoted is None:
                if not isinstance(left, UnknownType) and not isinstance(right, UnknownType):
                    diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, f"Operator {node.operator} has incompatible operands {left.display_name} and {right.display_name}.", node))
                return target.unknown
            return promoted
        if isinstance(node, AssignmentExpression):
            left, right = infer(node.target), infer(node.value)
            if not is_assignment_compatible(left, right):
                diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, f"Cannot assign {right.display_name} to {left.display_name}.", node))
            return left
        if isinstance(node, ConditionalExpression):
            condition = infer(node.condition)
            true_type, false_type = infer(node.when_true), infer(node.when_false)
            boolean = target.primitive("boolean")
            if not isinstance(condition, UnknownType) and condition != boolean:
                diagnostics.append(_diagnostic(EXPRESSION_INVALID_OPERANDS, "Conditional expression requires a boolean condition.", node))
            if true_type == false_type: return true_type
            promoted = _numeric_promotion(true_type, false_type, target)
            if promoted is not None: return promoted
            if is_assignment_compatible(true_type, false_type): return true_type
            if is_assignment_compatible(false_type, true_type): return false_type
            diagnostics.append(_diagnostic(EXPRESSION_CONDITIONAL_MISMATCH, f"Conditional branches have incompatible types {true_type.display_name} and {false_type.display_name}.", node))
            return target.unknown
        return target.unknown

    result_type = infer(expression)
    return ExpressionTypeInferenceResult(expression, result_type, tuple(diagnostics))


def attach_expression_type(document: SemanticDocument, expression: JavaExpression,
                           registry: TypeRegistry | None = None) -> SemanticDocument:
    result = infer_expression_type(expression, document.symbols, registry)
    updated = document.with_type(expression_node_key(expression), result.semantic_type)
    return updated.with_diagnostics(result.diagnostics)


class ExpressionTypeInferencePass(SemanticPass):
    descriptor = PassDescriptor(name="expression_type_inference", requires=frozenset({"symbols"}), produces=frozenset({"types"}))

    def __init__(self, registry: TypeRegistry | None = None) -> None:
        self.registry = registry if registry is not None else TypeRegistry()

    def run(self, document: SemanticDocument, context: PassContext) -> SemanticDocument:
        result = document
        seen: set[int] = set()
        def visit(node: object | None) -> None:
            nonlocal result
            if node is None or id(node) in seen: return
            seen.add(id(node))
            if isinstance(node, JavaExpression):
                result = attach_expression_type(result, node, self.registry)
            if hasattr(node, "__dataclass_fields__"):
                for field_name in node.__dataclass_fields__:
                    value = getattr(node, field_name)
                    if hasattr(value, "__dataclass_fields__"): visit(value)
                    elif isinstance(value, tuple):
                        for item in value:
                            if hasattr(item, "__dataclass_fields__"): visit(item)
        visit(document.syntax_tree)
        return result


__all__ = ["EXPRESSION_INVALID_OPERANDS", "EXPRESSION_CONDITIONAL_MISMATCH", "EXPRESSION_UNKNOWN_NAME",
           "ExpressionTypeInferencePass", "ExpressionTypeInferenceResult", "attach_expression_type",
           "expression_node_key", "infer_expression_type"]