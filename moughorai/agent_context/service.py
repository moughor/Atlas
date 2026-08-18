'''Deterministic bounded projection gateway over existing Atlas authorities.'''

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile
from typing import Iterable

from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    CodePathConfidence,
    CodeSubjectResolutionStatus,
)
from moughorai.engineering_agent import build_engineering_verification_plan
from moughorai.java_code_intelligence.code_graph import CodeGraphEdgeKind
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.story_planning import (
    StoryPlan,
    StoryPlanningRequest,
    StoryPlanningService,
    StoryRequirementStatus,
)

from .models import (
    AgentContextArtifacts,
    AgentContextPackage,
    AgentGraphConfiguration,
    AgentGraphDepth,
    AgentGraphEdge,
    AgentGraphNode,
    AgentGraphProjection,
    fingerprint,
)
from .renderer import render_agent_context, render_agent_graph_mermaid


_OUTPUT_NAMES = ('context.json', 'context.md', 'graph.json', 'graph.mmd')
_HIGH_EDGE_KINDS = frozenset({
    CodeGraphEdgeKind.RESOLVED_DIRECT_CALL,
    CodeGraphEdgeKind.CONSTRUCTOR_CALL,
})
_CANDIDATE_EDGE_KINDS = frozenset({
    CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
    CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
})
_ROLE_RANK = {
    'primary': 0,
    'collaborator': 1,
    'represented_test': 2,
    'callee': 3,
    'caller': 4,
    'requirement_anchor': 5,
    'impacted': 6,
    'candidate': 7,
    'project': 8,
    'story': 9,
}


class AgentContextError(ValueError):
    '''Raised when a fail-closed agent package cannot be projected.'''


@dataclass(slots=True)
class _NodeCandidate:
    node: AgentGraphNode
    rank: tuple[object, ...]


class AgentContextService:
    '''Export story-specific context without rescanning or invoking a provider.'''

    def __init__(
        self,
        runtime_session: RepositoryRuntimeSession,
        *,
        workspace_root: str | Path,
    ) -> None:
        if not isinstance(runtime_session, RepositoryRuntimeSession):
            raise TypeError('agent context requires a repository runtime session')
        self._session = runtime_session
        self._root = Path(workspace_root).expanduser().resolve()
        if not self._root.is_dir():
            raise AgentContextError('agent context repository root must be a directory')

    def generate(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        story_text: str,
        subject: str | None = None,
        project: str | None = None,
        depth: AgentGraphDepth | str = AgentGraphDepth.STORY,
    ) -> AgentContextArtifacts:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError('agent context requires a validated semantic snapshot')
        configuration = AgentGraphConfiguration.for_depth(depth)
        request = StoryPlanningRequest(
            story_text,
            snapshot.snapshot_id,
            subject,
            project,
        )
        planner = StoryPlanningService(
            self._session,
            workspace_root=self._root,
            llm_client=None,
        )
        plan = planner.plan(snapshot, request)
        primary = _primary_item(plan)
        if primary is None or plan.subject_resolution_status != 'resolved':
            detail = f' for project {project!r}' if project is not None else ''
            raise AgentContextError(
                'no exact authoritative primary Java subject was resolved'
                f'{detail}; agent context generation is fail-closed'
            )
        authoritative_project = primary.project
        if project is not None and project != authoritative_project:
            raise AgentContextError(
                'selected project does not own the authoritative primary subject'
            )

        runtime = self._session.runtime_for(snapshot)
        java = runtime.java_code_intelligence
        result = java.query(
            primary.canonical_subject_id,
            kind='method',
            project=authoritative_project,
            configuration=CodeIntelligenceConfiguration(
                max_depth=configuration.upstream_depth,
                max_nodes=configuration.query_max_nodes,
                max_direct_relationships=configuration.max_nodes * 2,
                max_paths_per_section=configuration.max_nodes * 2,
                max_limitation_representatives=8,
                max_resolution_candidates=8,
                max_candidates_per_call_site=8,
            ),
        )
        if (
            result.resolution.status is not CodeSubjectResolutionStatus.RESOLVED
            or result.report is None
        ):
            raise AgentContextError(
                'authoritative primary subject is unavailable from Java graph authority'
            )
        if result.report.subject.project != authoritative_project:
            raise AgentContextError(
                'Java graph project ownership conflicts with the story plan'
            )
        if java.callable_index is None or java.code_graph is None:
            raise AgentContextError('validated Java graph artifacts are unavailable')

        entries = {
            item.canonical_subject_id: item
            for item in java.callable_index.entries
        }
        graph = _project_graph(
            snapshot,
            plan,
            result.report,
            entries,
            java.code_graph,
            configuration,
            authoritative_project,
        )
        verification = build_engineering_verification_plan(self._root, plan)
        package = _context_package(
            snapshot,
            plan,
            result.report,
            graph,
            verification,
            authoritative_project,
            self._root,
        )
        markdown = render_agent_context(package)
        mermaid = render_agent_graph_mermaid(graph)
        return AgentContextArtifacts(package, graph, markdown, mermaid)

    def export(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        story_text: str,
        output: str | Path,
        subject: str | None = None,
        project: str | None = None,
        depth: AgentGraphDepth | str = AgentGraphDepth.STORY,
    ) -> AgentContextArtifacts:
        artifacts = self.generate(
            snapshot,
            story_text=story_text,
            subject=subject,
            project=project,
            depth=depth,
        )
        target = self._external_output(output)
        target.mkdir(parents=True, exist_ok=True)
        unexpected = tuple(sorted(
            item.name for item in target.iterdir() if item.name not in _OUTPUT_NAMES
        ))
        if unexpected:
            raise AgentContextError(
                'agent context output directory contains unrelated entries: '
                + ', '.join(unexpected)
            )
        payloads = {
            'context.json': artifacts.package.to_json(),
            'context.md': artifacts.context_markdown,
            'graph.json': artifacts.graph.to_json(),
            'graph.mmd': artifacts.graph_mermaid,
        }
        for name in _OUTPUT_NAMES:
            _atomic_write(target / name, payloads[name].encode('utf-8'))
        sizes = tuple(
            (name, (target / name).stat().st_size) for name in _OUTPUT_NAMES
        )
        return artifacts.with_output_files(sizes)

    def _external_output(self, output: str | Path) -> Path:
        target = Path(output).expanduser().resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            return target
        raise AgentContextError(
            'agent context output must be outside the repository source root'
        )


