from __future__ import annotations
from moughorai.security_analysis.models import SecurityFinding, TraceStep
from .models import FlowPath

def finding_with_flow(finding:SecurityFinding,path:FlowPath)->SecurityFinding:
    trace=tuple(TraceStep(n.message or f'{n.role.value}: {n.symbol}',n.location) for n in path.nodes)
    props=dict(finding.properties); props['dataflow_version']='1.0'; props['dataflow_truncated']=str(path.truncated).lower(); props['dataflow_recursion']=str(path.recursion_detected).lower()
    return SecurityFinding(finding.rule_id,finding.title,finding.message,finding.severity,finding.confidence,finding.cwe,finding.owasp,finding.location,trace,tuple(sorted(props.items())))

def sarif_code_flow(path:FlowPath):
    locations=[]
    for node in path.nodes:
        if node.location is None: continue
        locations.append({'location':{'message':{'text':node.message or f'{node.role.value}: {node.symbol}'},'physicalLocation':{'artifactLocation':{'uri':node.location.path},'region':{'startLine':node.location.line,'startColumn':node.location.column}}}})
    return {'threadFlows':[{'locations':locations}]}
