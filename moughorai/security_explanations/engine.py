from __future__ import annotations
from dataclasses import replace
from .models import EvidenceStep, ExplanationAudience, VulnerabilityExplanation
from .providers import IdentityExplanationProvider
from moughorai.security_knowledge import SecurityKnowledgeBase

_IMPACTS={
 'ATLAS-SQL-001':'An attacker may read, modify, or delete database data and may bypass authorization checks.',
 'ATLAS-CMD-001':'An attacker may execute operating-system commands with the application process privileges.',
 'ATLAS-PATH-001':'An attacker may access or overwrite files outside the intended directory.',
 'ATLAS-SSRF-001':'An attacker may reach internal services, cloud metadata endpoints, or restricted networks.',
 'ATLAS-DESER-001':'Crafted input may instantiate dangerous object graphs and lead to code execution or denial of service.',
 'ATLAS-REFLECT-001':'Attacker-selected classes or methods may execute unintended application behavior.',
 'ATLAS-XXE-001':'A malicious XML document may disclose local files or trigger server-side network requests.',
 'ATLAS-SECRET-001':'Anyone with source or artifact access may recover the credential and impersonate the application.',
 'ATLAS-CRYPTO-001':'Protected data may be recoverable or forgeable because the cryptographic primitive is inadequate.',
 'ATLAS-SPRING-EL-001':'An attacker may evaluate expressions that access sensitive objects or execute code.',
 'ATLAS-JPA-001':'An attacker may alter database queries, expose records, or modify persistent data.',
 'ATLAS-JACKSON-001':'Attacker-controlled type selection may instantiate dangerous classes during deserialization.',
}

class SecurityExplanationEngine:
    VERSION='1.0'
    def __init__(self, knowledge_base=None, provider=None):
        self.knowledge_base=knowledge_base or SecurityKnowledgeBase()
        self.provider=provider or IdentityExplanationProvider()
    def explain(self, finding, audience=ExplanationAudience.DEVELOPER):
        if isinstance(audience,str): audience=ExplanationAudience(audience)
        entry=self.knowledge_base.get(finding.rule_id)
        path=self._path(finding)
        title=entry.title if entry else finding.title
        summary=self._summary(finding,title,path,audience)
        impact=_IMPACTS.get(finding.rule_id, f'This {finding.severity.value} severity issue may compromise application security if the reported path is reachable.')
        remediation=entry.remediation if entry else None
        explanation=VulnerabilityExplanation(
            rule_id=finding.rule_id,fingerprint=finding.fingerprint,headline=f'{title} in {finding.location.path}',summary=summary,
            impact=impact,confidence=finding.confidence.value,confidence_reason=self._confidence_reason(finding,path),path=path,
            remediation_summary=remediation.summary if remediation else 'Review the reported data flow and prevent untrusted input from reaching the sensitive operation.',
            remediation_steps=remediation.steps if remediation else ('Validate or constrain the input.','Use a safe API at the sink.','Add a regression test for the vulnerable path.'),
            safe_example=remediation.safe_example if remediation else '',unsafe_example=remediation.unsafe_example if remediation else '',
            cwe=entry.cwe if entry else tuple(x for x in (finding.cwe,) if x),owasp=entry.owasp if entry else tuple(x for x in (finding.owasp,) if x),
            mitre=entry.mitre if entry else (),references=tuple({'title':r.title,'url':r.url,'kind':r.kind.value} for r in entry.references) if entry else (),audience=audience)
        polished=self.provider.polish(explanation)
        if not isinstance(polished,VulnerabilityExplanation): raise TypeError('explanation provider must return VulnerabilityExplanation')
        return replace(polished, generated_by=f'atlas-deterministic-v1+{getattr(self.provider,"name","provider")}')
    def explain_report(self, report, audience=ExplanationAudience.DEVELOPER):
        return tuple(self.explain(f,audience) for f in sorted(report.findings,key=lambda x:(x.location.path,x.location.line,x.location.column,x.rule_id,x.fingerprint)))
    def _path(self,finding):
        raw=list(finding.trace)
        if not raw:
            raw=[]
        steps=[]
        for i,step in enumerate(raw,1):
            role='sink' if len(raw)==1 else ('source' if i==1 else ('sink' if i==len(raw) else 'propagation'))
            loc=step.location
            steps.append(EvidenceStep(i,role,step.message,None if loc is None else loc.path,None if loc is None else loc.line,None if loc is None else loc.column))
        if not steps:
            loc=finding.location
            steps.append(EvidenceStep(1,'sink',finding.message,loc.path,loc.line,loc.column))
        elif steps[-1].path is None:
            loc=finding.location; last=steps[-1]
            steps[-1]=EvidenceStep(last.index,last.role,last.message,loc.path,loc.line,loc.column)
        return tuple(steps)
    def _summary(self,finding,title,path,audience):
        count=len(path)
        if audience is ExplanationAudience.EXECUTIVE:
            return f'Atlas identified {title.lower()} with {finding.severity.value} severity and {finding.confidence.value} confidence. The evidence contains {count} path step(s).'
        if audience is ExplanationAudience.SECURITY:
            return f'{title} is reported at {finding.location.path}:{finding.location.line}:{finding.location.column}; Atlas reconstructed {count} evidence step(s) from source to sensitive operation.'
        return f'Untrusted or unsafe data reaches the operation reported at {finding.location.path}:{finding.location.line}:{finding.location.column}. Atlas reconstructed {count} evidence step(s) that explain how the value arrived there.'
    def _confidence_reason(self,finding,path):
        if finding.confidence.value=='high': return f'The analyzer resolved a concrete sink and {len(path)} evidence step(s).'
        if finding.confidence.value=='medium': return f'The sink is identified, but part of the {len(path)}-step path relies on conservative inference.'
        return 'The pattern is security-relevant, but dynamic behavior or incomplete resolution limits certainty.'