def _project_graph(
    snapshot,
    plan,
    report,
    entries,
    code_graph,
    configuration,
    project,
) -> AgentGraphProjection:
    candidates: dict[str, _NodeCandidate] = {}
    edges: dict[tuple[object, ...], AgentGraphEdge] = {}
    story_id = 'story:' + plan.story_fingerprint.removeprefix('story:v1:')
    project_id = f'project:{project}'
    _add_special_node(
        candidates, story_id, 'story', 'Jira story', 'Jira story', 'story', (-3, story_id)
    )
    _add_special_node(
        candidates, project_id, 'project', project, project, 'project', (-2, project_id),
        project=project,
    )

    requirement_payloads = []
    for requirement in plan.requirements:
        requirement_node_id = _requirement_node_id(plan, requirement.requirement_id)
        _add_special_node(
            candidates,
            requirement_node_id,
            'requirement',
            f'{requirement.requirement_id}: {requirement.text}',
            requirement.requirement_id,
            'requirement_anchor',
            (-1, int(requirement.requirement_id[1:])),
        )
        _add_edge(edges, AgentGraphEdge(
            story_id,
            requirement_node_id,
            'story_requirement_relation',
            'story_declared',
            'atlas-pr172',
            (),
            status=requirement.status.value,
        ))
        linked = _requirement_subjects(requirement, entries)
        for subject_id in linked:
            _add_entry_node(
                candidates, entries[subject_id], 'requirement_anchor',
                (4, subject_id), _requirement_evidence_ids(requirement),
            )
            _add_edge(edges, AgentGraphEdge(
                requirement_node_id,
                subject_id,
                'story_requirement_relation',
                'reconciled',
                'atlas-pr172',
                _requirement_evidence_ids(requirement),
                status=requirement.status.value,
            ))
        requirement_payloads.append({
            'id': requirement.requirement_id,
            'text': requirement.text,
            'classification': requirement.classification.value,
            'status': requirement.status.value,
            'linked_subjects': list(linked),
            'evidence_ids': list(_requirement_evidence_ids(requirement)),
            'uncertainty': list(requirement.uncertainty),
        })

    primary_id = report.subject.canonical_id
    _add_entry_node(candidates, entries[primary_id], 'primary', (0, primary_id))
    for item in plan.implementation_surface:
        entry = entries.get(item.canonical_subject_id)
        if entry is None:
            continue
        role = (
            'primary' if item.role == 'primary'
            else 'candidate' if 'candidate' in item.role
            else 'collaborator'
        )
        rank = 0 if role == 'primary' else 6 if role == 'candidate' else 4
        _add_entry_node(
            candidates, entry, role,
            (rank, item.display_name.casefold(), item.canonical_subject_id),
            item.evidence_ids,
        )

    direct_sections = (
        (report.direct_callees_high_confidence, 'callee', 1),
        (report.direct_callers_high_confidence, 'caller', 2),
        (report.direct_callees_conservative, 'candidate', 6),
        (report.direct_callers_conservative, 'candidate', 6),
        (report.direct_callee_method_references, 'candidate', 7),
        (report.direct_caller_method_references, 'candidate', 7),
    )
    for section, role, rank in direct_sections:
        for relationship in section.items:
            _add_relationship(candidates, edges, entries, relationship, role, rank)

    upstream_paths = (
        *report.upstream_direct.items,
        *report.upstream_transitive.items,
    )
    for path in upstream_paths:
        entry = entries.get(path.consumer_subject_id)
        if entry is not None:
            _add_entry_node(
                candidates, entry, 'impacted',
                (5, path.depth, path.consumer_subject_id),
                path.producer_evidence_ids,
            )
        for step in path.steps:
            _add_relationship(candidates, edges, entries, step, 'impacted', 5)
        _add_edge(edges, AgentGraphEdge(
            path.consumer_subject_id,
            primary_id,
            'reverse_upstream',
            path.confidence.value,
            'atlas-pr159',
            path.producer_evidence_ids,
            depth=path.depth,
        ))

    test_paths = (
        *report.high_confidence_test_paths.items,
        *report.possible_test_paths.items,
    )
    for path in test_paths:
        entry = entries.get(path.consumer_subject_id)
        evidence = path.producer_evidence_ids
        if entry is not None:
            _add_entry_node(
                candidates, entry, 'represented_test',
                (3, entry.identity.name.casefold(), path.consumer_subject_id),
                evidence,
            )
        for step in path.steps:
            _add_relationship(candidates, edges, entries, step, 'caller', 3)
        _add_edge(edges, AgentGraphEdge(
            path.consumer_subject_id,
            primary_id,
            'forward_test_reachability',
            path.confidence.value,
            'atlas-pr158+atlas-pr159',
            evidence,
            depth=path.depth,
        ))

    for test in plan.represented_tests:
        entry = entries.get(test.canonical_subject_id)
        if entry is not None:
            _add_entry_node(
                candidates, entry, 'represented_test',
                (3, test.display_name.casefold(), test.canonical_subject_id),
                (test.evidence_id,),
            )

    if configuration.depth is AgentGraphDepth.EXPANDED:
        _add_expanded_forward_neighborhood(
            candidates, edges, entries, code_graph, primary_id, configuration
        )

    for candidate in tuple(candidates.values()):
        node = candidate.node
        if node.project is not None and node.kind not in {'story', 'requirement', 'project'}:
            owner_id = f'project:{node.project}'
            _add_edge(edges, AgentGraphEdge(
                owner_id,
                node.id,
                'project_ownership',
                'authoritative',
                'atlas-pr156',
            ))
            if owner_id not in candidates:
                _add_special_node(
                    candidates, owner_id, 'project', node.project, node.project,
                    'project', (-2, owner_id), project=node.project,
                )

    ordered_candidates = sorted(
        candidates.values(), key=lambda item: (item.rank, item.node.id)
    )
    selected_candidates = ordered_candidates[:configuration.max_nodes]
    selected_ids = {item.node.id for item in selected_candidates}
    selected_nodes = tuple(item.node for item in selected_candidates)
    eligible_edges = tuple(sorted(
        (
            edge for edge in edges.values()
            if edge.source in selected_ids and edge.target in selected_ids
        ),
        key=_edge_sort_key,
    ))
    selected_edges = eligible_edges[:configuration.max_edges]
    represented_tests = tuple(sorted(
        item.canonical_subject_id for item in plan.represented_tests
        if item.canonical_subject_id in selected_ids
    ))
    upstream_consumers = {item.consumer_subject_id for item in upstream_paths}
    direct_caller_total = (
        report.direct_callers_high_confidence.total_count
        + report.direct_callers_conservative.total_count
    )
    direct_callee_total = (
        report.direct_callees_high_confidence.total_count
        + report.direct_callees_conservative.total_count
    )
    included_edge_types = {(item.source, item.target, item.type) for item in selected_edges}
    included_callers = sum(
        (item.canonical_source, item.canonical_target, item.edge_kind.value)
        in included_edge_types
        for section in (
            report.direct_callers_high_confidence,
            report.direct_callers_conservative,
        )
        for item in section.items
    )
    included_callees = sum(
        (item.canonical_source, item.canonical_target, item.edge_kind.value)
        in included_edge_types
        for section in (
            report.direct_callees_high_confidence,
            report.direct_callees_conservative,
        )
        for item in section.items
    )
    candidate_total = sum(
        edge.type in {'possible_call_target', 'possible_dispatch_target'}
        for edge in edges.values()
    )
    candidate_included = sum(
        edge.type in {'possible_call_target', 'possible_dispatch_target'}
        for edge in selected_edges
    )
    all_uncertainties = _uncertainties(plan, report)
    uncertainties = all_uncertainties[:20]
    upstream_total = (
        report.upstream_direct.total_count
        + report.upstream_transitive.total_count
    )
    omitted_counts = {
        'candidate_edges': max(0, candidate_total - candidate_included),
        'direct_callees': max(0, direct_callee_total - included_callees),
        'direct_callers': max(0, direct_caller_total - included_callers),
        'edges': max(0, len(edges) - len(selected_edges)),
        'nodes': max(0, len(candidates) - len(selected_nodes)),
        'represented_tests': max(0, len(plan.represented_tests) - len(represented_tests)),
        'requirements': max(0, len(plan.requirements) - len(requirement_payloads)),
        'uncertainties': max(0, len(all_uncertainties) - len(uncertainties)),
        'upstream_impact': max(
            0,
            upstream_total - len(upstream_consumers & selected_ids),
        ),
    }
    provisional = AgentGraphProjection(
        'agent-graph:v1:' + '0' * 64,
        snapshot.snapshot_id,
        plan.story_fingerprint,
        plan.plan_fingerprint,
        configuration,
        tuple(plan.anchor_subjects),
        selected_nodes,
        selected_edges,
        represented_tests,
        tuple(requirement_payloads),
        uncertainties,
        omitted_counts,
    )
    return replace(
        provisional,
        graph_fingerprint=fingerprint(
            'agent-graph', provisional.payload_without_fingerprint()
        ),
    )


