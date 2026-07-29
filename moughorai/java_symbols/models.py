"""Immutable semantic symbol models for parsed Java sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from moughorai.java_ast.ast_nodes import TypeKind


class SymbolKind(str, Enum):
    TYPE = "type"
    FIELD = "field"
    CONSTRUCTOR = "constructor"
    METHOD = "method"


@dataclass(frozen=True)
class JavaSymbol:
    kind: SymbolKind
    name: str
    qualified_name: str
    owner: str | None
    source: Path | None


@dataclass(frozen=True)
class TypeSymbol(JavaSymbol):
    type_kind: TypeKind
    package_name: str
    modifiers: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldSymbol(JavaSymbol):
    type_name: str
    modifiers: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True)
class CallableSymbol(JavaSymbol):
    parameter_types: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()
    throws: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConstructorSymbol(CallableSymbol):
    pass


@dataclass(frozen=True)
class MethodSymbol(CallableSymbol):
    return_type: str = "void"
