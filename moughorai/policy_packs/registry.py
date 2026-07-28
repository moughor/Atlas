from __future__ import annotations
from dataclasses import replace
from moughorai.security_analysis.models import Confidence, Severity
from moughorai.taint_policy import TaintPolicy, TaintPolicyEngine
from .models import PolicyOverride, PolicyPack, PolicyPackDiagnostic, PolicyPackError

class PolicyPackRegistry:
    def __init__(self,packs=()):
        names=[p.name for p in packs]
        if len(names)!=len(set(names)): raise PolicyPackError('duplicate policy pack name')
        self.packs=tuple(sorted(packs,key=lambda p:(p.name,p.version)))
    def policies(self,overrides=(),strict=True):
        merged={}
        for pack in self.packs:
            for policy in pack.policies:
                if policy.rule_id in merged: raise PolicyPackError(f'duplicate policy rule_id across packs: {policy.rule_id}')
                merged[policy.rule_id]=policy
        for override in overrides:
            current=merged.get(override.rule_id)
            if current is None:
                if strict: raise PolicyPackError(f'override references unknown rule_id: {override.rule_id}')
                continue
            props=dict(current.properties); props.update(dict(override.properties))
            changes={'properties':tuple(sorted(props.items()))}
            if override.enabled is not None: changes['enabled']=override.enabled
            if override.priority is not None: changes['priority']=override.priority
            if override.severity is not None:
                try: changes['severity']=Severity(override.severity)
                except ValueError as exc: raise PolicyPackError(f'invalid override severity: {override.severity}') from exc
            if override.confidence is not None:
                try: changes['confidence']=Confidence(override.confidence)
                except ValueError as exc: raise PolicyPackError(f'invalid override confidence: {override.confidence}') from exc
            merged[override.rule_id]=replace(current,**changes)
        return tuple(sorted(merged.values(),key=lambda p:(p.priority,p.rule_id)))
    def engine(self,overrides=(),strict=True): return TaintPolicyEngine(self.policies(overrides,strict))
    def diagnostics(self): return tuple(d for p in self.packs for d in p.diagnostics)