def _context_package(
    snapshot,
    plan,
    report,
    graph,
    verification,
    project,
    repository_root,
) -> AgentContextPackage:
    nodes = {item.id: item for item in graph.nodes}
    primary = tuple(
        _node_reference(item) for item in graph.nodes if item.role == 'primary'
    )
    collaborators = tuple(
        _node_reference(item) for item in graph.nodes
        if item.role in {'collaborator', 'callee', 'candidate', 'requirement_anchor'}
        and item.kind not in {'story', 'requirement', 'project'}
    )[:24]
    callers = _relationship_references(
        (
            *report.direct_callers_high_confidence.items,
            *report.direct_callers_conservative.items,
        ),
        nodes,
        source=True,
    )
    callees = _relationship_references(
        (
            *report.direct_callees_high_confidence.items,
            *report.direct_callees_conservative.items,
        ),
        nodes,
        source=False,
    )
    impact = {}
    for path in (*report.upstream_direct.items, *report.upstream_transitive.items):
        node = nodes.get(path.consumer_subject_id)
        if node is None:
            continue
        current = impact.get(node.id)
        candidate = {
            **_node_reference(node),
            'depth': path.depth,
            'confidence': path.confidence.value,
        }
        if current is None or candidate['depth'] < current['depth']:
            impact[node.id] = candidate
    impact_subjects = tuple(sorted(
        impact.values(), key=lambda item: (
            item['depth'], item['qualified_name'].casefold(), item['id']
        )
    ))
    tests = tuple(
        _node_reference(nodes[item.canonical_subject_id])
        for item in plan.represented_tests
        if item.canonical_subject_id in nodes
    )
    requirements = tuple(graph.requirements)
    remediation_ids = set(plan.remediation_requirement_ids)
    remediation = tuple(
        item for item in requirements if item['id'] in remediation_ids
    )
    validation = {
        'commands': [
            {
                'label': item.label,
                'argv': list(item.argv),
                'working_directory': item.working_directory,
                'reason': item.reason,
            }
            for item in verification.commands
        ],
        'represented_tests': list(verification.represented_tests),
        'limitations': list(verification.limitations),
    }
    graph_artifacts = {
        'json': 'graph.json',
        'mermaid': 'graph.mmd',
        'depth': graph.configuration.depth.value,
        'fingerprint': graph.graph_fingerprint,
        'node_count': len(graph.nodes),
        'edge_count': len(graph.edges),
        'omitted_counts': graph.omitted_counts,
    }
    expected_subjects = tuple(sorted(
        item.id for item in graph.nodes
        if item.kind not in {'story', 'requirement', 'project'}
        and item.role != 'impacted'
    ))
    expected_paths = tuple(sorted({
        item.source_path for item in graph.nodes
        if item.source_path is not None
        and item.kind not in {'story', 'requirement', 'project'}
    }))
    provisional = AgentContextPackage(
        'agent-context:v1:' + '0' * 64,
        {
            'normalized_text': plan.normalized_story_text,
            'fingerprint': plan.story_fingerprint,
            'plan_fingerprint': plan.plan_fingerprint,
            'provider_decomposition_used': plan.provider_decomposition_used,
        },
        {
            'repository_root': Path(repository_root).as_posix(),
            'snapshot_id': snapshot.snapshot_id,
            'snapshot_schema_version': snapshot.schema_version,
            'workspace_fingerprint': snapshot.workspace_fingerprint,
            'analyzer_version': snapshot.analyzer_version,
            'history_reference': snapshot.history_reference,
            'callable_index_fingerprint': report.traceability.callable_index_fingerprint,
            'code_graph_fingerprint': report.traceability.code_graph_fingerprint,
            'test_evidence_fingerprint': report.traceability.test_evidence_fingerprint,
            'reachability_fingerprint': report.traceability.reachability_fingerprint,
        },
        project,
        report.subject.canonical_id,
        primary,
        collaborators,
        callers,
        callees,
        {
            'included_count': len(impact_subjects),
            'omitted_count': graph.omitted_counts['upstream_impact'],
            'subjects': list(impact_subjects),
            'direction': 'reverse_upstream',
        },
        tests,
        requirements,
        remediation,
        graph.uncertainties,
        _investigation_order(primary, collaborators, requirements, tests, remediation),
        validation,
        graph_artifacts,
        {
            'canonical_subject_ids': list(expected_subjects),
            'source_paths': list(expected_paths),
            'authoritative_project': project,
            'snapshot_id': snapshot.snapshot_id,
        },
    )
    return replace(
        provisional,
        context_fingerprint=fingerprint(
            'agent-context', provisional.payload_without_fingerprint()
        ),
    )


