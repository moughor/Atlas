'''Deterministic human renderer for Atlas agent post-change review.'''

from __future__ import annotations

from .models import AgentPostChangeReview


def render_agent_post_change_review(review: AgentPostChangeReview) -> str:
    if not isinstance(review, AgentPostChangeReview):
        raise TypeError('agent review renderer requires AgentPostChangeReview')
    lines = [
        'ATLAS POST-CHANGE REVIEW',
        '',
        'Story',
        '-----',
        review.story_summary or '(story text unavailable)',
        f'Story fingerprint: {review.story_fingerprint}',
        f'Review fingerprint: {review.review_fingerprint}',
        '',
        'Repository / base',
        '-----------------',
        f'Repository: {review.repository_root}',
        f'Snapshot: {review.snapshot_id}',
        f'Requested base: {review.requested_base}',
        f'Resolved base: {review.resolved_base}',
        'Current HEAD: ' + (review.current_head or 'unavailable'),
        f'Base provenance: {review.base_provenance.value}',
        '',
        'Scope summary',
        '-------------',
        'Overall scope: ' + (
            review.overall_scope.value if review.overall_scope else 'NO_CHANGED_FILES'
        ),
    ]
    lines.extend(f'- {name}: {count}' for name, count in review.scope_summary)
    lines.extend(('', 'Expected implementation surface', '-------------------------------'))
    lines.append(f'Expected projects: {len(review.expected_projects)}')
    lines.extend(f'- {item}' for item in review.expected_projects)
    lines.append(f'Expected source paths: {len(review.expected_paths)}')
    lines.extend(f'- {item}' for item in review.expected_paths)
    lines.append(f'Expected canonical subjects: {len(review.expected_subjects)}')
    lines.extend(f'- {item}' for item in review.expected_subjects)

    lines.extend(('', 'Actual changed files', '--------------------'))
    if not review.changed_files:
        lines.append('- None.')
    else:
        for item in review.changed_files:
            suffix = ' (binary)' if item.binary else ''
            lines.append(f'- {item.path} [{item.status.value}]{suffix}')

    lines.extend(('', 'Per-file classification', '-----------------------'))
    if not review.changed_files:
        lines.append('- None.')
    for item in review.changed_files:
        lines.append(f'- {item.path}')
        lines.append(f'  Scope: {item.scope_classification.value}')
        lines.append(f'  Freshness: {item.evidence_freshness.value}')
        if item.projects:
            lines.append('  Projects: ' + ', '.join(item.projects))
        for reason in item.justifications:
            lines.append(f'  Evidence: {reason}')
        for limitation in item.limitations:
            lines.append(f'  Limitation: {limitation}')

    _append_review_sections(lines, review)
    return '\n'.join(lines).rstrip() + '\n'


def _append_review_sections(lines: list[str], review: AgentPostChangeReview) -> None:
    lines.extend(('', 'Matched Atlas roots', '-------------------'))
    if not review.matched_roots:
        lines.append('- None.')
    for root in review.matched_roots:
        lines.append(
            f'- #{root.rank} {root.qualified_name} [{root.role}; '
            f'{root.classification}] - {root.canonical_subject_id}'
        )
    lines.extend(('', 'Project expansion', '-----------------'))
    lines.append('Changed projects: ' + (
        ', '.join(review.changed_projects) if review.changed_projects else 'none'
    ))
    lines.append('Projects outside expected set: ' + (
        ', '.join(review.project_expansion) if review.project_expansion else 'none'
    ))

    lines.extend((
        '', 'Relevant pre-change graph evidence',
        '----------------------------------',
        'These relationships describe the pre-change snapshot and may be stale now.',
    ))
    if not review.graph_relations:
        lines.append('- No directly associated bounded graph relationship was projected.')
    for item in review.graph_relations:
        lines.append(
            f'- {item.source} -> {item.target} [{item.type}; {item.confidence}]'
        )
    _append_references(lines, 'Represented pre-change callers', review.relevant_callers)
    _append_references(lines, 'Represented pre-change callees', review.relevant_callees)

    lines.extend((
        '', 'Represented tests to inspect/run',
        '--------------------------------',
        'These are inspection and initial validation guidance, not proof of coverage.',
    ))
    if not review.represented_tests:
        lines.append('- None projected.')
    for item in review.represented_tests:
        location = f' - {item.source_ref}' if item.source_ref else ''
        lines.append(f'- {item.qualified_name} [{item.canonical_id}]{location}')

    lines.extend(('', 'Requirement relationships', '-------------------------'))
    if not review.related_requirements:
        lines.append('- None projected for the changed surface.')
    for item in review.related_requirements:
        lines.append(f'- {item.requirement_id} - {item.status}: {item.text}')
        lines.append('  Status is preserved from pre-change Atlas evidence.')

    lines.extend(('', 'Evidence freshness', '------------------'))
    lines.extend(f'- {item.value}' for item in review.evidence_freshness)
    for limitation in review.limitations:
        lines.append(f'- {limitation}')

    lines.extend(('', 'What Atlas cannot prove', '-----------------------'))
    lines.extend(f'- {item}' for item in review.cannot_prove)
    lines.extend(('', 'Omitted counts', '--------------'))
    lines.extend(f'- {name}: {count}' for name, count in review.omitted_counts)


def _append_references(lines, title, values) -> None:
    lines.extend(('', title, '~' * len(title)))
    if not values:
        lines.append('- None projected.')
        return
    for item in values:
        edge = f' [{item.edge_type}]' if item.edge_type else ''
        lines.append(f'- {item.qualified_name}{edge} - {item.canonical_id}')
