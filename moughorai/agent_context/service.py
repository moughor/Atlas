'''Deterministic bounded projection gateway over existing Atlas authorities.'''

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
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
from moughorai.semantic_search import SemanticSearchRequest
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.story_planning import (
    StoryDiscoveryHit,
    StoryPlan,
    StoryPlanningRequest,
    StoryPlanningService,
    StoryRequirementStatus,
)

from .models import (
    AGENT_CONTEXT_LEGACY_PRODUCER,
    AGENT_CONTEXT_PRODUCER,
    AgentContextArtifacts,
    AgentContextPackage,
    AgentDiscoveredRoot,
    AgentGraphConfiguration,
    AgentGraphDepth,
    AgentGraphEdge,
    AgentGraphNode,
    AgentGraphProjection,
    fingerprint,
)
from .discovery import (
    PreparedStoryDiscovery,
    complete_story_discovery,
    prepare_story_discovery,
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
    'ui': 0,
    'controller': 1,
    'service_interface': 2,
    'service': 3,
    'persistence': 4,
    'domain': 5,
    'integration': 6,
    'external_symbol': 7,
    'collaborator': 1,
    'represented_test': 2,
    'callee': 3,
    'caller': 4,
    'requirement_anchor': 5,
    'impacted': 6,
    'candidate': 7,
    'neighborhood_context': 8,
    'project': 8,
    'story': 9,
}
_QUALIFIED_CALL = re.compile(
    r'\b(?P<owner>[A-Za-z_$][A-Za-z0-9_$]*)\s*\.\s*'
    r'(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)\s*\('
)
_STORY_WORD = re.compile(r'\b[A-Za-z][A-Za-z0-9]*\b')
_SUPPLEMENTARY_ACTIONS = frozenset({
    'matching', 'reset', 'retrieve', 'search', 'selected',
})
_MAXIMUM_SUPPLEMENTARY_ANCHORS = 8
_MAXIMUM_SUPPLEMENTARY_HITS = 5


class AgentContextError(ValueError):
    '''Raised when a fail-closed agent package cannot be projected.'''


@dataclass(slots=True)
class _NodeCandidate:
    node: AgentGraphNode
    rank: tuple[object, ...]


@dataclass(slots=True)
class _RootEvidence:
    entry: object
    matched_anchors: set[str] = field(default_factory=set)
    exact_anchors: set[str] = field(default_factory=set)
    unique_exact_anchors: set[str] = field(default_factory=set)
    evidence_ids: set[str] = field(default_factory=set)
    semantic: bool = False
    planner_selected: bool = False


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
        prepared = None
        if subject is None:
            runtime = self._session.runtime_for(snapshot)
            java = runtime.java_code_intelligence
            if java.callable_index is None or java.code_graph is None:
                raise AgentContextError('validated Java graph artifacts are unavailable')
            entries = {
                item.canonical_subject_id: item for item in java.callable_index.entries
            }
            represented_projects = {item.project_id for item in entries.values()}
            if project is not None and project not in represented_projects:
                raise AgentContextError(
                    f'requested project {project!r} is not represented by the validated '
                    'Java callable index; agent context generation is fail-closed'
                )
            prepared = prepare_story_discovery(
                snapshot, entries, story_text, project, self._root
            )
        request = StoryPlanningRequest(
            story_text,
            snapshot.snapshot_id,
            subject,
            project,
            discovery_anchors=(prepared.semantic_anchors if prepared else None),
        )
        planner = StoryPlanningService(
            self._session,
            workspace_root=self._root,
            llm_client=None,
        )
        plan = planner.plan(snapshot, request)
        if subject is None:
            return self._generate_discovered(
                snapshot,
                plan,
                project,
                configuration,
                prepared,
            )
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
            configuration=_query_configuration(configuration),
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

    def _generate_discovered(
        self,
        snapshot: AtlasSemanticSnapshot,
        plan: StoryPlan,
        project: str | None,
        configuration: AgentGraphConfiguration,
        prepared: PreparedStoryDiscovery,
    ) -> AgentContextArtifacts:
        runtime = self._session.runtime_for(snapshot)
        java = runtime.java_code_intelligence
        if java.callable_index is None or java.code_graph is None:
            raise AgentContextError('validated Java graph artifacts are unavailable')
        entries = {
            item.canonical_subject_id: item
            for item in java.callable_index.entries
        }
        represented_projects = {
            item.project_id for item in entries.values()
        }
        if project is not None and project not in represented_projects:
            raise AgentContextError(
                f'requested project {project!r} is not represented by the validated '
                'Java callable index; agent context generation is fail-closed'
            )

        root_limit = 8 if configuration.depth is AgentGraphDepth.STORY else 24
        discovery = complete_story_discovery(
            prepared,
            plan,
            entries,
            root_limit=root_limit,
        )
        selected_roots = discovery.roots
        if project is not None and not selected_roots:
            raise AgentContextError(
                f'no represented discovery root was found in requested project '
                f'{project!r}; agent context generation is fail-closed'
            )

        reports = []
        query_configuration = _query_configuration(configuration)
        for root in selected_roots:
            if root.kind != 'method' or root.project is None:
                continue
            result = java.query(
                root.canonical_subject_id,
                kind='method',
                project=root.project,
                configuration=query_configuration,
            )
            if (
                result.resolution.status is CodeSubjectResolutionStatus.RESOLVED
                and result.report is not None
                and result.report.subject.project == root.project
            ):
                reports.append(result.report)

        graph = _project_discovered_graph(
            snapshot,
            plan,
            tuple(reports),
            entries,
            java.code_graph,
            configuration,
            selected_roots,
            omitted_root_count=discovery.omitted_root_count,
            project=project,
            discovery_limitations=discovery.limitations,
            discovery_search_omitted_count=0,
        )
        verification = build_engineering_verification_plan(self._root, plan)
        package = _context_package_discovered(
            snapshot,
            plan,
            tuple(reports),
            graph,
            verification,
            project,
            self._root,
            discovery,
        )
        return AgentContextArtifacts(
            package,
            graph,
            render_agent_context(package),
            render_agent_graph_mermaid(graph),
        )

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


