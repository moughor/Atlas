'''Read-only comparison of an Atlas agent context with a bounded Git change set.'''

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from moughorai.agent_context import AgentContextPackage, AgentGraphProjection
from moughorai.git_diff import GitDiff, UntrackedPaths
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver

from .models import (
    AgentChangedFileReview,
    AgentPostChangeReview,
    AgentReviewConfiguration,
    AgentReviewGraphRelation,
    AgentReviewReference,
    AgentReviewRequirement,
    AgentReviewRoot,
    AgentReviewSubject,
    BaseProvenance,
    ChangedFileStatus,
    EvidenceFreshness,
    ScopeClassification,
    agent_review_fingerprint,
)


_REQUIREMENT_STATUSES = frozenset({'IMPLEMENTED', 'PARTIAL', 'MISSING', 'NOT_PROVEN'})
_CANNOT_PROVE = (
    'Atlas does not prove that the implementation satisfies the story.',
    'Pre-change call relationships may be stale after source edits.',
    'Represented TEST reachability is not runtime test coverage.',
    'A changed file does not prove that a requirement is satisfied.',
    'New, removed, or changed declarations cannot be reconstructed without a new snapshot.',
    'The context package does not prove which Git commit generated it.',
)


class AgentReviewError(ValueError):
    '''Raised when post-change review authority is incompatible or unsafe.'''


@dataclass(frozen=True, slots=True)
class _Change:
    path: str
    old_path: str | None
    new_path: str | None
    status: ChangedFileStatus
    binary: bool
    hunks: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _ProjectedFile:
    review: AgentChangedFileReview
    graph_node_ids: tuple[str, ...]
    omitted_subjects: int
    omitted_line_numbers: int


