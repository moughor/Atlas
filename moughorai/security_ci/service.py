from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from moughorai.java_security import JavaProjectInput,JavaSecurityAnalyzer,JavaSourceUnit
from moughorai.security_analysis import SecurityReportExporter
from .baseline import SecurityBaseline
from .config import PolicyLoader
from .gate import SecurityQualityGate
from .models import ScanPolicy

@dataclass(slots=True)
class RepositorySecurityScanner:
    analyzer:JavaSecurityAnalyzer=field(default_factory=JavaSecurityAnalyzer)
    gate:SecurityQualityGate=field(default_factory=SecurityQualityGate)
    def scan(self,root,policy:ScanPolicy|None=None,baseline:SecurityBaseline|None=None):
        root=Path(root)
        sources=[]; configs=[]
        excluded={'.git','.idea','.gradle','target','build','node_modules','.venv','venv'}
        for p in sorted(root.rglob('*')):
            if not p.is_file() or any(part in excluded for part in p.parts): continue
            rel=p.relative_to(root).as_posix()
            if p.suffix=='.java': sources.append(JavaSourceUnit(rel,p.read_text(encoding='utf-8',errors='replace')))
            elif p.name in {'application.properties','application.yml','application.yaml'}: configs.append((rel,p.read_text(encoding='utf-8',errors='replace')))
        result=self.analyzer.analyze_project(JavaProjectInput(tuple(sources),tuple(configs)))
        return self.gate.evaluate(result.report,policy,baseline)
    def scan_with_files(self,root,policy_path=None,baseline_path=None):
        policy=PolicyLoader.load(policy_path) if policy_path else ScanPolicy()
        baseline=SecurityBaseline.load(baseline_path) if baseline_path else SecurityBaseline()
        return self.scan(root,policy,baseline)
    @staticmethod
    def write_outputs(result,json_path=None,sarif_path=None,baseline_path=None):
        exporter=SecurityReportExporter()
        if json_path: Path(json_path).write_text(exporter.to_json(result.report)+"\n",encoding='utf-8')
        if sarif_path: Path(sarif_path).write_text(exporter.to_sarif(result.report)+"\n",encoding='utf-8')
        if baseline_path: SecurityBaseline.from_report(result.report).save(baseline_path)
