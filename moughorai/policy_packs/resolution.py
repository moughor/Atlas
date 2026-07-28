from __future__ import annotations
from dataclasses import dataclass
from functools import total_ordering
import hashlib, json, re
from typing import Iterable
from .models import PolicyPack, PolicyPackError
from .serialization import pack_to_dict

_VERSION_RE=re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$')

@total_ordering
@dataclass(frozen=True, slots=True)
class SemanticVersion:
    major:int; minor:int; patch:int; prerelease:str=''
    @classmethod
    def parse(cls,value:str)->'SemanticVersion':
        m=_VERSION_RE.fullmatch(value.strip())
        if not m: raise PolicyPackError(f'invalid semantic version: {value!r}')
        return cls(int(m.group(1)),int(m.group(2)),int(m.group(3)),m.group(4) or '')
    def __str__(self):
        base=f'{self.major}.{self.minor}.{self.patch}'
        return base+(f'-{self.prerelease}' if self.prerelease else '')
    def __lt__(self,other):
        if not isinstance(other,SemanticVersion): return NotImplemented
        core=(self.major,self.minor,self.patch); other_core=(other.major,other.minor,other.patch)
        if core!=other_core: return core<other_core
        if self.prerelease==other.prerelease: return False
        if not self.prerelease: return False
        if not other.prerelease: return True
        return self.prerelease<other.prerelease

@dataclass(frozen=True, slots=True)
class PackDependency:
    name:str
    constraint:str='*'
    optional:bool=False
    def __post_init__(self):
        if not self.name.strip(): raise PolicyPackError('dependency name must not be empty')
        VersionConstraint(self.constraint)

class VersionConstraint:
    def __init__(self,text='*'):
        self.text=(text or '*').strip()
        self.parts=tuple(p.strip() for p in self.text.split(',') if p.strip()) or ('*',)
        for p in self.parts: self._validate(p)
    def _validate(self,p):
        if p=='*': return
        if p.startswith(('^','~')): SemanticVersion.parse(p[1:]); return
        for op in ('>=','<=','==','>','<'):
            if p.startswith(op): SemanticVersion.parse(p[len(op):]); return
        SemanticVersion.parse(p)
    def matches(self,version:str|SemanticVersion)->bool:
        v=version if isinstance(version,SemanticVersion) else SemanticVersion.parse(version)
        return all(self._match(v,p) for p in self.parts)
    def _match(self,v,p):
        if p=='*': return True
        if p.startswith('^'):
            lo=SemanticVersion.parse(p[1:])
            hi=SemanticVersion(lo.major+1,0,0) if lo.major else (SemanticVersion(0,lo.minor+1,0) if lo.minor else SemanticVersion(0,0,lo.patch+1))
            return lo<=v<hi
        if p.startswith('~'):
            lo=SemanticVersion.parse(p[1:]); hi=SemanticVersion(lo.major,lo.minor+1,0)
            return lo<=v<hi
        for op in ('>=','<=','==','>','<'):
            if p.startswith(op):
                x=SemanticVersion.parse(p[len(op):]); return {'>=':v>=x,'<=':v<=x,'==':v==x,'>':v>x,'<':v<x}[op]
        return v==SemanticVersion.parse(p)

@dataclass(frozen=True, slots=True)
class LockedPack:
    name:str; version:str; sha256:str; dependencies:tuple[PackDependency,...]=()
    def to_dict(self):
        return {'name':self.name,'version':self.version,'sha256':self.sha256,'dependencies':[{'name':d.name,'constraint':d.constraint,'optional':d.optional} for d in self.dependencies]}

@dataclass(frozen=True, slots=True)
class PolicyPackLock:
    packs:tuple[LockedPack,...]; format_version:int=1
    def to_dict(self): return {'format_version':self.format_version,'packs':[p.to_dict() for p in self.packs]}
    def to_json(self): return json.dumps(self.to_dict(),indent=2,sort_keys=True)+'\n'
    @classmethod
    def from_json(cls,text):
        try: data=json.loads(text)
        except json.JSONDecodeError as exc: raise PolicyPackError(f'invalid lockfile JSON: {exc.msg}') from exc
        if data.get('format_version')!=1: raise PolicyPackError('unsupported lockfile format_version')
        packs=[]
        for p in data.get('packs',[]):
            deps=tuple(PackDependency(d['name'],d.get('constraint','*'),bool(d.get('optional',False))) for d in p.get('dependencies',[]))
            packs.append(LockedPack(p['name'],p['version'],p['sha256'],deps))
        return cls(tuple(packs))

def pack_digest(pack:PolicyPack)->str:
    payload=json.dumps(pack_to_dict(pack),sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(payload).hexdigest()

class PolicyPackResolver:
    def __init__(self,packs:Iterable[PolicyPack]):
        self._packs=tuple(packs)
        self._by_name={p.name:p for p in self._packs}
        if len(self._by_name)!=len(self._packs): raise PolicyPackError('duplicate policy pack name')
    def resolve(self,roots:Iterable[str]|None=None)->tuple[PolicyPack,...]:
        requested=tuple(sorted(roots or self._by_name))
        result=[]; visiting=[]; visited=set()
        def visit(name):
            if name in visited:return
            if name in visiting: raise PolicyPackError('policy pack dependency cycle: '+' -> '.join(visiting+[name]))
            pack=self._by_name.get(name)
            if pack is None: raise PolicyPackError(f'missing policy pack dependency: {name}')
            visiting.append(name)
            for dep in sorted(pack.dependencies,key=lambda d:d.name):
                target=self._by_name.get(dep.name)
                if target is None:
                    if dep.optional: continue
                    raise PolicyPackError(f'{pack.name} requires missing pack {dep.name} {dep.constraint}')
                if not VersionConstraint(dep.constraint).matches(target.version):
                    raise PolicyPackError(f'{pack.name} requires {dep.name} {dep.constraint}, found {target.version}')
                visit(dep.name)
            visiting.pop(); visited.add(name); result.append(pack)
        for name in requested: visit(name)
        return tuple(result)
    def lock(self,roots:Iterable[str]|None=None)->PolicyPackLock:
        resolved=self.resolve(roots)
        return PolicyPackLock(tuple(LockedPack(p.name,p.version,pack_digest(p),p.dependencies) for p in resolved))
    def verify(self,lock:PolicyPackLock)->bool:
        current=self.lock(tuple(p.name for p in lock.packs))
        if current!=lock: raise PolicyPackError('policy pack lockfile does not match installed packs')
        return True
