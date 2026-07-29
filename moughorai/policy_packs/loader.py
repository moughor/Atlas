from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
import yaml
from moughorai.security_analysis.models import Confidence, Severity
from moughorai.taint_policy import MatchMode, SymbolMatcher, TaintPolicy
from .models import PolicyOverride, PolicyPack, PolicyPackDiagnostic, PolicyPackError
from .resolution import PackDependency

class PolicyPackLoader:
    SCHEMA_VERSION=1
    def load_file(self,path:str|Path)->PolicyPack:
        p=Path(path)
        try: text=p.read_text(encoding='utf-8')
        except OSError as exc: raise PolicyPackError(f'cannot read policy pack: {p}') from exc
        suffix=p.suffix.lower()
        if suffix in ('.yaml','.yml'): return self.load_yaml(text,source=str(p))
        if suffix=='.json': return self.load_json(text,source=str(p))
        raise PolicyPackError(f'unsupported policy pack format: {suffix or "<none>"}')
    def load_yaml(self,text:str,source='<yaml>')->PolicyPack:
        try: data=yaml.safe_load(text)
        except yaml.YAMLError as exc: raise PolicyPackError(f'invalid YAML in {source}: {exc}') from exc
        return self.load_mapping(data,source)
    def load_json(self,text:str,source='<json>')->PolicyPack:
        try: data=json.loads(text)
        except json.JSONDecodeError as exc: raise PolicyPackError(f'invalid JSON in {source}: {exc.msg}') from exc
        return self.load_mapping(data,source)
    def load_mapping(self,data:Any,source='<mapping>')->PolicyPack:
        if not isinstance(data,Mapping): raise PolicyPackError(f'{source}: root must be a mapping')
        allowed={'schema_version','name','version','description','metadata','policies','dependencies'}
        unknown=sorted(set(data)-allowed)
        if unknown: raise PolicyPackError(f'{source}: unknown root fields: {", ".join(unknown)}')
        schema=data.get('schema_version',1)
        if not isinstance(schema,int): raise PolicyPackError(f'{source}: schema_version must be an integer')
        raw_policies=data.get('policies',[])
        if not isinstance(raw_policies,list): raise PolicyPackError(f'{source}: policies must be a list')
        policies=tuple(self._policy(x,f'{source}.policies[{i}]') for i,x in enumerate(raw_policies))
        metadata=self._string_pairs(data.get('metadata',{}),f'{source}.metadata')
        raw_deps=data.get('dependencies',[])
        if not isinstance(raw_deps,list): raise PolicyPackError(f'{source}: dependencies must be a list')
        dependencies=tuple(self._dependency(v,f'{source}.dependencies[{i}]') for i,v in enumerate(raw_deps))
        diagnostics=() if policies else (PolicyPackDiagnostic('warning','empty-pack','policy pack contains no policies',source),)
        return PolicyPack(str(data.get('name','')).strip(),str(data.get('version','')).strip(),policies,schema,str(data.get('description','')),metadata,diagnostics,dependencies)

    def _dependency(self,data,path):
        if isinstance(data,str): return PackDependency(data)
        if not isinstance(data,Mapping): raise PolicyPackError(f'{path}: dependency must be a string or mapping')
        unknown=sorted(set(data)-{'name','constraint','optional'})
        if unknown: raise PolicyPackError(f'{path}: unknown dependency fields: {", ".join(unknown)}')
        optional=data.get('optional',False)
        if not isinstance(optional,bool): raise PolicyPackError(f'{path}.optional: must be a boolean')
        return PackDependency(str(data.get('name','')),str(data.get('constraint','*')),optional)
    def _policy(self,data:Any,path:str)->TaintPolicy:
        if not isinstance(data,Mapping): raise PolicyPackError(f'{path}: policy must be a mapping')
        allowed={'rule_id','title','message','sources','sinks','sanitizers','severity','confidence','cwe','owasp','priority','enabled','properties'}
        unknown=sorted(set(data)-allowed)
        if unknown: raise PolicyPackError(f'{path}: unknown policy fields: {", ".join(unknown)}')
        def matchers(name,required=False):
            raw=data.get(name,[])
            if not isinstance(raw,list): raise PolicyPackError(f'{path}.{name}: must be a list')
            if required and not raw: raise PolicyPackError(f'{path}.{name}: must not be empty')
            return tuple(self._matcher(v,f'{path}.{name}[{i}]') for i,v in enumerate(raw))
        severity=self._enum(Severity,data.get('severity','high'),f'{path}.severity')
        confidence=self._enum(Confidence,data.get('confidence','high'),f'{path}.confidence')
        priority=data.get('priority',100)
        if not isinstance(priority,int): raise PolicyPackError(f'{path}.priority: must be an integer')
        enabled=data.get('enabled',True)
        if not isinstance(enabled,bool): raise PolicyPackError(f'{path}.enabled: must be a boolean')
        return TaintPolicy(str(data.get('rule_id','')),str(data.get('title','')),str(data.get('message','')),matchers('sources',True),matchers('sinks',True),matchers('sanitizers'),severity,confidence,str(data.get('cwe','CWE-20')),str(data.get('owasp','A03:2021')),priority,enabled,self._string_pairs(data.get('properties',{}),f'{path}.properties'))
    def _matcher(self,data:Any,path:str)->SymbolMatcher:
        if isinstance(data,str): return SymbolMatcher(data)
        if not isinstance(data,Mapping): raise PolicyPackError(f'{path}: matcher must be a string or mapping')
        unknown=sorted(set(data)-{'pattern','mode'})
        if unknown: raise PolicyPackError(f'{path}: unknown matcher fields: {", ".join(unknown)}')
        mode=self._enum(MatchMode,data.get('mode','exact'),f'{path}.mode')
        return SymbolMatcher(str(data.get('pattern','')),mode)
    def _enum(self,cls,value,path):
        try: return cls(value)
        except (ValueError,TypeError) as exc: raise PolicyPackError(f'{path}: invalid value {value!r}') from exc
    def _string_pairs(self,data,path):
        if not isinstance(data,Mapping): raise PolicyPackError(f'{path}: must be a mapping')
        return tuple(sorted((str(k),str(v)) for k,v in data.items()))
