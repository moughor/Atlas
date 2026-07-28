from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.security_analysis.rules import TaintRule

class Framework(str, Enum):
    SPRING_WEB='spring-web'; SPRING_SECURITY='spring-security'; SERVLET='servlet'; JDBC='jdbc'; JPA='jpa'; JACKSON='jackson'; GSON='gson'

@dataclass(frozen=True, slots=True)
class FrameworkProfile:
    framework: Framework
    markers: tuple[str, ...]
    sources: tuple[str, ...] = ()
    sanitizers: tuple[str, ...] = ()
    rules: tuple[TaintRule, ...] = ()
    entrypoint_annotations: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class FrameworkDetection:
    frameworks: tuple[Framework, ...]
    evidence: tuple[tuple[str, str], ...]

@dataclass(frozen=True, slots=True)
class FrameworkAnalysisMetrics:
    detected_frameworks: int
    active_sources: int
    active_sanitizers: int
    active_rules: int
    finding_count: int

@dataclass(frozen=True, slots=True)
class FrameworkAnalysisReport:
    detection: FrameworkDetection
    taint_report: object
    metrics: FrameworkAnalysisMetrics
