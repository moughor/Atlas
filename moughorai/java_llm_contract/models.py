"""Immutable contracts for grounded LLM interactions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnswerMode(str, Enum):
    FACTUAL = "factual"
    IMPACT = "impact"
    ARCHITECTURE = "architecture"
    EXPLANATION = "explanation"


class ValidationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, order=True)
class EvidenceItem:
    evidence_id: str
    kind: str
    statement: str


@dataclass(frozen=True)
class JavaLlmRequest:
    question: str
    system_prompt: str
    user_prompt: str
    evidence: tuple[EvidenceItem, ...] = ()
    allowed_evidence_ids: tuple[str, ...] = ()
    mode: AnswerMode = AnswerMode.FACTUAL


@dataclass(frozen=True, order=True)
class AnswerCitation:
    evidence_id: str
    start: int
    end: int


@dataclass(frozen=True)
class JavaLlmAnswer:
    text: str
    citations: tuple[AnswerCitation, ...] = ()
    insufficient_evidence: bool = False


@dataclass(frozen=True, order=True)
class ValidationFinding:
    severity: ValidationSeverity
    code: str
    message: str
    evidence_id: str = ""


@dataclass(frozen=True)
class AnswerValidationReport:
    valid: bool
    findings: tuple[ValidationFinding, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        return tuple(item for item in self.findings if item.severity is ValidationSeverity.ERROR)
