from __future__ import annotations
import json
from pathlib import Path
from moughorai.security_analysis import Severity
from .models import ScanPolicy,Suppression

class PolicyLoader:
    @staticmethod
    def from_dict(data):
        if not isinstance(data,dict): raise ValueError('policy must be an object')
        try: sev=Severity(str(data.get('minimum_severity','high')).lower())
        except ValueError as e: raise ValueError('invalid minimum_severity') from e
        sups=[]
        for item in data.get('suppressions',[]):
            if not isinstance(item,dict): raise ValueError('suppression must be an object')
            sups.append(Suppression(str(item.get('rule_id','*')),str(item.get('path_pattern','*')),str(item.get('reason','')),item.get('fingerprint')))
        return ScanPolicy(sev,tuple(data.get('enabled_rules',())),tuple(data.get('disabled_rules',())),tuple(sups),bool(data.get('fail_on_new_only',True)),data.get('max_findings'),tuple(data.get('include_paths',('**',))),tuple(data.get('exclude_paths',())))
    @classmethod
    def from_json(cls,text): return cls.from_dict(json.loads(text))
    @classmethod
    def load(cls,path):
        p=Path(path); text=p.read_text(encoding='utf-8')
        if p.suffix.lower() in {'.yaml','.yml'}:
            try:
                import yaml
            except ImportError as e: raise RuntimeError('PyYAML is required for YAML policies') from e
            return cls.from_dict(yaml.safe_load(text) or {})
        return cls.from_json(text)
