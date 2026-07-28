from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class ReferenceKind(str, Enum):
    CWE='cwe'; OWASP='owasp'; MITRE='mitre'; DOCUMENTATION='documentation'

@dataclass(frozen=True, slots=True)
class KnowledgeReference:
    title: str
    url: str
    kind: ReferenceKind = ReferenceKind.DOCUMENTATION

@dataclass(frozen=True, slots=True)
class Remediation:
    summary: str
    steps: tuple[str, ...] = ()
    safe_example: str = ''
    unsafe_example: str = ''

@dataclass(frozen=True, slots=True)
class SecurityKnowledge:
    rule_id: str
    title: str
    description: str
    cwe: tuple[str, ...]
    owasp: tuple[str, ...]
    mitre: tuple[str, ...]
    cvss_score: float
    cvss_vector: str
    remediation: Remediation
    references: tuple[KnowledgeReference, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip(): raise ValueError('rule_id must not be empty')
        if not 0.0 <= self.cvss_score <= 10.0: raise ValueError('cvss_score must be between 0 and 10')
        if self.cvss_vector and not self.cvss_vector.startswith('CVSS:3.1/'):
            raise ValueError('only CVSS 3.1 vectors are supported')

    @property
    def cvss_severity(self) -> str:
        if self.cvss_score == 0: return 'none'
        if self.cvss_score < 4: return 'low'
        if self.cvss_score < 7: return 'medium'
        if self.cvss_score < 9: return 'high'
        return 'critical'

    def to_dict(self) -> dict:
        return {
            'rule_id': self.rule_id, 'title': self.title, 'description': self.description,
            'cwe': list(self.cwe), 'owasp': list(self.owasp), 'mitre': list(self.mitre),
            'cvss': {'score': self.cvss_score, 'severity': self.cvss_severity, 'vector': self.cvss_vector},
            'remediation': {'summary': self.remediation.summary, 'steps': list(self.remediation.steps),
                'safe_example': self.remediation.safe_example, 'unsafe_example': self.remediation.unsafe_example},
            'references': [{'title': r.title, 'url': r.url, 'kind': r.kind.value} for r in self.references],
            'tags': list(self.tags),
        }