class AgentReviewService:
    '''Project scope and stale pre-change evidence without reading source files.'''

    def __init__(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        repository_root: str | Path,
    ) -> None:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError('agent review requires a validated semantic snapshot')
        self._snapshot = snapshot
        self._root = Path(repository_root).expanduser().resolve()
        if not self._root.is_dir():
            raise AgentReviewError('agent review repository root must be a directory')
        self._resolver = CanonicalSubjectResolver.from_snapshot(snapshot)

    def review(
        self,
        context: AgentContextPackage,
        graph: AgentGraphProjection,
        diff: GitDiff,
        untracked: UntrackedPaths,
        *,
        configuration: AgentReviewConfiguration | None = None,
    ) -> AgentPostChangeReview:
        if not isinstance(context, AgentContextPackage):
            raise TypeError('agent review context is invalid')
        if not isinstance(graph, AgentGraphProjection):
            raise TypeError('agent review graph is invalid')
        if not isinstance(diff, GitDiff):
            raise TypeError('agent review Git diff is invalid')
        if not isinstance(untracked, UntrackedPaths):
            raise TypeError('agent review untracked path set is invalid')
        if diff.base is None or diff.base_commit is None:
            raise AgentReviewError('agent review requires an explicit resolved Git base')
        selected = configuration or AgentReviewConfiguration()
        self._validate_authority(context, graph)

        expected_paths = _path_values(
            context.expected_change_surface.get('source_paths', ()),
            'expected source paths',
        )
        expected_subjects = _string_values(
            context.expected_change_surface.get('canonical_subject_ids', ()),
            'expected canonical subjects',
        )
        roots = _context_roots(context, graph)
        expected_projects = _expected_projects(context, roots)
        nodes_by_id = {item.id: item for item in graph.nodes}
        nodes_by_path: dict[str, tuple[object, ...]] = {}
        for path in sorted({
            item.source_path for item in graph.nodes if item.source_path is not None
        }):
            nodes_by_path[path] = tuple(
                item for item in graph.nodes if item.source_path == path
            )

        changes, omitted_changed_files = _bounded_changes(
            diff, untracked, selected.maximum_changed_files
        )
        projected = tuple(
            self._project_file(
                item,
                roots,
                expected_paths,
                expected_subjects,
                expected_projects,
                graph,
                nodes_by_path,
                selected,
            )
            for item in changes
        )
        files = tuple(item.review for item in projected)
        changed_node_ids = {
            node_id for item in projected for node_id in item.graph_node_ids
        }
        matched_roots = tuple(sorted({
            root for item in files for root in item.matched_roots
        }, key=_root_sort_key))
        touched_expected_surface = any(
            item.scope_classification is ScopeClassification.WITHIN_EXPECTED_SURFACE
            for item in files
        )

        relations, omitted_relations = _related_relations(
            graph, changed_node_ids, selected.maximum_graph_relations
        )
        adjacent_ids = {
            value
            for item in relations
            for value in (item.source, item.target)
        }
        callers = _references(
            context.represented_callers,
            adjacent_ids,
            include_all=touched_expected_surface,
        )
        callees = _references(
            context.represented_callees,
            adjacent_ids,
            include_all=touched_expected_surface,
        )
        tests, omitted_tests = _tests(
            context, graph, adjacent_ids, touched_expected_surface,
            selected.maximum_tests,
        )
        requirements, omitted_requirements = _requirements(
            context, graph, changed_node_ids, touched_expected_surface,
            selected.maximum_requirements,
        )

        changed_projects = tuple(sorted({
            project for item in files for project in item.projects
        }))
        project_expansion = tuple(
            item for item in changed_projects if item not in set(expected_projects)
        )
        scope_summary = tuple(
            (classification.value, sum(
                item.scope_classification is classification for item in files
            ))
            for classification in ScopeClassification
        )
        overall = _overall_scope(files)
        freshness = tuple(sorted({
            EvidenceFreshness.PRE_CHANGE_EVIDENCE,
            *(item.evidence_freshness for item in files),
        }, key=lambda item: item.value))
        story_text = str(context.story.get('normalized_text', '')).strip()
        story_summary = story_text[:500]
        limitations = {
            'UNKNOWN_BASE_PROVENANCE: context.json does not prove its Git generation commit.',
            'Snapshot graph, test, and requirement facts describe the pre-change repository.',
        }
        if len(story_text) > len(story_summary):
            story_summary = story_summary.rstrip() + '...'
            limitations.add('The human review contains a bounded 500-character story summary.')
        if untracked.omitted_count:
            limitations.add('Some non-ignored untracked paths were omitted by the Git bound.')
        omitted_counts = tuple(sorted({
            'changed_files': omitted_changed_files,
            'mapped_subjects': sum(item.omitted_subjects for item in projected),
            'line_numbers': sum(item.omitted_line_numbers for item in projected),
            'graph_relations': omitted_relations,
            'represented_tests': omitted_tests,
            'requirements': omitted_requirements,
            'untracked_paths': untracked.omitted_count,
        }.items()))
        provisional = AgentPostChangeReview(
            'agent-review:v1:' + '0' * 64,
            context.context_fingerprint,
            graph.graph_fingerprint,
            diff.fingerprint,
            _required_string(context.story, 'fingerprint', 'story fingerprint'),
            _optional_payload_string(context.story.get('plan_fingerprint')),
            story_summary,
            self._snapshot.snapshot_id,
            self._root.as_posix(),
            diff.base,
            diff.base_commit,
            diff.repository_head,
            BaseProvenance.UNKNOWN_BASE_PROVENANCE,
            selected,
            expected_paths,
            expected_subjects,
            roots,
            expected_projects,
            files,
            overall,
            scope_summary,
            changed_projects,
            project_expansion,
            matched_roots,
            callers,
            callees,
            relations,
            tests,
            requirements,
            freshness,
            omitted_counts,
            tuple(sorted(limitations)),
            _CANNOT_PROVE,
        )
        return replace(
            provisional,
            review_fingerprint=agent_review_fingerprint(provisional),
        )

    def _validate_authority(
        self,
        context: AgentContextPackage,
        graph: AgentGraphProjection,
    ) -> None:
        repository = context.repository_identity
        context_snapshot = _required_string(
            repository, 'snapshot_id', 'context snapshot ID'
        )
        expected_surface_snapshot = _required_string(
            context.expected_change_surface,
            'snapshot_id',
            'expected surface snapshot ID',
        )
        if context_snapshot != graph.snapshot_id or context_snapshot != expected_surface_snapshot:
            raise AgentReviewError('context and graph snapshot identities do not agree')
        if context_snapshot != self._snapshot.snapshot_id:
            raise AgentReviewError('context snapshot does not match the resolved snapshot')
        story_fingerprint = _required_string(
            context.story, 'fingerprint', 'context story fingerprint'
        )
        if story_fingerprint != graph.story_fingerprint:
            raise AgentReviewError('context and graph story fingerprints do not agree')
        plan_fingerprint = _required_string(
            context.story, 'plan_fingerprint', 'context plan fingerprint'
        )
        if plan_fingerprint != graph.plan_fingerprint:
            raise AgentReviewError('context and graph plan fingerprints do not agree')
        graph_artifacts = context.graph_artifacts
        if _required_string(
            graph_artifacts, 'fingerprint', 'context graph fingerprint'
        ) != graph.graph_fingerprint:
            raise AgentReviewError('context graph fingerprint does not match graph.json')
        if graph_artifacts.get('node_count') != len(graph.nodes):
            raise AgentReviewError('context graph node count does not match graph.json')
        if graph_artifacts.get('edge_count') != len(graph.edges):
            raise AgentReviewError('context graph edge count does not match graph.json')
        repository_root = _required_string(
            repository, 'repository_root', 'context repository root'
        )
        if Path(repository_root).expanduser().resolve() != self._root:
            raise AgentReviewError('context repository root does not match review root')

    def _project_file(
        self,
        change: _Change,
        roots: tuple[AgentReviewRoot, ...],
        expected_paths: tuple[str, ...],
        expected_subjects: tuple[str, ...],
        expected_projects: tuple[str, ...],
        graph: AgentGraphProjection,
        nodes_by_path: dict[str, tuple[object, ...]],
        configuration: AgentReviewConfiguration,
    ) -> _ProjectedFile:
        paths = tuple(sorted({
            item for item in (change.old_path, change.new_path) if item is not None
        }))
        association_path = change.old_path if change.status in {
            ChangedFileStatus.DELETED, ChangedFileStatus.RENAMED
        } else change.new_path or change.old_path
        if association_path is None:
            raise AgentReviewError('changed file has no usable path')
        candidates = self._resolver.candidates_for_path(
            association_path,
            maximum_candidates=configuration.maximum_subjects_per_file,
        )
        exact_subjects: list[AgentReviewSubject] = []
        fallback_projects: set[str] = set()
        for candidate in candidates.candidates:
            if candidates.project_fallback:
                fallback_projects.add(candidate.name)
                continue
            exact_subjects.append(AgentReviewSubject(
                candidate.canonical_id,
                candidate.kind.value,
                candidate.qualified_name,
                candidate.name,
                candidate.project,
                candidate.path,
            ))
        path_nodes = tuple(
            node for path in paths for node in nodes_by_path.get(path, ())
        )
        graph_node_ids = {
            node.id for node in path_nodes
        } | {item.canonical_id for item in exact_subjects}
        root_matches = tuple(sorted((
            root for root in roots
            if root.source_path in paths or root.canonical_subject_id in graph_node_ids
        ), key=_root_sort_key))
        matched_paths = tuple(path for path in paths if path in set(expected_paths))
        matched_subjects = tuple(sorted(
            graph_node_ids.intersection(expected_subjects)
        ))
        projects = {
            *fallback_projects,
            *(item.project for item in exact_subjects if item.project),
            *(root.project for root in root_matches if root.project),
            *(node.project for node in path_nodes if node.project),
        }
        related_edges = tuple(
            edge for edge in graph.edges
            if edge.source in graph_node_ids or edge.target in graph_node_ids
        )
        justifications: set[str] = set()
        if matched_paths:
            justifications.add('Exact source path is in the precomputed expected surface.')
        if matched_subjects:
            justifications.add('Exact canonical subject is in the expected surface.')
        if root_matches:
            justifications.add('Changed path matches an explicit Atlas context root.')
        within = bool(matched_paths or matched_subjects or root_matches)
        represented = bool(exact_subjects or path_nodes or fallback_projects)
        new_without_authority = (
            change.status in {ChangedFileStatus.ADDED, ChangedFileStatus.UNTRACKED}
            and not within
            and not exact_subjects
            and not path_nodes
        )
        if within:
            scope = ScopeClassification.WITHIN_EXPECTED_SURFACE
        elif new_without_authority or not represented:
            scope = ScopeClassification.UNREPRESENTED_CHANGE
            justifications.add('No sufficient pre-change file or subject authority exists.')
        elif set(projects).intersection(expected_projects):
            scope = ScopeClassification.PLAUSIBLE_SCOPE_EXPANSION
            justifications.add('Owning project is represented in the expected project set.')
        elif related_edges:
            scope = ScopeClassification.PLAUSIBLE_SCOPE_EXPANSION
            justifications.add('A bounded pre-change graph relationship connects this file.')
        else:
            scope = ScopeClassification.UNEXPECTED_SCOPE
            justifications.add(
                'The represented local change has no expected path, project, or graph justification.'
            )
        freshness = (
            EvidenceFreshness.NO_PRE_CHANGE_EVIDENCE
            if scope is ScopeClassification.UNREPRESENTED_CHANGE
            else EvidenceFreshness.STALE_FOR_CURRENT_SEMANTICS
        )
        limitations = set(candidates.limitations)
        if candidates.project_fallback:
            limitations.add(
                'Project-only fallback is structural context, not exact Java declaration authority.'
            )
        if change.binary:
            limitations.add('Binary content was not parsed or retained.')
        if change.status is ChangedFileStatus.RENAMED:
            limitations.add('Rename metadata does not prove semantic identity continuity.')
        if change.status is ChangedFileStatus.DELETED:
            limitations.add('Deleted-file mapping uses pre-change path authority.')
        line_limit = configuration.maximum_line_numbers_per_file
        added = tuple(line for hunk in change.hunks for line in hunk.added_lines)
        removed = tuple(line for hunk in change.hunks for line in hunk.removed_lines)
        retained_added = added[:line_limit]
        remaining = max(0, line_limit - len(retained_added))
        retained_removed = removed[:remaining]
        omitted_lines = len(added) + len(removed) - len(retained_added) - len(retained_removed)
        if omitted_lines:
            limitations.add('Changed line metadata was deterministically bounded.')
        review = AgentChangedFileReview(
            change.path,
            change.old_path,
            change.new_path,
            change.status,
            change.binary,
            len(change.hunks),
            retained_added,
            retained_removed,
            scope,
            freshness,
            matched_paths,
            matched_subjects,
            root_matches,
            tuple(sorted(exact_subjects, key=lambda item: item.canonical_id)),
            tuple(sorted(fallback_projects)),
            tuple(sorted(projects)),
            tuple(sorted(justifications)),
            tuple(sorted(limitations)),
        )
        return _ProjectedFile(
            review,
            tuple(sorted(graph_node_ids)),
            candidates.omitted_candidate_count,
            omitted_lines,
        )