def _query_configuration(
    configuration: AgentGraphConfiguration,
) -> CodeIntelligenceConfiguration:
    return CodeIntelligenceConfiguration(
        max_depth=configuration.upstream_depth,
        max_nodes=configuration.query_max_nodes,
        max_direct_relationships=configuration.max_nodes * 2,
        max_paths_per_section=configuration.max_nodes * 2,
        max_limitation_representatives=8,
        max_resolution_candidates=8,
        max_candidates_per_call_site=8,
    )


def _discover_roots(
    plan,
    entries,
    project,
    *,
    supplementary_anchors=(),
    supplementary_hits=(),
) -> tuple[AgentDiscoveredRoot, ...]:
    eligible = tuple(
        item for item in entries.values()
        if item.source_classification.value == 'production'
        and item.identity.kind.value == 'method'
        and (project is None or item.project_id == project)
    )
    eligible_ids = {
        item.canonical_subject_id for item in eligible
    }
    eligible_by_name = defaultdict(list)
    for item in eligible:
        eligible_by_name[item.identity.name.casefold()].append(item)
    records: dict[str, _RootEvidence] = {}
    qualified_owners = _qualified_call_owners(plan.normalized_story_text)

    def retain(entry):
        return records.setdefault(
            entry.canonical_subject_id,
            _RootEvidence(entry),
        )

    for hit in (*plan.discovery, *supplementary_hits):
        entry = entries.get(hit.canonical_subject_id)
        if entry is None or entry.canonical_subject_id not in eligible_ids:
            continue
        owners = qualified_owners.get(hit.anchor.casefold())
        if owners and _owner_simple_name(entry).casefold() not in owners:
            continue
        record = retain(entry)
        record.matched_anchors.add(hit.anchor)
        record.evidence_ids.update(hit.evidence_ids)
        record.semantic = True

    all_anchors = tuple(dict.fromkeys((*plan.anchors, *supplementary_anchors)))
    anchor_order = {
        anchor.casefold(): index for index, anchor in enumerate(all_anchors)
    }
    for anchor in all_anchors:
        owners = qualified_owners.get(anchor.casefold())
        matches = tuple(
            item for item in eligible_by_name.get(anchor.casefold(), ())
            if (
                not owners
                or _owner_simple_name(item).casefold() in owners
            )
        )
        for entry in matches:
            record = retain(entry)
            record.matched_anchors.add(anchor)
            record.exact_anchors.add(anchor)
            if len(matches) == 1:
                record.unique_exact_anchors.add(anchor)

    primary = _primary_item(plan)
    if primary is not None:
        entry = entries.get(primary.canonical_subject_id)
        if entry is not None and entry.canonical_subject_id in eligible_ids:
            retain(entry).planner_selected = True
    unique_exact_subjects = {
        subject_id for subject_id, record in records.items()
        if record.unique_exact_anchors
    }
    fallback_resolved_subject = (
        next(iter(unique_exact_subjects))
        if primary is None and len(unique_exact_subjects) == 1
        else None
    )

    ranked = []
    for subject_id, record in records.items():
        entry = record.entry
        fallback_resolved = subject_id == fallback_resolved_subject
        resolved = bool(record.planner_selected or fallback_resolved)
        exact = bool(record.exact_anchors)
        matched = tuple(sorted(
            record.matched_anchors,
            key=lambda item: (anchor_order.get(item.casefold(), 10_000), item.casefold(), item),
        ))
        rationale = []
        if record.planner_selected:
            rationale.append(
                'PR172 resolved this represented callable as an exact story anchor.'
            )
        if fallback_resolved:
            rationale.append(
                'No PR172 primary was selected and this is the only uniquely '
                'matching represented callable identity across the story anchors.'
            )
        for anchor in sorted(record.unique_exact_anchors, key=str.casefold):
            rationale.append(
                f'Story anchor {anchor!r} uniquely matches this represented callable identity.'
            )
        for anchor in sorted(
            record.exact_anchors - record.unique_exact_anchors,
            key=str.casefold,
        ):
            rationale.append(
                f'Story anchor {anchor!r} exactly matches multiple represented callable identities.'
            )
        if record.semantic:
            rationale.append(
                'Bounded Atlas semantic search connected one or more story anchors '
                'to this represented callable.'
            )
        classification = 'resolved' if resolved else 'candidate'
        if resolved:
            confidence = 'authoritative_unique_exact_identity'
            authority = 'atlas-pr172+callable-index+exact-story-anchor'
        elif record.unique_exact_anchors:
            confidence = 'candidate_unique_exact_identity'
            authority = 'atlas-callable-index+exact-story-anchor'
        elif exact:
            confidence = 'candidate_exact_ambiguous_identity'
            authority = 'atlas-callable-index+ambiguous-story-anchor'
        else:
            confidence = 'candidate_semantic_repository_match'
            authority = 'atlas-semantic-search+callable-index'
        first_anchor = min(
            (anchor_order.get(item.casefold(), 10_000) for item in matched),
            default=10_000,
        )
        sort_key = (
            0 if resolved else 1,
            0 if record.unique_exact_anchors else 1 if exact else 2,
            first_anchor,
            -len(matched),
            entry.identity.normalized_key.casefold(),
            subject_id,
        )
        ranked.append((sort_key, record, classification, confidence, authority, matched, rationale))

    roots = []
    for rank, item in enumerate(sorted(ranked, key=lambda value: value[0]), start=1):
        _, record, classification, confidence, authority, matched, rationale = item
        entry = record.entry
        roots.append(AgentDiscoveredRoot(
            entry.canonical_subject_id,
            entry.identity.kind.value,
            entry.identity.normalized_key,
            entry.identity.name,
            entry.project_id,
            entry.source.path,
            entry.source.declaration.to_dict(),
            rank,
            classification,
            confidence,
            authority,
            matched,
            tuple(rationale),
            tuple(sorted(record.evidence_ids))[:12],
        ))
    return tuple(roots)


