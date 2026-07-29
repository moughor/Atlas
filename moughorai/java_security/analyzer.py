from __future__ import annotations

from collections import Counter

from moughorai.security_analysis import ScanStatistics, SecurityAnalyzer, SecurityProgram, SecurityReport

from .config import JavaConfigurationParser
from .models import JavaProjectInput, JavaProjectScanResult, JavaSecurityParseResult, JavaSourceUnit
from .parser import JavaSecurityParser


class JavaSecurityAnalyzer:
    def __init__(self, parser: JavaSecurityParser | None = None, analyzer: SecurityAnalyzer | None = None) -> None:
        self.parser = parser or JavaSecurityParser()
        self.analyzer = analyzer or SecurityAnalyzer()

    def analyze_source(self, source: str, path: str = "Source.java") -> SecurityReport:
        parsed = self.parser.parse(JavaSourceUnit(path, source))
        report = self.analyzer.analyze(parsed.program)
        return SecurityReport(report.findings, report.statistics, tuple(w.message for w in parsed.warnings))

    def parse_source(self, source: str, path: str = "Source.java") -> JavaSecurityParseResult:
        return self.parser.parse(JavaSourceUnit(path, source))

    def analyze_project(self, project: JavaProjectInput) -> JavaProjectScanResult:
        assignments = []
        invocations = []
        annotations = []
        warnings = []
        for unit in project.sources:
            parsed = self.parser.parse(unit)
            assignments.extend(parsed.program.assignments)
            invocations.extend(parsed.program.invocations)
            annotations.extend(parsed.program.annotations)
            warnings.extend(parsed.warnings)

        configuration: dict[str, str] = {}
        config_parser = JavaConfigurationParser()
        for path, content in project.configurations:
            configuration.update(config_parser.parse(path, content))

        report = self.analyzer.analyze(SecurityProgram(
            tuple(assignments), tuple(invocations), tuple(annotations), tuple(sorted(configuration.items()))
        ))
        warning_messages = tuple(f"{w.path}:{w.line}: {w.message}" for w in warnings)
        merged_report = SecurityReport(report.findings, report.statistics, warning_messages)
        return JavaProjectScanResult(merged_report, len(project.sources), len(project.configurations), tuple(warnings))

    def rule_summary(self, report: SecurityReport) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(Counter(f.rule_id for f in report.findings).items()))