def resolve_default_graph_path(
    context_path: str | Path,
    context: AgentContextPackage,
) -> Path:
    parent = Path(context_path).expanduser().resolve().parent
    reference = _required_string(
        context.graph_artifacts, 'json', 'context graph artifact path'
    ).replace('\\', '/')
    relative = PurePosixPath(reference)
    if relative.is_absolute() or '..' in relative.parts or ':' in reference:
        raise AgentReviewError('context graph artifact path must stay beside context.json')
    selected = (parent / Path(*relative.parts)).resolve()
    try:
        selected.relative_to(parent)
    except ValueError as exc:
        raise AgentReviewError(
            'context graph artifact path escapes the context directory'
        ) from exc
    return selected


def _bounded_changes(
    diff: GitDiff,
    untracked: UntrackedPaths,
    maximum: int,
) -> tuple[tuple[_Change, ...], int]:
    values: list[_Change] = []
    tracked_paths: set[str] = set()
    for item in diff.files:
        path = item.new_path or item.old_path
        if path is None:
            continue
        tracked_paths.add(path)
        if item.renamed:
            status = ChangedFileStatus.RENAMED
        elif item.old_path is None:
            status = ChangedFileStatus.ADDED
        elif item.new_path is None:
            status = ChangedFileStatus.DELETED
        else:
            status = ChangedFileStatus.MODIFIED
        values.append(_Change(
            path, item.old_path, item.new_path, status, item.binary, item.hunks
        ))
    values.extend(
        _Change(
            path, None, path, ChangedFileStatus.UNTRACKED, False, ()
        )
        for path in untracked.paths
        if path not in tracked_paths
    )
    ordered = tuple(sorted(values, key=lambda item: (
        item.path, item.old_path or '', item.new_path or '', item.status.value
    )))
    return ordered[:maximum], max(0, len(ordered) - maximum)