def _qualified_call_owners(story: str) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for match in _QUALIFIED_CALL.finditer(story):
        values[match.group('method').casefold()].add(
            match.group('owner').casefold()
        )
    return {
        method: frozenset(sorted(owners))
        for method, owners in values.items()
    }


def _owner_simple_name(entry) -> str:
    return entry.identity.owner_type.rpartition('.')[2].rpartition('$')[2]


def _supplementary_story_anchors(plan) -> tuple[str, ...]:
    words = tuple(match.group(0) for match in _STORY_WORD.finditer(
        plan.normalized_story_text
    ))
    existing = {item.casefold() for item in plan.anchors}
    values = []
    for left, right in zip(words, words[1:]):
        left_key = left.casefold()
        right_key = right.casefold()
        if not ({left_key, right_key} & _SUPPLEMENTARY_ACTIONS):
            continue
        if not (left[0].isupper() or right[0].isupper()):
            continue
        phrase = f'{left} {right}'
        if phrase.casefold() in existing:
            continue
        values.append(phrase)
    return tuple(dict.fromkeys(values))[:_MAXIMUM_SUPPLEMENTARY_ANCHORS]


def _supplementary_discovery(runtime, anchors, project, entries):
    hits = []
    limitations = set()
    omitted_count = 0
    for anchor in anchors:
        try:
            response = runtime.semantic_search.search_semantic(
                SemanticSearchRequest(
                    anchor,
                    project=project,
                    limit=_MAXIMUM_SUPPLEMENTARY_HITS,
                )
            )
        except (TypeError, ValueError) as exc:
            limitations.add(
                f'Supplementary agent discovery for {anchor} was unavailable '
                f'({type(exc).__name__}).'
            )
            continue
        if response.omitted_count:
            omitted_count += response.omitted_count
            limitations.add(
                f'Supplementary agent discovery for {anchor} omitted '
                f'{response.omitted_count} lower-ranked semantic match(es).'
            )
        for hit in response.hits:
            entry = entries.get(hit.canonical_subject_id)
            if (
                entry is None
                or entry.source_classification.value != 'production'
                or entry.identity.kind.value != 'method'
                or (project is not None and entry.project_id != project)
            ):
                continue
            hits.append(StoryDiscoveryHit(
                anchor,
                entry.canonical_subject_id,
                entry.identity.normalized_key,
                entry.identity.kind.value,
                entry.project_id,
                entry.source.path,
                tuple(hit.evidence_ids),
            ))
    return tuple(hits), tuple(sorted(limitations)), omitted_count


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
        version=1,
        producer=AGENT_CONTEXT_LEGACY_PRODUCER,
    )
    return replace(
        provisional,
        graph_fingerprint=fingerprint(
            'agent-graph', provisional.payload_without_fingerprint()
        ),
    )


