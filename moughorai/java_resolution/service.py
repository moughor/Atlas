"""Resolve type references found in parsed Java compilation units."""

from __future__ import annotations

from moughorai.java_ast.ast_nodes import CompilationUnit, TypeDeclaration
from moughorai.java_resolution.models import ResolvedTypeReference
from moughorai.java_resolution.resolver import JavaTypeResolver


class JavaTypeResolutionService:
    def __init__(self, resolver: JavaTypeResolver) -> None:
        self._resolver = resolver

    def resolve_unit(self, unit: CompilationUnit) -> tuple[ResolvedTypeReference, ...]:
        package_name = unit.package.name if unit.package else ""
        references: list[ResolvedTypeReference] = []
        for declaration in unit.types:
            owner = f"{package_name}.{declaration.name}" if package_name else declaration.name
            self._collect_type(unit, declaration, owner, references)
        return tuple(references)

    def _collect_type(
        self,
        unit: CompilationUnit,
        declaration: TypeDeclaration,
        owner: str,
        references: list[ResolvedTypeReference],
    ) -> None:
        if declaration.extends:
            self._append(unit, owner, "extends", declaration.extends, references)
        for name in declaration.implements:
            self._append(unit, owner, "implements", name, references)
        for name in declaration.permits:
            self._append(unit, owner, "permits", name, references)

        for field in declaration.fields:
            self._append(unit, owner, f"field:{field.name}", field.type_name, references)
        for constructor in declaration.constructors:
            for parameter in constructor.parameters:
                self._append(unit, owner, f"constructor-parameter:{parameter.name}", parameter.type_name, references)
            for thrown in constructor.throws:
                self._append(unit, owner, "constructor-throws", thrown, references)
        for method in declaration.methods:
            self._append(unit, owner, f"method-return:{method.name}", method.return_type, references)
            for parameter in method.parameters:
                self._append(unit, owner, f"method-parameter:{method.name}:{parameter.name}", parameter.type_name, references)
            for thrown in method.throws:
                self._append(unit, owner, f"method-throws:{method.name}", thrown, references)

        for nested in declaration.nested_types:
            self._collect_type(unit, nested, f"{owner}.{nested.name}", references)

    def _append(
        self,
        unit: CompilationUnit,
        owner: str,
        role: str,
        name: str,
        references: list[ResolvedTypeReference],
    ) -> None:
        references.append(
            ResolvedTypeReference(
                owner=owner,
                role=role,
                name=name,
                resolution=self._resolver.resolve(name, unit),
            )
        )
