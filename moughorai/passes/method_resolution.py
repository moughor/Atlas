from __future__ import annotations

from moughorai.semantic.types.relations import PRIMITIVE_WIDENING

from dataclasses import dataclass
from typing import Iterable

from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import PrimitiveType, Type
from moughorai.semantic.types.base import TypeKind

METHOD_NOT_FOUND = "ATLAS-METHOD-001"
METHOD_AMBIGUOUS = "ATLAS-METHOD-002"
METHOD_INCOMPATIBLE_ARGUMENT = "ATLAS-METHOD-003"
METHOD_STATIC_CONTEXT_MISMATCH = "ATLAS-METHOD-004"


_BOXING = {
    "boolean": "java.lang.Boolean",
    "byte": "java.lang.Byte",
    "short": "java.lang.Short",
    "char": "java.lang.Character",
    "int": "java.lang.Integer",
    "long": "java.lang.Long",
    "float": "java.lang.Float",
    "double": "java.lang.Double",
}


@dataclass(frozen=True, slots=True)
class MethodSignature:
    owner: str
    name: str
    parameter_types: tuple[Type, ...]
    return_type: Type
    is_static: bool = False
    is_varargs: bool = False
    is_constructor: bool = False


@dataclass(frozen=True, slots=True)
class MethodResolutionResult:
    selected: MethodSignature | None
    diagnostics: tuple[Diagnostic, ...] = ()
    score: int | None = None


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        location=None,
        pass_name="method_resolution",
    )


def _conversion_cost(expected: Type, actual: Type) -> int | None:
    if actual.is_unknown:
        return 20

    if expected == actual:
        return 0

    if actual.kind is TypeKind.NULL and expected.is_reference:
        return 1

    if isinstance(expected, PrimitiveType) and isinstance(actual, PrimitiveType):
        widened = PRIMITIVE_WIDENING.get(actual.name, ())
        if expected.name in widened:
            return 1 + widened.index(expected.name)
        return None

    if isinstance(actual, PrimitiveType) and expected.is_reference:
        boxed = _BOXING.get(actual.name)
        if boxed and expected.display_name in {boxed, boxed.split(".")[-1]}:
            return 5

    if isinstance(expected, PrimitiveType) and actual.is_reference:
        boxed = _BOXING.get(expected.name)
        if boxed and actual.display_name in {boxed, boxed.split(".")[-1]}:
            return 5

    if expected.is_reference and actual.is_reference:
        if expected.display_name in {"java.lang.Object", "Object"}:
            return 10

    return None


def _applicability(
    signature: MethodSignature,
    arguments: tuple[Type, ...],
) -> int | None:
    parameters = signature.parameter_types

    if not signature.is_varargs:
        if len(parameters) != len(arguments):
            return None

        costs = [
            _conversion_cost(parameter, argument)
            for parameter, argument in zip(parameters, arguments)
        ]
        if any(cost is None for cost in costs):
            return None

        return sum(cost for cost in costs if cost is not None)

    if not parameters:
        return 30

    fixed_count = len(parameters) - 1
    if len(arguments) < fixed_count:
        return None

    costs = [
        _conversion_cost(parameters[index], arguments[index])
        for index in range(fixed_count)
    ]

    vararg_type = parameters[-1]
    costs.extend(
        _conversion_cost(vararg_type, argument)
        for argument in arguments[fixed_count:]
    )

    if any(cost is None for cost in costs):
        return None

    return 25 + sum(cost for cost in costs if cost is not None)


def resolve_method(
    owner: str,
    name: str,
    argument_types: Iterable[Type],
    candidates: Iterable[MethodSignature],
    *,
    static_context: bool | None = None,
    constructor: bool = False,
) -> MethodResolutionResult:
    arguments = tuple(argument_types)

    named = tuple(
        candidate
        for candidate in candidates
        if candidate.owner == owner
        and candidate.name == name
        and candidate.is_constructor == constructor
    )

    if static_context is not None:
        context_matches = tuple(
            candidate
            for candidate in named
            if candidate.is_static == static_context or candidate.is_constructor
        )

        if not context_matches and named:
            return MethodResolutionResult(
                None,
                (
                    _diag(
                        METHOD_STATIC_CONTEXT_MISMATCH,
                        f"Method '{owner}.{name}' is not valid in the requested "
                        "static/instance context.",
                    ),
                ),
            )

        named = context_matches

    scored = [
        (score, candidate)
        for candidate in named
        if (score := _applicability(candidate, arguments)) is not None
    ]

    if not scored:
        code = METHOD_INCOMPATIBLE_ARGUMENT if named else METHOD_NOT_FOUND
        kind = "constructor" if constructor else "method"

        return MethodResolutionResult(
            None,
            (
                _diag(
                    code,
                    f"No applicable {kind} '{owner}.{name}' for "
                    f"({', '.join(type_.display_name for type_ in arguments)}).",
                ),
            ),
        )

    scored.sort(key=lambda item: item[0])
    best_score = scored[0][0]
    best = [
        candidate
        for score, candidate in scored
        if score == best_score
    ]

    if len(best) != 1:
        return MethodResolutionResult(
            None,
            (
                _diag(
                    METHOD_AMBIGUOUS,
                    f"Invocation of '{owner}.{name}' is ambiguous between "
                    f"{len(best)} overloads.",
                ),
            ),
            best_score,
        )

    return MethodResolutionResult(best[0], (), best_score)


def resolve_constructor(
    owner: str,
    argument_types: Iterable[Type],
    candidates: Iterable[MethodSignature],
) -> MethodResolutionResult:
    return resolve_method(
        owner,
        "<init>",
        argument_types,
        candidates,
        constructor=True,
    )


__all__ = [
    "METHOD_AMBIGUOUS",
    "METHOD_INCOMPATIBLE_ARGUMENT",
    "METHOD_NOT_FOUND",
    "METHOD_STATIC_CONTEXT_MISMATCH",
    "MethodResolutionResult",
    "MethodSignature",
    "resolve_constructor",
    "resolve_method",
]