_MIN_USEFUL_GRAPH_NODES = 30
_EXPANSION_TARGET_NODES = 50


def _expand_small_graph_neighborhood(
    candidates,
    edges,
    entries,
    code_graph,
    root_ids,
    configuration,
) -> None:
    '''Expand 1-hop neighborhoods when the initial graph is too small.

    When the discovered graph contains fewer than _MIN_USEFUL_GRAPH_NODES
    semantic nodes (excluding story/project/requirement structural nodes), this
    expands direct callees and callers of each root until the graph reaches
    _EXPANSION_TARGET_NODES semantic nodes or the tier cap, whichever is lower.
    Expanded nodes are marked with role ``neighborhood_context`` so the external
    agent can distinguish them from primary/candidate targets.
    '''
    semantic_count = sum(
        1 for candidate in candidates.values()
        if candidate.node.kind not in {'story', 'project', 'requirement'}
    )
    if semantic_count >= _MIN_USEFUL_GRAPH_NODES:
        return

    target_count = min(_EXPANSION_TARGET_NODES, configuration.max_nodes)

    # Build adjacency from code_graph edges (both directions).
    outgoing: dict[str, list] = defaultdict(list)
    incoming: dict[str, list] = defaultdict(list)
    for edge in code_graph.edges:
        if edge.kind in _HIGH_EDGE_KINDS | _CANDIDATE_EDGE_KINDS:
            outgoing[edge.caller_subject_id].append(edge)
            incoming[edge.target_subject_id].append(edge)

    # Sort for determinism: high-confidence first, then by target/source id.
    for values in outgoing.values():
        values.sort(key=lambda item: (
            0 if item.kind in _HIGH_EDGE_KINDS else 1,
            item.target_subject_id,
            item.kind.value,
            item.evidence_id,
        ))
    for values in incoming.values():
        values.sort(key=lambda item: (
            0 if item.kind in _HIGH_EDGE_KINDS else 1,
            item.caller_subject_id,
            item.kind.value,
            item.evidence_id,
        ))

    # Expand deterministically: iterate roots in sorted order, callees first,
    # then callers.
    sorted_roots = sorted(root_ids)
    added = 0

    for root_id in sorted_roots:
        if semantic_count + added >= target_count:
            break
        # Outgoing (callees)
        for edge in outgoing.get(root_id, []):
            if semantic_count + added >= target_count:
                break
            target = edge.target_subject_id
            if target in candidates:
                continue
            target_entry = entries.get(target)
            if target_entry is None:
                continue
            if target_entry.source_classification.value != 'production':
                continue
            confidence = (
                'high_confidence_represented_path'
                if edge.kind in _HIGH_EDGE_KINDS
                else 'conservative_represented_path'
            )
            _add_entry_node(
                candidates,
                target_entry,
                'neighborhood_context',
                (10, 0, target),  # rank 10 = below all primary roles
                (edge.evidence_id,),
            )
            _add_edge(edges, AgentGraphEdge(
                root_id,
                target,
                edge.kind.value,
                confidence,
                'atlas-pr157+neighborhood-expansion',
                (edge.evidence_id,),
                depth=1,
            ))
            added += 1

    for root_id in sorted_roots:
        if semantic_count + added >= target_count:
            break
        # Incoming (callers)
        for edge in incoming.get(root_id, []):
            if semantic_count + added >= target_count:
                break
            source = edge.caller_subject_id
            if source in candidates:
                continue
            source_entry = entries.get(source)
            if source_entry is None:
                continue
            if source_entry.source_classification.value != 'production':
                continue
            confidence = (
                'high_confidence_represented_path'
                if edge.kind in _HIGH_EDGE_KINDS
                else 'conservative_represented_path'
            )
            _add_entry_node(
                candidates,
                source_entry,
                'neighborhood_context',
                (10, 1, source),  # rank 10, sub-rank 1 for callers
                (edge.evidence_id,),
            )
            _add_edge(edges, AgentGraphEdge(
                source,
                root_id,
                edge.kind.value,
                confidence,
                'atlas-pr157+neighborhood-expansion',
                (edge.evidence_id,),
                depth=1,
            ))
            added += 1


