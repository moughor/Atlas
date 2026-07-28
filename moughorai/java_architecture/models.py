"""Immutable models for the deterministic Java architecture graph."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ArchitectureEdgeKind(str, Enum):
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    PERMITS = "permits"
    FIELD_TYPE = "field-type"
    CONSTRUCTOR_PARAMETER = "constructor-parameter"
    CONSTRUCTOR_THROWS = "constructor-throws"
    METHOD_RETURN = "method-return"
    METHOD_PARAMETER = "method-parameter"
    METHOD_THROWS = "method-throws"


@dataclass(frozen=True)
class ArchitectureNode:
    qualified_name: str
    simple_name: str
    type_kind: str
    package_name: str
    source: Path | None = None


@dataclass(frozen=True)
class ArchitectureEdge:
    source: str
    target: str
    kind: ArchitectureEdgeKind
    role: str
    requested_name: str


@dataclass(frozen=True)
class UnresolvedArchitectureReference:
    owner: str
    role: str
    requested_name: str
    status: str
    candidates: tuple[str, ...] = ()
