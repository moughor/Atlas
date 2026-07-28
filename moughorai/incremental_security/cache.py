from __future__ import annotations
import json
from pathlib import Path
from moughorai.security_analysis import Confidence, SecurityFinding, Severity, SourceLocation, TraceStep
from .models import CacheEntry, IncrementalCache

class IncrementalCacheStore:
    @staticmethod
    def dumps(cache: IncrementalCache) -> str:
        def finding(f: SecurityFinding):
            return {"rule_id":f.rule_id,"title":f.title,"message":f.message,"severity":f.severity.value,"confidence":f.confidence.value,"cwe":f.cwe,"owasp":f.owasp,"location":{"path":f.location.path,"line":f.location.line,"column":f.location.column},"trace":[{"message":t.message,"location":None if t.location is None else {"path":t.location.path,"line":t.location.line,"column":t.location.column}} for t in f.trace],"properties":list(f.properties)}
        payload={"version":cache.version,"analyzer_key":cache.analyzer_key,"entries":[{"path":e.path,"fingerprint":e.fingerprint,"findings":[finding(f) for f in e.findings],"warnings":list(e.warnings),"dependencies":list(e.dependencies)} for e in sorted(cache.entries,key=lambda x:x.path.casefold())]}
        return json.dumps(payload,sort_keys=True,separators=(",",":"))
    @staticmethod
    def loads(text: str) -> IncrementalCache:
        raw=json.loads(text)
        def loc(v): return SourceLocation(v["path"],int(v["line"]),int(v.get("column",1)))
        def finding(v):
            return SecurityFinding(v["rule_id"],v["title"],v["message"],Severity(v["severity"]),Confidence(v["confidence"]),v["cwe"],v["owasp"],loc(v["location"]),tuple(TraceStep(t["message"],None if t.get("location") is None else loc(t["location"])) for t in v.get("trace",[])),tuple(tuple(p) for p in v.get("properties",[])))
        entries=tuple(CacheEntry(e["path"],e["fingerprint"],tuple(finding(f) for f in e.get("findings",[])),tuple(e.get("warnings",[])),tuple(e.get("dependencies",[]))) for e in raw.get("entries",[]))
        return IncrementalCache(int(raw.get("version",1)),str(raw.get("analyzer_key","")),entries)
    def save(self, cache: IncrementalCache, path: str|Path) -> None:
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(self.dumps(cache)+"\n",encoding="utf-8")
    def load(self, path: str|Path) -> IncrementalCache:
        target=Path(path)
        if not target.exists(): return IncrementalCache()
        return self.loads(target.read_text(encoding="utf-8"))