def _project_discovered_graph(
    snapshot,
    plan,
    reports,
    entries,
    code_graph,
    configuration,
    roots,
    *,
    omitted_root_count,
    project,
    discovery_limitations,
    discovery_search_omitted_count,
) -> AgentGraphProjection:
    partials = tuple(
        _project_graph(
            snapshot,
            plan,
            report,
            entries,
            code_graph,
            configuration,
            report.subject.project,
        )
        for report in reports
    )
    root_by_id = {
        item.canonical_subject_id: item for item in roots
    }
    candidates: dict[str, _NodeCandidate] = {}
    edges: dict[tuple[object, ...], AgentGraphEdge] = {}
    partial_omissions: dict[str, int] = defaultdict(int)

    for partial in partials:
        for key, count in partial.omitted_counts.items():
            partial_omissions[key] += count
        for node in partial.nodes:
            root = root_by_id.get(node.id)
            if root is not None:
                node = replace(
                    node,
                    role=root.role,
                    confidence=root.confidence,
                    evidence_ids=tuple(sorted(set(
                        node.evidence_ids + root.evidence_ids
                    )))[:12],
                )
            _merge_node(candidates, node, _discovery_node_rank(node, root))
        for edge in partial.edges:
            _add_edge(edges, edge)

    if not partials:
        _add_discovery_base(candidates, edges, plan, entries, project)

    story_id = 'story:' + plan.story_fingerprint.removeprefix('story:v1:')
    for root in roots:
        node = AgentGraphNode(
            root.canonical_subject_id,
            root.kind,
            root.qualified_name,
            root.simple_name,
            root.project,
            root.source_path,
            root.source_span,
            root.role,
            root.confidence,
            root.evidence_ids,
        )
        _merge_node(candidates, node, _discovery_node_rank(node, root))
        if root.project is not None:
            owner_id = f'project:{root.project}'
        else:
            owner_id = None
        if owner_id is not None and owner_id not in candidates:
            _add_special_node(
                candidates,
                owner_id,
                'project',
                root.project,
                root.project,
                'project',
                (-2, owner_id),
                project=root.project,
            )
        if owner_id is not None and not any(
            edge.source == owner_id
            and edge.target == root.canonical_subject_id
            and edge.type == 'project_ownership'
            for edge in edges.values()
        ):
            _add_edge(edges, AgentGraphEdge(
                owner_id,
                root.canonical_subject_id,
                'project_ownership',
                'authoritative',
                root.authority,
            ))
        _add_edge(edges, AgentGraphEdge(
            story_id,
            root.canonical_subject_id,
            'external_dependency' if root.role == 'external_symbol'
            else 'story_anchor_relation',
            root.confidence,
            root.authority,
        ))

    # Expand 1-hop neighborhoods when the initial graph is too small to give
    # the external agent enough implementation context.
    root_subject_ids = frozenset(
        item.canonical_subject_id for item in roots
    )
    _expand_small_graph_neighborhood(
        candidates, edges, entries, code_graph, root_subject_ids, configuration
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
        item.id for item in selected_nodes if item.role == 'represented_test'
    ))
    requirements = (
        partials[0].requirements if partials
        else _requirement_payloads(plan, entries)
    )
    all_uncertainties = _uncertainties_many(
        plan,
        reports,
        roots,
        omitted_root_count,
        discovery_limitations,
    )
    uncertainties = all_uncertainties[:20]
    candidate_total = sum(
        edge.type in {'possible_call_target', 'possible_dispatch_target'}
        for edge in edges.values()
    ) + partial_omissions['candidate_edges']
    candidate_included = sum(
        edge.type in {'possible_call_target', 'possible_dispatch_target'}
        for edge in selected_edges
    )
    omitted_counts = {
        'candidate_edges': max(0, candidate_total - candidate_included),
        'direct_callees': partial_omissions['direct_callees'],
        'direct_callers': partial_omissions['direct_callers'],
        'discovery_roots': omitted_root_count,
        'discovery_search_matches': discovery_search_omitted_count,
        'edges': (
            partial_omissions['edges']
            + max(0, len(edges) - len(selected_edges))
        ),
        'nodes': (
            partial_omissions['nodes']
            + max(0, len(candidates) - len(selected_nodes))
        ),
        'represented_tests': partial_omissions['represented_tests'],
        'requirements': max(0, len(plan.requirements) - len(requirements)),
        'uncertainties': max(0, len(all_uncertainties) - len(uncertainties)),
        'upstream_impact': partial_omissions['upstream_impact'],
    }
    included_roots = tuple(
        item for item in roots if item.canonical_subject_id in selected_ids
    )
    provisional = AgentGraphProjection(
        'agent-graph:v1:' + '0' * 64,
        snapshot.snapshot_id,
        plan.story_fingerprint,
        plan.plan_fingerprint,
        configuration,
        tuple(item.canonical_subject_id for item in included_roots),
        selected_nodes,
        selected_edges,
        represented_tests,
        tuple(requirements),
        uncertainties,
        omitted_counts,
        included_roots,
        version=3,
        producer=AGENT_CONTEXT_PRODUCER,
    )
    return replace(
        provisional,
        graph_fingerprint=fingerprint(
            'agent-graph', provisional.payload_without_fingerprint()
        ),
    )


