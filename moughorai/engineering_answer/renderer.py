"""Concise deterministic human rendering for engineering answers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import re

from .models import (
    EngineeringAnswer,
    EngineeringAnswerItem,
    EngineeringAnswerSection,
    EngineeringAnswerSynthesis,
)


class EngineeringAnswerView(str, Enum):
    SUMMARY = 'summary'
    DETAIL = 'detail'
    FULL = 'full'


EngineeringAnswerNameResolver = Callable[[str], str | None]


_UNCERTAINTY_LABELS = {
    'unresolved_sites': 'unresolved',
    'external_sites': 'external',
    'unsupported_sites': 'unsupported',
    'ambiguous_candidates': 'ambiguous',
    'possible_dispatch_candidates': 'possible dispatch',
    'method_references': 'method references',
    'call_extraction_failures': 'call extraction failures',
    'callable_bodies_unavailable': 'callable bodies unavailable',
    'omitted_callable_diagnostics': 'omitted callable diagnostics',
    'unindexed_callables': 'unindexed callables',
    'omitted_code_graph_diagnostics': 'omitted code graph diagnostics',
    'traversal_truncation': 'traversal truncation',
}
_UNCERTAINTY_SINGULAR_LABELS = {
    'unindexed_callables': 'unindexed callable',
}
_CALL_EVIDENCE_UNCERTAINTY = frozenset({
    'unresolved_sites',
    'external_sites',
    'unsupported_sites',
    'ambiguous_candidates',
    'possible_dispatch_candidates',
    'method_references',
    'traversal_truncation',
})
_WORKSPACE_ARTIFACT_LIMITATIONS = frozenset({
    'call_extraction_failures',
    'callable_bodies_unavailable',
    'omitted_callable_diagnostics',
    'omitted_code_graph_diagnostics',
    'unindexed_callables',
})
_HIGH_CONFIDENCE_UPSTREAM = 'high_confidence_represented_path'
_QUALIFIED_TYPE = re.compile(
    r'(?<![A-Za-z0-9_$])(?:[a-z_][A-Za-z0-9_$]*\.)+([A-Z][A-Za-z0-9_$]*)'
)


@dataclass(frozen=True, slots=True)
class _SummaryInspectCandidate:
    category: str
    reason: str
    canonical_reference: str
    source_ref: str
    evidence_ids: tuple[str, ...]


def render_engineering_answer(
    result: EngineeringAnswerSynthesis,
    *,
    view: EngineeringAnswerView | str = EngineeringAnswerView.FULL,
    name_resolver: EngineeringAnswerNameResolver | None = None,
) -> str:
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
    selected_view = (
        view if isinstance(view, EngineeringAnswerView)
        else EngineeringAnswerView(str(view).strip().casefold())
    )
    if selected_view is EngineeringAnswerView.SUMMARY:
        return _render_summary(result.answer, name_resolver=name_resolver)
    if selected_view is EngineeringAnswerView.DETAIL:
        return _render_detail(result.answer, name_resolver=name_resolver)
    return _render_answer(result.answer)


def _render_summary(
    answer: EngineeringAnswer,
    *,
    name_resolver: EngineeringAnswerNameResolver | None,
    include_more: bool = True,
) -> str:
    subject = answer.subject
    direct = answer.upstream_direct.total_count
    transitive = answer.upstream_transitive.total_count
    lines = [
        'ATLAS DETERMINISTIC ENGINEERING ANSWER',
        '',
        'SUBJECT',
        _human_callable_name(subject.qualified_name),
        f'project: {subject.project}',
        f'source: {subject.source_ref}',
        f'kind: {subject.kind}',
        f'canonical ID: {subject.canonical_id}',
        f'qualified callable: {subject.qualified_name}',
        '',
        'CHANGE IMPACT',
        _total_line(
            answer.direct_callers_high_confidence.total_count,
            'high-confidence represented direct caller',
        ),
    ]
    if answer.direct_caller_conservative_sites.total_count:
        lines.append(_total_line(
            answer.direct_caller_conservative_sites.total_count,
            'conservative represented caller site (candidate targets unproven)',
            'conservative represented caller sites (candidate targets unproven)',
        ))
    lines.extend((
        _total_line(direct, 'direct represented upstream consumer'),
        _total_line(transitive, 'transitive represented upstream consumer'),
    ))
    if answer.traversal.truncated:
        lines.extend((
            'truncated=true — TRAVERSAL TRUNCATED at the configured bound '
            f'(depth {answer.traversal.configured_max_depth}, '
            f'nodes {_number(answer.traversal.configured_max_nodes)}).',
            f'At least {_number(direct + transitive)} represented upstream consumers '
            'were found before the configured traversal bound.',
        ))
    else:
        lines.append('truncated=false')

    lines.extend((
        '',
        'DIRECT DEPENDENCIES',
        _total_line(
            answer.direct_callees_high_confidence.total_count,
            'high-confidence represented direct callee',
        ),
        _total_line(
            answer.direct_callee_conservative_sites.total_count,
            'conservative dependency site (candidate targets unproven)',
            'conservative dependency sites (candidate targets unproven)',
        ),
        '',
        'REPRESENTED TEST SIGNAL',
        _total_line(
            answer.direct_test_callers.total_count,
            'direct represented TEST caller',
        ),
        _total_line(
            answer.high_confidence_test_paths.total_count,
            'high-confidence represented TEST path',
        ),
        _total_line(
            answer.possible_test_paths.total_count,
            'possible represented TEST path',
        ),
    ))
    _append_summary_test_roots(
        lines,
        answer,
        name_resolver=name_resolver,
    )
    call_uncertainty = tuple(
        section for section in answer.uncertainty
        if section.section_id in _CALL_EVIDENCE_UNCERTAINTY
    )
    workspace_limitations = tuple(
        section for section in answer.uncertainty
        if section.section_id in _WORKSPACE_ARTIFACT_LIMITATIONS
    )
    other_limitations = tuple(
        section for section in answer.uncertainty
        if section.section_id not in (
            _CALL_EVIDENCE_UNCERTAINTY | _WORKSPACE_ARTIFACT_LIMITATIONS
        )
    )
    _append_uncertainty_scope(
        lines,
        'UNCERTAINTY IN REPRESENTED CALL EVIDENCE',
        call_uncertainty,
        empty='0 represented call-evidence uncertainty signals',
    )
    _append_uncertainty_scope(
        lines,
        'WORKSPACE ARTIFACT LIMITATIONS',
        workspace_limitations,
        empty='0 represented workspace artifact limitations',
        scope_note='Counts describe the loaded workspace artifact, not only this subject.',
    )
    if other_limitations:
        _append_uncertainty_scope(
            lines,
            'OTHER REPRESENTED LIMITATIONS',
            other_limitations,
            empty='0 other represented limitations',
            scope_note='These categories have no narrower scope classification in this presentation.',
        )

    lines.extend(('', 'INSPECT FIRST'))
    selected_inspect = _select_summary_inspect(answer, maximum=5)
    if selected_inspect:
        for ordinal, item in enumerate(selected_inspect, start=1):
            reference = _resolved_name(
                item.canonical_reference, name_resolver,
            )
            lines.append(
                f'{ordinal}. {reference} — {item.reason}; source={item.source_ref}'
            )
    else:
        lines.append('No represented priority item is available.')

    lines.extend((
        '',
        'LIMITS',
        'Represented source evidence only; a complete runtime blast radius is not proven.',
        'Runtime dispatch, reflection, dependency injection, generated wiring, and framework dispatch are not proven.',
        'Represented TEST reachability is not runtime coverage; runtime TEST execution and behavioral coverage are not proven.',
    ))
    if include_more:
        lines.extend((
            '',
            'MORE',
            'Use detail for bounded representatives or full for complete PR167 evidence traceability.',
        ))
    return '\n'.join(lines).rstrip() + '\n'


def _append_summary_test_roots(
    lines: list[str],
    answer: EngineeringAnswer,
    *,
    name_resolver: EngineeringAnswerNameResolver | None,
) -> None:
    roots = tuple((
        *answer.high_confidence_test_paths.items,
        *answer.possible_test_paths.items,
    ))
    root_ids = {item.canonical_reference for item in roots}
    lines.extend(('', 'REPRESENTED TEST ROOTS TO INSPECT'))
    if roots:
        lines.append('; '.join(
            f'{ordinal}. {_resolved_name(item.canonical_reference, name_resolver)} '
            f'[{item.confidence}; depth={item.depth}]'
            for ordinal, item in enumerate(roots, start=1)
        ))
    else:
        lines.append('No represented TEST-root path was found.')
    omitted = (
        answer.high_confidence_test_paths.omitted_count
        + answer.possible_test_paths.omitted_count
    )
    if omitted:
        lines.append(
            f'{_number(omitted)} additional represented TEST root(s) were '
            'omitted by the existing section bound.'
        )

    helper_candidates = tuple(
        item for item in answer.direct_test_callers.items
        if item.canonical_reference not in root_ids
    )
    test_projection_complete = not omitted
    lines.extend(('', 'TEST-SCOPED HELPER CONTEXT'))
    if helper_candidates and test_projection_complete:
        lines.extend(
            f'- {_resolved_name(item.canonical_reference, name_resolver)} — '
            'TEST-scoped helper context only; not a represented TEST root.'
            for item in helper_candidates
        )
    elif helper_candidates:
        lines.extend(
            f'- {_resolved_name(item.canonical_reference, name_resolver)} — '
            'direct TEST-scoped caller; the bounded TEST-root projection is incomplete.'
            for item in helper_candidates
        )
    else:
        lines.append('No separate TEST-scoped helper is represented.')


def _render_detail(
    answer: EngineeringAnswer,
    *,
    name_resolver: EngineeringAnswerNameResolver | None,
) -> str:
    lines = _render_summary(
        answer,
        name_resolver=name_resolver,
        include_more=False,
    ).rstrip().splitlines()
    lines.extend(('', 'DETAIL REPRESENTATIVES'))
    _append_detail_group(
        lines,
        'DIRECT CALLERS',
        (
            answer.direct_callers_high_confidence,
            answer.direct_caller_conservative_sites,
            answer.direct_caller_method_references,
        ),
        name_resolver,
    )
    _append_detail_group(
        lines,
        'UPSTREAM PATHS',
        (answer.upstream_direct, answer.upstream_transitive),
        name_resolver,
    )
    _append_detail_group(
        lines,
        'DIRECT DEPENDENCIES',
        (
            answer.direct_callees_high_confidence,
            answer.direct_callee_conservative_sites,
            answer.direct_callee_method_references,
        ),
        name_resolver,
    )
    _append_detail_group(
        lines,
        'REPRESENTED TEST PATHS',
        (
            answer.direct_test_callers,
            answer.high_confidence_test_paths,
            answer.possible_test_paths,
        ),
        name_resolver,
    )
    _append_detail_group(
        lines,
        'UNCERTAINTY EXAMPLES',
        answer.uncertainty,
        name_resolver,
    )
    lines.extend((
        '',
        'DETAIL TRACEABILITY',
        f'- snapshot: {answer.traceability.snapshot_id}',
        '- canonical direction: CALLER -> CALLEE',
        '- impact traversal direction: reverse upstream',
        '',
        'MORE',
        'Use full for complete bounded sections, evidence identities, and traceability.',
    ))
    return '\n'.join(lines).rstrip() + '\n'


def _append_detail_group(
    lines: list[str],
    title: str,
    sections: Sequence[EngineeringAnswerSection],
    name_resolver: EngineeringAnswerNameResolver | None,
) -> None:
    items = tuple(
        item
        for section in sections
        for item in section.items
    )[:3]
    lines.extend(('', title))
    if not items:
        lines.append('- No bounded representative is available.')
        return
    lines.extend(
        _detail_item_line(item, name_resolver=name_resolver)
        for item in items
    )


def _detail_item_line(
    item: EngineeringAnswerItem,
    *,
    name_resolver: EngineeringAnswerNameResolver | None,
) -> str:
    parts = [
        _resolved_name(item.canonical_reference, name_resolver),
        f'confidence={item.confidence}',
    ]
    if item.relationship_kind is not None:
        parts.append(f'relationship={item.relationship_kind}')
    if item.depth is not None:
        parts.append(f'depth={item.depth}')
    if item.total_candidate_count:
        parts.append(
            f'candidate targets={_number(item.total_candidate_count)} (not resolved)'
        )
    parts.extend((
        f'source={item.source_ref}',
        f'evidence={item.evidence_ids[0]}',
    ))
    return '- ' + '; '.join(parts)


def _append_uncertainty_scope(
    lines: list[str],
    title: str,
    sections: Sequence[EngineeringAnswerSection],
    *,
    empty: str,
    scope_note: str | None = None,
) -> None:
    lines.extend(('', title))
    if scope_note is not None:
        lines.append(scope_note)
    nonzero = tuple(section for section in sections if section.total_count)
    if not nonzero:
        lines.append(empty)
        return
    lines.extend(
        _total_line(
            section.total_count,
            _UNCERTAINTY_SINGULAR_LABELS.get(
                section.section_id,
                _UNCERTAINTY_LABELS.get(
                    section.section_id,
                    section.section_id.replace('_', ' '),
                ),
            ),
            _UNCERTAINTY_LABELS.get(
                section.section_id,
                section.section_id.replace('_', ' '),
            ),
        )
        for section in nonzero
    )


def _select_summary_inspect(
    answer: EngineeringAnswer,
    *,
    maximum: int,
) -> tuple[_SummaryInspectCandidate, ...]:
    if maximum < 1:
        return ()
    groups = _summary_inspect_groups(answer)
    selected: list[_SummaryInspectCandidate] = []

    # Pass 1: cover each non-empty category in the frozen semantic order.
    for group in groups:
        candidate = next(
            (
                item for item in group
                if not _duplicates_selected(item, selected)
            ),
            None,
        )
        if candidate is None:
            continue
        selected.append(candidate)
        if len(selected) == maximum:
            return tuple(selected)

    # Pass 2: fill remaining slots from the same semantic category order.
    for group in groups:
        for candidate in group:
            if candidate in selected or _duplicates_selected(candidate, selected):
                continue
            selected.append(candidate)
            if len(selected) == maximum:
                return tuple(selected)
    return tuple(selected)


def _summary_inspect_groups(
    answer: EngineeringAnswer,
) -> tuple[tuple[_SummaryInspectCandidate, ...], ...]:
    upstream = tuple(
        item
        for item in (*answer.upstream_direct.items, *answer.upstream_transitive.items)
        if item.confidence == _HIGH_CONFIDENCE_UPSTREAM
    )
    uncertainty = tuple(
        (section.section_id, item)
        for section in answer.uncertainty
        if section.section_id in {'unresolved_sites', 'unsupported_sites'}
        for item in section.items
    )
    return (
        _inspect_group(
            'high_confidence_callers',
            'Direct high-confidence represented caller',
            answer.direct_callers_high_confidence.items,
        ),
        _inspect_group(
            'direct_represented_test_callers',
            'Direct represented TEST caller',
            answer.direct_test_callers.items,
        ),
        _inspect_group(
            'high_confidence_upstream_paths',
            'High-confidence represented upstream path',
            upstream,
        ),
        _inspect_group(
            'conservative_caller_sites',
            'Conservative represented caller site; candidate targets remain unproven',
            answer.direct_caller_conservative_sites.items,
        ),
        _inspect_group(
            'conservative_dependency_sites',
            'Conservative represented dependency call site; candidate targets remain unproven',
            answer.direct_callee_conservative_sites.items,
        ),
        tuple(
            _SummaryInspectCandidate(
                'uncertainty_hotspots',
                f'{section_id} hotspot limits call certainty',
                item.canonical_reference,
                item.source_ref,
                item.evidence_ids,
            )
            for section_id, item in uncertainty
        ),
    )


def _inspect_group(
    category: str,
    reason: str,
    items: Sequence[EngineeringAnswerItem],
) -> tuple[_SummaryInspectCandidate, ...]:
    return tuple(
        _SummaryInspectCandidate(
            category,
            reason,
            item.canonical_reference,
            item.source_ref,
            item.evidence_ids,
        )
        for item in items
    )


def _duplicates_selected(
    candidate: _SummaryInspectCandidate,
    selected: Sequence[_SummaryInspectCandidate],
) -> bool:
    evidence = frozenset(candidate.evidence_ids)
    return any(
        candidate.canonical_reference == retained.canonical_reference
        and (
            candidate.source_ref == retained.source_ref
            or bool(evidence.intersection(retained.evidence_ids))
        )
        for retained in selected
    )


def _resolved_name(
    canonical_reference: str,
    resolver: EngineeringAnswerNameResolver | None,
) -> str:
    resolved = resolver(canonical_reference) if resolver is not None else None
    return _human_callable_name(resolved or canonical_reference)


def _human_callable_name(value: str) -> str:
    normalized = value.removeprefix('java-callable:v1:')
    owner, separator, callable_name = normalized.partition('#')
    if not separator:
        return normalized
    short_owner = owner.rsplit('.', 1)[-1]
    display = callable_name.replace('external:', '').replace('unresolved:', '')
    display = _QUALIFIED_TYPE.sub(r'\1', display)
    return f'{short_owner}#{display}'


def _number(value: int) -> str:
    return f'{value:,}'


def _total_line(
    value: int,
    singular: str,
    plural: str | None = None,
) -> str:
    label = singular if value == 1 else (plural or singular + 's')
    return f'{_number(value)} {label}'


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
