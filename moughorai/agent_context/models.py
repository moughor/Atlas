'''Versioned deterministic contracts for external-agent context projection.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


AGENT_CONTEXT_FORMAT = 'atlas-agent-context'
AGENT_CONTEXT_VERSION = 3
AGENT_GRAPH_FORMAT = 'atlas-agent-graph'
AGENT_GRAPH_VERSION = 3
AGENT_CONTEXT_PRODUCER = 'atlas-pr177/3'
AGENT_CONTEXT_LEGACY_PRODUCER = 'atlas-pr175/1'
SUPPORTED_AGENT_CONTEXT_PRODUCERS = {
    1: AGENT_CONTEXT_LEGACY_PRODUCER,
    2: 'atlas-pr176/2',
    3: AGENT_CONTEXT_PRODUCER,
}
SUPPORTED_AGENT_GRAPH_PRODUCERS = dict(SUPPORTED_AGENT_CONTEXT_PRODUCERS)
MAXIMUM_AGENT_CONTEXT_BYTES = 4 * 1024 * 1024
MAXIMUM_AGENT_GRAPH_BYTES = 16 * 1024 * 1024


def canonical_json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        separators=(',', ':') if indent is None else None,
        sort_keys=True,
        allow_nan=False,
    )


def fingerprint(prefix: str, value: object) -> str:
    digest = hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
    return f'{prefix}:v1:{digest}'


class AgentGraphDepth(str, Enum):
    STORY = 'story'
    EXPANDED = 'expanded'


@dataclass(frozen=True, slots=True)
class AgentGraphConfiguration:
    depth: AgentGraphDepth = AgentGraphDepth.STORY
    max_nodes: int = 100
    max_edges: int = 600
    upstream_depth: int = 3
    query_max_nodes: int = 1_024

    @classmethod
    def for_depth(cls, depth: AgentGraphDepth | str) -> 'AgentGraphConfiguration':
        selected = depth if isinstance(depth, AgentGraphDepth) else AgentGraphDepth(
            str(depth).strip().casefold()
        )
        if selected is AgentGraphDepth.EXPANDED:
            return cls(selected, 500, 4_000, 8, 4_096)
        return cls(selected, 100, 600, 3, 1_024)

    def __post_init__(self) -> None:
        if not isinstance(self.depth, AgentGraphDepth):
            raise TypeError('agent graph depth is invalid')
        for name in ('max_nodes', 'max_edges', 'upstream_depth', 'query_max_nodes'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        expected = (100, 600, 3, 1_024) if self.depth is AgentGraphDepth.STORY else (
            500, 4_000, 8, 4_096
        )
        if (
            self.max_nodes,
            self.max_edges,
            self.upstream_depth,
            self.query_max_nodes,
        ) != expected:
            raise ValueError('agent graph bounds must use the versioned tier contract')

    def to_dict(self) -> dict[str, object]:
        return {
            'depth': self.depth.value,
            'max_nodes': self.max_nodes,
            'max_edges': self.max_edges,
            'upstream_depth': self.upstream_depth,
            'query_max_nodes': self.query_max_nodes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentGraphConfiguration':
        _require_fields(
            value,
            {'depth', 'max_nodes', 'max_edges', 'upstream_depth', 'query_max_nodes'},
            'agent graph configuration',
        )
        return cls(
            AgentGraphDepth(_string(value['depth'], 'agent graph depth')),
            _integer(value['max_nodes'], 'agent graph maximum nodes'),
            _integer(value['max_edges'], 'agent graph maximum edges'),
            _integer(value['upstream_depth'], 'agent graph upstream depth'),
            _integer(value['query_max_nodes'], 'agent graph query maximum nodes'),
        )


@dataclass(frozen=True, slots=True)
class AgentGraphNode:
    id: str
    kind: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_path: str | None
    source_span: dict[str, object] | None
    role: str
    confidence: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            'id': self.id,
            'kind': self.kind,
            'qualified_name': self.qualified_name,
            'simple_name': self.simple_name,
            'project': self.project,
            'source_path': self.source_path,
            'source_span': self.source_span,
            'role': self.role,
            'confidence': self.confidence,
            'evidence_ids': list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentGraphNode':
        _require_fields(
            value,
            {
                'id', 'kind', 'qualified_name', 'simple_name', 'project',
                'source_path', 'source_span', 'role', 'confidence', 'evidence_ids',
            },
            'agent graph node',
        )
        return cls(
            _string(value['id'], 'agent graph node ID'),
            _string(value['kind'], 'agent graph node kind'),
            _string(value['qualified_name'], 'agent graph qualified name'),
            _string(value['simple_name'], 'agent graph simple name'),
            _optional_string(value['project'], 'agent graph node project'),
            _optional_string(value['source_path'], 'agent graph node source path'),
            _optional_mapping(value['source_span'], 'agent graph node source span'),
            _string(value['role'], 'agent graph node role'),
            _string(value['confidence'], 'agent graph node confidence'),
            _strings(value['evidence_ids'], 'agent graph node evidence IDs'),
        )


@dataclass(frozen=True, slots=True)
class AgentGraphEdge:
    source: str
    target: str
    type: str
    confidence: str
    authority: str
    evidence: tuple[str, ...] = ()
    depth: int | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            'from': self.source,
            'to': self.target,
            'type': self.type,
            'confidence': self.confidence,
            'authority': self.authority,
            'evidence': list(self.evidence),
        }
        if self.depth is not None:
            value['depth'] = self.depth
        if self.status is not None:
            value['status'] = self.status
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentGraphEdge':
        required = {'from', 'to', 'type', 'confidence', 'authority', 'evidence'}
        _require_allowed_fields(
            value, required, {*required, 'depth', 'status'}, 'agent graph edge'
        )
        depth = value.get('depth')
        return cls(
            _string(value['from'], 'agent graph edge source'),
            _string(value['to'], 'agent graph edge target'),
            _string(value['type'], 'agent graph edge type'),
            _string(value['confidence'], 'agent graph edge confidence'),
            _string(value['authority'], 'agent graph edge authority'),
            _strings(value['evidence'], 'agent graph edge evidence'),
            None if depth is None else _integer(depth, 'agent graph edge depth'),
            _optional_string(value.get('status'), 'agent graph edge status'),
        )


@dataclass(frozen=True, slots=True)
class StoryAnchor:
    text: str
    normalized_text: str
    anchor_type: str
    strength: int
    specificity: int
    source_location_in_story: dict[str, int]
    technical_note: bool
    identifier_like: bool
    exact_match_preferred: bool
    semantic_search_allowed: bool
    ambiguity_penalty: int
    provenance: str

    def __post_init__(self) -> None:
        if not self.text or not self.normalized_text:
            raise ValueError('story anchor text must not be blank')
        if not 0 <= self.strength <= 100 or not 0 <= self.specificity <= 100:
            raise ValueError('story anchor strength and specificity must be bounded')
        if not 0 <= self.ambiguity_penalty <= 100:
            raise ValueError('story anchor ambiguity penalty must be bounded')
        if set(self.source_location_in_story) != {'start', 'end'}:
            raise ValueError('story anchor location must contain start and end offsets')

    def to_dict(self) -> dict[str, object]:
        return {
            'text': self.text,
            'normalized_text': self.normalized_text,
            'anchor_type': self.anchor_type,
            'strength': self.strength,
            'specificity': self.specificity,
            'source_location_in_story': self.source_location_in_story,
            'technical_note': self.technical_note,
            'identifier_like': self.identifier_like,
            'exact_match_preferred': self.exact_match_preferred,
            'semantic_search_allowed': self.semantic_search_allowed,
            'ambiguity_penalty': self.ambiguity_penalty,
            'provenance': self.provenance,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'StoryAnchor':
        _require_fields(
            value,
            {
                'text', 'normalized_text', 'anchor_type', 'strength', 'specificity',
                'source_location_in_story', 'technical_note', 'identifier_like',
                'exact_match_preferred', 'semantic_search_allowed',
                'ambiguity_penalty', 'provenance',
            },
            'story anchor',
        )
        location = _mapping(
            value['source_location_in_story'], 'story anchor source location'
        )
        _require_fields(location, {'start', 'end'}, 'story anchor source location')
        return cls(
            _string(value['text'], 'story anchor text'),
            _string(value['normalized_text'], 'story anchor normalized text'),
            _string(value['anchor_type'], 'story anchor type'),
            _integer(value['strength'], 'story anchor strength'),
            _integer(value['specificity'], 'story anchor specificity'),
            {
                'start': _integer(location['start'], 'story anchor start'),
                'end': _integer(location['end'], 'story anchor end'),
            },
            _boolean(value['technical_note'], 'story anchor technical flag'),
            _boolean(value['identifier_like'], 'story anchor identifier flag'),
            _boolean(value['exact_match_preferred'], 'story anchor exact flag'),
            _boolean(value['semantic_search_allowed'], 'story anchor semantic flag'),
            _integer(value['ambiguity_penalty'], 'story anchor ambiguity penalty'),
            _string(value['provenance'], 'story anchor provenance'),
        )


@dataclass(frozen=True, slots=True)
class AgentDiscoveredRoot:
    canonical_subject_id: str
    kind: str
    qualified_name: str
    simple_name: str
    project: str | None
    source_path: str | None
    source_span: dict[str, object] | None
    rank: int
    classification: str
    confidence: str
    authority: str
    matched_anchors: tuple[str, ...]
    discovery_rationale: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    role: str = 'unknown'
    score: int = 0
    score_reasons: tuple[str, ...] = ()
    search_modes: tuple[str, ...] = ()
    contract_version: int = 3

    def __post_init__(self) -> None:
        if self.classification not in {'resolved', 'candidate'}:
            raise ValueError('discovered root classification is invalid')
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError('discovered root rank must be a positive integer')
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError('discovered root score must be an integer')
        if self.contract_version not in {2, 3}:
            raise ValueError('discovered root contract version is invalid')

    def to_dict(self) -> dict[str, object]:
        value = {
            'canonical_subject_id': self.canonical_subject_id,
            'kind': self.kind,
            'qualified_name': self.qualified_name,
            'simple_name': self.simple_name,
            'project': self.project,
            'source_path': self.source_path,
            'source_span': self.source_span,
            'rank': self.rank,
            'classification': self.classification,
            'confidence': self.confidence,
            'authority': self.authority,
            'matched_anchors': list(self.matched_anchors),
            'discovery_rationale': list(self.discovery_rationale),
            'evidence_ids': list(self.evidence_ids),
        }
        if self.contract_version >= 3:
            value.update({
                'role': self.role,
                'score': self.score,
                'score_reasons': list(self.score_reasons),
                'search_modes': list(self.search_modes),
            })
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentDiscoveredRoot':
        base_fields = {
            'canonical_subject_id', 'kind', 'qualified_name', 'simple_name',
            'project', 'source_path', 'source_span', 'rank', 'classification',
            'confidence', 'authority', 'matched_anchors',
            'discovery_rationale', 'evidence_ids',
        }
        version = 2 if set(value) == base_fields else 3
        fields = base_fields | (
            {'role', 'score', 'score_reasons', 'search_modes'} if version == 3 else set()
        )
        _require_fields(value, fields, 'agent discovered root')
        return cls(
            _string(value['canonical_subject_id'], 'discovered root ID'),
            _string(value['kind'], 'discovered root kind'),
            _string(value['qualified_name'], 'discovered root qualified name'),
            _string(value['simple_name'], 'discovered root simple name'),
            _optional_string(value['project'], 'discovered root project'),
            _optional_string(value['source_path'], 'discovered root source path'),
            _optional_mapping(value['source_span'], 'discovered root source span'),
            _integer(value['rank'], 'discovered root rank'),
            _string(value['classification'], 'discovered root classification'),
            _string(value['confidence'], 'discovered root confidence'),
            _string(value['authority'], 'discovered root authority'),
            _strings(value['matched_anchors'], 'discovered root matched anchors'),
            _strings(value['discovery_rationale'], 'discovered root rationale'),
            _strings(value['evidence_ids'], 'discovered root evidence IDs'),
            _string(value['role'], 'discovered root role') if version == 3 else 'unknown',
            _integer(value['score'], 'discovered root score') if version == 3 else 0,
            _strings(value['score_reasons'], 'discovered root score reasons')
            if version == 3 else (),
            _strings(value['search_modes'], 'discovered root search modes')
            if version == 3 else (),
            version,
        )


@dataclass(frozen=True, slots=True)
class AgentGraphProjection:
    graph_fingerprint: str
    snapshot_id: str
    story_fingerprint: str
    plan_fingerprint: str
    configuration: AgentGraphConfiguration
    root_subjects: tuple[str, ...]
    nodes: tuple[AgentGraphNode, ...]
    edges: tuple[AgentGraphEdge, ...]
    represented_tests: tuple[str, ...]
    requirements: tuple[dict[str, object], ...]
    uncertainties: tuple[str, ...]
    omitted_counts: dict[str, int]
    discovered_roots: tuple[AgentDiscoveredRoot, ...] = ()
    format: str = AGENT_GRAPH_FORMAT
    version: int = AGENT_GRAPH_VERSION
    producer: str = AGENT_CONTEXT_PRODUCER

    def payload_without_fingerprint(self) -> dict[str, object]:
        payload = {
            'format': self.format,
            'version': self.version,
            'producer': self.producer,
            'snapshot_id': self.snapshot_id,
            'story_fingerprint': self.story_fingerprint,
            'plan_fingerprint': self.plan_fingerprint,
            'configuration': self.configuration.to_dict(),
            'root_subjects': list(self.root_subjects),
            'nodes': [item.to_dict() for item in self.nodes],
            'edges': [item.to_dict() for item in self.edges],
            'represented_tests': list(self.represented_tests),
            'requirements': list(self.requirements),
            'uncertainties': list(self.uncertainties),
            'omitted_counts': dict(sorted(self.omitted_counts.items())),
        }
        if self.version >= 2:
            payload['discovered_roots'] = [
                item.to_dict() for item in self.discovered_roots
            ]
        return payload

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_without_fingerprint()
        payload['graph_fingerprint'] = self.graph_fingerprint
        return payload

    def to_json(self) -> str:
        return canonical_json(self.to_dict(), indent=2) + '\n'

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentGraphProjection':
        version = _supported_version(
            value, AGENT_GRAPH_FORMAT, SUPPORTED_AGENT_GRAPH_PRODUCERS,
            'agent graph',
        )
        fields = {
            'format', 'version', 'producer', 'graph_fingerprint', 'snapshot_id',
            'story_fingerprint', 'plan_fingerprint', 'configuration',
            'root_subjects', 'nodes', 'edges', 'represented_tests',
            'requirements', 'uncertainties', 'omitted_counts',
        }
        if version >= 2:
            fields.add('discovered_roots')
        _require_fields(value, fields, 'agent graph')
        nodes = tuple(
            AgentGraphNode.from_dict(item)
            for item in _mappings(value['nodes'], 'agent graph nodes')
        )
        edges = tuple(
            AgentGraphEdge.from_dict(item)
            for item in _mappings(value['edges'], 'agent graph edges')
        )
        node_ids = {item.id for item in nodes}
        if len(node_ids) != len(nodes):
            raise ValueError('agent graph node IDs must be unique')
        if any(item.source not in node_ids or item.target not in node_ids for item in edges):
            raise ValueError('agent graph edges must reference included nodes')
        omitted = _mapping(value['omitted_counts'], 'agent graph omitted counts')
        candidate = cls(
            _string(value['graph_fingerprint'], 'agent graph fingerprint'),
            _string(value['snapshot_id'], 'agent graph snapshot ID'),
            _string(value['story_fingerprint'], 'agent graph story fingerprint'),
            _string(value['plan_fingerprint'], 'agent graph plan fingerprint'),
            AgentGraphConfiguration.from_dict(
                _mapping(value['configuration'], 'agent graph configuration')
            ),
            _strings(value['root_subjects'], 'agent graph root subjects'),
            nodes,
            edges,
            _strings(value['represented_tests'], 'agent graph represented tests'),
            _mappings(value['requirements'], 'agent graph requirements'),
            _strings(value['uncertainties'], 'agent graph uncertainties'),
            {
                _string(key, 'agent graph omission name'): _integer(
                    count, 'agent graph omission count'
                )
                for key, count in omitted.items()
            },
            tuple(
                AgentDiscoveredRoot.from_dict(item)
                for item in _mappings(
                    value.get('discovered_roots', ()), 'agent graph discovered roots'
                )
            ),
            _string(value['format'], 'agent graph format'),
            version,
            _string(value['producer'], 'agent graph producer'),
        )
        expected = fingerprint('agent-graph', candidate.payload_without_fingerprint())
        if candidate.graph_fingerprint != expected:
            raise ValueError('agent graph fingerprint mismatch')
        return candidate


@dataclass(frozen=True, slots=True)
class AgentContextPackage:
    context_fingerprint: str
    story: dict[str, object]
    repository_identity: dict[str, object]
    authoritative_project: str | None
    selected_subject: str | None
    primary_implementation_surface: tuple[dict[str, object], ...]
    important_collaborators: tuple[dict[str, object], ...]
    represented_callers: tuple[dict[str, object], ...]
    represented_callees: tuple[dict[str, object], ...]
    impact_summary: dict[str, object]
    represented_tests: tuple[dict[str, object], ...]
    requirement_reconciliation: tuple[dict[str, object], ...]
    remediation_operational_work: tuple[dict[str, object], ...]
    uncertainty: tuple[str, ...]
    recommended_investigation_order: tuple[dict[str, object], ...]
    validation_guidance: dict[str, object]
    graph_artifacts: dict[str, object]
    expected_change_surface: dict[str, object]
    discovered_roots: tuple[AgentDiscoveredRoot, ...] = ()
    story_anchors: tuple[StoryAnchor, ...] = ()
    discovery_diagnostics: dict[str, object] | None = None
    format: str = AGENT_CONTEXT_FORMAT
    version: int = AGENT_CONTEXT_VERSION
    producer: str = AGENT_CONTEXT_PRODUCER

    def payload_without_fingerprint(self) -> dict[str, object]:
        payload = {
            'format': self.format,
            'version': self.version,
            'producer': self.producer,
            'story': self.story,
            'repository_identity': self.repository_identity,
            'authoritative_project': self.authoritative_project,
            'selected_subject': self.selected_subject,
            'primary_implementation_surface': list(self.primary_implementation_surface),
            'important_collaborators': list(self.important_collaborators),
            'represented_callers': list(self.represented_callers),
            'represented_callees': list(self.represented_callees),
            'impact_summary': self.impact_summary,
            'represented_tests': list(self.represented_tests),
            'requirement_reconciliation': list(self.requirement_reconciliation),
            'remediation_operational_work': list(self.remediation_operational_work),
            'uncertainty': list(self.uncertainty),
            'recommended_investigation_order': list(
                self.recommended_investigation_order
            ),
            'validation_guidance': self.validation_guidance,
            'graph_artifacts': self.graph_artifacts,
            'expected_change_surface': self.expected_change_surface,
        }
        if self.version >= 2:
            payload['discovered_roots'] = [
                item.to_dict() for item in self.discovered_roots
            ]
        if self.version >= 3:
            payload['story_anchors'] = [item.to_dict() for item in self.story_anchors]
            payload['discovery_diagnostics'] = self.discovery_diagnostics or {}
        return payload

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_without_fingerprint()
        payload['context_fingerprint'] = self.context_fingerprint
        return payload

    def to_json(self) -> str:
        return canonical_json(self.to_dict(), indent=2) + '\n'

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> 'AgentContextPackage':
        version = _supported_version(
            value, AGENT_CONTEXT_FORMAT, SUPPORTED_AGENT_CONTEXT_PRODUCERS,
            'agent context',
        )
        fields = {
            'format', 'version', 'producer', 'context_fingerprint', 'story',
            'repository_identity', 'authoritative_project', 'selected_subject',
            'primary_implementation_surface', 'important_collaborators',
            'represented_callers', 'represented_callees', 'impact_summary',
            'represented_tests', 'requirement_reconciliation',
            'remediation_operational_work', 'uncertainty',
            'recommended_investigation_order', 'validation_guidance',
            'graph_artifacts', 'expected_change_surface',
        }
        if version >= 2:
            fields.add('discovered_roots')
        if version >= 3:
            fields.update({'story_anchors', 'discovery_diagnostics'})
        _require_fields(value, fields, 'agent context')
        candidate = cls(
            _string(value['context_fingerprint'], 'agent context fingerprint'),
            _mapping(value['story'], 'agent context story'),
            _mapping(value['repository_identity'], 'agent repository identity'),
            _optional_string(
                value['authoritative_project'], 'agent context authoritative project'
            ),
            _optional_string(value['selected_subject'], 'agent context selected subject'),
            _mappings(
                value['primary_implementation_surface'],
                'agent primary implementation surface',
            ),
            _mappings(value['important_collaborators'], 'agent collaborators'),
            _mappings(value['represented_callers'], 'agent represented callers'),
            _mappings(value['represented_callees'], 'agent represented callees'),
            _mapping(value['impact_summary'], 'agent impact summary'),
            _mappings(value['represented_tests'], 'agent represented tests'),
            _mappings(
                value['requirement_reconciliation'], 'agent requirement reconciliation'
            ),
            _mappings(
                value['remediation_operational_work'], 'agent remediation work'
            ),
            _strings(value['uncertainty'], 'agent context uncertainty'),
            _mappings(
                value['recommended_investigation_order'],
                'agent investigation order',
            ),
            _mapping(value['validation_guidance'], 'agent validation guidance'),
            _mapping(value['graph_artifacts'], 'agent graph artifacts'),
            _mapping(value['expected_change_surface'], 'agent expected change surface'),
            tuple(
                AgentDiscoveredRoot.from_dict(item)
                for item in _mappings(
                    value.get('discovered_roots', ()), 'agent discovered roots'
                )
            ),
            tuple(
                StoryAnchor.from_dict(item)
                for item in _mappings(value.get('story_anchors', ()), 'story anchors')
            ),
            (
                _mapping(value['discovery_diagnostics'], 'discovery diagnostics')
                if version >= 3 else None
            ),
            _string(value['format'], 'agent context format'),
            version,
            _string(value['producer'], 'agent context producer'),
        )
        expected = fingerprint('agent-context', candidate.payload_without_fingerprint())
        if candidate.context_fingerprint != expected:
            raise ValueError('agent context fingerprint mismatch')
        return candidate


@dataclass(frozen=True, slots=True)
class AgentContextArtifacts:
    package: AgentContextPackage
    graph: AgentGraphProjection
    context_markdown: str
    graph_mermaid: str
    output_files: tuple[tuple[str, int], ...] = ()

    def with_output_files(
        self,
        values: tuple[tuple[str, int], ...],
    ) -> 'AgentContextArtifacts':
        return AgentContextArtifacts(
            self.package,
            self.graph,
            self.context_markdown,
            self.graph_mermaid,
            values,
        )


def json_value(value: Any) -> Any:
    '''Return a JSON-safe deep copy while rejecting non-deterministic values.'''
    return json.loads(canonical_json(value))


def load_agent_context_package(path: str | Path) -> AgentContextPackage:
    payload = _load_json_object(path, MAXIMUM_AGENT_CONTEXT_BYTES, 'agent context')
    try:
        return AgentContextPackage.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'agent context authority is invalid: {exc}') from exc


def load_agent_graph_projection(path: str | Path) -> AgentGraphProjection:
    payload = _load_json_object(path, MAXIMUM_AGENT_GRAPH_BYTES, 'agent graph')
    try:
        return AgentGraphProjection.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'agent graph authority is invalid: {exc}') from exc


def _load_json_object(
    path: str | Path,
    maximum_bytes: int,
    label: str,
) -> dict[str, object]:
    selected = Path(path).expanduser().resolve()
    if not selected.is_file():
        raise ValueError(f'{label} file does not exist: {selected}')
    with selected.open('rb') as handle:
        raw = handle.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError(f'{label} file exceeds the {maximum_bytes}-byte bound')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{label} file must be UTF-8') from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{label} file is not valid JSON') from exc
    return _mapping(payload, label)


def _supported_version(
    value: Mapping[str, object],
    expected_format: str,
    producers: Mapping[int, str],
    label: str,
) -> int:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    if value.get('format') != expected_format:
        raise ValueError(f'unsupported {label} format')
    version = _integer(value.get('version'), f'{label} version')
    if version not in producers:
        raise ValueError(f'unsupported {label} version: {version}')
    if value.get('producer') != producers[version]:
        raise ValueError(f'{label} producer does not match version {version}')
    return version


def _require_fields(
    value: Mapping[str, object], expected: set[str], label: str
) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f'invalid {label} fields')


def _require_allowed_fields(
    value: Mapping[str, object],
    required: set[str],
    allowed: set[str],
    label: str,
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    if not required <= set(value) or not set(value) <= allowed:
        raise ValueError(f'invalid {label} fields')


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f'{label} keys must be strings')
    return json_value(dict(value))


def _optional_mapping(value: object, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _mapping(value, label)


def _mappings(value: object, label: str) -> tuple[dict[str, object], ...]:
    values = _sequence(value, label)
    return tuple(_mapping(item, f'{label} entry') for item in values)


def _strings(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, f'{label} entry') for item in _sequence(value, label))


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise TypeError(f'{label} must be an array')
    return tuple(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f'{label} must be a non-empty string')
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'{label} must be an integer')
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f'{label} must be a boolean')
    return value
