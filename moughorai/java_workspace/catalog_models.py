"""Immutable workspace catalog models for large Java codebases."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BuildSystem(str, Enum):
    UNKNOWN = "unknown"
    MAVEN = "maven"
    GRADLE = "gradle"


class SourceRootKind(str, Enum):
    MAIN = "main"
    TEST = "test"
    GENERATED = "generated"
    RESOURCE = "resource"


@dataclass(frozen=True, order=True)
class SourceRoot:
    path: Path
    kind: SourceRootKind = SourceRootKind.MAIN
    language: str = "java"


@dataclass(frozen=True, order=True)
class BinaryLibrary:
    path: Path
    scope: str = "compile"
    coordinates: str | None = None


@dataclass(frozen=True)
class WorkspaceModule:
    key: str
    name: str
    root: Path
    build_system: BuildSystem = BuildSystem.UNKNOWN
    descriptor: Path | None = None
    source_roots: tuple[SourceRoot, ...] = ()
    libraries: tuple[BinaryLibrary, ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("module key must not be empty")
        if not self.name.strip():
            raise ValueError("module name must not be empty")


@dataclass(frozen=True)
class WorkspaceCatalog:
    root: Path
    modules: tuple[WorkspaceModule, ...] = ()
    schema_version: int = 1
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def module(self, key: str) -> WorkspaceModule | None:
        normalized = key.casefold()
        return next((m for m in self.modules if m.key.casefold() == normalized), None)

    @property
    def source_roots(self) -> tuple[SourceRoot, ...]:
        return tuple(root for module in self.modules for root in module.source_roots)

    @property
    def libraries(self) -> tuple[BinaryLibrary, ...]:
        return tuple(library for module in self.modules for library in module.libraries)
