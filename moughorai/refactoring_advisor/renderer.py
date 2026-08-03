"""Deterministic provider-free rendering for PR137 refactoring advice."""

from __future__ import annotations

from moughorai.subject_resolution import ResolutionStatus

from .models import RefactoringAdvice, RefactoringEstimate, RefactoringResponse


def render_refactoring_advice(
    response: RefactoringResponse,
    *,
    explain_score: bool = False,
) -> str:
    """Render a compact source-free report without invoking an LLM."""

    if not isinstance(response, RefactoringResponse):
        raise TypeError("refactoring renderer requires a RefactoringResponse")

    resolution = response.resolution
    lines = [
        "Atlas refactoring advisor",
        f"resolution: {resolution.status.value}",
    ]
    if resolution.status is ResolutionStatus.RESOLVED:
        if resolution.subject is None:
            raise ValueError("resolved refactoring response has no canonical subject")
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
            project = f" project={candidate.project}" if candidate.project else ""
            lines.append(
                f"- {candidate.qualified_name} [{candidate.kind.value}]"
                f" id={candidate.canonical_id}{project}"
            )
    else:
        lines.append("subject: unavailable")

    lines.extend((
        f"advice: {len(response.advice)}",
        f"candidates-discovered: {response.total_candidate_count}",
    ))
    if response.omitted_count:
        lines.append(f"omitted: {response.omitted_count}")
    if response.truncated:
        lines.append("truncated: yes")
    if response.advice:
        lines.append("recommendations:")
        for item in response.advice:
            lines.extend(_render_advice(item, explain_score=explain_score))
    elif resolution.status is ResolutionStatus.RESOLVED:
        lines.append(
            "No refactoring advice was proven from the available structured evidence."
        )

    lines.append("capabilities:")
    for capability in response.capabilities:
        coverage = (
            "unknown"
            if capability.coverage is None
            else f"{capability.coverage:.4f}"
        )
        lines.append(
            f"- {capability.family.value}: {capability.state.value}"
            f" candidates={capability.candidate_count} coverage={coverage}"
        )
        for limitation in capability.limitations:
            lines.append(f"  limitation: {limitation}")

    if response.limitations:
        lines.append("limitations:")
        lines.extend(f"- {item}" for item in response.limitations)
    return "\n".join(lines) + "\n"


def _render_advice(
    advice: RefactoringAdvice,
    *,
    explain_score: bool,
) -> tuple[str, ...]:
    attributes = dict(advice.attributes)
    by_id = {item.canonical_id: item for item in advice.subjects}
    source_id = attributes.get("source", advice.subjects[0].canonical_id)
    target_id = attributes.get("target", advice.subjects[-1].canonical_id)
    source = by_id.get(source_id)
    target = by_id.get(target_id)
    source_name = source.qualified_name if source is not None else source_id
    target_name = target.qualified_name if target is not None else target_id

    lines = [
        f"- {advice.operation.value}: {source_name} -> {target_name}",
        f"  id: {advice.advice_id}",
        f"  confidence: {advice.confidence.tier.value}"
        f" ({advice.confidence.score:.4f})",
        f"  expected-gain: {_estimate_summary(advice.expected_gain)}",
        f"  effort: {_estimate_summary(advice.effort)}",
        (
            f"  impact: {advice.impact.state.value}"
            f" affected={advice.impact.affected_count}"
            f" direct={advice.impact.direct_count}"
            f" transitive={advice.impact.transitive_count}"
            f" possible-breaking={advice.impact.possible_breaking_count}"
            f" breaking={advice.impact.breaking_state}"
            f" omitted={advice.impact.omitted_count}"
            f" truncated={'yes' if advice.impact.truncated else 'no'}"
        ),
        f"  rationale: {advice.rationale}",
        f"  evidence: {len(advice.evidence_ids)}",
    ]
    for precondition in advice.preconditions:
        lines.append(f"  precondition: {precondition}")
    if explain_score:
        lines.extend(_render_estimate_components("gain", advice.expected_gain))
        lines.extend(_render_estimate_components("effort", advice.effort))
        lines.extend((
            f"  confidence.support: {advice.confidence.support:.4f}",
            f"  confidence.coverage: {advice.confidence.coverage:.4f}",
            f"  confidence.agreement: {advice.confidence.agreement:.4f}",
            f"  confidence.contradiction-penalty: "
            f"{advice.confidence.contradiction_penalty:.4f}",
            f"  confidence.ambiguity-penalty: "
            f"{advice.confidence.ambiguity_penalty:.4f}",
        ))
    for limitation in advice.expected_gain.limitations:
        lines.append(f"  gain-limitation: {limitation}")
    for limitation in advice.effort.limitations:
        lines.append(f"  effort-limitation: {limitation}")
    for limitation in advice.impact.limitations:
        lines.append(f"  impact-limitation: {limitation}")
    for limitation in advice.limitations:
        lines.append(f"  limitation: {limitation}")
    for verification in advice.verification:
        lines.append(f"  verify: {verification}")
    return tuple(lines)


def _estimate_summary(estimate: RefactoringEstimate) -> str:
    score = "unknown" if estimate.score is None else f"{estimate.score:.4f}"
    return f"{estimate.level.value} score={score}"


def _render_estimate_components(
    prefix: str,
    estimate: RefactoringEstimate,
) -> tuple[str, ...]:
    lines = []
    for component in estimate.components:
        if component.available:
            lines.append(
                f"  {prefix}.{component.name}: value={component.value:.4f}"
                f" weight={component.weight:.4f}"
                f" contribution={component.contribution:.4f}"
            )
        else:
            lines.append(f"  {prefix}.{component.name}: unavailable")
            if component.limitation is not None:
                lines.append(
                    f"  {prefix}.{component.name}.limitation: "
                    f"{component.limitation}"
                )
    return tuple(lines)
