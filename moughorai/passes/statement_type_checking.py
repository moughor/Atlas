from __future__ import annotations

from dataclasses import dataclass

from moughorai.java_semantics.statements import (
    BlockStatement,
    BreakStatement,
    ContinueStatement,
    ExpressionStatement,
    IfStatement,
    JavaStatement,
    LocalVariableDeclaration,
    ReturnStatement,
    ThrowStatement,
    WhileStatement,
)
from moughorai.semantic import Diagnostic, DiagnosticSeverity, PassContext, SemanticDocument
from moughorai.semantic.types import NullType, PrimitiveType, Type, TypeRegistry, UnknownType

from .base import PassDescriptor, SemanticPass
from .expression_type_inference import infer_expression_type
from .variable_type_inference import is_assignment_compatible, resolve_declared_type

STATEMENT_NON_BOOLEAN_CONDITION = "ATLAS-STMT-001"
STATEMENT_DECLARATION_TYPE_MISMATCH = "ATLAS-STMT-002"
STATEMENT_RETURN_TYPE_MISMATCH = "ATLAS-STMT-003"
STATEMENT_MISSING_RETURN_VALUE = "ATLAS-STMT-004"
STATEMENT_UNEXPECTED_RETURN_VALUE = "ATLAS-STMT-005"
STATEMENT_INVALID_THROW_TYPE = "ATLAS-STMT-006"
STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP = "ATLAS-STMT-007"
STATEMENT_UNREACHABLE = "ATLAS-STMT-008"


@dataclass(frozen=True, slots=True)
class StatementTypeCheckingResult:
    statement: JavaStatement
    diagnostics: tuple[Diagnostic, ...] = ()
    completes_normally: bool = True


def _diagnostic(
    code: str,
    message: str,
    statement: JavaStatement,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity=severity,
        location=statement.span,
        pass_name="statement_type_checking",
    )


def _normalize_expected_return_type(
    expected_return_type: Type | str | None,
    registry: TypeRegistry,
) -> Type | None:
    if expected_return_type is None:
        return None
    if isinstance(expected_return_type, Type):
        return expected_return_type
    if isinstance(expected_return_type, str):
        normalized = expected_return_type.strip()
        if normalized == "void":
            return registry.void
        return resolve_declared_type(normalized, registry)
    raise TypeError("expected_return_type must be a Type, string, or None")


