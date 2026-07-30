"""Build semantic symbols from immutable Java AST nodes."""

from __future__ import annotations

from pathlib import Path

from moughorai.java_ast.ast_nodes import CompilationUnit, TypeDeclaration
from moughorai.java_symbols.index import JavaSymbolIndex
from moughorai.java_symbols.models import (
    ConstructorSymbol,
    FieldSymbol,
    JavaSymbol,
    MethodSymbol,
    SymbolKind,
    TypeSymbol,
)


class JavaSymbolIndexBuilder:
    """Collect fully qualified type and member symbols."""

    def build(
        self,
        units: tuple[CompilationUnit, ...],
        sources: tuple[Path | None, ...] | None = None,
        *,
        project_id: str | None = None,
    ) -> JavaSymbolIndex:
        if sources is not None and len(sources) != len(units):
            raise ValueError("sources must have the same length as units")

        symbols: list[JavaSymbol] = []
        for index, unit in enumerate(units):
            source = sources[index] if sources is not None else None
            package_name = unit.package.name if unit.package else ""
            for declaration in unit.types:
                self._collect_type(
                    declaration,
                    package_name=package_name,
                    enclosing_name=None,
                    source=source,
                    symbols=symbols,
                )
        return JavaSymbolIndex(symbols, project_id=project_id)

    def _collect_type(
        self,
        declaration: TypeDeclaration,
        *,
        package_name: str,
        enclosing_name: str | None,
        source: Path | None,
        symbols: list[JavaSymbol],
    ) -> None:
        if enclosing_name:
            qualified_name = f"{enclosing_name}.{declaration.name}"
        elif package_name:
            qualified_name = f"{package_name}.{declaration.name}"
        else:
            qualified_name = declaration.name

        symbols.append(
            TypeSymbol(
                kind=SymbolKind.TYPE,
                name=declaration.name,
                qualified_name=qualified_name,
                owner=enclosing_name,
                source=source,
                type_kind=declaration.kind,
                package_name=package_name,
                modifiers=declaration.modifiers,
                annotations=declaration.annotations,
            )
        )

        for field in declaration.fields:
            symbols.append(
                FieldSymbol(
                    kind=SymbolKind.FIELD,
                    name=field.name,
                    qualified_name=f"{qualified_name}.{field.name}",
                    owner=qualified_name,
                    source=source,
                    type_name=field.type_name,
                    modifiers=field.modifiers,
                    annotations=field.annotations,
                )
            )

        for constructor in declaration.constructors:
            parameter_types = tuple(p.type_name for p in constructor.parameters)
            signature = ",".join(parameter_types)
            symbols.append(
                ConstructorSymbol(
                    kind=SymbolKind.CONSTRUCTOR,
                    name=constructor.name,
                    qualified_name=f"{qualified_name}#<init>({signature})",
                    owner=qualified_name,
                    source=source,
                    parameter_types=parameter_types,
                    modifiers=constructor.modifiers,
                    annotations=constructor.annotations,
                    throws=constructor.throws,
                )
            )

        for method in declaration.methods:
            parameter_types = tuple(p.type_name for p in method.parameters)
            signature = ",".join(parameter_types)
            symbols.append(
                MethodSymbol(
                    kind=SymbolKind.METHOD,
                    name=method.name,
                    qualified_name=f"{qualified_name}#{method.name}({signature})",
                    owner=qualified_name,
                    source=source,
                    parameter_types=parameter_types,
                    modifiers=method.modifiers,
                    annotations=method.annotations,
                    throws=method.throws,
                    return_type=method.return_type,
                )
            )

        for nested in declaration.nested_types:
            self._collect_type(
                nested,
                package_name=package_name,
                enclosing_name=qualified_name,
                source=source,
                symbols=symbols,
            )
