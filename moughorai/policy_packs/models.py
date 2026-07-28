from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from moughorai.taint_policy import TaintPolicy
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .resolution import PackDependency

class PolicyPackError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class PolicyPackDiagnostic:
    level: str
    code: str
    message: str
    path: str = ''
    def to_dict(self) -> dict[str,str]:
        return {'level':self.level,'code':self.code,'message':self.message,'path':self.path}

@dataclass(frozen=True, slots=True)
class PolicyPack:
    name: str
    version: str
    policies: tuple[TaintPolicy,...]
    schema_version: int = 1
    description: str = ''
    metadata: tuple[tuple[str,str],...] = ()
    diagnostics: tuple[PolicyPackDiagnostic,...] = ()
    dependencies: tuple["PackDependency",...] = ()
    def __post_init__(self):
        if not self.name.strip(): raise PolicyPackError('pack name must not be empty')
        if not self.version.strip(): raise PolicyPackError('pack version must not be empty')
        if self.schema_version != 1: raise PolicyPackError(f'unsupported schema_version: {self.schema_version}')
        ids=[p.rule_id for p in self.policies]
        if len(ids)!=len(set(ids)): raise PolicyPackError('duplicate policy rule_id in pack')
    @property
    def metadata_map(self) -> Mapping[str,str]: return dict(self.metadata)
    def policy_map(self) -> Mapping[str,TaintPolicy]: return {p.rule_id:p for p in self.policies}

@dataclass(frozen=True, slots=True)
class PolicyOverride:
    rule_id: str
    enabled: bool | None = None
    priority: int | None = None
    severity: str | None = None
    confidence: str | None = None
    properties: tuple[tuple[str,str],...] = ()
    def __post_init__(self):
        if not self.rule_id.strip(): raise PolicyPackError('override rule_id must not be empty')
        if self.priority is not None and self.priority < 0: raise PolicyPackError('override priority must be non-negative')
