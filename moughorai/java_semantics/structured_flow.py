"""Structured statement reachability before CFG lowering removes dead tails."""
from __future__ import annotations
from dataclasses import dataclass
from .cfg_builder import (
    Stmt, ExprStmt, IfStmt, WhileStmt, ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt,
)
from .reachability import ReachabilityDiagnostic, ReachabilityDiagnosticCode

@dataclass(frozen=True, slots=True)
class StructuredFlowResult:
    can_complete_normally: bool
    always_returns_or_throws: bool
    diagnostics: tuple[ReachabilityDiagnostic, ...]

class StructuredFlowAnalyzer:
    def analyze(
        self,
        statements: tuple[Stmt, ...],
        *,
        requires_return: bool = False,
        constant_conditions: dict[str, bool] | None = None,
        in_loop: bool = False,
    ) -> StructuredFlowResult:
        constants = constant_conditions or {}
        diagnostics: list[ReachabilityDiagnostic] = []
        can_complete = True
        always_terminates = False

        for index, statement in enumerate(statements):
            if not can_complete:
                diagnostics.append(ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT,
                    f"Statement {index} is unreachable",
                    statement_index=index,
                ))
                continue
            result = self._statement(statement, constants, in_loop)
            diagnostics.extend(result.diagnostics)
            can_complete = result.can_complete_normally
            always_terminates = result.always_returns_or_throws if not can_complete else False

        if requires_return and can_complete:
            diagnostics.append(ReachabilityDiagnostic(
                ReachabilityDiagnosticCode.MISSING_RETURN,
                "Method can complete normally without returning a value",
            ))
        return StructuredFlowResult(can_complete, always_terminates, tuple(dict.fromkeys(diagnostics)))

    def _statement(self, statement: Stmt, constants: dict[str, bool], in_loop: bool) -> StructuredFlowResult:
        if isinstance(statement, ExprStmt):
            return StructuredFlowResult(True, False, ())
        if isinstance(statement, (ReturnStmt, ThrowStmt)):
            return StructuredFlowResult(False, True, ())
        if isinstance(statement, BreakStmt):
            if not in_loop:
                diagnostic = ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.INVALID_BREAK,
                    "break statement is not inside a loop",
                )
                return StructuredFlowResult(False, False, (diagnostic,))
            return StructuredFlowResult(False, False, ())
        if isinstance(statement, ContinueStmt):
            if not in_loop:
                diagnostic = ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.INVALID_CONTINUE,
                    "continue statement is not inside a loop",
                )
                return StructuredFlowResult(False, False, (diagnostic,))
            return StructuredFlowResult(False, False, ())
        if isinstance(statement, IfStmt):
            then_result = self.analyze(statement.then_body, constant_conditions=constants, in_loop=in_loop)
            else_result = self.analyze(statement.else_body, constant_conditions=constants, in_loop=in_loop)
            diagnostic_list = list(then_result.diagnostics + else_result.diagnostics)
            constant = constants.get(statement.condition)
            if constant is True:
                if statement.else_body:
                    diagnostic_list.append(ReachabilityDiagnostic(
                        ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT,
                        f"Else branch for '{statement.condition}' is unreachable",
                    ))
                return StructuredFlowResult(
                    then_result.can_complete_normally,
                    then_result.always_returns_or_throws,
                    tuple(diagnostic_list),
                )
            if constant is False:
                if statement.then_body:
                    diagnostic_list.append(ReachabilityDiagnostic(
                        ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT,
                        f"Then branch for '{statement.condition}' is unreachable",
                    ))
                return StructuredFlowResult(
                    else_result.can_complete_normally,
                    else_result.always_returns_or_throws,
                    tuple(diagnostic_list),
                )
            can_complete = then_result.can_complete_normally or else_result.can_complete_normally
            always_terminates = (
                bool(statement.else_body)
                and then_result.always_returns_or_throws
                and else_result.always_returns_or_throws
            )
            return StructuredFlowResult(can_complete, always_terminates, tuple(diagnostic_list))
        if isinstance(statement, WhileStmt):
            body = self.analyze(statement.body, constant_conditions=constants, in_loop=True)
            diagnostics = list(body.diagnostics)
            constant = constants.get(statement.condition)
            contains_break = self._contains_break(statement.body)
            if constant is False and statement.body:
                diagnostics.append(ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT,
                    f"Loop body for '{statement.condition}' is unreachable",
                ))
                return StructuredFlowResult(True, False, tuple(diagnostics))
            if constant is True and not contains_break:
                diagnostics.append(ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.INFINITE_LOOP,
                    f"Loop '{statement.condition}' cannot complete normally",
                ))
                return StructuredFlowResult(False, False, tuple(diagnostics))
            return StructuredFlowResult(True, False, tuple(diagnostics))
        raise TypeError(type(statement).__name__)

    def _contains_break(self, statements: tuple[Stmt, ...]) -> bool:
        for statement in statements:
            if isinstance(statement, BreakStmt):
                return True
            if isinstance(statement, IfStmt):
                if self._contains_break(statement.then_body) or self._contains_break(statement.else_body):
                    return True
            if isinstance(statement, WhileStmt):
                continue
        return False