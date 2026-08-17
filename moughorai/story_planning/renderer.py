'''Concise deterministic rendering for internal story plans.'''

from __future__ import annotations

from enum import Enum

from .models import (
    StoryPlan,
    StoryRequirementClassification,
    StoryRequirementStatus,
)


class StoryPlanView(str, Enum):
    SUMMARY = 'summary'
    DETAIL = 'detail'


def render_story_plan(
    plan: StoryPlan,
    *,
    view: StoryPlanView | str = StoryPlanView.SUMMARY,
) -> str:
    if not isinstance(plan, StoryPlan):
        raise TypeError('story plan renderer requires a StoryPlan')
    selected = view if isinstance(view, StoryPlanView) else StoryPlanView(
        str(view).strip().casefold()
    )
    lines = [
        'STORY PLAN',
        '',
        'Story',
        f'- characters: {len(plan.normalized_story_text)}',
        f'- story fingerprint: {plan.story_fingerprint}',
        f'- plan fingerprint: {plan.plan_fingerprint}',
        f'- decomposition: {_decomposition(plan)}',
        f'- subject resolution: {plan.subject_resolution_status}',
        '',
        'Repository anchors investigated',
    ]
    if plan.anchors:
        lines.append('- ' + ', '.join(plan.anchors))
    else:
        lines.append('- none derived')

    lines.extend(('', 'Primary implementation surface'))
    if plan.implementation_surface:
        included_surface = plan.implementation_surface[:12]
        for item in included_surface:
            authority = 'represented' if item.proven else 'candidate / unproven'
            source = f' — {item.source_ref}' if item.source_ref else ''
            lines.append(
                f'- {item.role}: {item.display_name} [{authority}] '
                f'({item.canonical_subject_id}){source}'
            )
        if len(plan.implementation_surface) > len(included_surface):
            lines.append(
                f'- {len(plan.implementation_surface) - len(included_surface)} '
                'additional candidate item(s); use /plan detail.'
            )
    else:
        lines.append('- none; planning remains fail-closed')

    lines.extend(('', 'Requirements'))
    for requirement in plan.requirements:
        lines.append(
            f'{requirement.requirement_id} '
            f'[{requirement.classification.value}] — {requirement.status.value}'
        )
        lines.append(f'- {requirement.text}')
        if requirement.evidence:
            summaries = tuple(dict.fromkeys(
                item.summary for item in requirement.evidence
            ))
            for summary in summaries[:3]:
                lines.append(f'  Evidence: {summary}')
            if len(summaries) > 3:
                lines.append(
                    f'  Evidence: {len(summaries) - 3} additional bounded '
                    'evidence item(s); use /plan detail.'
                )
        else:
            lines.append('  Evidence: none sufficient to prove this requirement.')
        if requirement.uncertainty:
            lines.append(f'  Gap: {requirement.uncertainty[0]}')

    lines.extend(('', 'Represented tests to inspect/run'))
    lines.append('- represented TEST intelligence; not runtime coverage or behavioral proof')
    if plan.represented_tests:
        for test in plan.represented_tests:
            lines.append(
                f'- {test.display_name} ({test.canonical_subject_id}) — '
                f'{test.source_ref}'
            )
    else:
        lines.append('- none projected from the authoritative anchor subject')

    lines.extend(('', 'Remediation / operational work'))
    if plan.remediation_requirement_ids:
        by_id = {item.requirement_id: item for item in plan.requirements}
        for requirement_id in plan.remediation_requirement_ids:
            requirement = by_id[requirement_id]
            lines.append(
                f'- {requirement_id}: {requirement.text} — '
                f'{requirement.status.value}'
            )
    else:
        lines.append('- none explicitly present in the loaded story')

    lines.extend(('', 'Uncertainty'))
    if plan.unresolved_questions:
        lines.extend(f'- {item}' for item in plan.unresolved_questions)
    else:
        lines.append('- no additional unresolved planning questions')

    lines.extend(('', 'Recommended implementation sequence'))
    sequence = _implementation_sequence(plan)
    lines.extend(f'{index}. {item}' for index, item in enumerate(sequence, start=1))

    if selected is StoryPlanView.DETAIL:
        _append_detail(lines, plan)
    return '\n'.join(lines).rstrip() + '\n'


def _decomposition(plan: StoryPlan) -> str:
    if plan.provider_decomposition_used:
        return (
            'provider-proposed exact story quotes; all repository facts and '
            'statuses validated independently by Atlas'
        )
    return 'deterministic story structure / fallback'


def _implementation_sequence(plan: StoryPlan) -> tuple[str, ...]:
    values = []
    if plan.implementation_surface:
        values.append(
            'Inspect the represented primary method and collaborating source spans.'
        )
    unresolved = tuple(
        item.requirement_id for item in plan.requirements
        if item.status is not StoryRequirementStatus.IMPLEMENTED
    )
    if unresolved:
        values.append(
            'Resolve evidence gaps for ' + ', '.join(unresolved) + ' before editing.'
        )
    values.append(
        'Make the smallest approved implementation change only after plan review.'
    )
    if plan.represented_tests:
        values.append(
            'Inspect and run the represented TEST roots; add or update tests for '
            'requirements they do not establish.'
        )
    if plan.remediation_requirement_ids:
        values.append(
            'Coordinate remediation/operational work separately; do not invent '
            'deployment or data-repair logic from repository names.'
        )
    return tuple(values)


def _append_detail(lines: list[str], plan: StoryPlan) -> None:
    lines.extend(('', 'Detailed autonomous discovery'))
    if plan.discovery:
        for hit in plan.discovery:
            source = f' source={hit.source_ref}' if hit.source_ref else ''
            lines.append(
                f'- anchor={hit.anchor} id={hit.canonical_subject_id} '
                f'kind={hit.kind} project={hit.project or "unknown"}{source}'
            )
            if hit.evidence_ids:
                lines.append('  evidence: ' + ', '.join(hit.evidence_ids))
    else:
        lines.append('- no project-authoritative discovery hits')

    lines.extend(('', 'Detailed requirement traceability'))
    for requirement in plan.requirements:
        lines.append(f'- {requirement.requirement_id}')
        lines.append(f'  decomposition-source: {requirement.decomposition_source}')
        if requirement.candidate_implementation_subjects:
            lines.append(
                '  candidate-subjects: '
                + ', '.join(requirement.candidate_implementation_subjects)
            )
        for evidence in requirement.evidence:
            source = f' source={evidence.source_ref}' if evidence.source_ref else ''
            subject = (
                f' subject={evidence.canonical_subject_id}'
                if evidence.canonical_subject_id else ''
            )
            lines.append(
                f'  evidence={evidence.evidence_id} kind={evidence.kind}'
                f'{subject}{source}'
            )

    lines.extend(('', 'Limitations'))
    lines.extend(f'- {item}' for item in plan.limitations)
