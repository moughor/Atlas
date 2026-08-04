from __future__ import annotations

import json

from .models import RepositoryEvolutionResponse


def render_repository_evolution(response: RepositoryEvolutionResponse) -> str:
    """Render the bounded source-free facts from one evolution response."""

    if not isinstance(response, RepositoryEvolutionResponse):
        raise TypeError(
            "repository evolution renderer requires a RepositoryEvolutionResponse"
        )
    lines = [
        "Atlas Repository Evolution",
        f"state: {_display(response.state.value)}",
        (
            f"base: {_display(response.base.snapshot_id)}; "
            f"git-head={_display(response.base.git_head or 'unavailable')}"
        ),
        (
            f"head: {_display(response.head.snapshot_id)}; "
            f"git-head={_display(response.head.git_head or 'unavailable')}"
        ),
        (
            "canonical node changes: "
            f"{len(response.node_changes)}/{response.total_node_change_count}; "
            f"unchanged={response.unchanged_node_count}"
        ),
        (
            "canonical relation changes: "
            f"{len(response.relation_changes)}/{response.total_relation_change_count}; "
            f"unchanged={response.unchanged_relation_count}"
        ),
        "",
        "Capabilities",
    ]
    for capability in response.capabilities:
        lines.append(
            f"- {_display(capability.capability.value)}: "
            f"{_display(capability.state.value)}"
        )
        for limitation in capability.limitations:
            lines.append(f"  limitation: {_display(limitation)}")

    lines.extend(("", "Canonical Node Changes"))
    if not response.node_changes:
        lines.append("- none observed in the retained canonical projection")
    for change in response.node_changes:
        subject = change.after or change.before
        if subject is None:  # pragma: no cover - model rejects this state
            continue
        fields = (
            f"; fields={','.join(map(_display, change.changed_fields))}"
            if change.changed_fields else ""
        )
        lines.append(
            f"- {_display(change.change.value)} "
            f"{_display(subject.kind.value)} "
            f"{_display(subject.qualified_name)} "
            f"({_display(subject.canonical_id)}); "
            f"confidence={change.confidence.tier.value}/{change.confidence.score:.4f}"
            f"{fields}"
        )

    lines.extend(("", "Canonical Relation Changes"))
    if not response.relation_changes:
        lines.append("- none observed in the retained canonical projection")
    for change in response.relation_changes:
        lines.append(
            f"- {_display(change.change.value)} "
            f"{_display(change.source.qualified_name)} "
            f"--{_display(change.relation.value)}--> "
            f"{_display(change.target.qualified_name)}; "
            f"evidence={change.before_evidence_count}->{change.after_evidence_count}; "
            f"confidence={change.confidence.tier.value}/{change.confidence.score:.4f}"
        )

    change_limitations = tuple(sorted({
        limitation
        for change in (*response.node_changes, *response.relation_changes)
        for limitation in change.limitations
    }))
    lines.extend(("", "Change Observation Limitations"))
    if not change_limitations:
        lines.append("- none")
    for limitation in change_limitations:
        lines.append(f"- {_display(limitation)}")

    lines.extend(("", "Limitations"))
    for limitation in response.limitations:
        lines.append(f"- {_display(limitation)}")
    return "\n".join(lines) + "\n"


def _display(value: object) -> str:
    encoded = json.dumps(str(value), ensure_ascii=True)
    return encoded[1:-1]
