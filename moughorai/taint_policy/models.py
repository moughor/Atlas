from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from moughorai.security_analysis.models import Confidence, Severity

class MatchMode(str, Enum):
    EXACT='exact'; PREFIX='prefix'; SUFFIX='suffix'; CONTAINS='contains'

@dataclass(frozen=True, slots=True)
class SymbolMatcher:
    pattern: str
    mode: MatchMode = MatchMode.EXACT
    def __post_init__(self):
        if not self.pattern.strip(): raise ValueError('pattern must not be empty')
    def matches(self, value: str) -> bool:
        if self.mode is MatchMode.EXACT: return value == self.pattern
        if self.mode is MatchMode.PREFIX: return value.startswith(self.pattern)
        if self.mode is MatchMode.SUFFIX: return value.endswith(self.pattern)
        return self.pattern in value

@dataclass(frozen=True, slots=True)
class TaintPolicy:
    rule_id: str
    title: str
    message: str
    sources: tuple[SymbolMatcher,...]
    sinks: tuple[SymbolMatcher,...]
    sanitizers: tuple[SymbolMatcher,...] = ()
    severity: Severity = Severity.HIGH
    confidence: Confidence = Confidence.HIGH
    cwe: str = 'CWE-20'
    owasp: str = 'A03:2021'
    priority: int = 100
    enabled: bool = True
    properties: tuple[tuple[str,str],...] = ()
    def __post_init__(self):
        if not self.rule_id.strip(): raise ValueError('rule_id must not be empty')
        if not self.title.strip(): raise ValueError('title must not be empty')
        if not self.sources: raise ValueError('at least one source matcher is required')
        if not self.sinks: raise ValueError('at least one sink matcher is required')
        if self.priority < 0: raise ValueError('priority must be non-negative')
    @property
    def property_map(self) -> Mapping[str,str]: return dict(self.properties)

@dataclass(frozen=True, slots=True)
class PolicyDecision:
    policy: TaintPolicy
    matched: bool
    sanitized: bool
    source_symbol: str | None = None
    sink_symbol: str | None = None
    sanitizer_symbol: str | None = None
    reason: str = ''
    def to_dict(self):
        return {'rule_id':self.policy.rule_id,'matched':self.matched,'sanitized':self.sanitized,'source_symbol':self.source_symbol,'sink_symbol':self.sink_symbol,'sanitizer_symbol':self.sanitizer_symbol,'reason':self.reason}
