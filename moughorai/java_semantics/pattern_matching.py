"""Java pattern-matching semantic foundations.

PR12 models type-pattern compatibility and the scope of pattern variables on
the true and false outcomes of boolean conditions. The model is AST-independent
so parser integration can be added incrementally in a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping

from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import ClassType, NullType, Type, UnknownType


class PatternDiagnosticCode(str, Enum):
    INCOMPATIBLE_TYPE = "ATLAS-PATTERN-001"
    DUPLICATE_BINDING = "ATLAS-PATTERN-002"
    INVALID_BINDING_NAME = "ATLAS-PATTERN-003"
    PRIMITIVE_PATTERN = "ATLAS-PATTERN-004"


@dataclass(frozen=True, slots=True)
class PatternDiagnostic:
    code: PatternDiagnosticCode
    message: str
    variable: str | None = None

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            location=None,
            pass_name="pattern_matching",
        )


@dataclass(frozen=True, slots=True)
class TypePattern:
    target_type: Type
    variable: str

    def __post_init__(self) -> None:
        normalized = self.variable.strip()
        object.__setattr__(self, "variable", normalized)


@dataclass(frozen=True, slots=True)
class PatternBinding:
    name: str
    semantic_type: Type


@dataclass(slots=True)
class PatternScope:
    """Pattern variables definitely available on a control-flow edge."""

    bindings: dict[str, PatternBinding] = field(default_factory=dict)
    diagnostics: list[PatternDiagnostic] = field(default_factory=list)

    def copy(self) -> "PatternScope":
        return PatternScope(dict(self.bindings), list(self.diagnostics))

    def bind(self, binding: PatternBinding) -> bool:
        if not binding.name:
            self.diagnostics.append(
                PatternDiagnostic(
                    PatternDiagnosticCode.INVALID_BINDING_NAME,
                    "Pattern variable name must not be empty.",
                )
            )
            return False
        if binding.name in self.bindings:
            self.diagnostics.append(
                PatternDiagnostic(
                    PatternDiagnosticCode.DUPLICATE_BINDING,
                    f"Pattern variable '{binding.name}' is already in scope.",
                    binding.name,
                )
            )
            return False
        self.bindings[binding.name] = binding
        return True

    def contains(self, name: str) -> bool:
        return name in self.bindings

    def type_of(self, name: str) -> Type | None:
        binding = self.bindings.get(name)
        return binding.semantic_type if binding else None

    @property
    def standard_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(item.to_diagnostic() for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class PatternFlow:
    """Scopes available when a condition evaluates true or false."""

    when_true: PatternScope
    when_false: PatternScope

    def negated(self) -> "PatternFlow":
        return PatternFlow(self.when_false.copy(), self.when_true.copy())


Hierarchy = Mapping[str, tuple[str, ...]]


def _is_primitive(semantic_type: Type) -> bool:
    return semantic_type.kind.value == "primitive"


def _is_reference(semantic_type: Type) -> bool:
    return semantic_type.is_reference or isinstance(
        semantic_type, (NullType, UnknownType)
    )


def is_pattern_compatible(
    expression_type: Type,
    target_type: Type,
    hierarchy: Hierarchy | None = None,
) -> bool:
    """Conservative compatibility check for ``expr instanceof Target``.

    Unknown types remain analyzable. Reference types are accepted when equal,
    related by the supplied hierarchy, or when either side is Object.
    """
    if isinstance(expression_type, UnknownType):
        return True
    if _is_primitive(expression_type) or _is_primitive(target_type):
        return False
    if isinstance(expression_type, NullType):
        return True
    if expression_type == target_type:
        return True
    if not _is_reference(expression_type) or not _is_reference(target_type):
        return False

    expression_name = expression_type.display_name
    target_name = target_type.display_name
    object_names = {"Object", "java.lang.Object"}
    if expression_name in object_names or target_name in object_names:
        return True

    graph = hierarchy or {}
    expression_supers = set(graph.get(expression_name, ()))
    target_supers = set(graph.get(target_name, ()))
    return target_name in expression_supers or expression_name in target_supers


def analyze_type_pattern(
    expression_type: Type,
    pattern: TypePattern,
    incoming: PatternScope | None = None,
    hierarchy: Hierarchy | None = None,
) -> PatternFlow:
    base = incoming.copy() if incoming else PatternScope()
    false_scope = base.copy()
    true_scope = base.copy()

    if not pattern.variable:
        true_scope.diagnostics.append(
            PatternDiagnostic(
                PatternDiagnosticCode.INVALID_BINDING_NAME,
                "Pattern variable name must not be empty.",
            )
        )
        return PatternFlow(true_scope, false_scope)

    if _is_primitive(pattern.target_type):
        true_scope.diagnostics.append(
            PatternDiagnostic(
                PatternDiagnosticCode.PRIMITIVE_PATTERN,
                "Type patterns require a reference target type.",
                pattern.variable,
            )
        )
        return PatternFlow(true_scope, false_scope)

    if not is_pattern_compatible(expression_type, pattern.target_type, hierarchy):
        true_scope.diagnostics.append(
            PatternDiagnostic(
                PatternDiagnosticCode.INCOMPATIBLE_TYPE,
                (
                    f"Expression type '{expression_type.display_name}' cannot "
                    f"be matched against '{pattern.target_type.display_name}'."
                ),
                pattern.variable,
            )
        )
        return PatternFlow(true_scope, false_scope)

    true_scope.bind(PatternBinding(pattern.variable, pattern.target_type))
    return PatternFlow(true_scope, false_scope)


def analyze_and(
    left: PatternFlow,
    right: Callable[[PatternScope], PatternFlow],
) -> PatternFlow:
    """Analyze ``left && right``.

    The right operand executes only on the left true edge, so left-side pattern
    bindings are available while analyzing the right operand.
    """
    right_flow = right(left.when_true.copy())
    false_scope = intersect_scopes(left.when_false, right_flow.when_false)
    false_scope.diagnostics.extend(left.when_false.diagnostics)
    return PatternFlow(right_flow.when_true, false_scope)


def analyze_or(
    left: PatternFlow,
    right: Callable[[PatternScope], PatternFlow],
) -> PatternFlow:
    """Analyze ``left || right``.

    The right operand executes only on the left false edge. A binding is
    available after a true result only when both true-producing paths provide
    the same binding and type.
    """
    right_flow = right(left.when_false.copy())
    true_scope = intersect_scopes(left.when_true, right_flow.when_true)
    false_scope = right_flow.when_false
    return PatternFlow(true_scope, false_scope)


def intersect_scopes(*scopes: PatternScope) -> PatternScope:
    """Keep bindings that are identically present on every incoming edge."""
    if not scopes:
        return PatternScope()
    common = dict(scopes[0].bindings)
    for scope in scopes[1:]:
        common = {
            name: binding
            for name, binding in common.items()
            if scope.bindings.get(name) == binding
        }
    diagnostics: list[PatternDiagnostic] = []
    for scope in scopes:
        diagnostics.extend(scope.diagnostics)
    return PatternScope(common, diagnostics)


def empty_condition(incoming: PatternScope | None = None) -> PatternFlow:
    base = incoming.copy() if incoming else PatternScope()
    return PatternFlow(base.copy(), base.copy())


class PatternAnalyzer:
    """Small facade for composing pattern-flow operations."""

    def __init__(
        self,
        hierarchy: Hierarchy | None = None,
        initial: PatternScope | None = None,
    ) -> None:
        self.hierarchy = dict(hierarchy or {})
        self.initial = initial.copy() if initial else PatternScope()

    def type_pattern(
        self,
        expression_type: Type,
        target_type: Type,
        variable: str,
        incoming: PatternScope | None = None,
    ) -> PatternFlow:
        return analyze_type_pattern(
            expression_type,
            TypePattern(target_type, variable),
            incoming or self.initial,
            self.hierarchy,
        )