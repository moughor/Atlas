from __future__ import annotations

import json

from .models import ChangeReviewResponse


def render_change_review(response: ChangeReviewResponse) -> str:
    """Render the same bounded deterministic facts exposed by canonical JSON."""

    if not isinstance(response, ChangeReviewResponse):
        raise TypeError("change review renderer requires a ChangeReviewResponse")
    lines = [
        "Atlas Change Review",
        f"diff: {_display(response.diff.mode.value)} ({_display(response.diff.fingerprint)})",
        (
            "files: "
            f"{response.diff.selected_file_count}/{response.diff.total_file_count}"
        ),
        f"snapshot alignment: {_display(response.alignment.value)}",
        f"subjects: {sum(len(item.subjects) for item in response.changed_files)}/{response.total_subject_count}",
        "",
        "Changed Files",
    ]
    if not response.changed_files:
        lines.append("- none in the selected tracked Git diff")
    for item in response.changed_files:
        flags = [item.status.value]
        if item.binary:
            flags.append("binary")
        lines.append(
            f"- {_display(item.path)} [{', '.join(map(_display, flags))}]; "
            f"hunks={item.hunk_count}; +{item.added_line_count}/-{item.removed_line_count}; "
            f"subjects={len(item.subjects)}/{item.total_subject_count}; "
            f"semantic-confidence={item.semantic_confidence.tier.value}/"
            f"{item.semantic_confidence.score:.4f}"
        )
        if item.old_path is not None and item.new_path is not None and item.old_path != item.new_path:
            lines.append(f"  from: {_display(item.old_path)}")
        for candidate in item.subjects:
            context = "project context" if item.project_fallback else "file-associated"
            lines.append(
                f"  - {_display(candidate.kind.value)}: "
                f"{_display(candidate.qualified_name)} "
                f"({_display(candidate.canonical_id)}; {_display(context)})"
            )

    lines.extend(("", "Review Capabilities"))
    for section in response.sections:
        lines.append(
            f"- {_display(section.name)}: {_display(section.state.value)}; "
            f"items={len(section.item_ids)}"
        )
        for limitation in section.limitations:
            lines.append(f"  limitation: {_display(limitation)}")

    if response.impact is not None and response.impact.findings:
        lines.extend(("", "Impact"))
        for finding in response.impact.findings:
            lines.append(
                f"- {_display(finding.category.value)}: "
                f"{_display(finding.subject.qualified_name)}; "
                f"confidence={finding.confidence.score:.3f}; "
                f"path={finding.path.length}"
            )

    advice = tuple(
        item
        for review in response.architecture_reviews
        for item in review.advice
    )
    if advice:
        lines.extend(("", "Architecture and Migration Context"))
        for item in advice:
            lines.append(
                f"- {_display(item.family.value)}/{_display(item.operation.value)}; "
                f"confidence={item.confidence.score:.3f}; evidence={len(item.evidence_ids)}"
            )
            lines.append(f"  rationale: {_display(item.rationale)}")

    lines.extend(("", "Review Limitations"))
    for limitation in response.limitations:
        lines.append(f"- {_display(limitation)}")
    return "\n".join(lines) + "\n"


def _display(value: object) -> str:
    """Escape control characters in all data crossing the terminal boundary."""

    encoded = json.dumps(str(value), ensure_ascii=True)
    return encoded[1:-1]
