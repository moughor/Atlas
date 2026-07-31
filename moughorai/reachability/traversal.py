from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .models import (
    ReachabilityPath,
    ReachabilityProtection,
    ReachabilityRoot,
    ReachabilityState,
    RootCategory,
)


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityRelation:
    source: str
    target: str
    kind: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ReachabilityTrace:
    root: str
    category: RootCategory
    root_evidence_id: str
    predecessor: str | None = None
    relation: str | None = None
    relation_evidence_id: str | None = None
    depth: int = 0


def select_protections(
    values: Sequence[ReachabilityProtection],
) -> Mapping[str, ReachabilityProtection]:
    priority = {
        ReachabilityState.UNREACHABLE: 0,
        ReachabilityState.SERVICE_LOADER_DISCOVERED: 1,
        ReachabilityState.REFLECTION_DISCOVERED: 2,
        ReachabilityState.FRAMEWORK_MANAGED: 3,
        ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED: 4,
        ReachabilityState.EXTERNALLY_REACHABLE: 5,
        ReachabilityState.CONDITIONALLY_REACHABLE: 6,
    }
    result: dict[str, ReachabilityProtection] = {}
    for item in sorted(values, key=lambda value: (value.subject_id, priority[value.state], value)):
        result.setdefault(item.subject_id, item)
    return result


def traverse(
    roots: tuple[ReachabilityRoot, ...],
    root_evidence: Mapping[tuple[str, RootCategory], str],
    adjacency: Mapping[str, tuple[ReachabilityRelation, ...]],
    max_nodes: int,
) -> tuple[dict[str, ReachabilityTrace], bool]:
    traces: dict[str, ReachabilityTrace] = {}
    queue: deque[str] = deque()
    for root in sorted(roots, key=lambda item: (item.subject_id, item.category.value)):
        if root.subject_id in traces:
            continue
        evidence_id = root_evidence[(root.subject_id, root.category)]
        traces[root.subject_id] = ReachabilityTrace(
            root.subject_id, root.category, evidence_id,
        )
        queue.append(root.subject_id)
    truncated = False
    while queue:
        current = queue.popleft()
        current_trace = traces[current]
        for relation in adjacency.get(current, ()):
            if relation.target in traces:
                continue
            if len(traces) >= max_nodes:
                truncated = True
                queue.clear()
                break
            traces[relation.target] = ReachabilityTrace(
                current_trace.root,
                current_trace.category,
                current_trace.root_evidence_id,
                current,
                relation.kind,
                relation.evidence_id,
                current_trace.depth + 1,
            )
            queue.append(relation.target)
    return traces, truncated


def materialize_path(
    target: str,
    trace: ReachabilityTrace,
    traces: Mapping[str, ReachabilityTrace],
    max_depth: int,
    scope: str,
) -> ReachabilityPath:
    relationships: list[str] = []
    evidence_ids = [trace.root_evidence_id]
    current = target
    truncated = False
    while current != trace.root:
        current_trace = traces[current]
        if len(relationships) >= max_depth or current_trace.predecessor is None:
            truncated = current != trace.root
            break
        relationships.append(current_trace.relation or "unknown")
        if current_trace.relation_evidence_id:
            evidence_ids.append(current_trace.relation_evidence_id)
        current = current_trace.predecessor
    relationships.reverse()
    return ReachabilityPath(
        trace.root,
        target,
        tuple(relationships),
        tuple(evidence_ids),
        scope,
        truncated,
        ("Path materialization reached its configured bound.",) if truncated else (),
    )