def check_statement_types(
    statement: JavaStatement,
    symbols=None,
    registry: TypeRegistry | None = None,
    expected_return_type: Type | str | None = None,
) -> StatementTypeCheckingResult:
    if not isinstance(statement, JavaStatement):
        raise TypeError("statement must be a JavaStatement")

    target = registry if registry is not None else TypeRegistry()
    expected = _normalize_expected_return_type(expected_return_type, target)
    diagnostics: list[Diagnostic] = []
    boolean_type = target.primitive("boolean")

    def expression_type(expression):
        result = infer_expression_type(expression, symbols, target)
        diagnostics.extend(result.diagnostics)
        return result.semantic_type

    def check(node: JavaStatement | None, loop_depth: int = 0) -> bool:
        if node is None:
            return True

        if isinstance(node, BlockStatement):
            reachable = True
            for child in node.statements:
                if not reachable:
                    diagnostics.append(_diagnostic(
                        STATEMENT_UNREACHABLE,
                        "Unreachable statement.",
                        child,
                        DiagnosticSeverity.WARNING,
                    ))
                child_completes = check(child, loop_depth)
                if reachable:
                    reachable = child_completes
            return reachable

        if isinstance(node, LocalVariableDeclaration):
            if node.initializer is None:
                return True
            initializer_type = expression_type(node.initializer)
            if node.type_name.strip() == "var":
                return True
            declared_type = resolve_declared_type(node.type_name, target)
            if not is_assignment_compatible(declared_type, initializer_type):
                diagnostics.append(_diagnostic(
                    STATEMENT_DECLARATION_TYPE_MISMATCH,
                    f"Cannot assign {initializer_type.display_name} to variable "
                    f"'{node.name}' of type {declared_type.display_name}.",
                    node,
                ))
            return True

        if isinstance(node, ExpressionStatement):
            if node.expression is not None:
                expression_type(node.expression)
            return True

        if isinstance(node, IfStatement):
            condition_type = expression_type(node.condition)
            if not isinstance(condition_type, UnknownType) and condition_type != boolean_type:
                diagnostics.append(_diagnostic(
                    STATEMENT_NON_BOOLEAN_CONDITION,
                    f"If condition must be boolean, not {condition_type.display_name}.",
                    node,
                ))
            then_completes = check(node.then_branch, loop_depth)
            else_completes = True if node.else_branch is None else check(node.else_branch, loop_depth)
            return then_completes or else_completes

        if isinstance(node, WhileStatement):
            condition_type = expression_type(node.condition)
            if not isinstance(condition_type, UnknownType) and condition_type != boolean_type:
                diagnostics.append(_diagnostic(
                    STATEMENT_NON_BOOLEAN_CONDITION,
                    f"While condition must be boolean, not {condition_type.display_name}.",
                    node,
                ))
            check(node.body, loop_depth + 1)
            return True

        if isinstance(node, ReturnStatement):
            if expected is not None:
                if expected == target.void:
                    if node.expression is not None:
                        diagnostics.append(_diagnostic(
                            STATEMENT_UNEXPECTED_RETURN_VALUE,
                            "A void context cannot return a value.",
                            node,
                        ))
                elif node.expression is None:
                    diagnostics.append(_diagnostic(
                        STATEMENT_MISSING_RETURN_VALUE,
                        f"Return statement must provide a value of type {expected.display_name}.",
                        node,
                    ))
                else:
                    actual = expression_type(node.expression)
                    if not is_assignment_compatible(expected, actual):
                        diagnostics.append(_diagnostic(
                            STATEMENT_RETURN_TYPE_MISMATCH,
                            f"Cannot return {actual.display_name} from a context expecting "
                            f"{expected.display_name}.",
                            node,
                        ))
            elif node.expression is not None:
                expression_type(node.expression)
            return False

        if isinstance(node, ThrowStatement):
            thrown_type = expression_type(node.expression)
            if (
                isinstance(thrown_type, PrimitiveType)
                or thrown_type == target.void
                or isinstance(thrown_type, NullType)
            ):
                diagnostics.append(_diagnostic(
                    STATEMENT_INVALID_THROW_TYPE,
                    f"Throw expression must have a non-null reference type, not "
                    f"{thrown_type.display_name}.",
                    node,
                ))
            return False

        if isinstance(node, (BreakStatement, ContinueStatement)):
            if loop_depth == 0:
                keyword = "break" if isinstance(node, BreakStatement) else "continue"
                diagnostics.append(_diagnostic(
                    STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP,
                    f"{keyword} may only be used inside a loop.",
                    node,
                ))
            return False

        return True

    completes_normally = check(statement)
    return StatementTypeCheckingResult(statement, tuple(diagnostics), completes_normally)


class StatementTypeCheckingPass(SemanticPass):
    descriptor = PassDescriptor(
        name="statement_type_checking",
        requires=frozenset({"symbols"}),
        produces=frozenset(),
    )

    def __init__(
        self,
        registry: TypeRegistry | None = None,
        expected_return_type: Type | str | None = None,
    ) -> None:
        self.registry = registry if registry is not None else TypeRegistry()
        self.expected_return_type = expected_return_type

    def run(self, document: SemanticDocument, context: PassContext) -> SemanticDocument:
        expected = self.expected_return_type
        if expected is None:
            expected = document.metadata.get("expected_return_type")
        result = check_statement_types(
            document.syntax_tree,
            document.symbols,
            self.registry,
            expected,
        )
        return document.with_diagnostics(result.diagnostics)


__all__ = [
    "STATEMENT_DECLARATION_TYPE_MISMATCH",
    "STATEMENT_INVALID_THROW_TYPE",
    "STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP",
    "STATEMENT_MISSING_RETURN_VALUE",
    "STATEMENT_NON_BOOLEAN_CONDITION",
    "STATEMENT_RETURN_TYPE_MISMATCH",
    "STATEMENT_UNEXPECTED_RETURN_VALUE",
    "STATEMENT_UNREACHABLE",
    "StatementTypeCheckingPass",
    "StatementTypeCheckingResult",
    "check_statement_types",
]