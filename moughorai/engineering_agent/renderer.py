'''Bounded user-controlled rendering for engineering-agent lifecycle state.'''

from __future__ import annotations

from .models import (
    EngineeringApplyResult,
    EngineeringDiffReport,
    EngineeringPatchProposal,
    EngineeringVerificationPlan,
)


def render_implementation_proposal(proposal: EngineeringPatchProposal) -> str:
    lines = [
        'IMPLEMENTATION PROPOSAL',
        '',
        f'- story fingerprint: {proposal.story_fingerprint}',
        f'- plan fingerprint: {proposal.plan_fingerprint}',
        f'- repository snapshot: {proposal.snapshot_id}',
        f'- proposal fingerprint: {proposal.proposal_fingerprint}',
        f'- provider: {proposal.provider}',
        f'- model: {proposal.model}',
        '- mode: PREVIEW ONLY; no source was modified',
        '',
        'Primary files',
    ]
    _paths(lines, proposal.primary_files)
    lines.extend(('', 'Candidate files'))
    _paths(lines, proposal.candidate_files)
    lines.extend(('', 'Test files'))
    _paths(lines, proposal.test_files)
    lines.extend(('', 'Represented tests'))
    _paths(lines, proposal.proposed_tests)
    lines.extend(('', 'Requirement coverage'))
    for item in proposal.requirement_coverage:
        lines.append(
            f'- {item.requirement_id}: {item.disposition.value} — {item.summary}'
        )
    lines.extend(('', 'Proposed edits'))
    if not proposal.edits:
        lines.append('- none; provider proposed no source-changing validated edit')
    for ordinal, edit in enumerate(proposal.edits, start=1):
        lines.append(
            f'{ordinal}. {edit.operation} {edit.relative_path} '
            f'[{", ".join(edit.requirement_ids)}]'
        )
        lines.append(f'   reason: {edit.reason}')
        lines.extend(_edit_preview(edit.original_text, edit.replacement_text))
    lines.extend(('', 'Provider rationale (non-authoritative)'))
    _paths(lines, proposal.rationale)
    lines.extend(('', 'Uncertainty'))
    _paths(lines, proposal.uncertainties)
    lines.extend(('', 'Validation commands (preview; not executed)'))
    if proposal.validation_commands:
        for command in proposal.validation_commands:
            lines.append(f'- {command.label}: {_command(command.argv)}')
            lines.append(f'  reason: {command.reason}')
    else:
        lines.append('- none derived')
    return '\n'.join(lines).rstrip() + '\n'


def render_apply_result(result: EngineeringApplyResult) -> str:
    lines = [
        'IMPLEMENTATION APPLIED',
        '',
        f'- proposal fingerprint: {result.proposal_fingerprint}',
        '- source changes only; no commit or push was performed',
        '- changed files:',
    ]
    lines.extend(f'  - {path}' for path in result.changed_files)
    lines.extend((
        '',
        'Git state before',
        f'- {result.before.branch_status}',
    ))
    lines.extend(_git_state_paths(result.before))
    lines.extend(('', 'Git state after', f'- {result.after.branch_status}'))
    lines.extend(_git_state_paths(result.after))
    return '\n'.join(lines).rstrip() + '\n'


def render_verification_plan(plan: EngineeringVerificationPlan) -> str:
    lines = [
        'VALIDATION PLAN',
        '',
        f'- story fingerprint: {plan.story_fingerprint}',
        f'- plan fingerprint: {plan.plan_fingerprint}',
        '- execution: preview only; no command was run',
        '',
        'Commands',
    ]
    if plan.commands:
        for ordinal, command in enumerate(plan.commands, start=1):
            lines.append(f'{ordinal}. {_command(command.argv)}')
            lines.append(f'   cwd: {command.working_directory}')
            lines.append(f'   reason: {command.reason}')
    else:
        lines.append('- none derived')
    lines.extend(('', 'Represented tests'))
    _paths(lines, plan.represented_tests)
    lines.extend(('', 'Limitations'))
    _paths(lines, plan.limitations)
    return '\n'.join(lines).rstrip() + '\n'


def render_engineering_diff(report: EngineeringDiffReport) -> str:
    lines = [
        'ENGINEERING DIFF REVIEW',
        '',
        f'- proposal fingerprint: {report.proposal_fingerprint}',
        '',
        'Changed files',
    ]
    if report.entries:
        for item in report.entries:
            insertions = '?' if item.insertions is None else str(item.insertions)
            deletions = '?' if item.deletions is None else str(item.deletions)
            lines.append(
                f'- {item.relative_path}: +{insertions}/-{deletions}'
            )
    else:
        _paths(lines, report.changed_files)
    lines.extend(('', 'Requirement IDs addressed by current diff'))
    _paths(lines, report.addressed_requirement_ids)
    lines.extend(('', 'Represented tests related to the change'))
    _paths(lines, report.represented_tests)
    lines.extend(('', 'Scope drift warnings'))
    if report.scope_drift:
        lines.extend(f'- unexpected changed path: {path}' for path in report.scope_drift)
    else:
        lines.append('- none')
    lines.extend(('', 'Unresolved StoryPlan requirements'))
    _paths(lines, report.unresolved_requirement_ids)
    lines.append('')
    lines.append('- completion is not inferred from this diff')
    return '\n'.join(lines).rstrip() + '\n'


def _paths(lines: list[str], values: tuple[str, ...]) -> None:
    if values:
        lines.extend(f'- {item}' for item in values)
    else:
        lines.append('- none')


def _git_state_paths(state) -> tuple[str, ...]:
    return (
        '- unstaged: ' + (', '.join(state.unstaged_paths) or 'none'),
        '- staged: ' + (', '.join(state.staged_paths) or 'none'),
        '- untracked: ' + (', '.join(state.untracked_paths) or 'none'),
    )


def _edit_preview(original: str, replacement: str) -> tuple[str, ...]:
    maximum_lines = 24
    values = []
    original_lines = original.splitlines() or ['']
    replacement_lines = replacement.splitlines() or ['']
    for line in original_lines[:maximum_lines // 2]:
        values.append('   - ' + line[:240])
    for line in replacement_lines[:maximum_lines // 2]:
        values.append('   + ' + line[:240])
    omitted = len(original_lines) + len(replacement_lines) - len(values)
    if omitted > 0:
        values.append(f'   ... {omitted} replacement preview line(s) omitted')
    return tuple(values)


def _command(argv: tuple[str, ...]) -> str:
    return ' '.join(
        f'"{item}"' if any(character.isspace() for character in item) else item
        for item in argv
    )
