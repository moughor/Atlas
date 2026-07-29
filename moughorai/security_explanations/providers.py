from __future__ import annotations
from typing import Protocol
from .models import VulnerabilityExplanation

class ExplanationProvider(Protocol):
    name: str
    def polish(self, explanation: VulnerabilityExplanation) -> VulnerabilityExplanation: ...

class IdentityExplanationProvider:
    name='identity'
    def polish(self, explanation): return explanation