def _discovery_node_rank(node, root) -> tuple[object, ...]:
    if node.kind == 'story':
        return (-3, node.id)
    if node.kind == 'project':
        return (-2, node.id)
    if node.kind == 'requirement':
        return (-1, node.simple_name, node.id)
    if root is not None:
        return (
            0 if root.classification == 'resolved' else 1,
            root.rank,
            node.id,
        )
    return (
        2 + _ROLE_RANK.get(node.role, 99),
        node.qualified_name.casefold(),
        node.id,
    )


def _add_discovery_base(candidates, edges, plan, entries, project) -> None:
    story_id = 'story:' + plan.story_fingerprint.removeprefix('story:v1:')
    _add_special_node(
        candidates,
        story_id,
        'story',
        'Jira story',
        'Jira story',
        'story',
        (-3, story_id),
    )
    if project is not None:
        project_id = f'project:{project}'
        _add_special_node(
            candidates,
            project_id,
            'project',
            project,
            project,
            'project',
            (-2, project_id),
            project=project,
        )
    for requirement in plan.requirements:
        requirement_node_id = _requirement_node_id(
            plan, requirement.requirement_id
        )
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
            status=requirement.status.value,
        ))
        for subject_id in _requirement_subjects(requirement, entries):
            entry = entries[subject_id]
            _add_entry_node(
                candidates,
                entry,
                'requirement_anchor',
                (4, subject_id),
                _requirement_evidence_ids(requirement),
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


def _requirement_payloads(plan, entries) -> tuple[dict[str, object], ...]:
    return tuple({
        'id': requirement.requirement_id,
        'text': requirement.text,
        'classification': requirement.classification.value,
        'status': requirement.status.value,
        'linked_subjects': list(_requirement_subjects(requirement, entries)),
        'evidence_ids': list(_requirement_evidence_ids(requirement)),
        'uncertainty': list(requirement.uncertainty),
    } for requirement in plan.requirements)


def _uncertainties_many(
    plan,
    reports,
    roots,
    omitted_root_count,
    discovery_limitations=(),
) -> tuple[str, ...]:
    values = {
        *plan.unresolved_questions,
        *(item for requirement in plan.requirements for item in requirement.uncertainty),
        *plan.limitations,
        *(item for report in reports for item in report.general_limitations),
        *discovery_limitations,
    }
    if not roots:
        values.add(
            'No sufficiently authoritative represented Java callable root was '
            'discovered; inspect the ranked story requirements and repository manually.'
        )
    elif any(item.classification == 'candidate' for item in roots):
        values.add(
            'Candidate discovery roots are represented repository matches, not '
            'authoritative implementation targets; inspect their source before editing.'
        )
    if omitted_root_count:
        values.add(
            f'Discovery omitted {omitted_root_count} lower-ranked root candidate(s) '
            'from the bounded projection.'
        )
    return tuple(sorted(values))


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
        version=1,
        producer=AGENT_CONTEXT_LEGACY_PRODUCER,
    )
    return replace(
        provisional,
        context_fingerprint=fingerprint(
            'agent-context', provisional.payload_without_fingerprint()
        ),
    )


