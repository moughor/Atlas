from __future__ import annotations
from dataclasses import dataclass, field, replace
from enum import Enum
from .expressions import *
from .statements import *

class ScopeKind(str, Enum):
    METHOD = "METHOD"
    BLOCK = "BLOCK"
    BRANCH = "BRANCH"
    LOOP = "LOOP"

class SymbolKind(str, Enum):
    LOCAL_VARIABLE = "LOCAL_VARIABLE"
    PARAMETER = "PARAMETER"

@dataclass(frozen=True, slots=True)
class Symbol:
    symbol_id: str
    name: str
    type_name: str
    kind: SymbolKind
    scope_id: str
    declaration_start: int = 0

@dataclass(slots=True)
class Scope:
    scope_id: str
    kind: ScopeKind
    parent: "Scope | None" = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list["Scope"] = field(default_factory=list)

    def declare(self, symbol: Symbol) -> None:
        self.symbols[symbol.name] = symbol

    def lookup(self, name: str) -> Symbol | None:
        current = self
        while current is not None:
            found = current.symbols.get(name)
            if found is not None:
                return found
            current = current.parent
        return None

@dataclass(frozen=True, slots=True)
class ResolutionResult:
    root: BlockStatement
    root_scope: Scope
    unresolved_names: tuple[str, ...]

class ScopeBuilder:
    def build(self, root: BlockStatement) -> Scope:
        counter = {"scope": 0, "symbol": 0}

        def new_scope(kind, parent):
            counter["scope"] += 1
            scope = Scope(f"scope:{counter['scope']}", kind, parent)
            if parent:
                parent.children.append(scope)
            return scope

        root_scope = new_scope(ScopeKind.METHOD, None)

        def visit_statement(stmt, scope):
            if isinstance(stmt, BlockStatement):
                block_scope = root_scope if stmt is root else new_scope(ScopeKind.BLOCK, scope)
                for child in stmt.statements:
                    visit_statement(child, block_scope)
            elif isinstance(stmt, LocalVariableDeclaration):
                counter["symbol"] += 1
                scope.declare(Symbol(
                    f"symbol:{counter['symbol']}", stmt.name, stmt.type_name,
                    SymbolKind.LOCAL_VARIABLE, scope.scope_id,
                    stmt.span.start if stmt.span else 0,
                ))
            elif isinstance(stmt, IfStatement):
                then_scope = new_scope(ScopeKind.BRANCH, scope)
                visit_statement(stmt.then_branch, then_scope)
                if stmt.else_branch:
                    else_scope = new_scope(ScopeKind.BRANCH, scope)
                    visit_statement(stmt.else_branch, else_scope)
            elif isinstance(stmt, WhileStatement):
                loop_scope = new_scope(ScopeKind.LOOP, scope)
                visit_statement(stmt.body, loop_scope)

        visit_statement(root, root_scope)
        return root_scope

class LocalResolver:
    def resolve(self, root: BlockStatement, root_scope: Scope) -> ResolutionResult:
        unresolved = []

        def resolve_expr(expr, scope):
            if expr is None:
                return None
            if isinstance(expr, UnresolvedNameExpression):
                current = scope
                symbol = None
                position = expr.span.start if expr.span else 10**18
                while current is not None and symbol is None:
                    candidate = current.symbols.get(expr.name)
                    if candidate is not None and candidate.declaration_start <= position:
                        symbol = candidate
                    current = current.parent
                if symbol is None:
                    unresolved.append(expr.name)
                    return expr
                return VariableExpression(expr.span, expr.name, symbol.symbol_id)
            if isinstance(expr, ParenthesizedExpression):
                return replace(expr, expression=resolve_expr(expr.expression, scope))
            if isinstance(expr, FieldAccessExpression):
                return replace(expr, target=resolve_expr(expr.target, scope))
            if isinstance(expr, ArrayAccessExpression):
                return replace(expr, target=resolve_expr(expr.target, scope), index=resolve_expr(expr.index, scope))
            if isinstance(expr, MethodCallExpression):
                return replace(expr, target=resolve_expr(expr.target, scope),
                               arguments=tuple(resolve_expr(a, scope) for a in expr.arguments))
            if isinstance(expr, ObjectCreationExpression):
                return replace(expr, arguments=tuple(resolve_expr(a, scope) for a in expr.arguments))
            if isinstance(expr, UnaryExpression):
                return replace(expr, operand=resolve_expr(expr.operand, scope))
            if isinstance(expr, BinaryExpression):
                return replace(expr, left=resolve_expr(expr.left, scope), right=resolve_expr(expr.right, scope))
            if isinstance(expr, AssignmentExpression):
                return replace(expr, target=resolve_expr(expr.target, scope), value=resolve_expr(expr.value, scope))
            if isinstance(expr, ConditionalExpression):
                return replace(expr,
                    condition=resolve_expr(expr.condition, scope),
                    when_true=resolve_expr(expr.when_true, scope),
                    when_false=resolve_expr(expr.when_false, scope))
            if isinstance(expr, CastExpression):
                return replace(expr, expression=resolve_expr(expr.expression, scope))
            return expr

        child_positions = {}

        def next_child(scope, kind):
            key = (scope.scope_id, kind)
            index = child_positions.get(key, 0)
            candidates = [c for c in scope.children if c.kind == kind]
            child_positions[key] = index + 1
            return candidates[index] if index < len(candidates) else scope

        def resolve_stmt(stmt, scope):
            if isinstance(stmt, BlockStatement):
                active = root_scope if stmt is root else next_child(scope, ScopeKind.BLOCK)
                return replace(stmt, statements=tuple(resolve_stmt(s, active) for s in stmt.statements))
            if isinstance(stmt, LocalVariableDeclaration):
                return replace(stmt, initializer=resolve_expr(stmt.initializer, scope))
            if isinstance(stmt, ExpressionStatement):
                return replace(stmt, expression=resolve_expr(stmt.expression, scope))
            if isinstance(stmt, ReturnStatement):
                return replace(stmt, expression=resolve_expr(stmt.expression, scope))
            if isinstance(stmt, ThrowStatement):
                return replace(stmt, expression=resolve_expr(stmt.expression, scope))
            if isinstance(stmt, IfStatement):
                condition = resolve_expr(stmt.condition, scope)
                then_scope = next_child(scope, ScopeKind.BRANCH)
                then_branch = resolve_stmt(stmt.then_branch, then_scope)
                else_branch = None
                if stmt.else_branch:
                    else_scope = next_child(scope, ScopeKind.BRANCH)
                    else_branch = resolve_stmt(stmt.else_branch, else_scope)
                return replace(stmt, condition=condition, then_branch=then_branch, else_branch=else_branch)
            if isinstance(stmt, WhileStatement):
                condition = resolve_expr(stmt.condition, scope)
                loop_scope = next_child(scope, ScopeKind.LOOP)
                return replace(stmt, condition=condition, body=resolve_stmt(stmt.body, loop_scope))
            return stmt

        resolved_root = resolve_stmt(root, root_scope)
        return ResolutionResult(resolved_root, root_scope, tuple(unresolved))