def _primary_item(plan: StoryPlan):
    return next(
        (item for item in plan.implementation_surface if item.role == 'primary'),
        None,
    )


def _requirement_node_id(plan: StoryPlan, requirement_id: str) -> str:
    digest = plan.story_fingerprint.removeprefix('story:v1:')
    return f'requirement:{digest}:{requirement_id}'


def _requirement_evidence_ids(requirement) -> tuple[str, ...]:
    return tuple(sorted({item.evidence_id for item in requirement.evidence}))[:12]


def _requirement_subjects(requirement, entries) -> tuple[str, ...]:
    values = {
        *requirement.candidate_implementation_subjects,
        *(
            item.canonical_subject_id for item in requirement.evidence
            if item.canonical_subject_id is not None
        ),
    }
    return tuple(sorted(item for item in values if item in entries))


def _add_special_node(
    candidates,
    node_id,
    kind,
    qualified_name,
    simple_name,
    role,
    rank,
    *,
    project=None,
) -> None:
    _merge_node(candidates, AgentGraphNode(
        node_id,
        kind,
        qualified_name,
        simple_name,
        project,
        None,
        None,
        role,
        'authoritative',
    ), rank)


def _add_entry_node(
    candidates,
    entry,
    role,
    rank,
    evidence_ids: Iterable[str] = (),
) -> None:
    _merge_node(candidates, AgentGraphNode(
        entry.canonical_subject_id,
        entry.identity.kind.value,
        entry.identity.normalized_key,
        entry.identity.name,
        entry.project_id,
        entry.source.path,
        entry.source.declaration.to_dict(),
        role,
        'represented',
        tuple(sorted(set(evidence_ids)))[:12],
    ), rank)


