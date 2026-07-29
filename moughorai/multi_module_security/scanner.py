from __future__ import annotations
from collections import Counter
from moughorai.java_security import JavaSecurityAnalyzer
from moughorai.security_analysis import ScanStatistics, SecurityReport, Severity
from .graph import ModuleGraphBuilder
from .models import ModuleDescriptor, ModuleScanResult, WorkspaceScanMetrics, WorkspaceSecurityResult

class MultiModuleSecurityScanner:
    def __init__(self, analyzer: JavaSecurityAnalyzer|None=None):
        self.analyzer=analyzer or JavaSecurityAnalyzer(); self.graph_builder=ModuleGraphBuilder()
    @staticmethod
    def _stats(findings):
        c=Counter(f.severity for f in findings)
        return ScanStatistics(len({f.rule_id for f in findings}),len(findings),c[Severity.CRITICAL],c[Severity.HIGH],c[Severity.MEDIUM],c[Severity.LOW],c[Severity.INFO])
    def scan(self, modules: tuple[ModuleDescriptor,...]) -> WorkspaceSecurityResult:
        graph=self.graph_builder.build(modules); order=self.graph_builder.scan_order(graph); by=graph.by_name(); results=[]
        for name in order:
            module=by[name]; findings=[]; warnings=[]
            for source in sorted(module.sources,key=lambda s:s.path.casefold()):
                report=self.analyzer.analyze_source(source.source,source.path)
                findings.extend(report.findings); warnings.extend(report.warnings)
            findings=tuple(sorted(findings,key=lambda f:(f.location.path.casefold(),f.location.line,f.location.column,f.rule_id)))
            results.append(ModuleScanResult(name,SecurityReport(findings,self._stats(findings),tuple(sorted(warnings))),len(module.sources)))
        all_findings=tuple(sorted((f for r in results for f in r.report.findings),key=lambda f:(f.location.path.casefold(),f.location.line,f.location.column,f.rule_id)))
        warnings=tuple(sorted(w for r in results for w in r.report.warnings))
        metrics=WorkspaceScanMetrics(len(modules),sum(len(m.sources) for m in modules),len(graph.edges),len(graph.unresolved_dependencies),len(graph.cycles))
        return WorkspaceSecurityResult(SecurityReport(all_findings,self._stats(all_findings),warnings),graph,tuple(results),order,metrics)
