"""Exhaustiveness, duplication, and dominance analysis for Java switches."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from moughorai.semantic import Diagnostic, DiagnosticSeverity

from .hierarchy_graph import HierarchyGraph


class SwitchDiagnosticCode(str, Enum):
    NON_EXHAUSTIVE = "ATLAS-SWITCH-001"
    DUPLICATE_CASE = "ATLAS-SWITCH-002"
    DOMINATED_CASE = "ATLAS-SWITCH-003"


class SwitchCaseKind(str, Enum):
    TYPE = "type"
    DEFAULT = "default"
    NULL = "null"
    CONSTANT = "constant"


@dataclass(frozen=True, slots=True)
class SwitchDiagnostic:
    code: SwitchDiagnosticCode
    message: str
    case_index: int | None = None

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            location=None,
            pass_name="switch_exhaustiveness",
        )


@dataclass(frozen=True, slots=True)
class SwitchCase:
    kind: SwitchCaseKind
    value: str | None = None
    guarded: bool = False

    @classmethod
    def type(cls, type_name: str, guarded: bool = False) -> "SwitchCase":
        return cls(SwitchCaseKind.TYPE, type_name.strip(), guarded)

    @classmethod
    def default(cls) -> "SwitchCase":
        return cls(SwitchCaseKind.DEFAULT)

    @classmethod
    def null(cls) -> "SwitchCase":
        return cls(SwitchCaseKind.NULL)

    @classmethod
    def constant(cls, value: str) -> "SwitchCase":
        return cls(SwitchCaseKind.CONSTANT, value)


@dataclass(frozen=True, slots=True)
class ExhaustivenessResult:
    exhaustive: bool
    required_types: tuple[str, ...]
    covered_types: tuple[str, ...]
    missing_types: tuple[str, ...]
    diagnostics: tuple[SwitchDiagnostic, ...]

    @property
    def standard_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(item.to_diagnostic() for item in self.diagnostics)


@dataclass(slots=True)
class SwitchAnalyzer:
    hierarchy: HierarchyGraph

    def analyze(
        self,
        selector_type: str,
        cases: Iterable[SwitchCase],
        *,
        require_exhaustive: bool = True,
    ) -> ExhaustivenessResult:
        case_list = tuple(cases)
        required = self.hierarchy.permitted_leaves(selector_type)
        covered: list[str] = []
        diagnostics: list[SwitchDiagnostic] = []
        seen_exact: dict[tuple[SwitchCaseKind, str | None], int] = {}
        prior_unguarded_types: list[str] = []
        default_index: int | None = None

        for index, case in enumerate(case_list):
            exact_key = (case.kind, case.value)
            if exact_key in seen_exact and not case.guarded:
                diagnostics.append(
                    SwitchDiagnostic(
                        SwitchDiagnosticCode.DUPLICATE_CASE,
                        f"Duplicate switch case '{case.value or case.kind.value}'.",
                        index,
                    )
                )
            elif not case.guarded:
                seen_exact[exact_key] = index

            if default_index is not None:
                diagnostics.append(
                    SwitchDiagnostic(
                        SwitchDiagnosticCode.DOMINATED_CASE,
                        "A case after default is unreachable.",
                        index,
                    )
                )
                continue

            if case.kind is SwitchCaseKind.DEFAULT:
                default_index = index
                continue

            if case.kind is not SwitchCaseKind.TYPE or not case.value:
                continue

            dominated_by = next(
                (
                    prior
                    for prior in prior_unguarded_types
                    if self.hierarchy.is_subtype(case.value, prior)
                ),
                None,
            )
            if dominated_by is not None:
                diagnostics.append(
                    SwitchDiagnostic(
                        SwitchDiagnosticCode.DOMINATED_CASE,
                        (
                            f"Case type '{case.value}' is dominated by earlier "
                            f"case type '{dominated_by}'."
                        ),
                        index,
                    )
                )
                continue

            if not case.guarded:
                prior_unguarded_types.append(case.value)
                for required_type in required:
                    if self.hierarchy.is_subtype(required_type, case.value):
                        if required_type not in covered:
                            covered.append(required_type)

        missing = tuple(item for item in required if item not in covered)
        exhaustive = default_index is not None or not missing
        if require_exhaustive and not exhaustive:
            diagnostics.append(
                SwitchDiagnostic(
                    SwitchDiagnosticCode.NON_EXHAUSTIVE,
                    "Non-exhaustive switch; missing: " + ", ".join(missing) + ".",
                )
            )

        return ExhaustivenessResult(
            exhaustive=exhaustive,
            required_types=required,
            covered_types=tuple(covered),
            missing_types=missing,
            diagnostics=tuple(diagnostics),
        )