from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JavaLocalVariable:
    type_name: str
    name: str
    initializer: str | None = None


@dataclass(frozen=True, slots=True)
class JavaAssignment:
    target: str
    expression: str


@dataclass(frozen=True, slots=True)
class JavaCall:
    qualifier: str | None
    method_name: str
    arguments: tuple[str, ...]
    expression: str


@dataclass(frozen=True, slots=True)
class JavaObjectCreation:
    type_name: str
    arguments: tuple[str, ...]
    expression: str


@dataclass(frozen=True, slots=True)
class JavaReturn:
    expression: str | None


@dataclass(frozen=True, slots=True)
class JavaControlStatement:
    kind: str
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class JavaMethodBody:
    source: str
    local_variables: tuple[JavaLocalVariable, ...] = ()
    assignments: tuple[JavaAssignment, ...] = ()
    calls: tuple[JavaCall, ...] = ()
    object_creations: tuple[JavaObjectCreation, ...] = ()
    returns: tuple[JavaReturn, ...] = ()
    control_statements: tuple[JavaControlStatement, ...] = ()
