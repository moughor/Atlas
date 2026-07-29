from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Language(str, Enum):
    JAVA = "java"
    KOTLIN = "kotlin"
    SCALA = "scala"
    GROOVY = "groovy"


@dataclass(frozen=True, slots=True, order=True)
class SourceSpan:
    path: str
    line: int
    column: int = 1
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class IRParameter:
    name: str
    type_name: str = ""
    annotations: tuple[str, ...] = ()
    span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class IRCall:
    name: str
    receiver: str = ""
    arguments: tuple[str, ...] = ()
    span: SourceSpan | None = None

    @property
    def arity(self) -> int:
        return len(self.arguments)


@dataclass(frozen=True, slots=True)
class IRAssignment:
    target: str
    expression: str
    span: SourceSpan | None = None


@dataclass(frozen=True, slots=True)
class IRFunction:
    owner: str
    name: str
    parameters: tuple[IRParameter, ...]
    return_type: str
    body: str
    span: SourceSpan
    annotations: tuple[str, ...] = ()
    calls: tuple[IRCall, ...] = ()
    assignments: tuple[IRAssignment, ...] = ()
    returns: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()

    @property
    def arity(self) -> int:
        return len(self.parameters)

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}/{self.arity}"


@dataclass(frozen=True, slots=True)
class IRType:
    qualified_name: str
    simple_name: str
    kind: str
    span: SourceSpan
    functions: tuple[IRFunction, ...] = ()
    annotations: tuple[str, ...] = ()
    supertypes: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IRModule:
    path: str
    language: Language
    package: str
    imports: tuple[str, ...]
    types: tuple[IRType, ...]
    top_level_functions: tuple[IRFunction, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def functions(self) -> tuple[IRFunction, ...]:
        nested = tuple(fn for typ in self.types for fn in typ.functions)
        return tuple(sorted(nested + self.top_level_functions, key=lambda f: f.qualified_name))


@dataclass(frozen=True, slots=True, order=True)
class IRCallEdge:
    caller: str
    callee: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class CrossLanguageMetrics:
    module_count: int
    type_count: int
    function_count: int
    call_edge_count: int
    unresolved_call_count: int
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossLanguageWorkspace:
    modules: tuple[IRModule, ...]
    call_edges: tuple[IRCallEdge, ...]
    unresolved_calls: tuple[str, ...]
    metrics: CrossLanguageMetrics

    def function(self, qualified_name: str) -> IRFunction | None:
        for module in self.modules:
            for function in module.functions:
                if function.qualified_name == qualified_name:
                    return function
        return None

    def functions_named(self, name: str) -> tuple[IRFunction, ...]:
        return tuple(sorted((f for m in self.modules for f in m.functions if f.name == name), key=lambda f: f.qualified_name))