def _merge_node(candidates, node, rank) -> None:
    existing = candidates.get(node.id)
    if existing is None:
        candidates[node.id] = _NodeCandidate(node, tuple(rank))
        return
    evidence = tuple(sorted(set(existing.node.evidence_ids + node.evidence_ids)))[:12]
    existing_role_rank = _ROLE_RANK.get(existing.node.role, 99)
    new_role_rank = _ROLE_RANK.get(node.role, 99)
    selected = node if new_role_rank < existing_role_rank else existing.node
    candidates[node.id] = _NodeCandidate(
        replace(selected, evidence_ids=evidence),
        min(existing.rank, tuple(rank)),
    )


def _add_relationship(candidates, edges, entries, relationship, role, rank) -> None:
    for subject_id in (relationship.canonical_source, relationship.canonical_target):
        entry = entries.get(subject_id)
        if entry is not None:
            _add_entry_node(
                candidates,
                entry,
                role,
                (rank, entry.identity.name.casefold(), subject_id),
                (relationship.producer_evidence_id,),
            )
    _add_edge(edges, AgentGraphEdge(
        relationship.canonical_source,
        relationship.canonical_target,
        relationship.edge_kind.value,
        relationship.confidence.value,
        'atlas-pr157',
        (
            relationship.producer_evidence_id,
            relationship.location.compact,
        ),
        depth=1,
    ))