def _context_roots(
    context: AgentContextPackage,
    graph: AgentGraphProjection,
) -> tuple[AgentReviewRoot, ...]:
    if context.discovered_roots:
        return tuple(sorted((AgentReviewRoot(
            item.canonical_subject_id,
            item.qualified_name,
            item.simple_name,
            item.project,
            item.source_path,
            item.rank,
            item.classification,
            item.role,
            item.confidence,
            item.authority,
        ) for item in context.discovered_roots), key=_root_sort_key))
    nodes = {item.id: item for item in graph.nodes}
    roots = []
    for rank, root_id in enumerate(graph.root_subjects, start=1):
        node = nodes.get(root_id)
        if node is None:
            raise AgentReviewError('agent graph root does not reference an included node')
        roots.append(AgentReviewRoot(
            node.id,
            node.qualified_name,
            node.simple_name,
            node.project,
            node.source_path,
            rank,
            'resolved' if root_id == context.selected_subject else 'candidate',
            node.role,
            node.confidence,
            'atlas-pr175-explicit-subject',
        ))
    return tuple(roots)


def _expected_projects(
    context: AgentContextPackage,
    roots: tuple[AgentReviewRoot, ...],
) -> tuple[str, ...]:
    values = {
        item.project for item in roots if item.project is not None
    }
    authoritative = context.expected_change_surface.get('authoritative_project')
    if authoritative is not None:
        values.add(_payload_string(authoritative, 'expected authoritative project'))
    listed = context.expected_change_surface.get('authoritative_projects', ())
    values.update(_string_values(listed, 'expected authoritative projects'))
    if context.authoritative_project is not None:
        values.add(context.authoritative_project)
    return tuple(sorted(values))


