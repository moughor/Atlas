"""Recursive validation and binding extraction for Java record patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from moughorai.semantic import Diagnostic, DiagnosticSeverity

from .record_patterns import (
    ComponentPattern,
    ComponentPatternKind,
    RecordDeclaration,
    RecordPattern,
    RecordPatternBinding,
)


class RecordPatternDiagnosticCode(str, Enum):
    INVALID_PATTERN = "ATLAS-RECORD-001"
    COMPONENT_COUNT = "ATLAS-RECORD-002"
    TYPE_MISMATCH = "ATLAS-RECORD-003"
    DUPLICATE_BINDING = "ATLAS-RECORD-004"
    INVALID_NESTED_PATTERN = "ATLAS-RECORD-005"
    UNSUPPORTED_DECOMPOSITION = "ATLAS-RECORD-006"


@dataclass(frozen=True, slots=True)
class RecordPatternDiagnostic:
    code: RecordPatternDiagnosticCode
    message: str
    component_path: tuple[int, ...] = ()

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            location=None,
            pass_name="record_patterns",
        )


@dataclass(frozen=True, slots=True)
class RecordPatternResult:
    valid: bool
    bindings: tuple[RecordPatternBinding, ...]
    diagnostics: tuple[RecordPatternDiagnostic, ...]

    @property
    def standard_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(item.to_diagnostic() for item in self.diagnostics)


@dataclass(slots=True)
class RecordPatternRegistry:
    declarations: dict[str, RecordDeclaration] = field(default_factory=dict)

    @classmethod
    def from_records(
        cls, declarations: Iterable[RecordDeclaration]
    ) -> "RecordPatternRegistry":
        registry = cls()
        for declaration in declarations:
            registry.add(declaration)
        return registry

    def add(self, declaration: RecordDeclaration) -> bool:
        if not declaration.name or declaration.name in self.declarations:
            return False
        self.declarations[declaration.name] = declaration
        return True

    def get(self, name: str) -> RecordDeclaration | None:
        return self.declarations.get(name)


@dataclass(slots=True)
class RecordPatternValidator:
    registry: RecordPatternRegistry
    subtype_relations: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def validate(
        self,
        pattern: RecordPattern,
        *,
        selector_type: str | None = None,
    ) -> RecordPatternResult:
        diagnostics: list[RecordPatternDiagnostic] = []
        bindings: list[RecordPatternBinding] = []
        binding_names: set[str] = set()
        self._validate_pattern(
            pattern,
            selector_type=selector_type,
            path=(),
            diagnostics=diagnostics,
            bindings=bindings,
            binding_names=binding_names,
        )
        return RecordPatternResult(
            valid=not diagnostics,
            bindings=tuple(bindings),
            diagnostics=tuple(diagnostics),
        )

    def _validate_pattern(
        self,
        pattern: RecordPattern,
        *,
        selector_type: str | None,
        path: tuple[int, ...],
        diagnostics: list[RecordPatternDiagnostic],
        bindings: list[RecordPatternBinding],
        binding_names: set[str],
    ) -> None:
        declaration = self.registry.get(pattern.record_type)
        if declaration is None:
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.UNSUPPORTED_DECOMPOSITION,
                    f"Type '{pattern.record_type}' is not a known record type.",
                    path,
                )
            )
            return

        if selector_type and not self._is_compatible(pattern.record_type, selector_type):
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.INVALID_PATTERN,
                    (
                        f"Record pattern '{pattern.record_type}' is not compatible "
                        f"with selector type '{selector_type}'."
                    ),
                    path,
                )
            )

        substitutions = self._substitutions(declaration, pattern, diagnostics, path)
        expected_components = declaration.components
        if len(pattern.components) != len(expected_components):
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.COMPONENT_COUNT,
                    (
                        f"Record pattern '{pattern.record_type}' expects "
                        f"{len(expected_components)} components but received "
                        f"{len(pattern.components)}."
                    ),
                    path,
                )
            )

        for index, component_pattern in enumerate(pattern.components):
            if index >= len(expected_components):
                break
            component = expected_components[index]
            expected_type = substitutions.get(component.type_name, component.type_name)
            self._validate_component(
                component_pattern,
                expected_type=expected_type,
                path=path + (index,),
                diagnostics=diagnostics,
                bindings=bindings,
                binding_names=binding_names,
            )

    def _substitutions(
        self,
        declaration: RecordDeclaration,
        pattern: RecordPattern,
        diagnostics: list[RecordPatternDiagnostic],
        path: tuple[int, ...],
    ) -> dict[str, str]:
        if not pattern.type_arguments:
            return {}
        if len(pattern.type_arguments) != len(declaration.type_parameters):
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.INVALID_PATTERN,
                    (
                        f"Record type '{declaration.name}' expects "
                        f"{len(declaration.type_parameters)} type arguments but received "
                        f"{len(pattern.type_arguments)}."
                    ),
                    path,
                )
            )
            return {}
        return dict(zip(declaration.type_parameters, pattern.type_arguments))

    def _validate_component(
        self,
        component: ComponentPattern,
        *,
        expected_type: str,
        path: tuple[int, ...],
        diagnostics: list[RecordPatternDiagnostic],
        bindings: list[RecordPatternBinding],
        binding_names: set[str],
    ) -> None:
        if component.kind is ComponentPatternKind.UNNAMED:
            return

        if component.kind is ComponentPatternKind.RECORD:
            if component.record is None:
                diagnostics.append(
                    RecordPatternDiagnostic(
                        RecordPatternDiagnosticCode.INVALID_NESTED_PATTERN,
                        "Nested record pattern is missing its record declaration.",
                        path,
                    )
                )
                return
            if not self._is_compatible(component.record.record_type, expected_type):
                diagnostics.append(
                    RecordPatternDiagnostic(
                        RecordPatternDiagnosticCode.INVALID_NESTED_PATTERN,
                        (
                            f"Nested record pattern '{component.record.record_type}' "
                            f"is not compatible with component type '{expected_type}'."
                        ),
                        path,
                    )
                )
            self._validate_pattern(
                component.record,
                selector_type=expected_type,
                path=path,
                diagnostics=diagnostics,
                bindings=bindings,
                binding_names=binding_names,
            )
            return

        binding = (component.binding or "").strip()
        if not binding:
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.INVALID_PATTERN,
                    "A binding component pattern must declare a variable name.",
                    path,
                )
            )
            return

        binding_type = expected_type
        if component.kind is ComponentPatternKind.TYPE:
            declared_type = (component.type_name or "").strip()
            if not declared_type:
                diagnostics.append(
                    RecordPatternDiagnostic(
                        RecordPatternDiagnosticCode.INVALID_PATTERN,
                        "A typed component pattern must declare a type.",
                        path,
                    )
                )
                return
            binding_type = declared_type
            if not self._is_compatible(declared_type, expected_type):
                diagnostics.append(
                    RecordPatternDiagnostic(
                        RecordPatternDiagnosticCode.TYPE_MISMATCH,
                        (
                            f"Component pattern type '{declared_type}' is not compatible "
                            f"with record component type '{expected_type}'."
                        ),
                        path,
                    )
                )

        if binding in binding_names:
            diagnostics.append(
                RecordPatternDiagnostic(
                    RecordPatternDiagnosticCode.DUPLICATE_BINDING,
                    f"Pattern variable '{binding}' is declared more than once.",
                    path,
                )
            )
            return

        binding_names.add(binding)
        bindings.append(RecordPatternBinding(binding, binding_type, path))

    def _is_compatible(self, candidate: str, expected: str) -> bool:
        if candidate == expected or candidate in {"Object", "java.lang.Object"}:
            return True
        return expected in self.subtype_relations.get(candidate, ())