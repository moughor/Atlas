from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from moughorai.security_analysis import Confidence, SecurityFinding, Severity, SourceLocation, TraceStep


class TaintKind(str, Enum):
    CLEAN = "clean"
    TAINTED = "tainted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class JavaMethodId:
    owner: str
    name: str
    arity: int

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}/{self.arity}"


@dataclass(frozen=True, slots=True)
class JavaMethod:
    method_id: JavaMethodId
    parameters: tuple[str, ...]
    body: str
    location: SourceLocation
    end_line: int
    return_type: str = ""
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JavaType:
    qualified_name: str
    simple_name: str
    path: str
    methods: tuple[JavaMethod, ...]
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaintValue:
    kind: TaintKind = TaintKind.CLEAN
    trace: tuple[TraceStep, ...] = ()

    @property
    def tainted(self) -> bool:
        return self.kind is TaintKind.TAINTED

    @classmethod
    def clean(cls) -> "TaintValue":
        return cls(TaintKind.CLEAN)

    @classmethod
    def taint(cls, message: str, location: SourceLocation | None = None) -> "TaintValue":
        return cls(TaintKind.TAINTED, (TraceStep(message, location),))

    def append(self, message: str, location: SourceLocation | None = None) -> "TaintValue":
        if not self.tainted:
            return self
        return TaintValue(self.kind, self.trace + (TraceStep(message, location),))

    @classmethod
    def merge(cls, *values: "TaintValue") -> "TaintValue":
        tainted = [value for value in values if value.tainted]
        if not tainted:
            return cls.clean()
        seen: set[tuple[str, str, int, int]] = set()
        trace: list[TraceStep] = []
        for value in tainted:
            for step in value.trace:
                loc = step.location
                key = (step.message, loc.path if loc else "", loc.line if loc else 0, loc.column if loc else 0)
                if key not in seen:
                    seen.add(key)
                    trace.append(step)
        return cls(TaintKind.TAINTED, tuple(trace))


@dataclass(frozen=True, slots=True)
class MethodSummary:
    method_id: JavaMethodId
    tainted_return_parameters: tuple[int, ...] = ()
    source_return: bool = False
    sanitized_return: bool = False
    field_writes: tuple[tuple[str, tuple[int, ...]], ...] = ()
    sink_parameters: tuple[tuple[str, int, SourceLocation], ...] = ()
    calls: tuple[JavaMethodId, ...] = ()


@dataclass(frozen=True, slots=True)
class InterproceduralTaintMetrics:
    type_count: int
    method_count: int
    call_edge_count: int
    analyzed_contexts: int
    summary_iterations: int
    finding_count: int
    unresolved_calls: int


@dataclass(frozen=True, slots=True)
class InterproceduralTaintReport:
    findings: tuple[SecurityFinding, ...]
    summaries: tuple[MethodSummary, ...]
    metrics: InterproceduralTaintMetrics
    warnings: tuple[str, ...] = ()

    def findings_for_rule(self, rule_id: str) -> tuple[SecurityFinding, ...]:
        return tuple(finding for finding in self.findings if finding.rule_id == rule_id)