def _context_package_discovered(
    snapshot,
    plan,
    reports,
    graph,
    verification,
    requested_project,
    repository_root,
    discovery,
) -> AgentContextPackage:
    nodes = {item.id: item for item in graph.nodes}
    roots = tuple(graph.discovered_roots)
    resolved_roots = tuple(
        item for item in roots if item.classification == 'resolved'
    )
    root_ids = {item.canonical_subject_id for item in roots}
    primary = tuple(
        _node_reference(nodes[item.canonical_subject_id])
        for item in resolved_roots
        if item.canonical_subject_id in nodes
    )
    collaborators = tuple(
        _node_reference(item) for item in graph.nodes
        if item.kind not in {'story', 'requirement', 'project'}
        and item.role not in {'impacted', 'represented_test'}
        and item.id not in root_ids
    )[:32]
    callers = _graph_relationship_references(
        graph,
        nodes,
        root_ids,
        callers=True,
    )
    callees = _graph_relationship_references(
        graph,
        nodes,
        root_ids,
        callers=False,
    )
    impact = {}
    for edge in graph.edges:
        if edge.type != 'reverse_upstream' or edge.target not in root_ids:
            continue
        node = nodes.get(edge.source)
        if node is None:
            continue
        candidate = {
            **_node_reference(node),
            'depth': edge.depth or 1,
            'confidence': edge.confidence,
        }
        current = impact.get(node.id)
        if current is None or candidate['depth'] < current['depth']:
            impact[node.id] = candidate
    impact_subjects = tuple(sorted(
        impact.values(),
        key=lambda item: (
            item['depth'], item['qualified_name'].casefold(), item['id']
        ),
    ))
    tests = tuple(
        _node_reference(nodes[subject_id])
        for subject_id in graph.represented_tests
        if subject_id in nodes
    )
    requirements = tuple(graph.requirements)
    remediation_ids = set(plan.remediation_requirement_ids)
    remediation = tuple(
        item for item in requirements if item['id'] in remediation_ids
    )
    root_projects = tuple(sorted({
        item.project for item in roots if item.project is not None
    }))
    authoritative_project = requested_project or (
        root_projects[0] if len(root_projects) == 1 else None
    )
    selected_subject = (
        resolved_roots[0].canonical_subject_id
        if len(resolved_roots) == 1 else None
    )
    first_report = reports[0] if reports else None
    traceability = first_report.traceability if first_report is not None else None
    validation_limitations = tuple(sorted({
        *verification.limitations,
        *(
            ('Candidate roots must be inspected from source before they are used '
             'as implementation targets.',)
            if any(item.classification == 'candidate' for item in roots)
            else ()
        ),
    }))
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
        'represented_tests': [item['simple_name'] for item in tests],
        'limitations': list(validation_limitations),
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
        and item.kind not in {'source_file', 'external_symbol'}
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
            'callable_index_fingerprint': (
                traceability.callable_index_fingerprint if traceability else None
            ),
            'code_graph_fingerprint': (
                traceability.code_graph_fingerprint if traceability else None
            ),
            'test_evidence_fingerprint': (
                traceability.test_evidence_fingerprint if traceability else None
            ),
            'reachability_fingerprint': (
                traceability.reachability_fingerprint if traceability else None
            ),
        },
        authoritative_project,
        selected_subject,
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
        _investigation_order_discovered(
            roots, nodes, requirements, tests, remediation
        ),
        validation,
        graph_artifacts,
        {
            'canonical_subject_ids': list(expected_subjects),
            'source_paths': list(expected_paths),
            'authoritative_project': authoritative_project,
            'authoritative_projects': list(root_projects),
            'root_subject_ids': [
                item.canonical_subject_id for item in roots
            ],
            'snapshot_id': snapshot.snapshot_id,
        },
        roots,
        discovery.anchors,
        discovery.diagnostics,
        version=3,
        producer=AGENT_CONTEXT_PRODUCER,
    )
    return replace(
        provisional,
        context_fingerprint=fingerprint(
            'agent-context', provisional.payload_without_fingerprint()
        ),
    )


