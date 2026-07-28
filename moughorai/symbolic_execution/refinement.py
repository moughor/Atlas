from __future__ import annotations
from dataclasses import dataclass
from moughorai.security_analysis import SecurityFinding,SecurityReport,ScanStatistics
from .models import SymbolicExecutionReport

@dataclass(frozen=True,slots=True)
class RefinedFinding:
    finding:SecurityFinding; reachable:bool; reason:str=''

def refine_findings(report:SecurityReport, executions:dict[str,SymbolicExecutionReport])->tuple[RefinedFinding,...]:
    out=[]
    for finding in report.findings:
        execution=executions.get(finding.location.path)
        if execution is None:out.append(RefinedFinding(finding,True,'no symbolic execution report'));continue
        unreachable_lines={i.index+1 for i in execution.unreachable_instructions}
        reachable=finding.location.line not in unreachable_lines
        out.append(RefinedFinding(finding,reachable,'' if reachable else 'finding occurs only on an infeasible path'))
    return tuple(out)