def _add_expanded_forward_neighborhood(
    candidates,
    edges,
    entries,
    code_graph,
    primary_id,
    configuration,
) -> None:
    outgoing = defaultdict(list)
    sites = {item.evidence_id: item for item in code_graph.call_sites}
    for edge in code_graph.edges:
        if edge.kind in _HIGH_EDGE_KINDS | _CANDIDATE_EDGE_KINDS:
            outgoing[edge.caller_subject_id].append(edge)
    for values in outgoing.values():
        values.sort(key=lambda item: (
            0 if item.kind in _HIGH_EDGE_KINDS else 1,
            item.target_subject_id,
            item.kind.value,
            item.evidence_id,
        ))
    queue = deque(((primary_id, 0),))
    visited = {primary_id}
    exploration_bound = configuration.max_nodes * 3
    while queue and len(visited) < exploration_bound:
        source, depth = queue.popleft()
        if depth >= min(configuration.upstream_depth, 5):
            continue
        for edge in outgoing.get(source, ()):
            target = edge.target_subject_id
            target_entry = entries.get(target)
            if source not in entries or target_entry is None:
                continue
            confidence = (
                CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH.value
                if edge.kind in _HIGH_EDGE_KINDS
                else CodePathConfidence.CONSERVATIVE_REPRESENTED_PATH.value
            )
            evidence = [edge.evidence_id]
            site = sites.get(edge.evidence_id)
            if site is not None:
                position = site.request.source_range
                evidence.append(
                    f'{site.request.source_path}#L{position.start.line}C{position.start.column}'
                    f'-L{position.end.line}C{position.end.column}'
                )
            _add_entry_node(
                candidates,
                target_entry,
                'callee' if edge.kind in _HIGH_EDGE_KINDS else 'candidate',
                (5 if edge.kind in _HIGH_EDGE_KINDS else 6, depth + 1, target),
                (edge.evidence_id,),
            )
            _add_edge(edges, AgentGraphEdge(
                source,
                target,
                edge.kind.value,
                confidence,
                'atlas-pr157',
                tuple(evidence),
                depth=depth + 1,
            ))
            if target not in visited:
                visited.add(target)
                queue.append((target, depth + 1))
            if len(visited) >= exploration_bound:
                break


