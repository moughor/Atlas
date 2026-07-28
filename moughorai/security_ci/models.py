from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from moughorai.security_analysis import SecurityFinding, SecurityReport, Severity

SEVERITY_RANK={Severity.INFO:0,Severity.LOW:1,Severity.MEDIUM:2,Severity.HIGH:3,Severity.CRITICAL:4}

class GateStatus(str,Enum): PASS='pass'; FAIL='fail'

@dataclass(frozen=True,slots=True)
class Suppression:
    rule_id:str='*'; path_pattern:str='*'; reason:str=''; fingerprint:str|None=None
    def matches(self,f:SecurityFinding)->bool:
        from fnmatch import fnmatch
        return (self.rule_id=='*' or self.rule_id==f.rule_id) and fnmatch(f.location.path,self.path_pattern) and (self.fingerprint is None or self.fingerprint==f.fingerprint)

@dataclass(frozen=True,slots=True)
class ScanPolicy:
    minimum_severity:Severity=Severity.HIGH
    enabled_rules:tuple[str,...]=()
    disabled_rules:tuple[str,...]=()
    suppressions:tuple[Suppression,...]=()
    fail_on_new_only:bool=True
    max_findings:int|None=None
    include_paths:tuple[str,...]=('**',)
    exclude_paths:tuple[str,...]=()
    def __post_init__(self):
        if self.max_findings is not None and self.max_findings<0: raise ValueError('max_findings must be non-negative')
        overlap=set(self.enabled_rules)&set(self.disabled_rules)
        if overlap: raise ValueError(f'rules cannot be enabled and disabled: {sorted(overlap)}')

@dataclass(frozen=True,slots=True)
class FindingDisposition:
    finding:SecurityFinding; is_new:bool; suppressed:bool; suppression_reason:str=''

@dataclass(frozen=True,slots=True)
class GateResult:
    status:GateStatus; exit_code:int; report:SecurityReport
    considered:tuple[FindingDisposition,...]
    ignored:tuple[FindingDisposition,...]
    new_count:int; existing_count:int; suppressed_count:int
    threshold_count:int; message:str
