"""Atlas-owned deterministic rendering for PR159 code intelligence."""

from __future__ import annotations

from .models import (
    BoundedPaths,
    BoundedRelationships,
    JavaCodeIntelligenceResult,
)


def render_code_intelligence(result: JavaCodeIntelligenceResult) -> str:
    if not isinstance(result, JavaCodeIntelligenceResult):
        raise TypeError("code-intelligence renderer requires a PR159 result")
    lines = [
        "Atlas Java code intelligence",
        f"availability: {result.availability.value}",
        f"resolution: {result.resolution.status.value}",
    ]
    if result.report is None:
        lines.append(f"subject-query: {result.resolution.query}")
        for candidate in result.resolution.candidates:
            lines.append(
                f"candidate: {candidate.canonical_id} "
                f"kind={candidate.kind.value} project={candidate.project}"
            )
        for limitation in result.limitations:
            lines.append(f"limitation: {limitation}")
        return "\n".join(lines) + "\n"

    report = result.report
    subject = report.subject
    lines.extend((
        f"subject: {subject.display_name}",
        f"canonical-id: {subject.canonical_id}",
        f"kind: {subject.kind.value}",
        f"project: {subject.project}",
        f"source: {subject.source.compact}",
        "canonical-direction: CALLER -> CALLEE",
        "canonical-relation: calls",
        "impact-traversal-direction: reverse upstream (CHANGED CALLEE <- CALLER)",
        "",
        "direct callers:",
    ))
    _relationships(lines, "high-confidence", report.direct_callers_high_confidence)
    _relationships(lines, "conservative", report.direct_callers_conservative)
    _relationships(lines, "method-reference", report.direct_caller_method_references)
    lines.extend(("", "direct callees:"))
    _relationships(lines, "high-confidence", report.direct_callees_high_confidence)
    _relationships(lines, "conservative", report.direct_callees_conservative)
    _relationships(lines, "method-reference", report.direct_callee_method_references)

    lines.extend(("", "upstream change impact:"))
    _paths(lines, "direct", report.upstream_direct)
    _paths(lines, "transitive", report.upstream_transitive)
    traversal = report.traversal
    histogram = ", ".join(
        f"depth {depth}={count}" for depth, count in traversal.depth_histogram
    ) or "none"
    lines.append(
        "traversal-metrics: "
        f"visited-nodes={traversal.visited_node_count} "
        f"visited-edges={traversal.visited_edge_count} "
        f"depths={histogram} truncated={str(traversal.truncated).lower()}"
    )

    lines.extend(("", "represented TEST intelligence:"))
    _relationships(lines, "direct-test-callers", report.direct_test_callers)
    _paths(lines, "high-confidence-test-paths", report.high_confidence_test_paths)
    _paths(lines, "possible-test-paths", report.possible_test_paths)
    if report.negative_test_statement:
        lines.append(f"statement: {report.negative_test_statement}")
    lines.append("runtime-test-coverage-proven: false")

    lines.extend(("", "capability availability:"))
    for capability in report.capability_availability:
        lines.append(f"- {capability.name}: {capability.availability.value}")
        for limitation in capability.limitations:
            lines.append(f"  limitation: {limitation}")

    lines.extend(("", "bounded limitations:"))
    if not report.limitations:
        lines.append("- none represented in the bounded neighborhood")
    for summary in report.limitations:
        lines.append(
            f"- {summary.category}: count={summary.total_count} "
            f"included={len(summary.representatives)} omitted={summary.omitted_count}"
        )
        for item in summary.representatives:
            lines.append(
                f"  evidence={item.producer_evidence_id} "
                f"caller={item.caller_subject_id} source={item.location.compact}"
            )

    lines.extend(("", "limitations:"))
    for limitation in report.general_limitations:
        lines.append(f"- {limitation}")
    trace = report.traceability
    lines.extend((
        "",
        "traceability:",
        f"- snapshot: {trace.snapshot_id}",
        f"- callable-index: {trace.callable_index_fingerprint}",
        f"- code-graph: {trace.code_graph_fingerprint}",
        f"- test-evidence: {trace.test_evidence_fingerprint}",
        f"- reachability: {trace.reachability_fingerprint or 'unavailable'}",
        f"- query-fingerprint: {report.input_fingerprint}",
    ))
    return "\n".join(lines) + "\n"


def _relationships(
    lines: list[str],
    label: str,
    section: BoundedRelationships,
) -> None:
    lines.append(
        f"{label}: total={section.total_count} "
        f"included={len(section.items)} omitted={section.omitted_count}"
    )
    for item in section.items:
        lines.append(
            f"- {item.canonical_source} -> {item.canonical_target} "
            f"relation={item.relation} role={item.subject_relative_role.value} "
            f"edge={item.edge_kind.value} confidence={item.confidence.value} "
            f"evidence={item.producer_evidence_id} source={item.location.compact}"
        )


def _paths(lines: list[str], label: str, section: BoundedPaths) -> None:
    lines.append(
        f"{label}: total={section.total_count} "
        f"included={len(section.items)} omitted={section.omitted_count}"
    )
    for item in section.items:
        canonical = " ; ".join(
            f"{step.canonical_source} -> {step.canonical_target}"
            for step in item.steps
        ) or item.subject_id
        lines.append(
            f"- consumer={item.consumer_subject_id} depth={item.depth} "
            f"confidence={item.confidence.value} "
            f"traversal={item.traversal_direction.value} "
            f"canonical-path={canonical} "
            f"evidence={','.join(item.producer_evidence_ids)}"
        )
