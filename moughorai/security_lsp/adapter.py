from __future__ import annotations
from moughorai.security_analysis import Confidence, SecurityFinding, Severity
from .models import Diagnostic, DiagnosticSeverity, Position, Range

_SEVERITY={Severity.CRITICAL:DiagnosticSeverity.ERROR,Severity.HIGH:DiagnosticSeverity.ERROR,Severity.MEDIUM:DiagnosticSeverity.WARNING,Severity.LOW:DiagnosticSeverity.INFORMATION,Severity.INFO:DiagnosticSeverity.HINT}

def finding_to_diagnostic(finding:SecurityFinding,line_text:str='')->Diagnostic:
    line=max(0,finding.location.line-1); start=max(0,finding.location.column-1)
    length=max(1,len(line_text.rstrip('\r\n'))-start) if line_text else 1
    end=start+min(length,120)
    return Diagnostic(Range(Position(line,start),Position(line,end)),finding.message,_SEVERITY[finding.severity],finding.rule_id,data=(('fingerprint',finding.fingerprint),('cwe',finding.cwe),('owasp',finding.owasp),('confidence',finding.confidence.value),('severity',finding.severity.value)))

def diagnostics_for_findings(findings, source:str):
    lines=source.splitlines()
    result=[]
    for finding in findings:
        line_text=lines[finding.location.line-1] if 0 < finding.location.line <= len(lines) else ''
        result.append(finding_to_diagnostic(finding,line_text))
    return tuple(sorted(result,key=lambda d:(d.range.start.line,d.range.start.character,d.code,d.message)))
