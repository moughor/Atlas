"""Validated hierarchy graph for Java sealed types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from moughorai.semantic import Diagnostic, DiagnosticSeverity

from .sealed_types import SealedType, TypeOpenness


class HierarchyDiagnosticCode(str, Enum):
    INVALID_HIERARCHY = "ATLAS-SWITCH-004"
    INVALID_PERMITS = "ATLAS-SWITCH-005"


@dataclass(frozen=True, slots=True)
class HierarchyDiagnostic:
    code: HierarchyDiagnosticCode
    message: str
    type_name: str | None = None

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            location=None,
            pass_name="sealed_hierarchy",
        )


@dataclass(slots=True)
class HierarchyGraph:
    declarations: dict[str, SealedType] = field(default_factory=dict)
    diagnostics: list[HierarchyDiagnostic] = field(default_factory=list)

    @classmethod
    def from_types(cls, declarations: Iterable[SealedType]) -> "HierarchyGraph":
        graph = cls()
        for declaration in declarations:
            graph.add(declaration)
        graph.validate()
        return graph

    def add(self, declaration: SealedType) -> bool:
        if not declaration.name:
            self.diagnostics.append(
                HierarchyDiagnostic(
                    HierarchyDiagnosticCode.INVALID_HIERARCHY,
                    "A sealed hierarchy declaration must have a name.",
                )
            )
            return False
        if declaration.name in self.declarations:
            self.diagnostics.append(
                HierarchyDiagnostic(
                    HierarchyDiagnosticCode.INVALID_HIERARCHY,
                    f"Type '{declaration.name}' is declared more than once.",
                    declaration.name,
                )
            )
            return False
        self.declarations[declaration.name] = declaration
        return True

    def direct_children(self, name: str) -> tuple[str, ...]:
        declaration = self.declarations.get(name)
        if declaration is None:
            return ()
        explicit = list(declaration.permits)
        inferred = [
            item.name
            for item in self.declarations.values()
            if item.direct_supertype == name and item.name not in explicit
        ]
        return tuple(explicit + sorted(inferred))

    def ancestors(self, name: str) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        current = self.declarations.get(name)
        while current and current.direct_supertype:
            parent = current.direct_supertype
            if parent in seen:
                break
            seen.add(parent)
            result.append(parent)
            current = self.declarations.get(parent)
        return tuple(result)

    def is_subtype(self, child: str, parent: str) -> bool:
        return child == parent or parent in self.ancestors(child)

    def permitted_leaves(self, name: str) -> tuple[str, ...]:
        """Return finite leaves required to cover a sealed selector.

        Final and non-sealed direct branches are leaves. A sealed branch is
        recursively expanded. Unknown declarations are retained as leaves so
        analysis remains conservative while hierarchy diagnostics report them.
        """
        if name not in self.declarations:
            return (name,)

        result: list[str] = []
        visiting: set[str] = set()

        def visit(type_name: str) -> None:
            if type_name in visiting:
                return
            declaration = self.declarations.get(type_name)
            if declaration is None:
                if type_name not in result:
                    result.append(type_name)
                return
            children = self.direct_children(type_name)
            if declaration.openness is not TypeOpenness.SEALED or not children:
                if type_name != name and type_name not in result:
                    result.append(type_name)
                return
            visiting.add(type_name)
            for child in children:
                visit(child)
            visiting.remove(type_name)

        visit(name)
        return tuple(result)

    def validate(self) -> tuple[HierarchyDiagnostic, ...]:
        existing = list(self.diagnostics)
        self.diagnostics = existing

        for declaration in self.declarations.values():
            if len(set(declaration.permits)) != len(declaration.permits):
                self.diagnostics.append(
                    HierarchyDiagnostic(
                        HierarchyDiagnosticCode.INVALID_PERMITS,
                        f"Type '{declaration.name}' contains duplicate permits entries.",
                        declaration.name,
                    )
                )
            if (
                declaration.openness is not TypeOpenness.SEALED
                and declaration.permits
            ):
                self.diagnostics.append(
                    HierarchyDiagnostic(
                        HierarchyDiagnosticCode.INVALID_PERMITS,
                        f"Only a sealed type may declare permitted subtypes: '{declaration.name}'.",
                        declaration.name,
                    )
                )
            for child_name in declaration.permits:
                child = self.declarations.get(child_name)
                if child is None:
                    self.diagnostics.append(
                        HierarchyDiagnostic(
                            HierarchyDiagnosticCode.INVALID_PERMITS,
                            f"Permitted subtype '{child_name}' is not declared.",
                            declaration.name,
                        )
                    )
                    continue
                if child.direct_supertype != declaration.name:
                    self.diagnostics.append(
                        HierarchyDiagnostic(
                            HierarchyDiagnosticCode.INVALID_PERMITS,
                            (
                                f"Permitted subtype '{child_name}' must directly extend "
                                f"'{declaration.name}'."
                            ),
                            child_name,
                        )
                    )

        for declaration in self.declarations.values():
            seen: set[str] = set()
            current = declaration
            while current.direct_supertype:
                parent = current.direct_supertype
                if parent == declaration.name or parent in seen:
                    self.diagnostics.append(
                        HierarchyDiagnostic(
                            HierarchyDiagnosticCode.INVALID_HIERARCHY,
                            f"Inheritance cycle detected at '{declaration.name}'.",
                            declaration.name,
                        )
                    )
                    break
                seen.add(parent)
                parent_decl = self.declarations.get(parent)
                if parent_decl is None:
                    break
                current = parent_decl

        unique: list[HierarchyDiagnostic] = []
        keys: set[tuple[HierarchyDiagnosticCode, str, str | None]] = set()
        for diagnostic in self.diagnostics:
            key = (diagnostic.code, diagnostic.message, diagnostic.type_name)
            if key not in keys:
                keys.add(key)
                unique.append(diagnostic)
        self.diagnostics = unique
        return tuple(self.diagnostics)

    @property
    def standard_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(item.to_diagnostic() for item in self.diagnostics)