from __future__ import annotations
from fnmatch import fnmatch
from moughorai.security_analysis import ScanStatistics,SecurityReport
from .baseline import SecurityBaseline
from .models import *

class SecurityQualityGate:
    def evaluate(self,report:SecurityReport,policy:ScanPolicy|None=None,baseline:SecurityBaseline|None=None)->GateResult:
        policy=policy or ScanPolicy(); baseline=baseline or SecurityBaseline()
        considered=[]; ignored=[]
        for f in report.findings:
            disp=FindingDisposition(f,not baseline.contains(f),False,'')
            if not self._path_allowed(f.location.path,policy) or not self._rule_allowed(f.rule_id,policy):
                ignored.append(disp); continue
            sup=next((s for s in policy.suppressions if s.matches(f)),None)
            if sup:
                ignored.append(FindingDisposition(f,disp.is_new,True,sup.reason)); continue
            considered.append(disp)
        threshold=[d for d in considered if SEVERITY_RANK[d.finding.severity]>=SEVERITY_RANK[policy.minimum_severity] and (d.is_new or not policy.fail_on_new_only)]
        failed=bool(threshold)
        if policy.max_findings is not None and len(considered)>policy.max_findings: failed=True
        status=GateStatus.FAIL if failed else GateStatus.PASS
        filtered=SecurityReport(tuple(d.finding for d in considered),self._stats(tuple(d.finding for d in considered)),report.warnings)
        new=sum(d.is_new for d in considered); existing=len(considered)-new; suppressed=sum(d.suppressed for d in ignored)
        msg=f'{status.value}: {len(threshold)} finding(s) at or above {policy.minimum_severity.value}; {new} new, {existing} existing, {suppressed} suppressed'
        return GateResult(status,1 if failed else 0,filtered,tuple(considered),tuple(ignored),new,existing,suppressed,len(threshold),msg)
    @staticmethod
    def _rule_allowed(rule,policy):
        if rule in policy.disabled_rules:return False
        return not policy.enabled_rules or rule in policy.enabled_rules
    @staticmethod
    def _path_allowed(path,policy):
        included=any(fnmatch(path,p) or (p=='**') for p in policy.include_paths)
        return included and not any(fnmatch(path,p) for p in policy.exclude_paths)
    @staticmethod
    def _stats(findings):
        from moughorai.security_analysis import Severity
        c={s:0 for s in Severity}
        for f in findings:c[f.severity]+=1
        return ScanStatistics(len({f.rule_id for f in findings}),len(findings),c[Severity.CRITICAL],c[Severity.HIGH],c[Severity.MEDIUM],c[Severity.LOW],c[Severity.INFO])
