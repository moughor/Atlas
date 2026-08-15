"""Concise deterministic human rendering for engineering answers."""

from __future__ import annotations

from .models import (
    EngineeringAnswer,
    EngineeringAnswerItem,
    EngineeringAnswerSection,
    EngineeringAnswerSynthesis,
)


def render_engineering_answer(result: EngineeringAnswerSynthesis) -> str:
    if not isinstance(result, EngineeringAnswerSynthesis):
        raise TypeError("renderer requires an EngineeringAnswerSynthesis")
    if result.answer is None:
        lines = [
            "ATLAS DETERMINISTIC ENGINEERING ANSWER",
            "",
            f"RESOLUTION: {result.resolution_status}",
            f"QUERY: {result.query}",
        ]
        if result.candidates:
            lines.extend(("", "DISAMBIGUATION CANDIDATES"))
            lines.extend(
                f"- {item.canonical_id} | {item.qualified_name} | "
                f"project={item.project} | kind={item.kind}"
                for item in result.candidates
            )
            if result.omitted_candidate_count:
                lines.append(
                    f"- omitted candidates: {result.omitted_candidate_count}"
                )
        if result.limitations:
            lines.extend(("", "LIMITATIONS"))
            lines.extend(f"- {item}" for item in result.limitations)
        lines.extend(("", "TRACEABILITY", f"- snapshot: {result.snapshot_id}"))
        return "\n".join(lines).rstrip() + "\n"
    return _render_answer(result.answer)


def _render_answer(answer: EngineeringAnswer) -> str:
    subject = answer.subject
    lines = [
        "ATLAS DETERMINISTIC ENGINEERING ANSWER",
        "",
        "SUBJECT",
        f"- canonical ID: {subject.canonical_id}",
        f"- qualified callable: {subject.qualified_name}",
        f"- kind: {subject.kind}",
        f"- authoritative project: {subject.project}",
        f"- source classification: {subject.source_classification}",
        f"- source: {subject.source_ref}",
        "",
        "CHANGE RISK SUMMARY",
    ]
    lines.extend(f"- {item}" for item in answer.change_risk_summary)
    lines.extend((
        "",
        "DIRECT CALLERS",
        _count_line(
            "high-confidence represented callers",
            answer.direct_callers_high_confidence,
        ),
    ))
    _append_items(lines, answer.direct_callers_high_confidence)
    lines.append(_count_line(
        "conservative represented caller sites",
        answer.direct_caller_conservative_sites,
        candidates=True,
    ))
    _append_items(lines, answer.direct_caller_conservative_sites)
    lines.append(_count_line(
        "caller method references (not execution impact)",
        answer.direct_caller_method_references,
    ))
    _append_items(lines, answer.direct_caller_method_references)

    lines.extend((
        "",
        "TRANSITIVE UPSTREAM IMPACT",
        _count_line("direct represented upstream paths", answer.upstream_direct),
        _count_line(
            "transitive represented upstream paths", answer.upstream_transitive,
        ),
        f"- traversal: direction={answer.traversal.direction}; "
        f"visited nodes={answer.traversal.visited_node_count}; "
        f"visited edges={answer.traversal.visited_edge_count}; "
        f"max depth={answer.traversal.configured_max_depth}; "
        f"max nodes={answer.traversal.configured_max_nodes}; "
        f"truncated={str(answer.traversal.truncated).lower()}",
    ))
    _append_upstream_items(lines, answer.upstream_direct)
    _append_upstream_items(lines, answer.upstream_transitive)

    lines.extend((
        "",
        "DIRECT DEPENDENCIES",
        _count_line(
            "high-confidence represented callees",
            answer.direct_callees_high_confidence,
        ),
    ))
    _append_items(lines, answer.direct_callees_high_confidence)
    lines.append(_count_line(
        "conservative call-site groups (candidate targets are not resolved dependencies)",
        answer.direct_callee_conservative_sites,
        candidates=True,
    ))
    _append_items(lines, answer.direct_callee_conservative_sites)
    lines.append(_count_line(
        "method references (not definite dependencies)",
        answer.direct_callee_method_references,
    ))
    _append_items(lines, answer.direct_callee_method_references)

    lines.extend((
        "",
        "REPRESENTED TEST SIGNAL",
        _count_line("direct represented TEST callers", answer.direct_test_callers),
        _count_line(
            "high-confidence represented TEST paths",
            answer.high_confidence_test_paths,
        ),
        _count_line(
            "possible represented TEST paths", answer.possible_test_paths,
        ),
        "- represented TEST reachability is not runtime test coverage",
        "- absence of a represented TEST path does not prove this subject is untested",
    ))
    _append_items(lines, answer.direct_test_callers)
    _append_items(lines, answer.high_confidence_test_paths)
    _append_items(lines, answer.possible_test_paths)

    lines.extend(("", "UNCERTAINTY"))
    for section in answer.uncertainty:
        lines.append(_count_line(section.section_id, section))
        _append_items(lines, section)
    lines.extend(("", "WHAT ATLAS CANNOT PROVE"))
    lines.extend(f"- {item}" for item in answer.limitations)

    lines.extend(("", "WHAT TO INSPECT FIRST"))
    if answer.inspect_first:
        for item in answer.inspect_first:
            lines.append(
                f"{item.priority}. {item.reason}; "
                f"reference={item.canonical_reference}; "
                f"source={item.source_ref}; "
                f"evidence={','.join(item.evidence_ids)}"
            )
    else:
        lines.append("- No represented priority item is available.")

    trace = answer.traceability
    lines.extend((
        "",
        "TRACEABILITY",
        "- canonical direction: CALLER -> CALLEE",
        "- impact traversal direction: reverse upstream",
        f"- snapshot: {trace.snapshot_id}",
        f"- PR159 input: {trace.code_impact_fingerprint}",
        f"- callable index: {trace.callable_index_fingerprint}",
        f"- code graph: {trace.code_graph_fingerprint}",
        f"- TEST evidence: {trace.test_evidence_fingerprint}",
        f"- reachability: {trace.reachability_fingerprint or 'unavailable'}",
        f"- deterministic hash: {answer.deterministic_hash}",
    ))
    return "\n".join(lines).rstrip() + "\n"


