from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class ExplanationAudience(str, Enum):
    DEVELOPER='developer'; SECURITY='security'; EXECUTIVE='executive'

@dataclass(frozen=True, slots=True)
class EvidenceStep:
    index: int
    role: str
    message: str
    path: str|None = None
    line: int|None = None
    column: int|None = None
    def to_dict(self):
        return {'index':self.index,'role':self.role,'message':self.message,'location':None if self.path is None else {'path':self.path,'line':self.line,'column':self.column}}

@dataclass(frozen=True, slots=True)
class VulnerabilityExplanation:
    rule_id: str
    fingerprint: str
    headline: str
    summary: str
    impact: str
    confidence: str
    confidence_reason: str
    path: tuple[EvidenceStep,...]
    remediation_summary: str
    remediation_steps: tuple[str,...]
    safe_example: str = ''
    unsafe_example: str = ''
    cwe: tuple[str,...] = ()
    owasp: tuple[str,...] = ()
    mitre: tuple[str,...] = ()
    references: tuple[dict,...] = ()
    audience: ExplanationAudience = ExplanationAudience.DEVELOPER
    generated_by: str = 'atlas-deterministic-v1'
    def to_dict(self):
        return {'schema_version':1,'rule_id':self.rule_id,'fingerprint':self.fingerprint,'headline':self.headline,'summary':self.summary,'impact':self.impact,'confidence':self.confidence,'confidence_reason':self.confidence_reason,'path':[s.to_dict() for s in self.path],'remediation':{'summary':self.remediation_summary,'steps':list(self.remediation_steps),'safe_example':self.safe_example,'unsafe_example':self.unsafe_example},'taxonomy':{'cwe':list(self.cwe),'owasp':list(self.owasp),'mitre':list(self.mitre)},'references':[dict(r) for r in self.references],'audience':self.audience.value,'generated_by':self.generated_by}
    def to_markdown(self):
        lines=[f'### {self.headline}',self.summary,'',f'**Impact:** {self.impact}',f'**Confidence:** {self.confidence} — {self.confidence_reason}']
        if self.path:
            lines += ['', '**Evidence path**'] + [f'{s.index}. **{s.role.title()}** — {s.message}' + (f' (`{s.path}:{s.line}:{s.column}`)' if s.path else '') for s in self.path]
        lines += ['', '**Remediation**', self.remediation_summary]
        lines += [f'- {step}' for step in self.remediation_steps]
        return '\n'.join(lines)
