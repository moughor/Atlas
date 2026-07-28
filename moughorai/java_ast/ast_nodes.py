"""Immutable Java abstract syntax tree node definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class AstNode:
    """Base class for immutable Java AST nodes."""


class TypeKind(str, Enum):
    """Supported Java type declarations."""

    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    RECORD = "record"
    ANNOTATION = "annotation"


@dataclass(frozen=True)
class PackageDeclaration(AstNode):
    name: str


@dataclass(frozen=True)
class ImportDeclaration(AstNode):
    name: str
    is_static: bool = False
    is_wildcard: bool = False


@dataclass(frozen=True)
class AnnotationArgument(AstNode):
    name: str | None
    value: str


@dataclass(frozen=True)
class Annotation(AstNode):
    name: str
    arguments: tuple[AnnotationArgument, ...] = ()

    def argument(self, name: str = "value") -> str | None:
        for argument in self.arguments:
            effective_name = argument.name or "value"
            if effective_name == name:
                return argument.value
        return None


@dataclass(frozen=True)
class ParameterDeclaration(AstNode):
    """A method or constructor parameter."""

    name: str
    type_name: str
    annotations: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    is_varargs: bool = False
    annotation_nodes: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class FieldDeclaration(AstNode):
    """A field declaration. Initializer expressions are intentionally opaque."""

    name: str
    type_name: str
    annotations: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    initializer: str | None = None
    annotation_nodes: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class ConstructorDeclaration(AstNode):
    name: str
    parameters: tuple[ParameterDeclaration, ...] = ()
    annotations: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    throws: tuple[str, ...] = ()
    annotation_nodes: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class MethodDeclaration(AstNode):
    name: str
    return_type: str
    parameters: tuple[ParameterDeclaration, ...] = ()
    annotations: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    type_parameters: str | None = None
    throws: tuple[str, ...] = ()
    annotation_nodes: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class TypeDeclaration(AstNode):
    """Common representation of a Java type."""

    name: str
    kind: TypeKind
    annotations: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    extends: str | None = None
    implements: tuple[str, ...] = ()
    permits: tuple[str, ...] = ()
    fields: tuple[FieldDeclaration, ...] = ()
    constructors: tuple[ConstructorDeclaration, ...] = ()
    methods: tuple[MethodDeclaration, ...] = ()
    nested_types: tuple[TypeDeclaration, ...] = ()
    annotation_nodes: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class ClassDeclaration(TypeDeclaration):
    kind: TypeKind = TypeKind.CLASS


@dataclass(frozen=True)
class InterfaceDeclaration(TypeDeclaration):
    kind: TypeKind = TypeKind.INTERFACE


@dataclass(frozen=True)
class EnumDeclaration(TypeDeclaration):
    kind: TypeKind = TypeKind.ENUM


@dataclass(frozen=True)
class RecordDeclaration(TypeDeclaration):
    kind: TypeKind = TypeKind.RECORD


@dataclass(frozen=True)
class AnnotationDeclaration(TypeDeclaration):
    kind: TypeKind = TypeKind.ANNOTATION


@dataclass(frozen=True)
class CompilationUnit(AstNode):
    package: PackageDeclaration | None = None
    imports: tuple[ImportDeclaration, ...] = ()
    types: tuple[TypeDeclaration, ...] = ()
