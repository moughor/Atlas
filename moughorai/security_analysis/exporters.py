from __future__ import annotations
import json
from .models import *

class SecurityReportExporter:
    def __init__(self, knowledge_base=None): self.knowledge_base=knowledge_base
    LEVEL={Severity.INFO:'note',Severity.LOW:'note',Severity.MEDIUM:'warning',Severity.HIGH:'error',Severity.CRITICAL:'error'}
    def to_dict(self,report):
        return {'schema_version':1,'statistics':report.statistics.__dict__ if hasattr(report.statistics,'__dict__') else {k:getattr(report.statistics,k) for k in report.statistics.__slots__},'warnings':list(report.warnings),'findings':[self._enrich(self._finding(f)) for f in report.findings]}
    def _enrich(self, item):
        return self.knowledge_base.enrich_dict(item) if self.knowledge_base is not None else item
    def _finding(self,f):
        return {'rule_id':f.rule_id,'title':f.title,'message':f.message,'severity':f.severity.value,'confidence':f.confidence.value,'cwe':f.cwe,'owasp':f.owasp,'location':{'path':f.location.path,'line':f.location.line,'column':f.location.column},'fingerprint':f.fingerprint,'trace':[{'message':s.message,'location':None if s.location is None else {'path':s.location.path,'line':s.location.line,'column':s.location.column}} for s in f.trace],'properties':dict(f.properties)}
    def to_json(self,report,indent=2): return json.dumps(self.to_dict(report),indent=indent,sort_keys=True)
    def _sarif_rule_properties(self, finding):
        entry=self.knowledge_base.get(finding.rule_id) if self.knowledge_base is not None else None
        score=entry.cvss_score if entry is not None else {Severity.CRITICAL:9.5,Severity.HIGH:8.0,Severity.MEDIUM:5.0,Severity.LOW:2.0,Severity.INFO:0.0}[finding.severity]
        tags=list(dict.fromkeys(([finding.cwe,finding.owasp] + ([] if entry is None else [*entry.cwe,*entry.owasp,*entry.mitre]))))
        result={'security-severity':str(score),'tags':tags}
        if entry is not None: result.update({'cvss-vector':entry.cvss_vector,'knowledge-version':self.knowledge_base.VERSION})
        return result
    def to_sarif(self,report,indent=2):
        rules={f.rule_id:f for f in report.findings}
        payload={'version':'2.1.0','$schema':'https://json.schemastore.org/sarif-2.1.0.json','runs':[{'tool':{'driver':{'name':'Atlas Security Analyzer','informationUri':'https://github.com/moughor/Atlas','rules':[{'id':r.rule_id,'name':r.title,'shortDescription':{'text':r.title},'properties':self._sarif_rule_properties(r)} for r in rules.values()]}},'results':[{'ruleId':f.rule_id,'level':self.LEVEL[f.severity],'message':{'text':f.message},'locations':[{'physicalLocation':{'artifactLocation':{'uri':f.location.path},'region':{'startLine':f.location.line,'startColumn':f.location.column}}}],'partialFingerprints':{'primaryLocationLineHash':f.fingerprint}} for f in report.findings]}]}
        return json.dumps(payload,indent=indent,sort_keys=True)