def _related_relations(
    graph: AgentGraphProjection,
    changed_node_ids: set[str],
    maximum: int,
) -> tuple[tuple[AgentReviewGraphRelation, ...], int]:
    values = tuple(sorted((AgentReviewGraphRelation(
        item.source,
        item.target,
        item.type,
        item.confidence,
        item.authority,
        item.status,
        item.depth,
    ) for item in graph.edges
        if item.source in changed_node_ids or item.target in changed_node_ids
    ), key=lambda item: (
        item.type, item.source, item.target,
        item.depth if item.depth is not None else -1,
        item.confidence, item.authority,
    )))
    return values[:maximum], max(0, len(values) - maximum)


def _references(
    payloads: tuple[dict[str, object], ...],
    adjacent_ids: set[str],
    *,
    include_all: bool,
) -> tuple[AgentReviewReference, ...]:
    values = []
    for payload in payloads:
        canonical_id = _required_string(payload, 'id', 'represented reference ID')
        if not include_all and canonical_id not in adjacent_ids:
            continue
        values.append(_reference_from_payload(payload))
    return tuple(sorted(set(values), key=_reference_sort_key))


def _tests(
    context: AgentContextPackage,
    graph: AgentGraphProjection,
    adjacent_ids: set[str],
    touched_expected_surface: bool,
    maximum: int,
) -> tuple[tuple[AgentReviewReference, ...], int]:
    values = list(_references(
        context.represented_tests,
        adjacent_ids,
        include_all=touched_expected_surface,
    ))
    retained_ids = {item.canonical_id for item in values}
    nodes = {item.id: item for item in graph.nodes}
    for canonical_id in graph.represented_tests:
        if canonical_id in retained_ids:
            continue
        if not touched_expected_surface and canonical_id not in adjacent_ids:
            continue
        node = nodes.get(canonical_id)
        if node is None:
            continue
        values.append(AgentReviewReference(
            node.id,
            node.qualified_name,
            node.simple_name,
            node.project,
            _node_source_ref(node),
            node.role,
            node.confidence,
        ))
    ordered = tuple(sorted(set(values), key=_reference_sort_key))
    return ordered[:maximum], max(0, len(ordered) - maximum)


