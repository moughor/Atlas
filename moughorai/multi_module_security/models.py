from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.java_security import JavaSourceUnit
from moughorai.security_analysis import SecurityReport

class ModuleKind(str, Enum):
    MAVEN='maven'; GRADLE='gradle'; PLAIN='plain'

@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    name: str
    root: str
    kind: ModuleKind = ModuleKind.PLAIN
    dependencies: tuple[str, ...] = ()
    sources: tuple[JavaSourceUnit, ...] = ()
    coordinates: str | None = None
    def __post_init__(self):
        if not self.name.strip(): raise ValueError('module name must not be empty')
        if not self.root.strip(): raise ValueError('module root must not be empty')

@dataclass(frozen=True, slots=True)
class ModuleGraph:
    modules: tuple[ModuleDescriptor, ...]
    edges: tuple[tuple[str,str], ...]
    unresolved_dependencies: tuple[tuple[str,str], ...] = ()
    cycles: tuple[tuple[str,...], ...] = ()
    def by_name(self): return {m.name:m for m in self.modules}
    def dependencies_of(self,name): return tuple(dst for src,dst in self.edges if src==name)
    def dependents_of(self,name): return tuple(src for src,dst in self.edges if dst==name)

@dataclass(frozen=True, slots=True)
class ModuleScanResult:
    module: str
    report: SecurityReport
    source_files: int

@dataclass(frozen=True, slots=True)
class WorkspaceScanMetrics:
    module_count: int
    source_files: int
    dependency_edges: int
    unresolved_dependencies: int
    cycle_count: int

@dataclass(frozen=True, slots=True)
class WorkspaceSecurityResult:
    report: SecurityReport
    graph: ModuleGraph
    module_results: tuple[ModuleScanResult,...]
    scan_order: tuple[str,...]
    metrics: WorkspaceScanMetrics