def _graph_relationship_references(graph, nodes, root_ids, *, callers):
    values = {}
    edge_types = {
        'resolved_direct_call',
        'constructor_call',
        'possible_call_target',
        'possible_dispatch_target',
        'method_reference',
    }
    for edge in graph.edges:
        if edge.type not in edge_types:
            continue
        if callers:
            if edge.target not in root_ids:
                continue
            subject_id = edge.source
        else:
            if edge.source not in root_ids:
                continue
            subject_id = edge.target
        node = nodes.get(subject_id)
        if node is None or subject_id in root_ids:
            continue
        key = (subject_id, edge.type)
        values[key] = {
            **_node_reference(node),
            'edge_type': edge.type,
            'edge_confidence': edge.confidence,
        }
    return tuple(sorted(
        values.values(),
        key=lambda item: (
            item['qualified_name'].casefold(), item['id'], item['edge_type']
        ),
    ))


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
    proposed_rank = tuple(rank)
    try:
        selected_rank = min(existing.rank, proposed_rank)
    except TypeError:
        selected_rank = min(
            (existing.rank, proposed_rank),
            key=lambda value: tuple(
                (type(item).__name__, str(item)) for item in value
            ),
        )
    candidates[node.id] = _NodeCandidate(
        replace(selected, evidence_ids=evidence),
        selected_rank,
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
        'story_anchor_relation': 1,
        'external_dependency': 2,
        'project_ownership': 3,
        'resolved_direct_call': 4,
        'constructor_call': 5,
        'possible_call_target': 6,
        'possible_dispatch_target': 7,
        'method_reference': 8,
        'reverse_upstream': 9,
        'forward_test_reachability': 10,
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


def _investigation_order_discovered(roots, nodes, requirements, tests, remediation):
    values = []
    for root in roots[:8]:
        node = nodes.get(root.canonical_subject_id)
        values.append({
            'action': (
                'Inspect Atlas ranked authoritative root.'
                if root.classification == 'resolved'
                else 'Inspect Atlas ranked candidate root before treating it as an implementation target.'
            ),
            'subject_id': root.canonical_subject_id,
            'source_ref': (
                _node_reference(node)['source_ref'] if node is not None else None
            ),
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
