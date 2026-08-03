"""Deterministic provider-free rendering for PR136 impact predictions."""

from __future__ import annotations

from moughorai.subject_resolution import ResolutionStatus

from .models import ImpactFinding, ImpactPredictionResponse


def render_impact_prediction(
    response: ImpactPredictionResponse,
    *,
    explain_score: bool = False,
) -> str:
    """Render a compact source-free report without an LLM."""

    if not isinstance(response, ImpactPredictionResponse):
        raise TypeError("impact renderer requires an ImpactPredictionResponse")
    resolution = response.resolution
    lines = [
        "Atlas impact prediction",
        f"resolution: {resolution.status.value}",
        f"change: {response.request.change_kind.value}",
    ]
    if resolution.status is ResolutionStatus.RESOLVED:
        if resolution.subject is None:
            raise ValueError("resolved impact response has no canonical subject")
        subject = resolution.subject
        lines.extend((
            f"subject: {subject.qualified_name}",
            f"canonical-id: {subject.canonical_id}",
            f"graph: {response.graph_digest}",
        ))
    elif resolution.status is ResolutionStatus.AMBIGUOUS:
        lines.append(
            f"candidates: {len(resolution.candidates)}"
            + (
                f" (+{resolution.omitted_candidate_count} omitted)"
                if resolution.omitted_candidate_count
                else ""
            )
        )
        for candidate in resolution.candidates:
            scope = f" project={candidate.project}" if candidate.project else ""
            lines.append(
                f"- {candidate.qualified_name} [{candidate.kind.value}]"
                f" id={candidate.canonical_id}{scope}"
            )
    else:
        lines.append("subject: unavailable")

    if response.additional_resolutions:
        lines.append(
            f"additional-sources: {len(response.additional_resolutions)}"
        )
        for additional in response.additional_resolutions:
            if additional.subject is not None:
                lines.append(
                    f"- {additional.subject.qualified_name}"
                    f" status={additional.status.value}"
                    f" id={additional.subject.canonical_id}"
                )
            else:
                omitted = (
                    f" omitted={additional.omitted_candidate_count}"
                    if additional.omitted_candidate_count
                    else ""
                )
                lines.append(
                    f"- {additional.query.identifier}"
                    f" status={additional.status.value}"
                    f" candidates={len(additional.candidates)}{omitted}"
                )

    if resolution.status is ResolutionStatus.RESOLVED:
        lines.extend((
            f"findings: {len(response.findings)}",
            f"direct: {len(response.direct_impacts)}",
            f"transitive: {len(response.transitive_impacts)}",
        ))
        if response.omitted_count:
            lines.append(f"omitted: {response.omitted_count}")
        if response.truncated:
            lines.append("truncated: yes")
        if not response.findings:
            lines.append(
                "No affected in-repository subject was proven from the available structured evidence."
            )
        else:
            lines.append("impacts:")
            lines.extend(
                _render_finding(item, explain_score=explain_score)
                for item in response.findings
            )

    breaking = response.breaking_change
    lines.extend((
        "breaking-change:",
        f"- state: {breaking.state.value}",
        f"- explanation: {breaking.explanation}",
    ))
    for limitation in breaking.limitations:
        lines.append(f"- limitation: {limitation}")

    lines.append("capabilities:")
    for capability in response.capabilities:
        coverage = (
            "unknown"
            if capability.coverage is None
            else f"{capability.coverage:.4f}"
        )
        lines.append(
            f"- {capability.name}: {capability.state.value} coverage={coverage}"
        )
        for limitation in capability.limitations:
            lines.append(f"  limitation: {limitation}")
    if response.limitations:
        lines.append("limitations:")
        lines.extend(f"- {item}" for item in response.limitations)
    return "\n".join(lines) + "\n"


def _render_finding(
    finding: ImpactFinding,
    *,
    explain_score: bool,
) -> str:
    relationship_path = " -> ".join(
        step.relation.value for step in finding.path.steps
    )
    scope = f" project={finding.subject.project}" if finding.subject.project else ""
    lines = [
        f"- {finding.subject.qualified_name} [{finding.category.value}]"
        f" direct={'yes' if finding.direct else 'no'}"
        f" depth={finding.path.length} score={finding.score.value:.4f}"
        f" confidence={finding.confidence.tier.value}"
        f" id={finding.subject.canonical_id}{scope}",
        f"  evidence-path: {relationship_path}",
        f"  reason: {finding.explanation}",
    ]
    if explain_score:
        for component in finding.score.components:
            lines.append(
                f"  score.{component.name}: value={component.value:.4f}"
                f" weight={component.weight:.4f}"
                f" contribution={component.contribution:.4f}"
            )
    for limitation in finding.limitations:
        lines.append(f"  limitation: {limitation}")
    return "\n".join(lines)
