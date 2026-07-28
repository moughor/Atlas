from __future__ import annotations
from dataclasses import dataclass, field
from moughorai.interprocedural_taint import InterproceduralTaintAnalyzer
from moughorai.java_security import JavaSourceUnit
from moughorai.security_analysis.rules import SOURCES, SANITIZERS, TAINT_RULES
from .catalog import PROFILES
from .detector import FrameworkDetector
from .models import FrameworkAnalysisMetrics, FrameworkAnalysisReport

@dataclass(slots=True)
class FrameworkAwareAnalyzer:
    detector: FrameworkDetector = field(default_factory=FrameworkDetector)
    def analyze_units(self, units: tuple[JavaSourceUnit,...] | list[JavaSourceUnit], configurations: tuple[tuple[str,str], ...]=(), entrypoints: tuple[str,...]=()):
        detection=self.detector.detect(units,configurations)
        active=[p for p in PROFILES if p.framework in detection.frameworks]
        sources=tuple(dict.fromkeys((*SOURCES,*(x for p in active for x in p.sources))))
        sanitizers=tuple(dict.fromkeys((*SANITIZERS,*(x for p in active for x in p.sanitizers))))
        rules=tuple(dict.fromkeys((*TAINT_RULES,*(x for p in active for x in p.rules))))
        annotations=tuple(dict.fromkeys(x for p in active for x in p.entrypoint_annotations))
        engine=InterproceduralTaintAnalyzer(sources=sources,sanitizers=sanitizers,rules=rules,entrypoint_annotations=annotations)
        report=engine.analyze_units(units,entrypoints)
        metrics=FrameworkAnalysisMetrics(len(active),len(sources),len(sanitizers),len(rules),len(report.findings))
        return FrameworkAnalysisReport(detection,report,metrics)
