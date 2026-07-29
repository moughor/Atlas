from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

class WorkspaceConfigurationError(ValueError): pass

def _norm(v: Any) -> Any:
    if isinstance(v, Mapping): return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_norm(x) for x in v]
    return v

def _merge(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    out={str(k):_norm(v) for k,v in a.items()}
    for k,v in b.items():
        k=str(k)
        out[k]=_merge(out[k],v) if isinstance(v,Mapping) and isinstance(out.get(k),Mapping) else _norm(v)
    return out

def _flat(v: Mapping[str,Any], p: str='') -> dict[str,Any]:
    out={}
    for k in sorted(v):
        q=f'{p}.{k}' if p else str(k); x=v[k]
        out.update(_flat(x,q)) if isinstance(x,Mapping) else out.__setitem__(q,x)
    return out

def _set(target: dict[str,Any], key: str, value: Any) -> None:
    parts=[x.strip() for x in key.split('.')]
    if not parts or any(not x for x in parts): raise WorkspaceConfigurationError(f'invalid configuration key: {key!r}')
    cur=target
    for part in parts[:-1]:
        old=cur.get(part)
        if old is None: cur[part]={}; cur=cur[part]
        elif isinstance(old,dict): cur=old
        else: raise WorkspaceConfigurationError(f'cannot set {key!r}: {part!r} is not an object')
    cur[parts[-1]]=_norm(value)

@dataclass(frozen=True, slots=True)
class ConfigurationLayer:
    name: str
    values: Mapping[str,Any]
    source: str|None=None
    def __post_init__(self):
        if not self.name.strip(): raise WorkspaceConfigurationError('configuration layer name must not be empty')
        if not isinstance(self.values,Mapping): raise WorkspaceConfigurationError('configuration layer values must be an object')
        object.__setattr__(self,'values',_norm(self.values))
    @classmethod
    def from_file(cls,name:str,path:str|Path,*,optional:bool=False):
        p=Path(path).expanduser().resolve()
        if not p.exists():
            if optional:return cls(name,{},str(p))
            raise FileNotFoundError(p)
        try:v=yaml.safe_load(p.read_text(encoding='utf-8-sig'))
        except yaml.YAMLError as e: raise WorkspaceConfigurationError(f'invalid configuration YAML in {p}: {e}') from e
        if v is None:v={}
        if not isinstance(v,Mapping): raise WorkspaceConfigurationError(f'configuration root in {p} must be an object')
        return cls(name,v,str(p))
    @classmethod
    def from_overrides(cls,values:Mapping[str,Any],*,name:str='cli'):
        nested={}
        for k,v in values.items(): _set(nested,str(k),v)
        return cls(name,nested,'command-line')

@dataclass(frozen=True, slots=True)
class ResolvedConfiguration:
    values: Mapping[str,Any]
    provenance: Mapping[str,str]
    layers: tuple[str,...]
    def get(self,key:str,default:Any=None)->Any:
        cur:Any=self.values
        for part in key.split('.'):
            if not isinstance(cur,Mapping) or part not in cur:return default
            cur=cur[part]
        return cur
    def require(self,key:str)->Any:
        marker=object(); value=self.get(key,marker)
        if value is marker: raise KeyError(key)
        return value
    def source_of(self,key:str)->str|None:return self.provenance.get(key)
    def to_dict(self)->dict[str,Any]:return _norm(self.values)

class WorkspaceConfigurationResolver:
    def resolve(self,*layers:ConfigurationLayer)->ResolvedConfiguration:
        merged={}; provenance={}; names=[]
        for layer in layers:
            names.append(layer.name); merged=_merge(merged,layer.values)
            for key in _flat(layer.values): provenance[key]=layer.name
        return ResolvedConfiguration(merged,provenance,tuple(names))
    def for_project(self,*,global_values=None,workspace_values=None,project_values=None,cli_overrides=None)->ResolvedConfiguration:
        layers=[ConfigurationLayer('global',global_values or {}),ConfigurationLayer('workspace',workspace_values or {}),ConfigurationLayer('project',project_values or {})]
        if cli_overrides: layers.append(ConfigurationLayer.from_overrides(cli_overrides))
        return self.resolve(*layers)
