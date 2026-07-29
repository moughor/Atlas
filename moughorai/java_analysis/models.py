"""Immutable models for deterministic Java source parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class JavaSourceSet(str, Enum):
    MAIN = "main"
    TEST = "test"
    GENERATED = "generated"
    UNKNOWN = "unknown"


class JavaTypeKind(str, Enum):
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    RECORD = "record"
    ANNOTATION = "annotation"


@dataclass(frozen=True)
class JavaImport:
    qualified_name: str
    is_static: bool = False
    is_wildcard: bool = False

    @property
    def package_name(self) -> str:
        if self.is_wildcard:
            return self.qualified_name.removesuffix(".*")

        if "." not in self.qualified_name:
            return ""

        return self.qualified_name.rsplit(".", maxsplit=1)[0]


@dataclass(frozen=True)
class JavaAnnotation:
    qualified_name: str

    @property
    def simple_name(self) -> str:
        return self.qualified_name.rsplit(".", maxsplit=1)[-1]


@dataclass(frozen=True)
class JavaTypeDeclaration:
    name: str
    kind: JavaTypeKind
    annotations: tuple[JavaAnnotation, ...] = ()
    modifiers: tuple[str, ...] = ()

    @property
    def is_public(self) -> bool:
        return "public" in self.modifiers


@dataclass(frozen=True)
class JavaSourceFile:
    path: Path
    package_name: str | None
    imports: tuple[JavaImport, ...]
    types: tuple[JavaTypeDeclaration, ...]
    source_set: JavaSourceSet

    @property
    def primary_type(self) -> JavaTypeDeclaration | None:
        stem = self.path.stem

        for declaration in self.types:
            if declaration.name == stem:
                return declaration

        return self.types[0] if self.types else None

    @property
    def qualified_primary_name(self) -> str | None:
        primary = self.primary_type

        if primary is None:
            return None

        if not self.package_name:
            return primary.name

        return f"{self.package_name}.{primary.name}"
