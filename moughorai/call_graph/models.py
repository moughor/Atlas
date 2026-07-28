from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TypeKind(str, Enum):
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    RECORD = "record"
    ANNOTATION = "annotation"


class DispatchKind(str, Enum):
    STATIC = "static"
    SPECIAL = "special"
    VIRTUAL = "virtual"
    INTERFACE = "interface"
    DYNAMIC = "dynamic"


class CallSiteKind(str, Enum):
    INVOCATION = "invocation"
    CONSTRUCTOR = "constructor"
    METHOD_REFERENCE = "method_reference"
    LAMBDA = "lambda"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    POLYMORPHIC = "polymorphic"
    UNRESOLVED = "unresolved"
    EXTERNAL = "external"


@dataclass(frozen=True, order=True, slots=True)
class MethodId:
    owner: str
    name: str
    descriptor: str = "()"

    def __post_init__(self) -> None:
        for field_name in ("owner", "name", "descriptor"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}#{self.name}{self.descriptor}"

    def __str__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True, order=True, slots=True)
class TypeSymbol:
    qualified_name: str
    kind: TypeKind = TypeKind.CLASS
    super_type: str | None = None
    interfaces: tuple[str, ...] = ()
    abstract: bool = False
    external: bool = False

    def __post_init__(self) -> None:
        name = self.qualified_name.strip()
        if not name:
            raise ValueError("qualified_name must not be empty")
        object.__setattr__(self, "qualified_name", name)
        object.__setattr__(self, "interfaces", tuple(sorted(set(self.interfaces))))


@dataclass(frozen=True, order=True, slots=True)
class MethodSymbol:
    id: MethodId
    static: bool = False
    abstract: bool = False
    final: bool = False
    synthetic: bool = False
    external: bool = False
    source_path: str | None = None
    line: int | None = None
    annotations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "annotations", tuple(sorted(set(self.annotations))))
        if self.line is not None and self.line < 1:
            raise ValueError("line must be positive")


@dataclass(frozen=True, order=True, slots=True)
class CallSite:
    caller: MethodId
    declared_owner: str
    method_name: str
    descriptor: str = "()"
    dispatch: DispatchKind = DispatchKind.VIRTUAL
    kind: CallSiteKind = CallSiteKind.INVOCATION
    source_path: str | None = None
    line: int | None = None
    column: int | None = None
    ordinal: int = 0

    def __post_init__(self) -> None:
        for field_name in ("declared_owner", "method_name", "descriptor"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        if self.line is not None and self.line < 1:
            raise ValueError("line must be positive")
        if self.column is not None and self.column < 1:
            raise ValueError("column must be positive")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")

    @property
    def declared_target(self) -> MethodId:
        return MethodId(self.declared_owner, self.method_name, self.descriptor)

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.caller,
            self.source_path or "",
            self.line or 0,
            self.column or 0,
            self.ordinal,
            self.declared_owner,
            self.method_name,
            self.descriptor,
            self.dispatch.value,
            self.kind.value,
        )


@dataclass(frozen=True, order=True, slots=True)
class CallEdge:
    caller: MethodId
    callee: MethodId
    dispatch: DispatchKind
    kind: CallSiteKind = CallSiteKind.INVOCATION
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    source_path: str | None = None
    line: int | None = None
    column: int | None = None
    declared_target: MethodId | None = None

    @property
    def is_recursive(self) -> bool:
        return self.caller == self.callee


@dataclass(frozen=True, slots=True)
class Resolution:
    call_site: CallSite
    targets: tuple[MethodId, ...] = ()
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CallPath:
    methods: tuple[MethodId, ...]
    edges: tuple[CallEdge, ...] = ()
    cycle: bool = False

    @property
    def length(self) -> int:
        return len(self.edges)


@dataclass(frozen=True, slots=True)
class StronglyConnectedComponent:
    methods: tuple[MethodId, ...]
    recursive: bool = True


@dataclass(frozen=True, slots=True)
class CallGraphStatistics:
    method_count: int
    edge_count: int
    unresolved_call_sites: int
    external_method_count: int
    polymorphic_call_sites: int
    recursive_component_count: int


@dataclass(frozen=True, slots=True)
class BuildReport:
    graph: "CallGraph"
    resolutions: tuple[Resolution, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def unresolved(self) -> tuple[Resolution, ...]:
        return tuple(r for r in self.resolutions if r.status is ResolutionStatus.UNRESOLVED)

    @property
    def external(self) -> tuple[Resolution, ...]:
        return tuple(r for r in self.resolutions if r.status is ResolutionStatus.EXTERNAL)
