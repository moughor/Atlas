"""Deterministic source-free rendering for PR142 results."""

from __future__ import annotations

import json

from .models import TechnicalDebtResponse


def render_technical_debt(response: TechnicalDebtResponse) -> str:
    if not isinstance(response, TechnicalDebtResponse):
        raise TypeError("technical debt renderer requires TechnicalDebtResponse")
    lines = [
        "Atlas Technical Debt Observations",
        (
            f"upstream-observations: total={response.total_candidate_count}; "
            f"evaluated={response.evaluated_count}; "
            f"equivalent={response.equivalent_observation_count}; "
            f"unevaluated={response.unevaluated_count}"
        ),
        (
            f"unique-candidates: evaluated={response.unique_evaluated_count}; "
            f"returned={response.returned_count}; "
            f"output-omitted={response.output_omitted_count}; "
            f"all-omitted-observations={response.omitted_count}"
        ),
        (
            f"ranking: ranked={response.ranked_count}; "
            f"unranked={response.unranked_count}; ordinal-only=yes"
        ),
        "",
        "Capabilities",
    ]
    for capability in response.capabilities:
        coverage = (
            f"; coverage={capability.coverage:.4f}"
            if capability.coverage is not None else ""
        )
        lines.append(
            f"- {_display(capability.capability.value)}: "
            f"{_display(capability.state.value)}{coverage}"
        )
        for limitation in capability.limitations:
            lines.append(f"  limitation: {_display(limitation)}")

    lines.extend(("", "Dependency-Cycle Observations"))
    if not response.items:
        lines.append("- none retained; this does not prove that the repository has no technical debt")
    for item in response.items:
        rank = str(item.rank) if item.rank is not None else "unranked"
        risk = (
            f"; risk-subject={_display(item.risk_subject_id)}; "
            f"risk-rank={item.risk_context.rank}; "
            f"risk-score={item.risk_context.score:.4f}"
            if item.risk_context is not None else "; risk=unavailable"
        )
        complexity = (
            "; complexity=observed; complexity-subjects="
            + _display(",".join(item.complexity_subject_ids))
            if item.complexity_observed
            else "; complexity=unknown"
        )
        lines.append(
            f"- rank={rank}; source={_display(item.source.qualified_name)}; "
            f"target={_display(item.target.qualified_name)}; "
            f"impact={_display(item.impact.state.value)}; "
            f"affected={item.impact.affected_count}; "
            f"confidence={item.confidence.tier.value}/{item.confidence.score:.4f}"
            f"{risk}{complexity}; "
            f"advice-evidence={len(item.evidence_backed_refactoring_advice_ids)}/"
            f"{len(item.refactoring_advice_ids)}"
        )
        lines.append(f"  observation: {_display(item.observation)}")

    lines.extend(("", "Interpretation Limits"))
    lines.extend((
        "- A dependency cycle is not by itself proof of a defect or technical debt.",
        "- Risk context is not proof of debt and does not rescore the ranking.",
        "- Static impact is not runtime execution or external-consumer behavior.",
        "- Effort, business priority, ownership, developer intent, and remediation remain unknown.",
    ))
    for limitation in response.limitations:
        lines.append(f"- {_display(limitation)}")
    return "\n".join(lines) + "\n"


def _display(value: object) -> str:
    encoded = json.dumps(str(value), ensure_ascii=True)
    return encoded[1:-1]
