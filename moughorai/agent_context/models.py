'''Versioned deterministic contracts for external-agent context projection.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any


AGENT_CONTEXT_FORMAT = 'atlas-agent-context'
AGENT_CONTEXT_VERSION = 3
AGENT_GRAPH_FORMAT = 'atlas-agent-graph'
AGENT_GRAPH_VERSION = 3
AGENT_CONTEXT_PRODUCER = 'atlas-pr177/3'
AGENT_CONTEXT_LEGACY_PRODUCER = 'atlas-pr175/1'


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

    def __post_init__(self) -> None:
        if self.classification not in {'resolved', 'candidate'}:
            raise ValueError('discovered root classification is invalid')
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError('discovered root rank must be a positive integer')
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError('discovered root score must be an integer')

    def to_dict(self) -> dict[str, object]:
        return {
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
            'role': self.role,
            'score': self.score,
            'score_reasons': list(self.score_reasons),
            'search_modes': list(self.search_modes),
        }


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
