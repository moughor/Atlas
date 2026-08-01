from __future__ import annotations

import re

from .models import StructuredExplanation


class StructuredExplanationRenderer:
    """Render the deterministic PR134 result without adding repository facts."""

    def render(self, explanation: StructuredExplanation) -> str:
        if not isinstance(explanation, StructuredExplanation):
            raise TypeError("renderer requires a StructuredExplanation")
        lines = [
            "# Atlas Structured Explanation",
            "",
            f"Availability: **{explanation.availability.value}**",
        ]
        if explanation.subject is not None:
            subject = explanation.subject
            lines.extend((
                "",
                "## Subject",
                "",
                f"- Name: {_code(subject.name)}",
                f"- Kind: {_code(subject.kind)}",
                f"- Canonical reference: {_code(subject.subject_id)}",
                f"- Language: {_code(subject.language)}",
            ))
            if subject.project:
                lines.append(f"- Project: {_code(subject.project)}")
            if subject.qualified_name:
                lines.append(f"- Qualified name: {_code(subject.qualified_name)}")
        if explanation.candidates:
            lines.extend(("", "## Disambiguation candidates", ""))
            for candidate in explanation.candidates:
                scope = f"; project {_code(candidate.project)}" if candidate.project else ""
                lines.append(
                    f"- {_code(candidate.subject_id)} — {_text(candidate.kind)} {_code(candidate.qualified_name or candidate.name)}{scope}"
                )
        if explanation.facts:
            lines.extend(("", "## Atlas facts", ""))
            for fact in explanation.facts:
                lines.append(f"### {fact.title}")
                lines.append("")
                lines.append(_text(fact.statement))
                lines.append("")
                lines.append(f"- Availability: {_code(fact.availability.value)}")
                lines.append(f"- Producers: {', '.join(_code(item) for item in fact.producer_ids) or _code('unavailable')}")
                if fact.confidence is not None:
                    lines.append(
                        f"- Confidence: `{fact.confidence.tier.value}` ({fact.confidence.score:.4f}; {fact.confidence_basis.value})"
                    )
                else:
                    lines.append(f"- Confidence: `{fact.confidence_basis.value}`")
                lines.append(
                    f"- Evidence: {', '.join(_code(item) for item in fact.evidence_ids) or _code('unavailable')}"
                )
                if fact.attributes:
                    lines.append(
                        "- Attributes: "
                        + ", ".join(
                            f"{_code(item.key)}={_code(str(item.value))}"
                            for item in fact.attributes
                        )
                    )
                if fact.references:
                    lines.append(
                        "- References: "
                        + ", ".join(_code(item) for item in fact.references)
                    )
                if fact.limitations:
                    lines.append(
                        "- Limitations: " + "; ".join(_text(item) for item in fact.limitations)
                    )
                lines.append("")
        lines.extend(("## Capability availability", ""))
        for capability in explanation.capabilities:
            suffix = ""
            if capability.coverage is not None:
                suffix = f"; coverage {capability.coverage:.4f}"
            lines.append(
                f"- {_code(capability.name)}: {_code(capability.availability.value)}{suffix}"
            )
            if capability.producer_ids:
                lines.append(
                    "  - Producers: "
                    + ", ".join(_code(item) for item in capability.producer_ids)
                )
            for limitation in capability.limitations:
                lines.append(f"  - Limitation: {_text(limitation)}")
        if explanation.limitations:
            lines.extend(("", "## Limitations", ""))
            lines.extend(f"- {_text(item)}" for item in explanation.limitations)
        lines.extend((
            "",
            "## Traceability",
            "",
            f"- Snapshot: `{explanation.snapshot_id}`",
            f"- Graph digest: `{explanation.graph_digest}`",
            f"- Context digest: `{explanation.context_digest}`",
            f"- Citations: `{len(explanation.citations)}`",
            f"- Truncated: `{str(explanation.selection.truncated).lower()}`",
        ))
        if explanation.selection.applied:
            lines.extend((
                f"- Token budget: `{explanation.selection.token_budget}`",
                f"- Estimated tokens: `{explanation.selection.estimated_tokens}`",
                f"- Facts: `{explanation.selection.included_fact_count}` included / `{explanation.selection.omitted_fact_count}` omitted",
                f"- Evidence: `{explanation.selection.included_evidence_count}` included / `{explanation.selection.omitted_evidence_count}` omitted",
            ))
        return "\n".join(lines).rstrip() + "\n"


def _one_line(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def _code(value: str) -> str:
    text = _one_line(str(value))
    longest = max((len(item) for item in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _text(value: str) -> str:
    text = _one_line(str(value))
    return re.sub(r"([\\`*_\[\]<>#])", r"\\\1", text)
