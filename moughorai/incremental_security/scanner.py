from __future__ import annotations
from collections import Counter, defaultdict, deque
from hashlib import sha256
import re
from moughorai.java_security import JavaSecurityAnalyzer, JavaSourceUnit
from moughorai.security_analysis import ScanStatistics, SecurityReport, Severity
from .models import CacheEntry, IncrementalCache, IncrementalScanMetrics, IncrementalScanResult

class IncrementalJavaSecurityScanner:
    def __init__(self, analyzer: JavaSecurityAnalyzer|None=None, analyzer_key: str="java-security-v1"):
        self.analyzer=analyzer or JavaSecurityAnalyzer(); self.analyzer_key=analyzer_key
    @staticmethod
    def fingerprint(content: str) -> str: return sha256(content.encode("utf-8")).hexdigest()
    @staticmethod
    def _type_name(path: str, source: str) -> str:
        m=re.search(r"\b(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)",source)
        return m.group(1) if m else path.rsplit("/",1)[-1].rsplit(".",1)[0]
    @staticmethod
    def _dependencies(source: str) -> tuple[str,...]:
        names=set(re.findall(r"\b(?:extends|implements|new|instanceof)\s+([A-Z][A-Za-z0-9_$]*)",source))
        names.update(re.findall(r"\bimport\s+(?:static\s+)?[\w.]+\.([A-Z][A-Za-z0-9_$]*)(?:\.\*)?\s*;",source))
        return tuple(sorted(names))
    @staticmethod
    def _stats(findings):
        c=Counter(f.severity for f in findings)
        return ScanStatistics(len({f.rule_id for f in findings}),len(findings),c[Severity.CRITICAL],c[Severity.HIGH],c[Severity.MEDIUM],c[Severity.LOW],c[Severity.INFO])
    def scan(self, sources: tuple[JavaSourceUnit,...], cache: IncrementalCache|None=None, *, force: bool=False) -> IncrementalScanResult:
        cache=cache or IncrementalCache(); old=cache.by_path() if cache.analyzer_key==self.analyzer_key and cache.version==1 and not force else {}
        current={u.path:u for u in sources}; type_to_path={self._type_name(u.path,u.source):u.path for u in sources}
        deps={u.path:tuple(sorted(type_to_path[n] for n in self._dependencies(u.source) if n in type_to_path and type_to_path[n]!=u.path)) for u in sources}
        changed={p for p,u in current.items() if p not in old or old[p].fingerprint!=self.fingerprint(u.source)}
        removed=set(old)-set(current)
        reverse=defaultdict(set)
        for path,ds in deps.items():
            for dep in ds: reverse[dep].add(path)
        for path,e in old.items():
            for dep in e.dependencies:
                reverse[dep].add(path)
        invalidated=set(changed); q=deque(changed|removed)
        while q:
            p=q.popleft()
            for dependent in sorted(reverse.get(p,())):
                if dependent in current and dependent not in invalidated:
                    invalidated.add(dependent); q.append(dependent)
        entries=[]; analyzed=[]; reused=[]
        for path in sorted(current,key=str.casefold):
            unit=current[path]; fp=self.fingerprint(unit.source)
            if path not in invalidated and path in old:
                entry=old[path]; reused.append(path)
            else:
                report=self.analyzer.analyze_source(unit.source,path)
                entry=CacheEntry(path,fp,report.findings,report.warnings,deps[path]); analyzed.append(path)
            if entry.dependencies!=deps[path] or entry.fingerprint!=fp:
                entry=CacheEntry(path,fp,entry.findings,entry.warnings,deps[path])
            entries.append(entry)
        findings=tuple(sorted((f for e in entries for f in e.findings),key=lambda f:(f.location.path.casefold(),f.location.line,f.location.column,f.rule_id)))
        warnings=tuple(sorted(w for e in entries for w in e.warnings))
        new_cache=IncrementalCache(1,self.analyzer_key,tuple(entries))
        total=len(current); hit=len(reused)/total if total else 1.0
        metrics=IncrementalScanMetrics(total,len(analyzed),len(reused),len(invalidated),len(removed),hit)
        return IncrementalScanResult(SecurityReport(findings,self._stats(findings),warnings),new_cache,metrics,tuple(analyzed),tuple(reused),tuple(sorted(invalidated)),tuple(sorted(removed)))
