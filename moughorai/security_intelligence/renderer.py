"""Provider-free rendering for deterministic PR138 security intelligence."""

from __future__ import annotations

from .models import SecurityIntelligenceReport


def render_security_intelligence(
    report: SecurityIntelligenceReport,
    *,
    explain_priority: bool = False,
) -> str:
    if not isinstance(report, SecurityIntelligenceReport):
        raise TypeError("security intelligence renderer requires a report")
    lines = [
        "Atlas security intelligence",
        f"findings: {len(report.findings)}",
        f"findings-discovered: {report.total_finding_count}",
        f"graph: {report.graph_digest}",
    ]
    if report.omitted_count:
        lines.append(f"omitted: {report.omitted_count}")
    if report.truncated:
        lines.append("truncated: yes")
    if report.findings:
        lines.append("prioritized-findings:")
        for finding in report.findings:
            lines.extend((
                f"- {finding.rule_id} [{finding.severity.value}] {finding.category.value}",
                f"  id: {finding.finding_id}",
                f"  project: {finding.project_id}",
                f"  location: {finding.location.path}:{finding.location.line}:{finding.location.column}",
                f"  confidence: {finding.confidence.tier.value} ({finding.confidence.score:.4f})",
                f"  priority: {finding.priority.tier.value} ({finding.priority.score:.4f}) coverage={finding.priority.coverage:.4f}",
                f"  evidence: {len(finding.evidence_ids)}",
            ))
            if finding.canonical_subject_id is not None:
                lines.append(f"  canonical-subject: {finding.canonical_subject_id}")
            if explain_priority:
                for component in finding.priority.components:
                    if component.available:
                        lines.append(
                            f"  priority.{component.name}: value={component.value:.4f} "
                            f"weight={component.weight:.4f} contribution={component.contribution:.4f}"
                        )
                    else:
                        lines.append(f"  priority.{component.name}: unavailable")
            for limitation in finding.limitations:
                lines.append(f"  limitation: {limitation}")
    else:
        lines.append("No finding was proven from the available producer evidence.")
        lines.append("This does not establish that the requested scope is secure.")
    lines.append("capabilities:")
    for capability in report.capabilities:
        coverage = "unknown" if capability.coverage is None else f"{capability.coverage:.4f}"
        lines.append(
            f"- {capability.category.value}: {capability.state.value} "
            f"findings={capability.finding_count} coverage={coverage}"
        )
        for limitation in capability.limitations:
            lines.append(f"  limitation: {limitation}")
    if report.limitations:
        lines.append("limitations:")
        lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines) + "\n"


__all__ = ["render_security_intelligence"]
