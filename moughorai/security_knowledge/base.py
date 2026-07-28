from __future__ import annotations
from dataclasses import replace
from typing import Iterable
from .catalog import CATALOG
from .models import SecurityKnowledge

class SecurityKnowledgeBase:
    VERSION='1.0'
    def __init__(self, entries: Iterable[SecurityKnowledge]=CATALOG):
        ordered=tuple(sorted(entries,key=lambda e:e.rule_id))
        ids=[e.rule_id for e in ordered]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate rule_id in knowledge base')
        self._entries=ordered; self._by_id={e.rule_id:e for e in ordered}
    def __len__(self): return len(self._entries)
    def __iter__(self): return iter(self._entries)
    def get(self, rule_id: str) -> SecurityKnowledge|None: return self._by_id.get(rule_id)
    def require(self, rule_id: str) -> SecurityKnowledge:
        try: return self._by_id[rule_id]
        except KeyError as exc: raise KeyError(f'unknown security rule: {rule_id}') from exc
    def search(self, query: str='', *, cwe: str|None=None, owasp: str|None=None, mitre: str|None=None, tag: str|None=None):
        q=query.strip().lower(); result=[]
        for e in self._entries:
            hay=' '.join((e.rule_id,e.title,e.description,*e.tags,*e.cwe,*e.owasp,*e.mitre)).lower()
            if q and q not in hay: continue
            if cwe and cwe not in e.cwe: continue
            if owasp and owasp not in e.owasp: continue
            if mitre and mitre not in e.mitre: continue
            if tag and tag.lower() not in (t.lower() for t in e.tags): continue
            result.append(e)
        return tuple(result)
    def to_dict(self): return {'schema_version':1,'knowledge_version':self.VERSION,'entries':[e.to_dict() for e in self._entries]}
    def enrich_dict(self, finding: dict) -> dict:
        entry=self.get(str(finding.get('rule_id','')))
        if entry is None: return dict(finding)
        out=dict(finding); out['knowledge']=entry.to_dict(); return out
    def coverage(self, rule_ids: Iterable[str]):
        ids=tuple(sorted(set(rule_ids))); covered=tuple(i for i in ids if i in self._by_id)
        missing=tuple(i for i in ids if i not in self._by_id)
        return {'total':len(ids),'covered':len(covered),'coverage':1.0 if not ids else len(covered)/len(ids),'covered_rule_ids':covered,'missing_rule_ids':missing}