def _add_edge(edges, edge) -> None:
    key = (
        edge.source,
        edge.target,
        edge.type,
        edge.confidence,
        edge.authority,
        edge.evidence,
        edge.depth,
        edge.status,
    )
    edges[key] = edge


def _edge_sort_key(edge) -> tuple[object, ...]:
    rank = {
        'story_requirement_relation': 0,
        'project_ownership': 1,
        'resolved_direct_call': 2,
        'constructor_call': 3,
        'possible_call_target': 4,
        'possible_dispatch_target': 5,
        'method_reference': 6,
        'reverse_upstream': 7,
        'forward_test_reachability': 8,
    }.get(edge.type, 99)
    return (
        rank,
        edge.source,
        edge.target,
        edge.depth if edge.depth is not None else -1,
        edge.confidence,
        edge.evidence,
    )


def _node_reference(node) -> dict[str, object]:
    source_ref = None
    if node.source_path is not None and node.source_span is not None:
        start = node.source_span['start']
        end = node.source_span['end']
        source_ref = (
            f"{node.source_path}#L{start['line']}C{start['column']}"
            f"-L{end['line']}C{end['column']}"
        )
    return {
        'id': node.id,
        'qualified_name': node.qualified_name,
        'simple_name': node.simple_name,
        'project': node.project,
        'source_ref': source_ref,
        'role': node.role,
        'confidence': node.confidence,
    }


def _relationship_references(relationships, nodes, *, source) -> tuple[dict[str, object], ...]:
    values = []
    seen = set()
    for relationship in relationships:
        subject_id = relationship.canonical_source if source else relationship.canonical_target
        node = nodes.get(subject_id)
        if node is None:
            continue
        key = (subject_id, relationship.edge_kind.value)
        if key in seen:
            continue
        seen.add(key)
        values.append({
            **_node_reference(node),
            'edge_type': relationship.edge_kind.value,
            'edge_confidence': relationship.confidence.value,
        })
    return tuple(sorted(values, key=lambda item: (
        item['qualified_name'].casefold(), item['id'], item['edge_type']
    )))


def _uncertainties(plan, report) -> tuple[str, ...]:
    values = {
        *plan.unresolved_questions,
        *(item for requirement in plan.requirements for item in requirement.uncertainty),
        *plan.limitations,
        *report.general_limitations,
    }
    return tuple(sorted(values))


def _investigation_order(primary, collaborators, requirements, tests, remediation):
    values = []
    if primary:
        values.append({
            'action': 'Inspect the authoritative primary implementation first.',
            'subject_id': primary[0]['id'],
            'source_ref': primary[0]['source_ref'],
        })
    unresolved = [
        item['id'] for item in requirements
        if item['status'] in {
            StoryRequirementStatus.PARTIAL.value,
            StoryRequirementStatus.NOT_PROVEN.value,
            StoryRequirementStatus.MISSING.value,
        }
    ]
    if unresolved:
        values.append({
            'action': 'Resolve source evidence for ' + ', '.join(unresolved) + ' before editing.',
            'subject_id': None,
            'source_ref': None,
        })
    if collaborators:
        first = collaborators[0]
        values.append({
            'action': 'Inspect the ranked collaborators and preserve resolved/candidate distinctions.',
            'subject_id': first['id'],
            'source_ref': first['source_ref'],
        })
    if tests:
        values.append({
            'action': 'Inspect and run the represented TEST roots as the first validation set.',
            'subject_id': tests[0]['id'],
            'source_ref': tests[0]['source_ref'],
        })
    if remediation:
        values.append({
            'action': 'Coordinate supplied remediation work separately from source behavior changes.',
            'subject_id': None,
            'source_ref': None,
        })
    return tuple(
        {'order': index, **item} for index, item in enumerate(values, start=1)
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f'.{path.name}.',
        suffix='.tmp',
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
