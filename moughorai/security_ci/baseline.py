from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from moughorai.security_analysis import SecurityReport

@dataclass(frozen=True,slots=True)
class SecurityBaseline:
    fingerprints:frozenset[str]=frozenset()
    @classmethod
    def from_report(cls,report:SecurityReport): return cls(frozenset(f.fingerprint for f in report.findings))
    @classmethod
    def from_dict(cls,data):
        values=data.get('fingerprints',())
        if not isinstance(values,list): raise ValueError('fingerprints must be a list')
        return cls(frozenset(str(x) for x in values))
    @classmethod
    def from_json(cls,text): return cls.from_dict(json.loads(text))
    @classmethod
    def load(cls,path): return cls.from_json(Path(path).read_text(encoding='utf-8'))
    def to_dict(self): return {'schema_version':1,'fingerprints':sorted(self.fingerprints)}
    def to_json(self,indent=2): return json.dumps(self.to_dict(),indent=indent,sort_keys=True)
    def save(self,path): Path(path).write_text(self.to_json()+"\n",encoding='utf-8')
    def contains(self,finding): return finding.fingerprint in self.fingerprints
