from __future__ import annotations
from dataclasses import replace
from moughorai.dataflow.models import FlowPath
from moughorai.security_analysis.models import ScanStatistics, SecurityFinding, SecurityReport, TraceStep
from .models import PolicyDecision, TaintPolicy

class TaintPolicyEngine:
    VERSION='1.0'
    def __init__(self, policies=()):
        ids=[p.rule_id for p in policies]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate policy rule_id')
        self.policies=tuple(sorted(policies,key=lambda p:(p.priority,p.rule_id)))
    def evaluate(self,path:FlowPath,policy:TaintPolicy)->PolicyDecision:
        if not policy.enabled: return PolicyDecision(policy,False,False,reason='policy disabled')
        if not path.nodes: return PolicyDecision(policy,False,False,reason='empty path')
        source=path.nodes[0].symbol; sink=path.nodes[-1].symbol
        if not any(m.matches(source) for m in policy.sources): return PolicyDecision(policy,False,False,source_symbol=source,sink_symbol=sink,reason='source did not match')
        if not any(m.matches(sink) for m in policy.sinks): return PolicyDecision(policy,False,False,source_symbol=source,sink_symbol=sink,reason='sink did not match')
        for node in path.nodes[1:-1]:
            if any(m.matches(node.symbol) for m in policy.sanitizers):
                return PolicyDecision(policy,False,True,source,sink,node.symbol,f'path sanitized by {node.symbol}')
        return PolicyDecision(policy,True,False,source,sink,reason=f'{source} reaches {sink}')
    def decisions(self,paths):
        result=[]
        for path in paths:
            for policy in self.policies: result.append((path,self.evaluate(path,policy)))
        return tuple(result)
    def findings(self,paths)->tuple[SecurityFinding,...]:
        findings=[]
        for path,decision in self.decisions(paths):
            if not decision.matched: continue
            p=decision.policy; sink=path.sink; location=sink.location if sink and sink.location is not None else next((n.location for n in reversed(path.nodes) if n.location is not None),None)
            if location is None: continue
            props=dict(p.properties); props.update({'policy_engine_version':self.VERSION,'policy_priority':str(p.priority),'source_symbol':decision.source_symbol or '','sink_symbol':decision.sink_symbol or '','dataflow_truncated':str(path.truncated).lower(),'dataflow_recursion':str(path.recursion_detected).lower()})
            trace=tuple(TraceStep(n.message or f'{n.role.value}: {n.symbol}',n.location) for n in path.nodes)
            findings.append(SecurityFinding(p.rule_id,p.title,p.message,p.severity,p.confidence,p.cwe,p.owasp,location,trace,tuple(sorted(props.items()))))
        unique={f.fingerprint:f for f in findings}
        return tuple(unique[k] for k in sorted(unique))
    def report(self,paths,warnings=())->SecurityReport:
        findings=self.findings(paths)
        counts={s.value:0 for s in __import__('moughorai.security_analysis.models',fromlist=['Severity']).Severity}
        for f in findings: counts[f.severity.value]+=1
        stats=ScanStatistics(len(self.policies),len(findings),counts['critical'],counts['high'],counts['medium'],counts['low'],counts['info'])
        return SecurityReport(findings,stats,tuple(warnings))
