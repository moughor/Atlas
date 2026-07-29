from __future__ import annotations

from moughorai.semantic.types.relations import PRIMITIVE_WIDENING

from dataclasses import dataclass
from typing import Iterable

from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import Type
from moughorai.passes.method_resolution import MethodSignature

LAMBDA_ARITY_MISMATCH = "ATLAS-LAMBDA-001"
LAMBDA_PARAMETER_MISMATCH = "ATLAS-LAMBDA-002"
LAMBDA_RETURN_MISMATCH = "ATLAS-LAMBDA-003"
METHOD_REFERENCE_NOT_FOUND = "ATLAS-LAMBDA-004"
METHOD_REFERENCE_AMBIGUOUS = "ATLAS-LAMBDA-005"
METHOD_REFERENCE_STATIC_MISMATCH = "ATLAS-LAMBDA-006"



@dataclass(frozen=True, slots=True)
class FunctionalInterface:
    name: str
    parameter_types: tuple[Type, ...]
    return_type: Type


@dataclass(frozen=True, slots=True)
class LambdaExpression:
    parameter_types: tuple[Type | None, ...]
    return_types: tuple[Type, ...]


@dataclass(frozen=True, slots=True)
class MethodReference:
    owner: str
    name: str
    kind: str = "static"

    def __post_init__(self) -> None:
        if self.kind not in {"static", "bound", "unbound", "constructor"}:
            raise ValueError("Method-reference kind must be static, bound, unbound, or constructor")


@dataclass(frozen=True, slots=True)
class TargetTypingResult:
    compatible: bool
    diagnostics: tuple[Diagnostic, ...] = ()
    selected: MethodSignature | None = None


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        location=None,
        pass_name="functional_interface_typing",
    )


def _assignable(expected: Type, actual: Type) -> bool:
    if expected == actual or actual.is_unknown:
        return True
    if actual.kind.value == "null" and expected.is_reference:
        return True
    expected_name = expected.display_name
    actual_name = actual.display_name
    if actual.kind.value == "primitive" and expected.kind.value == "primitive":
        return expected_name in PRIMITIVE_WIDENING.get(actual_name, ())
    if expected.is_reference and actual.is_reference:
        return expected_name in {"Object", "java.lang.Object"}
    return False


def check_lambda(
    expression: LambdaExpression,
    target: FunctionalInterface,
) -> TargetTypingResult:
    diagnostics: list[Diagnostic] = []
    if len(expression.parameter_types) != len(target.parameter_types):
        diagnostics.append(_diag(
            LAMBDA_ARITY_MISMATCH,
            f"Lambda declares {len(expression.parameter_types)} parameters but "
            f"target '{target.name}' requires {len(target.parameter_types)}.",
        ))
        return TargetTypingResult(False, tuple(diagnostics))

    for index, (declared, expected) in enumerate(
        zip(expression.parameter_types, target.parameter_types), start=1
    ):
        if declared is not None and declared != expected:
            diagnostics.append(_diag(
                LAMBDA_PARAMETER_MISMATCH,
                f"Lambda parameter {index} has type '{declared.display_name}' but "
                f"target requires '{expected.display_name}'.",
            ))

    target_is_void = target.return_type.display_name == "void"
    if not target_is_void:
        if not expression.return_types:
            diagnostics.append(_diag(
                LAMBDA_RETURN_MISMATCH,
                f"Lambda targeting '{target.name}' must return "
                f"'{target.return_type.display_name}'.",
            ))
        for actual in expression.return_types:
            if not _assignable(target.return_type, actual):
                diagnostics.append(_diag(
                    LAMBDA_RETURN_MISMATCH,
                    f"Lambda return type '{actual.display_name}' is not compatible with "
                    f"'{target.return_type.display_name}'.",
                ))
    elif expression.return_types:
        diagnostics.append(_diag(
            LAMBDA_RETURN_MISMATCH,
            f"Void lambda target '{target.name}' cannot return a value.",
        ))

    return TargetTypingResult(not diagnostics, tuple(diagnostics))


def _reference_parameter_types(
    reference: MethodReference,
    signature: MethodSignature,
) -> tuple[Type, ...]:
    if reference.kind == "unbound":
        # TypeName::instanceMethod consumes the receiver as the first SAM parameter.
        from moughorai.semantic.types import TypeRegistry
        return (TypeRegistry().class_type(signature.owner),) + signature.parameter_types
    return signature.parameter_types


def resolve_method_reference(
    reference: MethodReference,
    target: FunctionalInterface,
    candidates: Iterable[MethodSignature],
) -> TargetTypingResult:
    named = tuple(
        candidate for candidate in candidates
        if candidate.owner == reference.owner
        and candidate.name == ("<init>" if reference.kind == "constructor" else reference.name)
        and candidate.is_constructor == (reference.kind == "constructor")
    )
    if not named:
        return TargetTypingResult(False, (_diag(
            METHOD_REFERENCE_NOT_FOUND,
            f"No referenced member '{reference.owner}::{reference.name}' was found.",
        ),))

    context_matches: list[MethodSignature] = []
    for candidate in named:
        if reference.kind == "static" and not candidate.is_static:
            continue
        if reference.kind in {"bound", "unbound"} and candidate.is_static:
            continue
        context_matches.append(candidate)

    if not context_matches:
        return TargetTypingResult(False, (_diag(
            METHOD_REFERENCE_STATIC_MISMATCH,
            f"Referenced member '{reference.owner}::{reference.name}' does not match "
            f"the requested {reference.kind} form.",
        ),))

    applicable: list[MethodSignature] = []
    for candidate in context_matches:
        parameters = _reference_parameter_types(reference, candidate)
        if len(parameters) != len(target.parameter_types):
            continue
        if not all(
            _assignable(candidate_parameter, target_parameter)
            for candidate_parameter, target_parameter in zip(parameters, target.parameter_types)
        ):
            continue
        result_type = candidate.return_type
        if target.return_type.display_name != "void" and not _assignable(target.return_type, result_type):
            continue
        applicable.append(candidate)

    if not applicable:
        return TargetTypingResult(False, (_diag(
            METHOD_REFERENCE_NOT_FOUND,
            f"No overload of '{reference.owner}::{reference.name}' is compatible with "
            f"functional interface '{target.name}'.",
        ),))
    if len(applicable) > 1:
        return TargetTypingResult(False, (_diag(
            METHOD_REFERENCE_AMBIGUOUS,
            f"Method reference '{reference.owner}::{reference.name}' is ambiguous "
            f"between {len(applicable)} overloads.",
        ),))
    return TargetTypingResult(True, (), applicable[0])


__all__ = [
    "FunctionalInterface", "LambdaExpression", "MethodReference",
    "TargetTypingResult", "check_lambda", "resolve_method_reference",
    "LAMBDA_ARITY_MISMATCH", "LAMBDA_PARAMETER_MISMATCH",
    "LAMBDA_RETURN_MISMATCH", "METHOD_REFERENCE_NOT_FOUND",
    "METHOD_REFERENCE_AMBIGUOUS", "METHOD_REFERENCE_STATIC_MISMATCH",
]
