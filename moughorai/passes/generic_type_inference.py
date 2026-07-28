from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import ArrayType, ClassType, GenericType, Type, TypeRegistry

GENERIC_INFERENCE_CONFLICT = "ATLAS-GENERIC-001"
GENERIC_INFERENCE_UNRESOLVED = "ATLAS-GENERIC-002"
GENERIC_INFERENCE_ARITY = "ATLAS-GENERIC-003"


@dataclass(frozen=True, slots=True)
class GenericInferenceResult:
    substitutions: Mapping[str, Type]
    resolved_return_type: Type
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.diagnostics


def _diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        location=None,
        pass_name="generic_type_inference",
    )


def _is_variable(template: Type, variables: frozenset[str]) -> bool:
    return isinstance(template, ClassType) and template.name in variables


def _same_raw_type(left: GenericType, right: GenericType) -> bool:
    return left.base_type.display_name == right.base_type.display_name


def _collect_constraint(
    template: Type,
    actual: Type,
    variables: frozenset[str],
    substitutions: dict[str, Type],
    diagnostics: list[Diagnostic],
) -> None:
    if _is_variable(template, variables):
        name = template.display_name
        existing = substitutions.get(name)
        if existing is None or existing.is_unknown:
            substitutions[name] = actual
        elif actual.is_unknown:
            return
        elif existing != actual:
            diagnostics.append(
                _diag(
                    GENERIC_INFERENCE_CONFLICT,
                    f"Conflicting inferred types for '{name}': "
                    f"{existing.display_name} and {actual.display_name}.",
                )
            )
        return

    if isinstance(template, ArrayType) and isinstance(actual, ArrayType):
        if template.dimensions == actual.dimensions:
            _collect_constraint(
                template.element_type,
                actual.element_type,
                variables,
                substitutions,
                diagnostics,
            )
        return

    if isinstance(template, GenericType) and isinstance(actual, GenericType):
        if not _same_raw_type(template, actual):
            return
        if len(template.arguments) != len(actual.arguments):
            diagnostics.append(
                _diag(
                    GENERIC_INFERENCE_ARITY,
                    f"Generic arity mismatch for '{template.base_type.display_name}'.",
                )
            )
            return
        for expected_argument, actual_argument in zip(template.arguments, actual.arguments):
            _collect_constraint(
                expected_argument,
                actual_argument,
                variables,
                substitutions,
                diagnostics,
            )


def substitute_type(
    template: Type,
    substitutions: Mapping[str, Type],
    *,
    registry: TypeRegistry | None = None,
) -> Type:
    target = registry if registry is not None else TypeRegistry()

    if isinstance(template, ClassType) and template.name in substitutions:
        return substitutions[template.name]

    if isinstance(template, ArrayType):
        return target.array(
            substitute_type(template.element_type, substitutions, registry=target),
            template.dimensions,
        )

    if isinstance(template, GenericType):
        return target.generic(
            template.base_type,
            tuple(
                substitute_type(argument, substitutions, registry=target)
                for argument in template.arguments
            ),
        )

    return template


def infer_method_type_arguments(
    type_parameters: Iterable[str],
    parameter_types: Iterable[Type],
    argument_types: Iterable[Type],
    return_type: Type,
    *,
    explicit_type_arguments: Iterable[Type] | None = None,
    registry: TypeRegistry | None = None,
) -> GenericInferenceResult:
    names = tuple(name.strip() for name in type_parameters)
    variables = frozenset(name for name in names if name)
    parameters = tuple(parameter_types)
    arguments = tuple(argument_types)
    diagnostics: list[Diagnostic] = []
    substitutions: dict[str, Type] = {}

    if len(parameters) != len(arguments):
        diagnostics.append(
            _diag(
                GENERIC_INFERENCE_ARITY,
                f"Expected {len(parameters)} arguments but received {len(arguments)}.",
            )
        )

    if explicit_type_arguments is not None:
        explicit = tuple(explicit_type_arguments)
        if len(explicit) != len(names):
            diagnostics.append(
                _diag(
                    GENERIC_INFERENCE_ARITY,
                    f"Expected {len(names)} explicit type arguments but received {len(explicit)}.",
                )
            )
        else:
            substitutions.update(zip(names, explicit))

    for parameter, argument in zip(parameters, arguments):
        _collect_constraint(
            parameter,
            argument,
            variables,
            substitutions,
            diagnostics,
        )

    unresolved = [name for name in names if name not in substitutions]
    if unresolved:
        diagnostics.append(
            _diag(
                GENERIC_INFERENCE_UNRESOLVED,
                "Could not infer type arguments: " + ", ".join(unresolved) + ".",
            )
        )

    resolved = substitute_type(return_type, substitutions, registry=registry)
    return GenericInferenceResult(dict(substitutions), resolved, tuple(diagnostics))


__all__ = [
    "GENERIC_INFERENCE_ARITY",
    "GENERIC_INFERENCE_CONFLICT",
    "GENERIC_INFERENCE_UNRESOLVED",
    "GenericInferenceResult",
    "infer_method_type_arguments",
    "substitute_type",
]