def _count_line(
    label: str,
    section: EngineeringAnswerSection,
    *,
    candidates: bool = False,
) -> str:
    line = (
        f"- {label}: total={section.total_count}; "
        f"included={section.included_count}; omitted={section.omitted_count}"
    )
    if candidates:
        line += (
            f"; candidate projections={section.candidate_projection_count}; "
            f"included candidates={section.included_candidate_count}; "
            f"omitted candidates={section.omitted_candidate_count}"
        )
    return line


def _append_items(
    lines: list[str],
    section: EngineeringAnswerSection,
) -> None:
    for item in section.items:
        lines.append(_item_line(item))


def _append_upstream_items(
    lines: list[str], section: EngineeringAnswerSection,
) -> None:
    high = tuple(
        item for item in section.items
        if item.confidence == 'high_confidence_represented_path'
    )
    conservative = tuple(
        item for item in section.items
        if item.confidence == 'conservative_represented_path'
    )
    lines.append(
        f'- {section.section_id} included high-confidence representatives: {len(high)}'
    )
    lines.extend(_item_line(item) for item in high)
    lines.append(
        f'- {section.section_id} included conservative representatives: {len(conservative)}'
    )
    lines.extend(_item_line(item) for item in conservative)
    if section.omitted_count:
        lines.append(
            f'- {section.section_id} omitted paths: {section.omitted_count}; '
            'their confidence distribution is not exposed by the bounded PR159 section'
        )


def _item_line(item: EngineeringAnswerItem) -> str:
    parts = [
        f"reference={item.canonical_reference}",
        f"confidence={item.confidence}",
    ]
    if item.canonical_source is not None and item.canonical_target is not None:
        parts.append(
            f"CALLER -> CALLEE={item.canonical_source} -> {item.canonical_target}"
        )
    if item.relationship_kind is not None:
        parts.append(f"relationship={item.relationship_kind}")
    if item.depth is not None:
        parts.append(f"depth={item.depth}")
    if item.total_candidate_count:
        candidates = ",".join(item.candidate_target_ids) or "none included"
        parts.extend((
            f"candidate targets (not resolved)={candidates}",
            f"total candidates={item.total_candidate_count}",
            f"omitted candidates={item.omitted_candidate_count}",
        ))
    parts.extend((
        f"source={item.source_ref}",
        f"evidence={','.join(item.evidence_ids)}",
    ))
    return "  - " + "; ".join(parts)
