"""Validate LLM answers against an explicit deterministic evidence contract."""
from __future__ import annotations

import re

from moughorai.java_llm_contract.models import (
    AnswerCitation,
    AnswerValidationReport,
    JavaLlmAnswer,
    JavaLlmRequest,
    ValidationFinding,
    ValidationSeverity,
)

_CITATION_RE = re.compile(r"\[([A-Za-z]+\d+)\]")
_INSUFFICIENT_RE = re.compile(r"\binsufficient evidence\b", re.IGNORECASE)


class JavaLlmAnswerValidator:
    def parse(self, text: str) -> JavaLlmAnswer:
        citations = tuple(
            AnswerCitation(match.group(1), match.start(), match.end())
            for match in _CITATION_RE.finditer(text)
        )
        return JavaLlmAnswer(
            text=text,
            citations=citations,
            insufficient_evidence=bool(_INSUFFICIENT_RE.search(text)),
        )

    def validate(self, request: JavaLlmRequest, answer: JavaLlmAnswer | str) -> AnswerValidationReport:
        parsed = self.parse(answer) if isinstance(answer, str) else answer
        allowed = set(request.allowed_evidence_ids)
        cited = tuple(dict.fromkeys(item.evidence_id for item in parsed.citations))
        findings: list[ValidationFinding] = []

        for evidence_id in cited:
            if evidence_id not in allowed:
                findings.append(
                    ValidationFinding(
                        ValidationSeverity.ERROR,
                        "unknown-citation",
                        f"Answer cites evidence not present in the request: {evidence_id}",
                        evidence_id,
                    )
                )

        if parsed.text.strip() and not parsed.insufficient_evidence and not cited:
            findings.append(
                ValidationFinding(
                    ValidationSeverity.ERROR,
                    "missing-citation",
                    "A substantive answer must cite deterministic evidence.",
                )
            )

        if parsed.insufficient_evidence and cited:
            findings.append(
                ValidationFinding(
                    ValidationSeverity.WARNING,
                    "mixed-insufficiency",
                    "The answer declares insufficient evidence but also cites evidence.",
                )
            )

        if not allowed and not parsed.insufficient_evidence:
            findings.append(
                ValidationFinding(
                    ValidationSeverity.ERROR,
                    "unsupported-answer",
                    "No evidence was supplied; the answer must report insufficient evidence.",
                )
            )

        findings.sort(key=lambda item: (item.severity.value, item.code, item.evidence_id, item.message))
        valid = not any(item.severity is ValidationSeverity.ERROR for item in findings)
        return AnswerValidationReport(valid, tuple(findings), cited)