def _requirements(
    context: AgentContextPackage,
    graph: AgentGraphProjection,
    changed_node_ids: set[str],
    touched_expected_surface: bool,
    maximum: int,
) -> tuple[tuple[AgentReviewRequirement, ...], int]:
    related_ids = {
        value
        for edge in graph.edges
        if edge.type == 'story_requirement_relation'
        and (edge.source in changed_node_ids or edge.target in changed_node_ids)
        for value in (edge.source, edge.target)
    }
    values = []
    for payload in context.requirement_reconciliation:
        requirement_id = _required_string(payload, 'id', 'requirement ID')
        if not touched_expected_surface and requirement_id not in related_ids:
            continue
        status = _required_string(payload, 'status', 'requirement status')
        if status not in _REQUIREMENT_STATUSES:
            raise AgentReviewError(f'unsupported requirement status: {status}')
        values.append(AgentReviewRequirement(
            requirement_id,
            _required_string(payload, 'text', 'requirement text'),
            status,
            _required_string(payload, 'classification', 'requirement classification'),
            _string_values(payload.get('linked_subjects', ()), 'linked subjects'),
            _string_values(payload.get('evidence_ids', ()), 'requirement evidence IDs'),
        ))
    ordered = tuple(sorted(values, key=lambda item: item.requirement_id))
    return ordered[:maximum], max(0, len(ordered) - maximum)


def _reference_from_payload(payload: dict[str, object]) -> AgentReviewReference:
    return AgentReviewReference(
        _required_string(payload, 'id', 'represented reference ID'),
        _required_string(payload, 'qualified_name', 'represented qualified name'),
        _required_string(payload, 'simple_name', 'represented simple name'),
        _optional_payload_string(payload.get('project')),
        _optional_payload_string(payload.get('source_ref')),
        _optional_payload_string(payload.get('role')),
        _optional_payload_string(
            payload.get('edge_confidence', payload.get('confidence'))
        ),
        _optional_payload_string(payload.get('edge_type')),
    )


def _node_source_ref(node) -> str | None:
    if node.source_path is None:
        return None
    if node.source_span is None:
        return node.source_path
    start = node.source_span.get('start')
    end = node.source_span.get('end')
    if not isinstance(start, dict) or not isinstance(end, dict):
        return node.source_path
    start_line = start.get('line')
    start_column = start.get('column')
    end_line = end.get('line')
    end_column = end.get('column')
    return (
        f'{node.source_path}#L{start_line}C{start_column}'
        f'-L{end_line}C{end_column}'
    )


def _overall_scope(
    files: tuple[AgentChangedFileReview, ...],
) -> ScopeClassification | None:
    present = {item.scope_classification for item in files}
    for value in (
        ScopeClassification.UNEXPECTED_SCOPE,
        ScopeClassification.UNREPRESENTED_CHANGE,
        ScopeClassification.PLAUSIBLE_SCOPE_EXPANSION,
        ScopeClassification.WITHIN_EXPECTED_SURFACE,
    ):
        if value in present:
            return value
    return None


def _root_sort_key(item: AgentReviewRoot) -> tuple[object, ...]:
    return (item.rank, item.canonical_subject_id, item.source_path or '')


def _reference_sort_key(item: AgentReviewReference) -> tuple[str, str, str]:
    return (item.qualified_name.casefold(), item.canonical_id, item.edge_type or '')


def _path_values(value: object, label: str) -> tuple[str, ...]:
    paths = []
    for item in _string_values(value, label):
        normalized = item.replace('\\', '/')
        path = PurePosixPath(normalized)
        if path.is_absolute() or '..' in path.parts or ':' in normalized:
            raise AgentReviewError(f'{label} must contain safe relative paths')
        paths.append(path.as_posix())
    return tuple(sorted(set(paths)))


def _string_values(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise AgentReviewError(f'{label} must be an array')
    return tuple(sorted({_payload_string(item, f'{label} entry') for item in value}))


def _required_string(
    payload: dict[str, object], key: str, label: str
) -> str:
    if key not in payload:
        raise AgentReviewError(f'{label} is missing')
    return _payload_string(payload[key], label)


def _payload_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentReviewError(f'{label} must be a non-empty string')
    return value


def _optional_payload_string(value: object) -> str | None:
    if value is None:
        return None
    return _payload_string(value, 'optional review value')
