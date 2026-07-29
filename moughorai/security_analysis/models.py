from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class Severity(str, Enum):
    INFO='info'; LOW='low'; MEDIUM='medium'; HIGH='high'; CRITICAL='critical'
class Confidence(str, Enum):
    LOW='low'; MEDIUM='medium'; HIGH='high'
class ValueKind(str, Enum):
    LITERAL='literal'; VARIABLE='variable'; CONCAT='concat'; CALL='call'; UNKNOWN='unknown'

@dataclass(frozen=True, slots=True)
class SourceLocation:
    path: str
    line: int
    column: int = 1
    def __post_init__(self):
        if not self.path.strip(): raise ValueError('path must not be empty')
        if self.line < 1 or self.column < 1: raise ValueError('line and column must be positive')

@dataclass(frozen=True, slots=True)
class Expression:
    kind: ValueKind
    value: Any = None
    parts: tuple['Expression', ...] = ()
    location: SourceLocation | None = None
    @classmethod
    def literal(cls, value, location=None): return cls(ValueKind.LITERAL, value, (), location)
    @classmethod
    def variable(cls, name, location=None): return cls(ValueKind.VARIABLE, name, (), location)
    @classmethod
    def concat(cls, *parts, location=None): return cls(ValueKind.CONCAT, None, tuple(parts), location)
    @classmethod
    def call(cls, name, *args, location=None): return cls(ValueKind.CALL, name, tuple(args), location)

@dataclass(frozen=True, slots=True)
class Assignment:
    target: str
    value: Expression
    location: SourceLocation

@dataclass(frozen=True, slots=True)
class Invocation:
    name: str
    arguments: tuple[Expression, ...]
    location: SourceLocation
    receiver: str | None = None
    metadata: tuple[tuple[str,str], ...] = ()

@dataclass(frozen=True, slots=True)
class SecurityProgram:
    assignments: tuple[Assignment, ...] = ()
    invocations: tuple[Invocation, ...] = ()
    annotations: tuple[str, ...] = ()
    configuration: tuple[tuple[str,str], ...] = ()

@dataclass(frozen=True, slots=True)
class TraceStep:
    message: str
    location: SourceLocation | None = None

@dataclass(frozen=True, slots=True)
class SecurityFinding:
    rule_id: str
    title: str
    message: str
    severity: Severity
    confidence: Confidence
    cwe: str
    owasp: str
    location: SourceLocation
    trace: tuple[TraceStep, ...] = ()
    properties: tuple[tuple[str, str], ...] = ()
    @property
    def fingerprint(self) -> str:
        return f'{self.rule_id}:{self.location.path}:{self.location.line}:{self.location.column}'

@dataclass(frozen=True, slots=True)
class ScanStatistics:
    rule_count: int
    finding_count: int
    critical: int
    high: int
    medium: int
    low: int
    info: int

@dataclass(frozen=True, slots=True)
class SecurityReport:
    findings: tuple[SecurityFinding, ...]
    statistics: ScanStatistics
    warnings: tuple[str, ...] = ()
