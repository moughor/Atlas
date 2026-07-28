"""Build stable, evidence-constrained prompts from deterministic retrieval context."""
from __future__ import annotations

import re

from moughorai.java_retrieval.models import LlmContext
from moughorai.java_llm_contract.models import AnswerMode, EvidenceItem, JavaLlmRequest

_EVIDENCE_RE = re.compile(r"^\[([SRE]\d+)\]\s*(.+)$")


class JavaLlmRequestBuilder:
    SYSTEM_PROMPT = (
        "You are the explanation layer for a deterministic Java analysis engine. "
        "Use only the supplied evidence. Cite every architecture or code claim with "
        "an evidence identifier in square brackets. Never invent symbols, dependencies, "
        "endpoints, entities, files, or call paths. When evidence is insufficient, state "
        "that explicitly."
    )

    def build(
        self,
        context: LlmContext,
        *,
        mode: AnswerMode = AnswerMode.FACTUAL,
    ) -> JavaLlmRequest:
        evidence = self._extract_evidence(context.text)
        allowed = tuple(item.evidence_id for item in evidence)
        unresolved = "\n".join(f"- {item}" for item in context.unresolved) or "- none"
        user_prompt = "\n".join(
            (
                f"QUESTION: {context.query}",
                f"ANSWER MODE: {mode.value}",
                "",
                "EVIDENCE:",
                context.text,
                "",
                "UNRESOLVED REFERENCES:",
                unresolved,
                "",
                "RESPONSE CONTRACT:",
                "1. Answer only from EVIDENCE.",
                "2. Put citations such as [S1] or [E2] immediately after supported claims.",
                "3. Do not cite identifiers absent from ALLOWED EVIDENCE IDS.",
                "4. Say 'Insufficient evidence' when the evidence does not support an answer.",
                "5. Keep uncertainty explicit.",
                "",
                "ALLOWED EVIDENCE IDS: " + (", ".join(allowed) if allowed else "none"),
            )
        )
        return JavaLlmRequest(
            question=context.query,
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            evidence=evidence,
            allowed_evidence_ids=allowed,
            mode=mode,
        )

    def _extract_evidence(self, text: str) -> tuple[EvidenceItem, ...]:
        items: list[EvidenceItem] = []
        for line in text.splitlines():
            match = _EVIDENCE_RE.match(line.strip())
            if not match:
                continue
            evidence_id, statement = match.groups()
            kind = {"S": "primary-symbol", "R": "related-symbol", "E": "relationship"}[evidence_id[0]]
            items.append(EvidenceItem(evidence_id, kind, statement.strip()))
        return tuple(items)
