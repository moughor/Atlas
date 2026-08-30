"""Bounded database context selection for story/impediment analysis.

Phase C3 — selects a relevant subgraph from a reconciled DatabaseGraph
by extracting domain terms from story text, matching them against graph
nodes with a weighted scoring system, pinning exact matches and their
essential neighbourhood, expanding via FK connectivity, and capping the
result at a bounded size.

Phase B hardens the cap: the total number of selected objects (nodes)
never exceeds ``max_objects`` even when pinned nodes are present.  When
the pinned neighbourhood alone would exceed the cap, a deterministic
priority eviction keeps directly-mentioned tables and their required
relationships while trimming lower-priority FK expansions and columns.

All outputs are frozen dataclasses with deterministic fingerprints and
full round-trip serialisation (to_dict / from_dict).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    NodeKind,
    canonical_json,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_HOPS: int = 2
_DEFAULT_MAX_OBJECTS: int = 60

# Scoring weights
_SCORE_EXACT_IDENTIFIER: int = 100    # Exact full identifier match (e.g. 'TB_GRP_PF_FEATURE')
_SCORE_EXACT_ENTITY: int = 90         # Exact Java entity/constant name match
_SCORE_MAPS_TO_TARGET: int = 85       # MAPS_TO target of matched entity
_SCORE_FK_COLUMN_NEIGHBOR: int = 70   # Declared FK/column neighbor of matched table
_SCORE_DOMAIN_PHRASE: int = 50        # Normalized domain phrase match
_SCORE_FUZZY_SUBSTRING: int = 20      # Fuzzy/substring match (5+ chars)
_MIN_SUBSTRING_LENGTH: int = 5        # Minimum chars for a substring match to score

# Entity bridge matching: require this many camelCase word hits (from distinct
# story terms) to bridge a single entity.  A full-name exact match always
# passes regardless of this threshold.
_ENTITY_BRIDGE_MIN_WORD_HITS: int = 2

# Tier constants for ranking — lower tier = higher priority.
_TIER_PINNED: int = 0         # Pinned nodes (exact match + essential neighborhood)
_TIER_FK_CONNECTED: int = 1   # FK-connected tables of pinned nodes
_TIER_FK_COLUMNS: int = 2     # Columns of tier-1 tables
_TIER_DOMAIN: int = 3         # Domain phrase matches
_TIER_FUZZY: int = 4          # Fuzzy/substring matches

# Sub-tier constants within TIER_PINNED for priority eviction.
_SUB_EXACT_TABLE: int = 0     # Directly mentioned table (score 100)
_SUB_EXACT_ENTITY: int = 1    # Directly mentioned entity (score 90)
_SUB_ENTITY_BRIDGE: int = 2   # Entity-bridged table (score 85)
_SUB_FK_OF_EXACT: int = 3     # FK neighbor of an exact-matched table
_SUB_COL_OF_EXACT: int = 4    # Column of a pinned table

# Node kinds that are structural anchors
_ANCHOR_KINDS: frozenset[str] = frozenset({
    NodeKind.TABLE.value,
    NodeKind.VIEW.value,
    NodeKind.MATERIALIZED_VIEW.value,
    NodeKind.JAVA_ENTITY.value,
    NodeKind.SEQUENCE.value,
    NodeKind.SYNONYM.value,
    NodeKind.TRIGGER.value,
    NodeKind.PROCEDURE.value,
    NodeKind.FUNCTION.value,
    NodeKind.PACKAGE.value,
    NodeKind.DOMAIN_CONCEPT.value,
})

_TABLE_KINDS: frozenset[str] = frozenset({
    NodeKind.TABLE.value,
    NodeKind.VIEW.value,
    NodeKind.MATERIALIZED_VIEW.value,
})

_ENTITY_KINDS: frozenset[str] = frozenset({
    NodeKind.JAVA_ENTITY.value,
})

# Word boundary tokeniser
_SPLIT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_CAMEL_SPLIT_RE = re.compile(
    r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|_"
)

_MIN_TERM_LENGTH: int = 3

# NOTE: Static abbreviation dictionary removed. Alias expansion now relies
# exclusively on repository evidence (entity names, table segments, view
# definitions) already present in the alias index.

# Pure English stop-words that are NEVER valid Oracle identifiers.
# Terms that also appear as graph identifiers are NOT filtered — see
# _filter_stop_words() which checks the graph before discarding.
_ENGLISH_STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "have", "has",
    "had", "are", "was", "were", "been", "being", "not", "but", "can",
    "will", "should", "would", "could", "may", "might", "shall", "must",
    "need", "needs", "want", "wants", "get", "gets", "got", "set", "use",
    "used", "using", "make", "makes", "made", "when", "where", "how",
    "why", "what", "which", "who", "whom", "also", "just", "only", "than",
    "then", "into", "each", "all", "any", "both", "few", "more", "most",
    "some", "such", "too", "very", "does", "did", "its", "our", "their",
    "your", "per", "via", "see", "ensure", "bug", "issue", "story",
    "task", "ticket", "impediment", "requirement", "implement",
})


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------

def _sha256(payload: object) -> str:
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# SelectionDetail — per-tier breakdown of selected / omitted nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SelectionDetail:
    """Per-tier breakdown of how many nodes were selected and omitted.

    Attributes:
        tier: Tier constant (_TIER_PINNED .. _TIER_FUZZY).
        tier_label: Human-readable tier name.
        selected: Number of nodes selected in this tier.
        omitted: Number of candidate nodes in this tier that were trimmed.
    """

    tier: int
    tier_label: str
    selected: int = 0
    omitted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_label": self.tier_label,
            "selected": self.selected,
            "omitted": self.omitted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionDetail:
        if not isinstance(data, dict):
            raise ValueError("selection detail must be an object")
        return cls(
            tier=int(data.get("tier", 0)),
            tier_label=str(data.get("tier_label", "")),
            selected=int(data.get("selected", 0)),
            omitted=int(data.get("omitted", 0)),
        )


_TIER_LABELS: dict[int, str] = {
    _TIER_PINNED: "pinned",
    _TIER_FK_CONNECTED: "fk_connected",
    _TIER_FK_COLUMNS: "fk_columns",
    _TIER_DOMAIN: "domain",
    _TIER_FUZZY: "fuzzy",
}

# Selection strategy identifiers
SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1: str = "evidence_bundles_v1"
SELECTION_STRATEGY_LEGACY: str = "legacy_neighbourhood"


# ---------------------------------------------------------------------------
# SelectionUncertainty — typed uncertainty records for unresolved evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SelectionUncertainty:
    """Typed uncertainty record for unresolved evidence in context selection.

    Attributes:
        code: Semantic code identifying the uncertainty type (e.g.,
              'DYNAMIC_SYNONYM_TARGET_UNPROVEN', 'SCHEMA_FALLBACK_UNVERIFIED').
        object_id: Node ID or identifier of the object/candidate.
        object_name: Human-readable name of the object.
        reason: Explanation of why the evidence is uncertain.
        evidence_source: Source of the evidence (e.g., 'graph_node_property',
                        'story_extraction', 'fk_expansion').
        source_revision: Revision/provenance of the source (graph fingerprint).
        resolved: False if the uncertainty blocks full resolution; True if
                  the object is included despite uncertainty.
    """

    code: str
    object_id: str
    object_name: str
    reason: str
    evidence_source: str
    source_revision: str
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "object_id": self.object_id,
            "object_name": self.object_name,
            "reason": self.reason,
            "evidence_source": self.evidence_source,
            "source_revision": self.source_revision,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectionUncertainty":
        if not isinstance(data, dict):
            raise ValueError("selection uncertainty must be an object")
        return cls(
            code=str(data.get("code", "")),
            object_id=str(data.get("object_id", "")),
            object_name=str(data.get("object_name", "")),
            reason=str(data.get("reason", "")),
            evidence_source=str(data.get("evidence_source", "")),
            source_revision=str(data.get("source_revision", "")),
            resolved=bool(data.get("resolved", False)),
        )


# ---------------------------------------------------------------------------
# TruncationMetadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TruncationMetadata:
    """Records whether and how the bounded context was truncated.

    Attributes:
        was_truncated: True if any candidate nodes were removed.
        hard_cap: The max_objects cap that was enforced.
        total_candidates: Total scored nodes before capping.
        total_selected: Total nodes in the final result.
        tier_details: Per-tier selection/omission breakdown.
        pinned_evicted: Number of pinned-tier nodes evicted to meet the hard cap.
    """

    was_truncated: bool = False
    hard_cap: int = _DEFAULT_MAX_OBJECTS
    total_candidates: int = 0
    total_selected: int = 0
    tier_details: tuple[SelectionDetail, ...] = ()
    pinned_evicted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "was_truncated": self.was_truncated,
            "hard_cap": self.hard_cap,
            "total_candidates": self.total_candidates,
            "total_selected": self.total_selected,
            "tier_details": [d.to_dict() for d in self.tier_details],
            "pinned_evicted": self.pinned_evicted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TruncationMetadata:
        if not isinstance(data, dict):
            raise ValueError("truncation metadata must be an object")
        return cls(
            was_truncated=bool(data.get("was_truncated", False)),
            hard_cap=int(data.get("hard_cap", _DEFAULT_MAX_OBJECTS)),
            total_candidates=int(data.get("total_candidates", 0)),
            total_selected=int(data.get("total_selected", 0)),
            tier_details=tuple(
                SelectionDetail.from_dict(d)
                for d in data.get("tier_details", ())
            ),
            pinned_evicted=int(data.get("pinned_evicted", 0)),
        )


# ---------------------------------------------------------------------------
# OmittedCounts
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OmittedCounts:
    """Tracks how many nodes and edges were trimmed from the full expansion.

    Attributes:
        nodes_omitted: Number of nodes removed to reach the cap.
        edges_omitted: Number of edges removed because at least one
                       endpoint was trimmed.
        total_candidate_nodes: Total nodes in the expanded neighbourhood
                               before capping.
        total_candidate_edges: Total edges in the expanded neighbourhood
                               before capping.
    """

    nodes_omitted: int = 0
    edges_omitted: int = 0
    total_candidate_nodes: int = 0
    total_candidate_edges: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_omitted": self.nodes_omitted,
            "edges_omitted": self.edges_omitted,
            "total_candidate_nodes": self.total_candidate_nodes,
            "total_candidate_edges": self.total_candidate_edges,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OmittedCounts:
        if not isinstance(data, dict):
            raise ValueError("omitted counts must be an object")
        return cls(
            nodes_omitted=int(data.get("nodes_omitted", 0)),
            edges_omitted=int(data.get("edges_omitted", 0)),
            total_candidate_nodes=int(data.get("total_candidate_nodes", 0)),
            total_candidate_edges=int(data.get("total_candidate_edges", 0)),
        )


# ---------------------------------------------------------------------------
# DatabaseContextResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseContextResult:
    """Bounded database context for a story or impediment.

    Attributes:
        selected_nodes: Nodes included in the bounded context.
        selected_edges: Edges included (both endpoints are in selected_nodes).
        story_terms_matched: Domain terms from the story that matched graph nodes.
        story_terms_unmatched: Domain terms from the story that had no match.
        omitted_counts: Trimming statistics.
        full_graph_fingerprint: SHA-256 fingerprint of the source DatabaseGraph.
        context_fingerprint: SHA-256 fingerprint of this bounded context payload.
        max_hops: Maximum hop depth used for expansion.
        max_objects: Maximum node cap used.
        truncation: Detailed truncation metadata (Phase B).
        selection_strategy: Machine-readable identifier of the selection
                           algorithm used (e.g., 'evidence_bundles_v1').
        uncertainties: Typed uncertainty records for unresolved evidence.
                       Always present (empty list if no uncertainties).
    """

    selected_nodes: tuple[DatabaseGraphNode, ...]
    selected_edges: tuple[DatabaseGraphEdge, ...]
    story_terms_matched: tuple[str, ...]
    story_terms_unmatched: tuple[str, ...]
    omitted_counts: OmittedCounts
    full_graph_fingerprint: str
    context_fingerprint: str
    max_hops: int
    max_objects: int
    truncation: TruncationMetadata = field(default_factory=TruncationMetadata)
    selection_strategy: str = SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1
    uncertainties: tuple["SelectionUncertainty", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_nodes", tuple(self.selected_nodes))
        object.__setattr__(self, "selected_edges", tuple(self.selected_edges))
        object.__setattr__(self, "story_terms_matched", tuple(self.story_terms_matched))
        object.__setattr__(self, "story_terms_unmatched", tuple(self.story_terms_unmatched))
        object.__setattr__(self, "uncertainties", tuple(self.uncertainties))
        if not self.full_graph_fingerprint:
            raise ValueError("full_graph_fingerprint must not be empty")
        if not self.context_fingerprint:
            raise ValueError("context_fingerprint must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_nodes": [n.to_dict() for n in self.selected_nodes],
            "selected_edges": [e.to_dict() for e in self.selected_edges],
            "story_terms_matched": list(self.story_terms_matched),
            "story_terms_unmatched": list(self.story_terms_unmatched),
            "omitted_counts": self.omitted_counts.to_dict(),
            "full_graph_fingerprint": self.full_graph_fingerprint,
            "context_fingerprint": self.context_fingerprint,
            "max_hops": self.max_hops,
            "max_objects": self.max_objects,
            "truncation": self.truncation.to_dict(),
            "selection_strategy": self.selection_strategy,
            "uncertainties": [u.to_dict() for u in self.uncertainties],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseContextResult:
        if not isinstance(data, dict):
            raise ValueError("database context result must be an object")
        trunc_raw = data.get("truncation")
        trunc = TruncationMetadata.from_dict(trunc_raw) if isinstance(trunc_raw, dict) else TruncationMetadata()
        uncert_raw = data.get("uncertainties", ())
        uncertainties = tuple(
            SelectionUncertainty.from_dict(u) for u in uncert_raw
        ) if uncert_raw else ()
        return cls(
            selected_nodes=tuple(
                DatabaseGraphNode.from_dict(n)
                for n in data.get("selected_nodes", ())
            ),
            selected_edges=tuple(
                DatabaseGraphEdge.from_dict(e)
                for e in data.get("selected_edges", ())
            ),
            story_terms_matched=tuple(data.get("story_terms_matched", ())),
            story_terms_unmatched=tuple(data.get("story_terms_unmatched", ())),
            omitted_counts=OmittedCounts.from_dict(
                data.get("omitted_counts", {})
            ),
            full_graph_fingerprint=data["full_graph_fingerprint"],
            context_fingerprint=data["context_fingerprint"],
            max_hops=int(data.get("max_hops", _DEFAULT_MAX_HOPS)),
            max_objects=int(data.get("max_objects", _DEFAULT_MAX_OBJECTS)),
            truncation=trunc,
            selection_strategy=str(data.get("selection_strategy", SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1)),
            uncertainties=uncertainties,
        )


# ---------------------------------------------------------------------------
# Graph index — precomputed lookups for fast matching
# ---------------------------------------------------------------------------

class _GraphIndex:
    """Pre-built indexes over a DatabaseGraph for efficient matching."""

    __slots__ = (
        "graph",
        "node_by_id",
        "short_name_to_nodes",
        "qname_upper_to_nodes",
        "all_identifiers_upper",
        "table_nodes",
        "entity_nodes",
        "outgoing",
        "incoming",
        "alias_to_nodes",
        "table_evidence_terms",
    )

    def __init__(self, graph: DatabaseGraph) -> None:
        self.graph = graph
        self.node_by_id: dict[str, DatabaseGraphNode] = {}
        # short name (upper) -> list of nodes
        self.short_name_to_nodes: dict[str, list[DatabaseGraphNode]] = {}
        # full qualified name (upper) -> node
        self.qname_upper_to_nodes: dict[str, DatabaseGraphNode] = {}
        # set of all identifiers (upper) present in the graph — for stop-word checking
        self.all_identifiers_upper: set[str] = set()
        self.table_nodes: list[DatabaseGraphNode] = []
        self.entity_nodes: list[DatabaseGraphNode] = []
        # adjacency: node_id -> list of (edge, neighbor_id, direction)
        self.outgoing: dict[str, list[DatabaseGraphEdge]] = {}
        self.incoming: dict[str, list[DatabaseGraphEdge]] = {}

        for node in graph.nodes:
            self.node_by_id[node.id] = node
            short = node.qualified_name.rsplit(".", 1)[-1].upper()
            self.short_name_to_nodes.setdefault(short, []).append(node)
            qn_upper = node.qualified_name.upper()
            self.qname_upper_to_nodes[qn_upper] = node
            self.all_identifiers_upper.add(short)
            self.all_identifiers_upper.add(qn_upper)
            if node.kind in _TABLE_KINDS:
                self.table_nodes.append(node)
            elif node.kind in _ENTITY_KINDS:
                self.entity_nodes.append(node)

        for edge in graph.edges:
            self.outgoing.setdefault(edge.from_node, []).append(edge)
            self.incoming.setdefault(edge.to_node, []).append(edge)

        # --- Semantic alias index ---
        # Maps normalized multi-word phrases to table/view node IDs.
        # Built from entity class names, table name segments, and
        # view/FK relationship evidence.
        self.alias_to_nodes: dict[str, list[tuple[str, int]]] = {}  # phrase → [(node_id, weight)]
        self._build_alias_index(graph)

        # Build per-table semantic evidence term documents.
        # Each table gets a set of lowercase terms derived from:
        #   - Entity class name words (via MAPS_TO_TABLE edges)
        #   - Field names (via qualified name hierarchy of java_field nodes)
        #   - Table name segments
        #   - Column names
        # These documents power corpus-frequency scoring.
        self.table_evidence_terms: dict[str, set[str]] = {}
        self._build_evidence_terms(graph)

    def edges_from(self, node_id: str, kind: str | None = None) -> list[DatabaseGraphEdge]:
        """Return outgoing edges, optionally filtered by kind."""
        edges = self.outgoing.get(node_id, [])
        if kind is not None:
            return [e for e in edges if e.kind == kind]
        return edges

    def _build_alias_index(self, graph: DatabaseGraph) -> None:
        """Build a semantic alias index from repository evidence.

        Sources:
        1. Entity class names → MAPS_TO table (weight 90)
        2. Table/view name segments after prefix stripping (weight 70)
        3. Multi-word compounds from table names (weight 80)

        Each alias is a lowercase multi-word phrase. The index maps
        phrases to (node_id, weight) pairs for weighted retrieval.
        """
        def _add_alias(phrase: str, node_id: str, weight: int) -> None:
            phrase = phrase.lower().strip()
            if len(phrase) < 3:
                return
            self.alias_to_nodes.setdefault(phrase, []).append((node_id, weight))

        # Common table name prefixes to strip
        _PREFIXES = [
            "TB_RT_", "TB_APP_", "TB_GRP_", "TB_MDL_", "TB_LOG_",
            "TB_GRP_PR_", "TB_GRP_PL_", "TB_GRP_C_",
            "VW_HD_", "VW_", "MV_A_", "MV_", "TB_",
        ]

        # 1. Entity MAPS_TO aliases
        for edge in graph.edges:
            if edge.kind != EdgeKind.MAPS_TO_TABLE.value:
                continue
            ent_node = self.node_by_id.get(edge.from_node)
            tbl_node = self.node_by_id.get(edge.to_node)
            if not ent_node or not tbl_node:
                continue
            ent_short = ent_node.qualified_name.rsplit(".", 1)[-1]
            words = _split_camel_case(ent_short)
            # Full entity name as alias
            _add_alias(" ".join(words), tbl_node.id, 90)
            # Consecutive 2-word and 3-word sub-phrases
            for wlen in (3, 2):
                for i in range(len(words) - wlen + 1):
                    _add_alias(" ".join(words[i:i + wlen]), tbl_node.id, 85)

        # 2. Table/view name segment aliases
        for node in graph.nodes:
            if node.kind not in _TABLE_KINDS:
                continue
            qn = node.qualified_name.upper()
            short = qn.rsplit(".", 1)[-1]

            # Strip known prefixes
            stripped = short
            for prefix in _PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    break

            segments = [s for s in stripped.split("_") if len(s) >= 2]
            if not segments:
                continue

            # Full stripped name as one phrase
            full_phrase = " ".join(s.lower() for s in segments)
            _add_alias(full_phrase, node.id, 70)

            # Consecutive 2-segment and 3-segment sub-phrases
            for wlen in (3, 2):
                for i in range(len(segments) - wlen + 1):
                    phrase = " ".join(s.lower() for s in segments[i:i + wlen])
                    _add_alias(phrase, node.id, 75)

            # Single significant segments (4+ chars, avoids noise from short
            # segments like "PR", "PL", "AI")
            for s in segments:
                if len(s) >= 4:
                    _add_alias(s.lower(), node.id, 55)

    def edges_to(self, node_id: str, kind: str | None = None) -> list[DatabaseGraphEdge]:
        """Return incoming edges, optionally filtered by kind."""
        edges = self.incoming.get(node_id, [])
        if kind is not None:
            return [e for e in edges if e.kind == kind]
        return edges

    def _build_evidence_terms(self, graph: DatabaseGraph) -> None:
        """Build per-table semantic evidence term documents.

        For each table/view/MV node, collects lowercase terms from:
        1. Table name segments (after stripping TB_/VW_/MV_ prefix)
        2. Entity class name words (from MAPS_TO_TABLE incoming edges)
        3. Java field names (from java_field nodes whose qname starts
           with the entity qname)
        4. Column names (from HAS_COLUMN edges)

        Stores ``self.table_evidence_terms[node_id] = {set of terms}``.
        """
        _PREFIXES = (
            "TB_RT_", "TB_APP_", "TB_GRP_", "TB_MDL_", "TB_LOG_",
            "TB_GRP_PR_", "TB_GRP_PL_", "TB_GRP_C_",
            "VW_HD_", "VW_", "MV_A_", "MV_", "TB_",
        )

        # Pre-build entity→table mapping from MAPS_TO_TABLE edges
        entity_to_table: dict[str, str] = {}  # entity_id → table_id
        table_to_entities: dict[str, list[str]] = {}  # table_id → [entity_ids]
        for edge in graph.edges:
            if edge.kind == EdgeKind.MAPS_TO_TABLE.value:
                entity_to_table[edge.from_node] = edge.to_node
                table_to_entities.setdefault(edge.to_node, []).append(edge.from_node)

        # Pre-build entity qname set for field lookup
        entity_qnames: dict[str, str] = {}  # entity_id → qname
        for node in graph.nodes:
            if node.kind in _ENTITY_KINDS:
                entity_qnames[node.id] = node.qualified_name

        # Collect java_field nodes indexed by their qname prefix (entity qname)
        field_names_by_entity: dict[str, list[str]] = {}
        for node in graph.nodes:
            if node.kind == "java_field":
                # Field qname is typically "pkg.EntityName.fieldName"
                qn = node.qualified_name
                for ent_id, ent_qn in entity_qnames.items():
                    if qn.startswith(ent_qn + "."):
                        field_short = qn[len(ent_qn) + 1:].rsplit(".", 1)[-1]
                        field_names_by_entity.setdefault(ent_id, []).append(field_short)

        for node in graph.nodes:
            if node.kind not in _TABLE_KINDS:
                continue

            terms: set[str] = set()
            short = node.qualified_name.rsplit(".", 1)[-1].upper()

            # 1. Table name segments after prefix stripping
            stripped = short
            for prefix in _PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    break
            for seg in stripped.split("_"):
                if len(seg) >= 2:
                    terms.add(seg.lower())

            # 2. Entity class name words (from MAPS_TO_TABLE incoming edges)
            for ent_id in table_to_entities.get(node.id, []):
                ent_node = self.node_by_id.get(ent_id)
                if ent_node is None:
                    continue
                ent_short = ent_node.qualified_name.rsplit(".", 1)[-1]
                for w in _split_camel_case(ent_short):
                    terms.add(w)

                # 3. Java field names from fields of this entity
                for field_name in field_names_by_entity.get(ent_id, []):
                    for w in _split_camel_case(field_name):
                        terms.add(w)

            # Column names are intentionally EXCLUDED from evidence terms.
            # Generic column names (ID, NAME, CREATE_DATE, UPDATE_USER) appear
            # on nearly every table and would inflate concept-match counts,
            # defeating the purpose of specificity-based scoring.

            self.table_evidence_terms[node.id] = terms

    def columns_of(self, table_id: str) -> list[str]:
        """Return node IDs of columns connected via HAS_COLUMN from table_id."""
        return [
            e.to_node
            for e in self.edges_from(table_id, EdgeKind.HAS_COLUMN.value)
        ]

    def fk_neighbors_of(self, table_id: str) -> list[tuple[str, DatabaseGraphEdge]]:
        """Return (neighbor_table_id, fk_edge) for FK connections from/to table_id."""
        result: list[tuple[str, DatabaseGraphEdge]] = []
        for e in self.edges_from(table_id, EdgeKind.FOREIGN_KEY_TO.value):
            result.append((e.to_node, e))
        for e in self.edges_to(table_id, EdgeKind.FOREIGN_KEY_TO.value):
            result.append((e.from_node, e))
        return result

    def maps_to_target(self, entity_id: str) -> str | None:
        """Return the table node ID that an entity MAPS_TO_TABLE, or None."""
        edges = self.edges_from(entity_id, EdgeKind.MAPS_TO_TABLE.value)
        if edges:
            return edges[0].to_node
        return None


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

def _extract_terms(text: str) -> list[str]:
    """Extract candidate domain terms from story text.

    Strategy:
    1. Tokenise on non-alphanumeric boundaries.
    2. Split camelCase and snake_case tokens into sub-words.
    3. Also keep the original unsplit token (for compound names like
       'UserAccount' or 'ORDER_ITEM').
    4. Normalise to uppercase for matching (graph identifiers are uppercase).
    5. Deduplicate while preserving first-occurrence order.
    6. Filter out tokens shorter than _MIN_TERM_LENGTH.

    Note: stop-word filtering happens later in _filter_stop_words() because
    we need the graph index to check whether a stop-word is also a valid
    Oracle identifier.

    Returns a deduplicated list of UPPERCASE candidate terms.
    """
    raw_tokens = _SPLIT_RE.split(text)

    seen: set[str] = set()
    terms: list[str] = []

    for token in raw_tokens:
        if not token:
            continue

        # Keep the full token (e.g. "UserAccount", "ORDER_ITEM", "TB_GRP_PF_FEATURE")
        upper_full = token.upper()
        if len(upper_full) >= _MIN_TERM_LENGTH and upper_full not in seen:
            seen.add(upper_full)
            terms.append(upper_full)

        # Split on camelCase / underscore boundaries
        sub_parts = _CAMEL_SPLIT_RE.split(token)
        for part in sub_parts:
            upper_part = part.upper()
            if len(upper_part) >= _MIN_TERM_LENGTH and upper_part not in seen:
                seen.add(upper_part)
                terms.append(upper_part)

    return terms


# ---------------------------------------------------------------------------
# Database pattern extraction (Fix 3A)
# ---------------------------------------------------------------------------

# Regex for known database object naming conventions
_DB_OBJECT_RE = re.compile(
    r"\b(TB_[A-Z0-9_]+|VW_[A-Z0-9_]+|MV_[A-Z0-9_]+|SQ_[A-Z0-9_]+"
    r"|MV_A_[A-Z0-9_]+|BCK_[A-Z0-9_]+)\b"
)

# Regex for generic ALL_CAPS_UNDERSCORE tokens of 8+ chars (likely db identifiers)
_ALLCAPS_IDENT_RE = re.compile(r"\b([A-Z][A-Z0-9_]{7,})\b")

# SQL DML patterns: FROM <table>, JOIN <table>, INTO <table>, UPDATE <table>
_SQL_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)


def _extract_database_patterns(text: str) -> list[str]:
    """Extract database object naming patterns from text.

    Finds:
    - TB_*, VW_*, MV_*, SQ_*, MV_A_*, BCK_* naming conventions
    - Any ALL_CAPS_UNDERSCORE tokens of 8+ chars (likely database identifiers)

    Returns a deduplicated list of UPPERCASE patterns.
    """
    seen: set[str] = set()
    results: list[str] = []

    # Convert text to uppercase for pattern matching
    upper_text = text.upper()

    # Named DB object patterns (TB_, VW_, MV_, SQ_, MV_A_, BCK_)
    for m in _DB_OBJECT_RE.finditer(upper_text):
        token = m.group(1)
        if token not in seen:
            seen.add(token)
            results.append(token)

    # Generic ALL_CAPS_UNDERSCORE identifiers (8+ chars)
    for m in _ALLCAPS_IDENT_RE.finditer(text):
        token = m.group(1).upper()
        if token not in seen and "_" in token:
            seen.add(token)
            results.append(token)

    return results


def _extract_sql_table_references(text: str) -> list[str]:
    """Extract table names from SQL-like patterns in text.

    Finds table names after FROM, JOIN, INTO, UPDATE keywords.
    Returns a deduplicated list of UPPERCASE table references.
    """
    seen: set[str] = set()
    results: list[str] = []

    for m in _SQL_TABLE_REF_RE.finditer(text):
        # Take the last segment if qualified (schema.table)
        raw = m.group(1).strip().rstrip(",;)")
        token = raw.upper()
        if len(token) >= _MIN_TERM_LENGTH and token not in seen:
            seen.add(token)
            results.append(token)

    return results


def _split_camel_case(name: str) -> list[str]:
    """Split a camelCase or PascalCase name into lowercase words.

    E.g. 'ProjectFeature' -> ['project', 'feature']
         'RuleExceptionDef' -> ['rule', 'exception', 'def']
    """
    parts = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).split()
    return [p.lower() for p in parts if len(p) >= _MIN_TERM_LENGTH]


def _normalize_plural(word: str) -> set[str]:
    """Return a set of singular/plural variants of a lowercase word.

    E.g. 'features' → {'features', 'feature'}
         'property' → {'property', 'properties'}
    """
    forms = {word}
    if word.endswith("ies"):
        forms.add(word[:-3] + "y")  # properties → property
    elif word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        forms.add(word[:-2])  # processes → process
    elif word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])  # features → feature
    # reverse: add plural form
    if word.endswith("y") and len(word) > 3 and word[-2] not in "aeiou":
        forms.add(word[:-1] + "ies")  # property → properties
    else:
        forms.add(word + "s")  # feature → features
    return forms


def _filter_stop_words(
    terms: list[str],
    idx: _GraphIndex,
) -> list[str]:
    """Remove pure English stop-words that have NO match in the graph.

    A term that is in _ENGLISH_STOP_WORDS BUT also matches a graph identifier
    (short name or qualified name) is KEPT — it's a valid Oracle identifier.
    """
    result: list[str] = []
    for term in terms:
        lower = term.lower()
        if lower in _ENGLISH_STOP_WORDS:
            # Check if this stop-word is also a valid identifier in the graph
            if term in idx.all_identifiers_upper:
                result.append(term)
            # else: pure stop-word with no graph match — discard
        else:
            result.append(term)
    return result


# ---------------------------------------------------------------------------
# Scored node matching
# ---------------------------------------------------------------------------

@dataclass
class _ScoredNode:
    """A graph node with a relevance score and tier assignment."""
    node_id: str
    score: int
    tier: int
    reason: str  # debugging breadcrumb
    sub_tier: int = _SUB_COL_OF_EXACT  # default: lowest pinned priority
    kind_priority: int = 1  # 0 = table/view/entity, 1 = column/other
    concept_matches: int = 0  # distinct story concepts matching evidence terms

    def sort_key(self) -> tuple[int, int, int, int, int, str]:
        """Sort: tier, sub_tier, kind_priority, -concept_matches, -score, id.

        kind_priority ensures tables/views/entities survive before columns
        when competing for the same tier+sub_tier slot.
        concept_matches ensures tables matching more story concepts rank
        higher within the same tier/sub_tier/kind_priority.
        """
        return (self.tier, self.sub_tier, self.kind_priority, -self.concept_matches, -self.score, self.node_id)


def _apply_prefix_diversity(
    entries: list[_ScoredNode],
    idx: _GraphIndex,
    max_per_family: int = 3,
) -> list[_ScoredNode]:
    """Apply diminishing-returns filtering by 3-segment underscore prefix.

    Groups items by their 3-segment prefix (e.g. 'TB_GRP_PR' from
    'TB_GRP_PR_AI') and keeps only the top-K scored items per family.
    This prevents large prefix families (e.g. 256 TB_GRP_PR_* tables)
    from consuming all structural slots.

    Entries are assumed to already be sorted by sort_key() (best first).
    """
    family_counts: dict[str, int] = {}
    result: list[_ScoredNode] = []
    for sn in entries:
        node = idx.node_by_id.get(sn.node_id)
        if node is None:
            result.append(sn)
            continue
        short = node.qualified_name.rsplit(".", 1)[-1].upper()
        parts = short.split("_")
        if len(parts) >= 5:
            prefix = "_".join(parts[:4])
        else:
            # Short names: no family grouping, always keep
            result.append(sn)
            continue
        count = family_counts.get(prefix, 0)
        if count < max_per_family:
            result.append(sn)
            family_counts[prefix] = count + 1
        # else: suppressed — over the per-family cap
    return result


def _compute_idf(terms: list[str], idx: _GraphIndex) -> dict[str, float]:
    """Compute IDF weights for story terms against table evidence documents.

    For each story term, counts how many table/view evidence documents
    contain it (document frequency).  Returns IDF weight per term:

        IDF = log(N_tables / (1 + doc_freq))

    Properties:
    - Terms appearing in >30% of tables get IDF < 1.0 (penalized).
    - Terms appearing in <5% of tables get IDF > 3.0 (boosted).
    - Terms with no evidence matches get IDF = 1.0 (neutral).
    """
    n_tables = max(len(idx.table_evidence_terms), 1)
    idf: dict[str, float] = {}

    for term in terms:
        t_lower = term.lower()
        # Count how many table evidence documents contain this term
        # (including plural/singular variants)
        variants = _normalize_plural(t_lower)
        doc_freq = 0
        for _table_id, ev_terms in idx.table_evidence_terms.items():
            if variants & ev_terms:
                doc_freq += 1
        if doc_freq > 0:
            idf[t_lower] = math.log(n_tables / (1 + doc_freq))
        else:
            idf[t_lower] = 1.0

    return idf


def _apply_concept_coverage_boost(
    scored: dict[str, _ScoredNode],
    terms: list[str],
    idx: _GraphIndex,
) -> None:
    """Apply multi-concept coverage bonus to scored table/view/MV nodes.

    Only counts terms whose IDF >= 1.5 (uncommon terms) as distinct
    concepts.  Common infrastructure terms (project, session, id) that
    appear in >30% of table evidence documents are excluded from the
    concept count.

    The bonus is deliberately modest — it breaks ties between similarly
    scored candidates, not override the scoring fundamentals.
    """
    if not terms:
        return

    # Compute IDF for story terms
    idf = _compute_idf(terms, idx)

    # Only count uncommon terms as distinct concepts
    _IDF_CONCEPT_THRESHOLD = 1.5
    terms_lower = [t.lower() for t in terms]
    rare_terms: dict[str, set[str]] = {}  # term -> plural variants
    for t in terms_lower:
        if idf.get(t, 0.0) >= _IDF_CONCEPT_THRESHOLD:
            rare_terms[t] = _normalize_plural(t)

    n_total_rare = len(rare_terms)

    for node_id, sn in list(scored.items()):
        node = idx.node_by_id.get(node_id)
        if node is None or node.kind not in _TABLE_KINDS:
            sn.concept_matches = 0
            continue

        ev_terms = idx.table_evidence_terms.get(node_id, set())
        if not ev_terms:
            sn.concept_matches = 0
            continue

        # Count distinct RARE story terms matching evidence terms
        matched_concepts: set[str] = set()
        for t_lower, variants in rare_terms.items():
            if variants & ev_terms:
                matched_concepts.add(t_lower)

        n_matches = len(matched_concepts)
        sn.concept_matches = n_matches

        # Modest bonus: only for 2+ rare concept matches
        if n_matches >= 3:
            bonus = n_matches * 8
        elif n_matches >= 2:
            bonus = n_matches * 5
        else:
            continue  # No bonus for single-concept matches

        # Update the scored node's score
        scored[node_id] = _ScoredNode(
            node_id=sn.node_id,
            score=sn.score + bonus,
            tier=sn.tier,
            reason=sn.reason,
            sub_tier=sn.sub_tier,
            kind_priority=sn.kind_priority,
            concept_matches=n_matches,
        )


def _score_and_match(
    terms: list[str],
    idx: _GraphIndex,
) -> tuple[dict[str, _ScoredNode], list[str], list[str]]:
    """Score every candidate node against the extracted terms.

    Returns (scored_nodes_by_id, matched_terms, unmatched_terms).
    """
    scored: dict[str, _ScoredNode] = {}
    matched_terms: list[str] = []
    unmatched_terms: list[str] = []

    def _upsert(node_id: str, score: int, tier: int, reason: str,
                sub_tier: int = _SUB_COL_OF_EXACT) -> None:
        # Determine kind_priority: tables/views/entities get 0, columns/other get 1
        node = idx.node_by_id.get(node_id)
        kp = 0 if node and node.kind in _ANCHOR_KINDS else 1
        existing = scored.get(node_id)
        if existing is None:
            scored[node_id] = _ScoredNode(
                node_id=node_id, score=score, tier=tier, reason=reason,
                sub_tier=sub_tier, kind_priority=kp,
            )
        elif score > existing.score or tier < existing.tier or sub_tier < existing.sub_tier:
            scored[node_id] = _ScoredNode(
                node_id=node_id,
                score=max(score, existing.score),
                tier=min(tier, existing.tier),
                reason=reason if score > existing.score else existing.reason,
                sub_tier=min(sub_tier, existing.sub_tier),
                kind_priority=min(kp, existing.kind_priority),
            )

    # --- Phase 0: Alias-based multi-word retrieval ---
    # For each alias phrase in the index, check if ALL its words appear
    # in the story terms (unordered).  This handles stories where related
    # words are separated by other terms, e.g., "rule ... exception"
    # matching the alias "rule exception".
    terms_lower = [t.lower() for t in terms]
    terms_lower_set: set[str] = set(terms_lower)

    # Build normalized term set (including plural/singular variants)
    terms_normalized_set: set[str] = set()
    for t in terms_lower_set:
        terms_normalized_set.update(_normalize_plural(t))

    _alias_matched_terms: set[str] = set()

    # Score each alias phrase by checking word containment
    for phrase, hits in idx.alias_to_nodes.items():
        phrase_words = phrase.split()
        if len(phrase_words) < 2:
            continue  # Single-word aliases handled separately below

        # Check if all phrase words appear in story terms (with normalization)
        all_present = all(
            w in terms_lower_set or w in terms_normalized_set
            for w in phrase_words
        )
        if not all_present:
            continue

        # Multi-word alias match — score the corresponding nodes
        for node_id, weight in hits:
            # Boost weight by number of matching words
            boosted = weight + len(phrase_words) * 3
            _upsert(node_id, boosted, _TIER_PINNED,
                     f"alias:{phrase}", _SUB_ENTITY_BRIDGE)
            # Track which terms were used
            for pw in phrase_words:
                for t in terms:
                    if t.lower() == pw or pw in _normalize_plural(t.lower()):
                        _alias_matched_terms.add(t)

    # Single-word alias matches — boost hub tables (high FK degree)
    for t in terms_lower:
        for v in _normalize_plural(t):
            hits = idx.alias_to_nodes.get(v, [])
            if not hits:
                continue
            # Compute FK degree for each hit node to identify hubs
            for node_id, weight in hits:
                node = idx.node_by_id.get(node_id)
                if node is None or node.kind not in _TABLE_KINDS:
                    continue
                fk_degree = len(idx.fk_neighbors_of(node_id))
                # Hub boost: tables with many FK connections get promoted
                # to PINNED tier if they have high connectivity (>= 5 FK)
                if fk_degree >= 5:
                    _upsert(node_id, weight,
                             _TIER_PINNED, f"alias_hub:{v}(fk={fk_degree})",
                             _SUB_FK_OF_EXACT)
                else:
                    _upsert(node_id, max(weight - 20, _SCORE_DOMAIN_PHRASE),
                             _TIER_DOMAIN, f"alias1:{v}", _SUB_FK_OF_EXACT)

    for term in terms:
        found = False

        # --- 1. Exact full identifier match (score 100) ---
        # Check against short names (the last segment of qualified_name)
        exact_nodes = idx.short_name_to_nodes.get(term, [])
        for node in exact_nodes:
            if node.kind in _TABLE_KINDS:
                _upsert(node.id, _SCORE_EXACT_IDENTIFIER, _TIER_PINNED,
                         f"exact_table:{term}", _SUB_EXACT_TABLE)
                found = True
            elif node.kind in _ENTITY_KINDS:
                _upsert(node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED,
                         f"exact_entity:{term}", _SUB_EXACT_ENTITY)
                found = True
            elif node.kind == NodeKind.COLUMN.value:
                # Column exact match — scored as FK/column neighbor level
                _upsert(node.id, _SCORE_FK_COLUMN_NEIGHBOR, _TIER_PINNED,
                         f"exact_column:{term}", _SUB_COL_OF_EXACT)
                found = True
            else:
                # Other node kinds (sequence, synonym, etc.)
                _upsert(node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED,
                         f"exact_other:{term}", _SUB_EXACT_ENTITY)
                found = True

        # Also check full qualified name exact match
        qn_node = idx.qname_upper_to_nodes.get(term)
        if qn_node is not None:
            if qn_node.kind in _TABLE_KINDS:
                _upsert(qn_node.id, _SCORE_EXACT_IDENTIFIER, _TIER_PINNED,
                         f"exact_qname_table:{term}", _SUB_EXACT_TABLE)
            elif qn_node.kind in _ENTITY_KINDS:
                _upsert(qn_node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED,
                         f"exact_qname_entity:{term}", _SUB_EXACT_ENTITY)
            else:
                _upsert(qn_node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED,
                         f"exact_qname_other:{term}", _SUB_EXACT_ENTITY)
            found = True

        # --- 2. Normalized domain phrase match (score 50) ---
        # The term appears as a complete segment within an underscore-delimited
        # qualified_name. E.g. term "FEATURE" matches "TB_GRP_PF_FEATURE"
        # because "FEATURE" is one of the underscore-delimited segments.
        # Also matches with plural/singular normalization.
        if not found:
            term_variants = _normalize_plural(term.lower())
            term_variants_upper = {v.upper() for v in term_variants}
            for node in idx.graph.nodes:
                qn_upper = node.qualified_name.upper()
                short_upper = qn_upper.rsplit(".", 1)[-1]
                # Split on underscores to get segments
                segments = short_upper.split("_")
                if term in segments or term_variants_upper.intersection(segments):
                    _upsert(node.id, _SCORE_DOMAIN_PHRASE, _TIER_DOMAIN,
                             f"domain_segment:{term}")
                    found = True

        # --- 3. Fuzzy/substring match (score 20, min 5 chars) ---
        if not found and len(term) >= _MIN_SUBSTRING_LENGTH:
            for node in idx.graph.nodes:
                qn_upper = node.qualified_name.upper()
                if term in qn_upper:
                    _upsert(node.id, _SCORE_FUZZY_SUBSTRING, _TIER_FUZZY,
                             f"substring:{term}")
                    found = True

        if found:
            matched_terms.append(term)
        else:
            unmatched_terms.append(term)

    # --- Fix 3B (Phase B/C): Entity→table bridging ---
    # For each JPA entity, count how many distinct story terms match its
    # camelCase words (with plural/singular normalization).
    #
    # Matching tiers:
    #   - Full entity name match → sub_tier _SUB_EXACT_ENTITY
    #   - ≥2 word hits           → sub_tier _SUB_ENTITY_BRIDGE
    #   - 1 word hit             → sub_tier _SUB_FK_OF_EXACT (lower priority,
    #                               evicted first when the 60-slot cap bites)
    #
    # Plural/singular normalization: "features" matches "feature", etc.
    terms_lower_set: set[str] = {t.lower() for t in terms}

    # Build a normalized set for plural/singular matching
    terms_normalized: set[str] = set()
    for t in terms_lower_set:
        terms_normalized.update(_normalize_plural(t))

    for entity_node in idx.entity_nodes:
        entity_short = entity_node.qualified_name.rsplit(".", 1)[-1]
        entity_upper = entity_short.upper()
        entity_words = _split_camel_case(entity_short)

        # Check full-name exact match first
        full_match = entity_upper.lower() in terms_lower_set

        if not full_match:
            # Count how many distinct camelCase words have a matching term
            # (with plural/singular normalization)
            word_hits = sum(
                1 for w in entity_words
                if w in terms_lower_set or w in terms_normalized
            )
            if word_hits < _ENTITY_BRIDGE_MIN_WORD_HITS:
                continue  # Not enough word overlap — skip
            # Determine sub-tier based on hit count
            if word_hits >= 3:
                bridge_sub_tier = _SUB_ENTITY_BRIDGE
            else:
                bridge_sub_tier = _SUB_ENTITY_BRIDGE
        else:
            bridge_sub_tier = _SUB_EXACT_ENTITY

        # Determine which term triggered the match (for matched_terms tracking)
        trigger_term: str | None = None
        for term in terms:
            tl = term.lower()
            if tl == entity_upper.lower() or tl in entity_words:
                trigger_term = term
                break
            # Check normalized forms
            for w in entity_words:
                if tl in _normalize_plural(w):
                    trigger_term = term
                    break
            if trigger_term:
                break

        # Score based on match quality
        bridge_score = _SCORE_EXACT_ENTITY if full_match else _SCORE_MAPS_TO_TARGET

        # Pin the entity
        _upsert(entity_node.id, bridge_score, _TIER_PINNED,
                 f"entity_bridge:{trigger_term or entity_short}",
                 bridge_sub_tier)

        # Follow MAPS_TO_TABLE to find and pin the target table
        target_id = idx.maps_to_target(entity_node.id)
        if target_id is not None:
            _upsert(target_id, _SCORE_MAPS_TO_TARGET, _TIER_PINNED,
                     f"entity_bridge_table:{entity_short}",
                     _SUB_EXACT_TABLE if full_match else bridge_sub_tier)

        # Mark trigger term as matched if not already
        if trigger_term and trigger_term not in matched_terms:
            matched_terms.append(trigger_term)
            if trigger_term in unmatched_terms:
                unmatched_terms.remove(trigger_term)

    # --- Fix 3B (cont): Column-name matching ---
    # For each term, check if it matches a column name; if so, include the
    # parent table.
    for term in terms:
        for node in idx.graph.nodes:
            if node.kind != NodeKind.COLUMN.value:
                continue
            col_short = node.qualified_name.rsplit(".", 1)[-1].upper()
            if term == col_short:
                # Pin the column
                _upsert(node.id, _SCORE_FK_COLUMN_NEIGHBOR, _TIER_DOMAIN,
                         f"column_match:{term}")
                # Find parent table via incoming HAS_COLUMN edge
                for edge in idx.edges_to(node.id, EdgeKind.HAS_COLUMN.value):
                    parent_id = edge.from_node
                    _upsert(parent_id, _SCORE_DOMAIN_PHRASE, _TIER_DOMAIN,
                             f"parent_of_matched_col:{term}")
                if term not in matched_terms:
                    matched_terms.append(term)
                    if term in unmatched_terms:
                        unmatched_terms.remove(term)

    # --- Phase C: Compound phrase matching ---
    # Generate 2-word and 3-word compounds from consecutive story terms
    # and match against consecutive underscore segments in table/view names.
    # E.g. ["SESSION", "INSTANCE"] → "SESSION_INSTANCE" matches
    # "TB_RT_SESSION_INSTANCE" because "SESSION" and "INSTANCE" are
    # consecutive segments.
    #
    # Also match with plural normalization: "REPORTING_PERIODS" matches
    # "REPORTING_PERIOD" etc.
    for window_size in (3, 2):  # prefer longer compounds
        for i in range(len(terms) - window_size + 1):
            compound_parts = terms[i:i + window_size]
            compound = "_".join(compound_parts)
            # Also generate normalized variants
            compound_variants = {compound}
            for j, part in enumerate(compound_parts):
                for variant in _normalize_plural(part.lower()):
                    alt_parts = list(compound_parts)
                    alt_parts[j] = variant.upper()
                    compound_variants.add("_".join(alt_parts))

            for node in idx.graph.nodes:
                if node.kind not in _TABLE_KINDS and node.kind != NodeKind.JAVA_ENTITY.value:
                    continue
                qn_upper = node.qualified_name.upper()
                short_upper = qn_upper.rsplit(".", 1)[-1]
                # Check if any compound variant appears as consecutive
                # segments in the short name
                for cv in compound_variants:
                    if cv in short_upper:
                        # Compound match — score higher than single segment
                        compound_score = _SCORE_FK_COLUMN_NEIGHBOR + window_size * 5
                        _upsert(node.id, compound_score, _TIER_PINNED,
                                 f"compound_phrase:{compound}",
                                 _SUB_ENTITY_BRIDGE)
                        for part in compound_parts:
                            if part not in matched_terms:
                                matched_terms.append(part)
                                if part in unmatched_terms:
                                    unmatched_terms.remove(part)
                        break

    # --- Phase D: Corpus-frequency concept coverage boost ---
    # Apply IDF-weighted multi-concept scoring.  Tables whose evidence
    # documents match multiple distinct story terms receive a bonus that
    # penalises generic terms (high doc-frequency → low IDF) and boosts
    # rare multi-concept matches.
    _apply_concept_coverage_boost(scored, terms, idx)

    return scored, matched_terms, unmatched_terms


# ---------------------------------------------------------------------------
# Pinning: exact matches + essential neighbourhood
# ---------------------------------------------------------------------------

def _pin_essential_neighbourhood(
    scored: dict[str, _ScoredNode],
    idx: _GraphIndex,
) -> set[str]:
    """Pin exact-matched nodes and their essential neighbourhood.

    For each exact-matched table (score >= 85):
      - Include its columns (HAS_COLUMN edges)
      - Include its FK edges (the target/source tables)

    For each exact-matched entity (score >= 90):
      - Include its MAPS_TO_TABLE target table
      - Include that table's columns and FK edges

    Returns the set of pinned node IDs. These are high priority during
    the hard-cap eviction but can be trimmed if the total exceeds
    max_objects.
    """
    pinned: set[str] = set()

    # Collect exact-matched table and entity IDs
    exact_table_ids: list[str] = []
    exact_entity_ids: list[str] = []

    for node_id, sn in scored.items():
        node = idx.node_by_id.get(node_id)
        if node is None:
            continue
        if sn.score >= _SCORE_MAPS_TO_TARGET:  # 85 — includes exact table and entity
            if node.kind in _TABLE_KINDS:
                exact_table_ids.append(node_id)
                pinned.add(node_id)
            elif node.kind in _ENTITY_KINDS:
                exact_entity_ids.append(node_id)
                pinned.add(node_id)
            elif node.kind == NodeKind.COLUMN.value:
                pinned.add(node_id)

    # For each entity: pin the MAPS_TO target table
    for ent_id in exact_entity_ids:
        target_table_id = idx.maps_to_target(ent_id)
        if target_table_id is not None:
            pinned.add(target_table_id)
            existing = scored.get(target_table_id)
            if existing is None or existing.tier > _TIER_PINNED or existing.sub_tier > _SUB_ENTITY_BRIDGE:
                scored[target_table_id] = _ScoredNode(
                    node_id=target_table_id,
                    score=max(_SCORE_MAPS_TO_TARGET, existing.score if existing else 0),
                    tier=_TIER_PINNED,
                    reason=f"maps_to_target_of:{ent_id}" if existing is None else existing.reason,
                    sub_tier=_SUB_ENTITY_BRIDGE,
                    kind_priority=0,  # table
                )
            exact_table_ids.append(target_table_id)

    # For each pinned table: pin columns and FK neighbors
    for tbl_id in exact_table_ids:
        # Columns
        for col_id in idx.columns_of(tbl_id):
            pinned.add(col_id)
            existing = scored.get(col_id)
            if existing is None or existing.tier > _TIER_PINNED or existing.sub_tier > _SUB_COL_OF_EXACT:
                scored[col_id] = _ScoredNode(
                    node_id=col_id,
                    score=max(_SCORE_FK_COLUMN_NEIGHBOR, existing.score if existing else 0),
                    tier=_TIER_PINNED,
                    reason=f"column_of_pinned:{tbl_id}" if existing is None else existing.reason,
                    sub_tier=_SUB_COL_OF_EXACT,
                    kind_priority=1,  # column
                )

        # FK neighbors — mark as pinned with FK_OF_EXACT sub-tier
        for neighbor_id, _fk_edge in idx.fk_neighbors_of(tbl_id):
            pinned.add(neighbor_id)
            existing = scored.get(neighbor_id)
            if existing is None or existing.tier > _TIER_PINNED or existing.sub_tier > _SUB_FK_OF_EXACT:
                _neighbor_node = idx.node_by_id.get(neighbor_id)
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=max(_SCORE_FK_COLUMN_NEIGHBOR, existing.score if existing else 0),
                    tier=_TIER_PINNED,
                    reason=f"fk_neighbor_of_pinned:{tbl_id}" if existing is None else existing.reason,
                    sub_tier=_SUB_FK_OF_EXACT,
                    kind_priority=0 if _neighbor_node and _neighbor_node.kind in _ANCHOR_KINDS else 1,
                )

    return pinned


# ---------------------------------------------------------------------------
# Tier 1/2 expansion: FK-connected tables and their columns
# ---------------------------------------------------------------------------

def _expand_fk_tiers(
    pinned: set[str],
    scored: dict[str, _ScoredNode],
    idx: _GraphIndex,
) -> None:
    """Expand connected tables of pinned nodes (tier 1) and their columns (tier 2).

    Expands via ALL relationship edge kinds (Fix 3C):
    - FOREIGN_KEY_TO
    - LOGICAL_REFERENCE_TO
    - JAVA_RELATION_TO
    - DERIVED_FROM (view dependencies)
    - READS_FROM
    - ALIAS_OF (synonyms)

    This does NOT add to the pinned set (those nodes CAN be capped).
    """
    # Edge kinds to traverse for expansion
    _EXPANSION_EDGE_KINDS: frozenset[str] = frozenset({
        EdgeKind.FOREIGN_KEY_TO.value,
        EdgeKind.LOGICAL_REFERENCE_TO.value,
        EdgeKind.JAVA_RELATION_TO.value,
        EdgeKind.DERIVED_FROM.value,
        EdgeKind.READS_FROM.value,
        EdgeKind.ALIAS_OF.value,
    })

    tier1_table_ids: list[str] = []

    for node_id in list(pinned):
        node = idx.node_by_id.get(node_id)
        if node is None or node.kind not in _TABLE_KINDS:
            continue
        # Expand via all relationship edge kinds (outgoing and incoming)
        for edge in idx.edges_from(node_id):
            if edge.kind not in _EXPANSION_EDGE_KINDS:
                continue
            neighbor_id = edge.to_node
            _nb = idx.node_by_id.get(neighbor_id)
            _nbkp = 0 if _nb and _nb.kind in _ANCHOR_KINDS else 1
            if neighbor_id not in scored:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_FK_CONNECTED,
                    reason=f"expand_{edge.kind}_from:{node_id}",
                    kind_priority=_nbkp,
                )
                tier1_table_ids.append(neighbor_id)
            elif scored[neighbor_id].tier > _TIER_FK_CONNECTED:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=max(scored[neighbor_id].score, _SCORE_FK_COLUMN_NEIGHBOR),
                    tier=_TIER_FK_CONNECTED,
                    reason=scored[neighbor_id].reason,
                    kind_priority=min(_nbkp, scored[neighbor_id].kind_priority),
                )

        for edge in idx.edges_to(node_id):
            if edge.kind not in _EXPANSION_EDGE_KINDS:
                continue
            neighbor_id = edge.from_node
            _nb = idx.node_by_id.get(neighbor_id)
            _nbkp = 0 if _nb and _nb.kind in _ANCHOR_KINDS else 1
            if neighbor_id not in scored:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_FK_CONNECTED,
                    reason=f"expand_{edge.kind}_to:{node_id}",
                    kind_priority=_nbkp,
                )
                tier1_table_ids.append(neighbor_id)
            elif scored[neighbor_id].tier > _TIER_FK_CONNECTED:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=max(scored[neighbor_id].score, _SCORE_FK_COLUMN_NEIGHBOR),
                    tier=_TIER_FK_CONNECTED,
                    reason=scored[neighbor_id].reason,
                    kind_priority=min(_nbkp, scored[neighbor_id].kind_priority),
                )

    # Tier 2: columns of tier-1 tables
    for tbl_id in tier1_table_ids:
        for col_id in idx.columns_of(tbl_id):
            if col_id not in scored:
                scored[col_id] = _ScoredNode(
                    node_id=col_id,
                    score=_SCORE_FUZZY_SUBSTRING,
                    tier=_TIER_FK_COLUMNS,
                    reason=f"col_of_tier1:{tbl_id}",
                    kind_priority=1,  # column
                )

    # Tier 1b: Name-based parent inference.
    # When a pinned table like TB_GRP_PR_AI_GR exists, infer that
    # TB_GRP_PR_AI might be the parent table by stripping the last
    # underscore segment. If the parent exists in the graph, promote it
    # to PINNED tier with FK_OF_EXACT sub-tier so it survives the budget.
    for node_id in list(pinned):
        node = idx.node_by_id.get(node_id)
        if node is None or node.kind not in _TABLE_KINDS:
            continue
        qn = node.qualified_name
        # Strip last segment to get potential parent
        parts = qn.split("_")
        if len(parts) >= 4:  # At least TB_PREFIX_NAME_CHILD
            parent_name = "_".join(parts[:-1])
            parent_nodes = idx.short_name_to_nodes.get(parent_name.upper(), [])
            for pn in parent_nodes:
                if pn.kind not in _TABLE_KINDS:
                    continue
                existing = scored.get(pn.id)
                # Promote to PINNED/FK_OF_EXACT — parent of a pinned child
                # is structurally important
                new_score = max(_SCORE_FK_COLUMN_NEIGHBOR,
                                existing.score if existing else 0)
                if existing is None or existing.tier > _TIER_PINNED or (
                    existing.tier == _TIER_PINNED and existing.sub_tier > _SUB_FK_OF_EXACT
                ):
                    scored[pn.id] = _ScoredNode(
                        node_id=pn.id,
                        score=new_score,
                        tier=_TIER_PINNED,
                        reason=f"name_parent_of:{node_id}",
                        sub_tier=_SUB_FK_OF_EXACT,
                        kind_priority=0,
                    )
                    pinned.add(pn.id)


# ---------------------------------------------------------------------------
# Edge collection — include ALL edges between selected nodes
# ---------------------------------------------------------------------------

def _collect_edges(
    graph: DatabaseGraph,
    selected_ids: set[str],
) -> list[DatabaseGraphEdge]:
    """Return ALL graph edges where both endpoints are in selected_ids."""
    return [
        e for e in graph.edges
        if e.from_node in selected_ids and e.to_node in selected_ids
    ]


# ---------------------------------------------------------------------------
# Context fingerprint
# ---------------------------------------------------------------------------

def _context_fingerprint(
    selected_nodes: tuple[DatabaseGraphNode, ...],
    selected_edges: tuple[DatabaseGraphEdge, ...],
    story_terms_matched: tuple[str, ...],
    story_terms_unmatched: tuple[str, ...],
    full_graph_fingerprint: str,
    max_hops: int,
    max_objects: int,
) -> str:
    """Compute a deterministic SHA-256 fingerprint for the bounded context."""
    payload = {
        "full_graph_fingerprint": full_graph_fingerprint,
        "max_hops": max_hops,
        "max_objects": max_objects,
        "selected_node_ids": sorted(n.id for n in selected_nodes),
        "selected_edge_ids": sorted(e.id for e in selected_edges),
        "story_terms_matched": list(story_terms_matched),
        "story_terms_unmatched": list(story_terms_unmatched),
    }
    return _sha256(payload)


# ---------------------------------------------------------------------------
# Main selector
# ---------------------------------------------------------------------------

def select_database_context(
    graph: DatabaseGraph,
    story_text: str,
    *,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_objects: int = _DEFAULT_MAX_OBJECTS,
) -> DatabaseContextResult:
    """Select a bounded relevant database subgraph for a story/impediment.

    This is the canonical public entry point. It uses evidence-backed bundle
    selection (SelectionBundle) to produce bounded, reproducible context with
    explicit uncertainty tracking.

    The implementation:
    1. Builds candidate bundles for all tables with story evidence
    2. Scores bundles by concept coverage, confidence, and evidence strength
    3. Selects anchors first (high-confidence, multi-concept tables)
    4. Adds bridge bundles connecting selected anchors
    5. Enforces family limits to prevent prefix flooding
    6. Evicts lowest-marginal-benefit bundles atomically under budget
    7. Detects and tracks unresolved evidence (dynamic synonyms, schema fallbacks)

    The `selection_strategy` field in the result identifies the algorithm used,
    enabling tests to verify which implementation ran.

    Args:
        graph: The full reconciled DatabaseGraph.
        story_text: Free-text story or impediment description.
        max_hops: Maximum BFS expansion depth (kept for API compat).
        max_objects: Maximum number of nodes in the result.

    Returns:
        A frozen DatabaseContextResult with bounded subgraph and uncertainties.
    """
    from .bundle_selector import build_and_select_bundles

    if max_hops < 0:
        raise ValueError(f"max_hops must be >= 0, got {max_hops}")
    if max_objects < 1:
        raise ValueError(f"max_objects must be >= 1, got {max_objects}")

    # Run bundle selection
    bundle_result = build_and_select_bundles(
        graph, story_text,
        max_objects=max_objects,
        max_per_family=2,
    )

    # Build node index
    node_by_id = {n.id: n for n in graph.nodes}

    # Collect selected node IDs from bundles
    selected_ids: set[str] = set()
    for bundle in bundle_result.selected_bundles:
        selected_ids.add(bundle.table_id)
        # Include entity node if present (for MAPS_TO_TABLE edge preservation)
        if bundle.entity_id:
            selected_ids.add(bundle.entity_id)
        for col in bundle.columns:
            selected_ids.add(col.column_id)

    # FK column closure: when FK edges would be selected, ensure their columns fit
    # If adding FK columns would exceed budget, DON'T include the FK edge
    # First, identify candidate FK edges (both endpoints selected)
    candidate_fk_edges: list[tuple[DatabaseGraphEdge, str | None, str | None]] = []  # (edge, src_col_id, tgt_col_id)
    
    for edge in graph.edges:
        if edge.kind != EdgeKind.FOREIGN_KEY_TO.value:
            continue
        if edge.from_node not in selected_ids or edge.to_node not in selected_ids:
            continue
        
        props = dict(edge.properties)
        src_tbl = props.get("source_table")
        src_col = props.get("source_column")
        tgt_tbl = props.get("target_table")
        tgt_col = props.get("target_column")
        
        src_col_id: str | None = None
        tgt_col_id: str | None = None
        
        if src_tbl and src_col:
            src_col_name = f"{src_tbl}.{src_col}"
            for node in graph.nodes:
                if node.qualified_name == src_col_name and node.kind == NodeKind.COLUMN.value:
                    src_col_id = node.id
                    break
        
        if tgt_tbl and tgt_col:
            tgt_col_name = f"{tgt_tbl}.{tgt_col}"
            for node in graph.nodes:
                if node.qualified_name == tgt_col_name and node.kind == NodeKind.COLUMN.value:
                    tgt_col_id = node.id
                    break
        
        candidate_fk_edges.append((edge, src_col_id, tgt_col_id))
    
    # Now add FK columns respecting the budget
    # Count how many new nodes we'd add
    current_node_count = len(selected_ids)
    fk_columns_to_add: set[str] = set()
    
    for edge, src_col_id, tgt_col_id in candidate_fk_edges:
        new_cols: set[str] = set()
        if src_col_id and src_col_id not in selected_ids:
            new_cols.add(src_col_id)
        if tgt_col_id and tgt_col_id not in selected_ids:
            new_cols.add(tgt_col_id)
        
        # Check if adding these columns would exceed budget
        projected_count = current_node_count + len(fk_columns_to_add) + len(new_cols)
        if projected_count <= max_objects:
            fk_columns_to_add.update(new_cols)
        # else: skip this FK edge's columns (edge won't be selected)
    
    selected_ids.update(fk_columns_to_add)

    # Collect edges between selected nodes (final pass)
    selected_edges_list = [
        e for e in graph.edges
        if e.from_node in selected_ids and e.to_node in selected_ids
    ]

    # Build final node list
    selected_node_list = [
        node_by_id[nid] for nid in selected_ids
        if nid in node_by_id
    ]

    # Sort for deterministic output
    selected_nodes = tuple(sorted(selected_node_list, key=lambda n: n.qualified_name))
    selected_edges = tuple(
        sorted(selected_edges_list, key=lambda e: (e.from_node, e.to_node, e.kind))
    )

    # Extract story terms for reporting
    raw_terms = _extract_terms(story_text)
    terms = [t for t in raw_terms if t.lower() not in _ENGLISH_STOP_WORDS]

    # Determine matched vs unmatched terms
    matched_terms: list[str] = []
    unmatched_terms: list[str] = []
    matched_set: set[str] = set()

    for bundle in bundle_result.selected_bundles:
        for term in bundle.story_terms_matched:
            matched_set.add(term.upper())

    for term in terms:
        if term.upper() in matched_set:
            matched_terms.append(term)
        else:
            unmatched_terms.append(term)

    # Compute omitted counts
    total_candidate_objects = sum(
        b.object_cost for b in bundle_result.selected_bundles
    ) + sum(
        b.object_cost for b in bundle_result.evicted_bundles
    )

    omitted = OmittedCounts(
        nodes_omitted=total_candidate_objects - len(selected_ids),
        edges_omitted=0,
        total_candidate_nodes=total_candidate_objects,
        total_candidate_edges=len(graph.edges),
    )

    # Build truncation metadata
    truncation = TruncationMetadata(
        was_truncated=len(bundle_result.evicted_bundles) > 0,
        hard_cap=max_objects,
        total_candidates=total_candidate_objects,
        total_selected=len(selected_ids),
        tier_details=(),
        pinned_evicted=0,
    )

    # Collect uncertainties from the graph
    # Check for dynamic synonyms, schema-qualified references, and budget omission
    evicted_names = [b.table_name for b in bundle_result.evicted_bundles]
    uncertainties = _collect_selection_uncertainties(
        graph, story_text, selected_ids, node_by_id,
        evicted_bundle_names=evicted_names if len(bundle_result.evicted_bundles) > 0 else None,
        was_truncated=truncation.was_truncated,
    )

    # Compute context fingerprint
    ctx_fp = _context_fingerprint(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=tuple(matched_terms),
        story_terms_unmatched=tuple(unmatched_terms),
        full_graph_fingerprint=graph.fingerprint,
        max_hops=max_hops,
        max_objects=max_objects,
    )

    return DatabaseContextResult(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=tuple(matched_terms),
        story_terms_unmatched=tuple(unmatched_terms),
        omitted_counts=omitted,
        full_graph_fingerprint=graph.fingerprint,
        context_fingerprint=ctx_fp,
        max_hops=max_hops,
        max_objects=max_objects,
        truncation=truncation,
        selection_strategy=SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1,
        uncertainties=tuple(uncertainties),
    )


def _collect_selection_uncertainties(
    graph: DatabaseGraph,
    story_text: str,
    selected_ids: set[str],
    node_by_id: dict[str, DatabaseGraphNode],
    *,
    evicted_bundle_names: list[str] | None = None,
    was_truncated: bool = False,
) -> list[SelectionUncertainty]:
    """Collect uncertainties from the graph and story analysis.
    
    STEP 6: Comprehensive uncertainty detection.
    
    Detects:
    - Dynamic synonyms (runtime-generated, target unproven)
    - Schema-qualified references to non-native schemas
    - Objects with incomplete/inferred evidence
    - Budget omission when relevant tables are evicted
    - Unresolved entity mappings
    """
    uncertainties: list[SelectionUncertainty] = []
    story_upper = story_text.upper()
    
    # Detect schema-qualified references like CONSUMER.TB_GRP_PF
    _SCHEMA_QUAL_RE = re.compile(r'\b([A-Z][A-Z0-9_]+)\.([A-Z][A-Z0-9_]+)\b')
    _NATIVE_SCHEMAS = {"SYGMA", ""}
    
    for m in _SCHEMA_QUAL_RE.finditer(story_upper):
        schema, table = m.group(1), m.group(2)
        # Skip common false positives
        if schema in ('E', 'I', 'A', 'THE', 'REQ'):
            continue
        # If schema is not native and mentions "dynamic" or "synonym" in story
        if schema not in _NATIVE_SCHEMAS:
            if 'dynamic' in story_text.lower() and 'synonym' in story_text.lower():
                # Check if there are any dynamic synonyms in the graph
                has_dynamic = False
                for node in graph.nodes:
                    if node.kind == NodeKind.SYNONYM.value:
                        if (
                            node.get_property("dynamic") is True
                            or node.get_property("generated") is True
                            or node.get_property("runtime_dependent") in (True, "true", "True")
                        ):
                            has_dynamic = True
                            break
                
                if has_dynamic:
                    obj_name = f"DYNAMIC:ALL_{schema}_OBJECTS"
                    uncertainties.append(SelectionUncertainty(
                        code="DYNAMIC_SYNONYM_TARGET_UNPROVEN",
                        object_id=f"dynamic_synonym_{schema}",
                        object_name=obj_name,
                        reason=(
                            f"Schema '{schema}' synonym references require a dynamic "
                            f"runtime generator whose execution is unproven"
                        ),
                        evidence_source="story_extraction",
                        source_revision=graph.fingerprint,
                        resolved=False,
                    ))
    
    # Check for dynamic synonym nodes in the selected context
    for node_id in selected_ids:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        
        if node.kind == NodeKind.SYNONYM.value:
            is_dynamic = (
                node.get_property("dynamic") is True
                or node.get_property("generated") is True
                or node.get_property("runtime_dependent") in (True, "true", "True")
            )
            if is_dynamic:
                uncertainties.append(SelectionUncertainty(
                    code="DYNAMIC_SYNONYM_TARGET_UNPROVEN",
                    object_id=node_id,
                    object_name=node.qualified_name,
                    reason=(
                        f"Synonym '{node.qualified_name}' is dynamic/generated; "
                        f"target may not be stable at runtime"
                    ),
                    evidence_source="graph_node_property",
                    source_revision=graph.fingerprint,
                    resolved=False,
                ))
    
    # STEP 6: Check for incomplete/inferred evidence in selected nodes
    for node_id in selected_ids:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        
        # Check evidence status (if available)
        if node.evidence is not None:
            status = getattr(node.evidence, 'status', None)
            if status == 'inferred':
                uncertainties.append(SelectionUncertainty(
                    code="EVIDENCE_INFERRED",
                    object_id=node_id,
                    object_name=node.qualified_name,
                    reason=(
                        f"Object '{node.qualified_name}' has inferred evidence only; "
                        f"not verified by authoritative source"
                    ),
                    evidence_source="graph_node_evidence",
                    source_revision=graph.fingerprint,
                    resolved=True,  # Included despite uncertainty
                ))
    
    # STEP 6: Record budget omission if tables were evicted due to truncation
    if was_truncated and evicted_bundle_names:
        # Only report up to 5 evicted tables to avoid noise
        evicted_sample = evicted_bundle_names[:5]
        more_count = len(evicted_bundle_names) - 5 if len(evicted_bundle_names) > 5 else 0
        
        reason = f"Budget exceeded; {len(evicted_bundle_names)} tables evicted"
        if more_count > 0:
            reason += f" (showing 5: {', '.join(evicted_sample)}; and {more_count} more)"
        else:
            reason += f": {', '.join(evicted_sample)}"
        
        uncertainties.append(SelectionUncertainty(
            code="BUDGET_OMISSION",
            object_id="budget_truncation",
            object_name="TRUNCATED_TABLES",
            reason=reason,
            evidence_source="bundle_selection",
            source_revision=graph.fingerprint,
            resolved=True,  # Context is complete within budget
        ))
    
    # NOTE: VIEW_SEMANTIC_FILTERING and BACKUP_CLASSIFICATION_UNPROVEN
    # uncertainties were removed because:
    # 1. Story text alone cannot prove a semantic uncertainty
    # 2. View-name patterns (FAILED, PENDING) don't prove SQL filtering semantics
    # 3. Uncertainty text must derive from repository evidence, not pack expectations
    #
    # Uncertainties require authoritative repository evidence:
    # - Schema analysis proving actual filter predicates
    # - Migration evidence proving column semantics
    # - Constraint definitions proving referential behavior
    #
    # Without such evidence, we report no uncertainty rather than fabricate one.
    
    return uncertainties


# ---------------------------------------------------------------------------
# Legacy selector (preserved for comparison/debugging)
# ---------------------------------------------------------------------------

def _select_database_context_legacy(
    graph: DatabaseGraph,
    story_text: str,
    *,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_objects: int = _DEFAULT_MAX_OBJECTS,
) -> DatabaseContextResult:
    """Legacy selector using neighbourhood expansion.

    This is the original implementation preserved for comparison and debugging.
    It is NOT called by the public entry point.

    Algorithm:
    1. Build a pre-computed graph index.
    2. Extract and filter domain terms from story_text.
       Detect schema-qualified references and dynamic synonym patterns.
    3. Score nodes against terms with a weighted system.
    4. Pin exact matches and their essential neighbourhood.
    5. Expand FK tiers (tier 1: FK-connected tables, tier 2: their columns).
       Resolve schema-qualified and dynamic synonym nodes.
       Multi-hop BFS expansion for transitive FK reachability.
       Name-based parent inference for hierarchical table naming.
    6. Enforce hard cap at max_objects using three-stage budget allocation:
       Stage 1: grounded tables/views/entities (must-have).
       Stage 2: bridge and FK-connected structural nodes.
       Stage 3: columns of selected tables, owned first.
    7. Include ALL edges between selected nodes.
    8. Compute a deterministic context fingerprint.

    The hard cap is enforced on the total selected set.  When pinned
    nodes alone exceed max_objects, deterministic priority eviction
    removes the lowest-priority pinned nodes first (columns of pinned
    tables, then FK neighbors, then entity-bridged tables) while
    preserving directly-mentioned tables and entities.

    Args:
        graph: The full reconciled DatabaseGraph.
        story_text: Free-text story or impediment description.
        max_hops: Maximum BFS expansion depth (kept for API compat).
        max_objects: Maximum number of nodes in the result.

    Returns:
        A frozen DatabaseContextResult with the bounded subgraph.
    """
    if max_hops < 0:
        raise ValueError(f"max_hops must be >= 0, got {max_hops}")
    if max_objects < 1:
        raise ValueError(f"max_objects must be >= 1, got {max_objects}")

    # 1. Build graph index
    idx = _GraphIndex(graph)

    # 2. Extract terms and filter stop-words (graph-aware)
    #    Multi-anchor discovery (Fix 3): combine multiple extraction strategies
    raw_terms = _extract_terms(story_text)
    db_patterns = _extract_database_patterns(story_text)
    sql_refs = _extract_sql_table_references(story_text)

    # Merge all extracted terms, deduplicating while preserving order
    seen_terms: set[str] = set(raw_terms)
    all_raw_terms = list(raw_terms)
    for t in db_patterns:
        if t not in seen_terms:
            seen_terms.add(t)
            all_raw_terms.append(t)
    for t in sql_refs:
        if t not in seen_terms:
            seen_terms.add(t)
            all_raw_terms.append(t)

    terms = _filter_stop_words(all_raw_terms, idx)

    # --- Schema-qualified object resolution ---
    # Detect SCHEMA.TABLE patterns (dot notation) in the story text.
    _SCHEMA_QUAL_RE = re.compile(r'\b([A-Z][A-Z0-9_]+)\.([A-Z][A-Z0-9_]+)\b')
    schema_qualified_refs: list[tuple[str, str]] = []  # (schema, table)
    for m in _SCHEMA_QUAL_RE.finditer(story_text.upper()):
        schema, table = m.group(1), m.group(2)
        if schema in ('E', 'I', 'A', 'THE', 'REQ'):
            continue
        schema_qualified_refs.append((schema, table))

    # Also detect "<SCHEMA>-qualified" or "verified <SCHEMA>" patterns.
    _SCHEMA_QUAL_ADJ_RE = re.compile(
        r'\b([A-Z][A-Z0-9_]{2,})[-\s]qualified\b', re.IGNORECASE
    )
    _detected_schemas: set[str] = set()
    for m in _SCHEMA_QUAL_ADJ_RE.finditer(story_text):
        _detected_schemas.add(m.group(1).upper())

    # If we detected a schema like "SYGMA" but no dot-qualified ref,
    # try to find tables/views mentioned in the story that match graph nodes.
    for ds in _detected_schemas:
        if not any(s == ds for s, _ in schema_qualified_refs):
            # Look for any table-like name patterns in the story terms
            _found_table = False
            for t_term in terms:
                t_nodes = idx.short_name_to_nodes.get(t_term, [])
                for tn in t_nodes:
                    if tn.kind in _TABLE_KINDS:
                        schema_qualified_refs.append((ds, t_term))
                        _found_table = True
                        break
                if _found_table:
                    break
            if not _found_table:
                # Use any table with the schema name as a segment in its name
                for node in idx.table_nodes:
                    short = node.qualified_name.rsplit(".", 1)[-1].upper()
                    if ds in short.split("_"):
                        schema_qualified_refs.append((ds, short))
                        break

    # --- Dynamic synonym detection ---
    dynamic_synonym_refs: list[str] = []  # placeholder names
    story_lower = story_text.lower()
    if 'dynamic' in story_lower and 'synonym' in story_lower:
        # Extract schema names from qualified refs or detected schemas
        _all_schemas = {s for s, _ in schema_qualified_refs} | _detected_schemas
        for schema in sorted(_all_schemas):
            dynamic_synonym_refs.append(f"DYNAMIC:ALL_{schema}_OBJECTS")

    # 3. Score nodes against terms
    scored, matched_terms, unmatched_terms = _score_and_match(terms, idx)

    # 4. Pin exact matches + essential neighbourhood
    pinned = _pin_essential_neighbourhood(scored, idx)

    # 5. Expand FK tiers
    _expand_fk_tiers(pinned, scored, idx)

    # 5a. Resolve schema-qualified references into scored nodes.
    #     Create synthetic schema-qualified nodes for the bounded context.
    _synthetic_nodes: list[DatabaseGraphNode] = []
    for schema, table in schema_qualified_refs:
        # Try exact match on the unqualified table name
        table_nodes = idx.short_name_to_nodes.get(table, [])
        for tn in table_nodes:
            if tn.kind in _TABLE_KINDS:
                # Pin the unqualified table
                existing = scored.get(tn.id)
                if existing is None or existing.score < _SCORE_EXACT_IDENTIFIER:
                    scored[tn.id] = _ScoredNode(
                        node_id=tn.id,
                        score=_SCORE_EXACT_IDENTIFIER,
                        tier=_TIER_PINNED,
                        reason=f"schema_qual:{schema}.{table}",
                        sub_tier=_SUB_EXACT_TABLE,
                        kind_priority=0,
                    )
                    pinned.add(tn.id)

                # Create a synthetic schema-qualified node
                sq_id = f"{schema.lower()}.{tn.id}"
                sq_qn = f"{schema}.{table}"
                _synthetic_nodes.append(DatabaseGraphNode(
                    id=sq_id,
                    kind=tn.kind,
                    qualified_name=sq_qn,
                    schema=schema,
                    evidence=tn.evidence,
                    properties=tn.properties,
                ))
                scored[sq_id] = _ScoredNode(
                    node_id=sq_id,
                    score=_SCORE_EXACT_IDENTIFIER,
                    tier=_TIER_PINNED,
                    reason=f"schema_qualified:{sq_qn}",
                    sub_tier=_SUB_EXACT_TABLE,
                    kind_priority=0,
                )
                pinned.add(sq_id)
                break  # Only first matching table

    # 5b. Create dynamic synonym placeholder nodes.
    for dyn_ref in dynamic_synonym_refs:
        dyn_id = dyn_ref.lower().replace(":", "_").replace(" ", "_")
        _synthetic_nodes.append(DatabaseGraphNode(
            id=dyn_id,
            kind=NodeKind.SYNONYM.value,
            qualified_name=dyn_ref,
            evidence=EvidenceRecord(
                status="unknown",
                confidence=0.0,
            ),
        ))
        scored[dyn_id] = _ScoredNode(
            node_id=dyn_id,
            score=_SCORE_EXACT_ENTITY,
            tier=_TIER_PINNED,
            reason=f"dynamic_synonym:{dyn_ref}",
            sub_tier=_SUB_EXACT_ENTITY,
            kind_priority=0,
        )
        pinned.add(dyn_id)

    # 5c. Multi-hop BFS expansion (bounded).
    #     Extend FK reachability from ALL pinned table/view nodes (not just
    #     tier-1 FK nodes) up to min(2, max_hops) hops.  Each hop follows
    #     relationship edge kinds and fan-out is capped at 8 per node to
    #     prevent explosion from high-degree hub tables.
    _BFS_EDGE_KINDS: frozenset[str] = frozenset({
        EdgeKind.FOREIGN_KEY_TO.value,
        EdgeKind.LOGICAL_REFERENCE_TO.value,
        EdgeKind.JAVA_RELATION_TO.value,
        EdgeKind.DERIVED_FROM.value,
        EdgeKind.READS_FROM.value,
    })

    _BFS_MAX_FANOUT: int = 8

    # Seed the BFS frontier with ALL pinned table/view nodes
    bfs_frontier: set[str] = set()
    for sn in list(scored.values()):
        if sn.tier <= _TIER_PINNED or sn.tier == _TIER_FK_CONNECTED:
            node = idx.node_by_id.get(sn.node_id)
            if node and node.kind in _TABLE_KINDS:
                bfs_frontier.add(sn.node_id)

    bfs_visited: set[str] = set(scored.keys())
    bfs_depth = min(2, max_hops)
    for _hop in range(bfs_depth):
        if not bfs_frontier:
            break
        next_frontier: set[str] = set()
        # Tier decreases with each hop: first hop → FK_CONNECTED, deeper → FK_COLUMNS
        hop_tier = _TIER_FK_CONNECTED if _hop == 0 else _TIER_FK_COLUMNS
        hop_score = _SCORE_FK_COLUMN_NEIGHBOR if _hop == 0 else _SCORE_FUZZY_SUBSTRING
        for src_id in bfs_frontier:
            # Collect candidate neighbors (outgoing + incoming), cap fan-out
            candidates: list[tuple[str, str]] = []  # (neighbor_id, reason_dir)
            for edge in idx.edges_from(src_id):
                if edge.kind not in _BFS_EDGE_KINDS:
                    continue
                if edge.to_node not in bfs_visited:
                    candidates.append((edge.to_node, "from"))
            for edge in idx.edges_to(src_id):
                if edge.kind not in _BFS_EDGE_KINDS:
                    continue
                if edge.from_node not in bfs_visited:
                    candidates.append((edge.from_node, "to"))
            # Cap fan-out per node
            for nb_id, direction in candidates[:_BFS_MAX_FANOUT]:
                nb_node = idx.node_by_id.get(nb_id)
                if nb_node is None:
                    continue
                nbkp = 0 if nb_node.kind in _ANCHOR_KINDS else 1
                scored[nb_id] = _ScoredNode(
                    node_id=nb_id,
                    score=hop_score,
                    tier=hop_tier,
                    reason=f"bfs_hop{_hop + 1}_{direction}:{src_id}",
                    kind_priority=nbkp,
                )
                bfs_visited.add(nb_id)
                if nb_node.kind in _TABLE_KINDS:
                    next_frontier.add(nb_id)
        bfs_frontier = next_frontier

    # 5d. Boost story-relevant FK expansion nodes.
    #     If a node was matched by alias (any tier) AND is an FK/expansion
    #     neighbor of a pinned table, promote it to PINNED tier with
    #     FK_OF_EXACT sub-tier.  This ensures that story-mentioned objects
    #     that are also structurally connected survive the budget cap.
    _alias_scored_ids = {sn.node_id for sn in scored.values()
                         if sn.reason.startswith("alias:") or sn.reason.startswith("alias1:")}
    for node_id in list(_alias_scored_ids):
        sn = scored.get(node_id)
        if sn is None or sn.tier <= _TIER_PINNED:
            continue  # Already pinned
        # Check if this node is an FK neighbor of any pinned table
        node = idx.node_by_id.get(node_id)
        if node is None or node.kind not in _TABLE_KINDS:
            continue
        is_fk_of_pinned = False
        for p_id in pinned:
            p_node = idx.node_by_id.get(p_id)
            if p_node is None or p_node.kind not in _TABLE_KINDS:
                continue
            for neighbor_id, _ in idx.fk_neighbors_of(p_id):
                if neighbor_id == node_id:
                    is_fk_of_pinned = True
                    break
            if is_fk_of_pinned:
                break
        if is_fk_of_pinned:
            scored[node_id] = _ScoredNode(
                node_id=node_id,
                score=max(sn.score, _SCORE_FK_COLUMN_NEIGHBOR),
                tier=_TIER_PINNED,
                reason=sn.reason,
                sub_tier=_SUB_FK_OF_EXACT,
                kind_priority=0,
            )
            pinned.add(node_id)

    # 6. Hard cap at max_objects — tiered budget allocation.
    #
    #    The budget is split dynamically between structural objects
    #    (tables/views/entities) and their columns, ensuring that
    #    every selected table gets its required columns included.
    #
    #    Phase A: Count high-priority structural objects and estimate
    #             how many columns they need.
    #    Phase B: Cap structural objects so that columns of
    #             directly-mentioned tables always fit.
    #    Phase C: Fill remaining slots with columns, prioritising
    #             columns of the highest-priority tables.

    total_candidate_nodes = len(scored)

    # Separate scored nodes by category
    exact_structural = []   # sub_tier <= SUB_EXACT_ENTITY: directly mentioned
    bridge_structural = []  # sub_tier == SUB_ENTITY_BRIDGE: entity-bridged
    fk_structural = []      # sub_tier == SUB_FK_OF_EXACT or tier FK_CONNECTED
    other_structural = []   # tier >= DOMAIN, non-column
    column_entries = []

    for sn in scored.values():
        if sn.kind_priority == 1:  # column
            column_entries.append(sn)
        elif sn.tier == _TIER_PINNED and sn.sub_tier <= _SUB_EXACT_ENTITY:
            exact_structural.append(sn)
        elif sn.tier == _TIER_PINNED and sn.sub_tier == _SUB_ENTITY_BRIDGE:
            bridge_structural.append(sn)
        elif sn.tier == _TIER_PINNED and sn.sub_tier == _SUB_FK_OF_EXACT:
            # Direct FK neighbors of exact-matched tables get bridge priority
            bridge_structural.append(sn)
        elif sn.tier <= _TIER_FK_CONNECTED:
            fk_structural.append(sn)
        else:
            other_structural.append(sn)

    exact_structural.sort(key=lambda s: s.sort_key())
    bridge_structural.sort(key=lambda s: s.sort_key())
    fk_structural.sort(key=lambda s: s.sort_key())
    other_structural.sort(key=lambda s: s.sort_key())
    column_entries.sort(key=lambda s: s.sort_key())

    # Prefix-family diversity: suppress large families in non-exact categories
    # so that e.g. 256 TB_GRP_PR_* tables don't consume all structural slots.
    # exact_structural is NOT filtered — directly mentioned items must survive.
    bridge_structural = _apply_prefix_diversity(bridge_structural, idx)
    fk_structural = _apply_prefix_diversity(fk_structural, idx)
    other_structural = _apply_prefix_diversity(other_structural, idx)

    # Phase A: Determine how many structural objects to keep.
    # For every selected table, we want to include ~5 columns.
    # So with max_objects=60, if we have 10 tables we want ~50 columns.
    # But we must guarantee at least the directly-mentioned tables.
    n_exact = len(exact_structural)
    n_bridge = len(bridge_structural)
    n_all_structural = n_exact + n_bridge + len(fk_structural) + len(other_structural)

    # Estimate column demand: count distinct table parents across all tiers
    _parent_ids_exact: set[str] = set()
    for sn in exact_structural + bridge_structural + fk_structural + other_structural:
        nd = idx.node_by_id.get(sn.node_id)
        if nd and nd.kind in _TABLE_KINDS:
            _parent_ids_exact.add(sn.node_id)

    # Each table needs ~5 columns; cap column demand to available columns
    est_col_demand = min(len(_parent_ids_exact) * 5, len(column_entries))
    n_high_priority_tables = len(_parent_ids_exact)

    target_structural = min(
        max_objects - min(est_col_demand, int(max_objects * 0.75)),
        n_all_structural,
    )
    target_structural = max(target_structural, n_exact)
    # Dynamic structural cap based on column demand
    if column_entries:
        # With many tables needing columns, use only 40% for structural
        if n_high_priority_tables >= 5:
            max_pct = 0.35
        elif n_high_priority_tables >= 3:
            max_pct = 0.40
        else:
            max_pct = 0.55
        target_structural = min(target_structural, int(max_objects * max_pct))
    else:
        target_structural = min(target_structural, max_objects)
    # Always at least the exact count
    target_structural = max(target_structural, min(n_exact + n_bridge, max_objects))
    # If everything fits, keep all structural items
    if n_all_structural + len(column_entries) <= max_objects:
        target_structural = n_all_structural

    # Phase B: Fill structural slots in priority order
    kept: list[_ScoredNode] = []
    remaining = target_structural

    # B1: exact structural (directly mentioned)
    kept.extend(exact_structural[:remaining])
    remaining = target_structural - len(kept)

    # B2: entity-bridged structural
    if remaining > 0:
        kept.extend(bridge_structural[:remaining])
        remaining = target_structural - len(kept)

    # B3: FK-connected structural
    if remaining > 0:
        kept.extend(fk_structural[:remaining])
        remaining = target_structural - len(kept)

    # B4: other structural (domain/fuzzy matches)
    if remaining > 0:
        kept.extend(other_structural[:remaining])

    # Phase C: Fill remaining budget with columns, distributed proportionally.
    #
    # Strategy: Distribute column slots evenly across all selected tables
    # so every table gets some columns rather than the first few tables
    # consuming all column slots.
    remaining = max_objects - len(kept)
    selected_table_ids = {sn.node_id for sn in kept if sn.kind_priority == 0}

    # Ensure columns of ALL selected tables/views are available as candidates.
    # Some columns may not have been scored (e.g., columns of alias-matched
    # views that were only added during FK expansion).
    for tid in list(selected_table_ids):
        for col_id in idx.columns_of(tid):
            if col_id not in scored:
                scored[col_id] = _ScoredNode(
                    node_id=col_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_FK_COLUMNS,
                    reason=f"col_of_selected:{tid}",
                    kind_priority=1,
                )
                column_entries.append(scored[col_id])

    # Build column-to-parent mapping
    col_by_parent: dict[str, list[_ScoredNode]] = {}
    orphan_cols: list[_ScoredNode] = []
    for cn in column_entries:
        parent_id: str | None = None
        for edge in idx.edges_to(cn.node_id, EdgeKind.HAS_COLUMN.value):
            if edge.from_node in selected_table_ids:
                parent_id = edge.from_node
                break
        if parent_id:
            col_by_parent.setdefault(parent_id, []).append(cn)
        else:
            orphan_cols.append(cn)

    # Sort parents by structural priority (exact tables first, then bridge, then FK)
    parent_priority: dict[str, tuple] = {}
    for sn in kept:
        if sn.node_id in col_by_parent:
            parent_priority[sn.node_id] = sn.sort_key()
    sorted_parents = sorted(col_by_parent.keys(),
                            key=lambda pid: parent_priority.get(pid, (99, 99, 99, 0, 0, "")))

    # Within each parent, re-sort columns to prioritize:
    # 1. ID column (always structurally important)
    # 2. FK reference columns (ending in _ID) — story-matched first
    # 3. Story-grounded columns (segments match story terms)
    # 4. PK/version columns
    # 5. Everything else — story-matched first within this tier
    _PK_FK_PATTERNS = {"ID", "PK", "ROW_VERSION"}
    _story_terms_upper: set[str] = set(terms)  # terms from earlier extraction
    for pid in col_by_parent:
        cols = col_by_parent[pid]
        def _col_priority(sn: _ScoredNode) -> tuple:
            nd = idx.node_by_id.get(sn.node_id)
            if nd:
                short = nd.qualified_name.rsplit(".", 1)[-1].upper()
                segments = set(short.split("_"))
                story_match = 0 if (segments & _story_terms_upper) else 1
                # ID column
                if short == "ID":
                    return (0, story_match, sn.sort_key())
                # FK column (ends in _ID)
                if short.endswith("_ID") and short != "ID":
                    return (1, story_match, sn.sort_key())
                # PK/version
                if short in _PK_FK_PATTERNS:
                    return (2, story_match, sn.sort_key())
                # Other — story-matched columns come before non-matched
                return (3, story_match, sn.sort_key())
            return (4, 1, sn.sort_key())
        col_by_parent[pid] = sorted(cols, key=_col_priority)

    # Count total columns needed to include ALL columns of all parents
    total_all_cols = sum(len(cols) for cols in col_by_parent.values())

    if total_all_cols <= remaining:
        # All columns fit — include everything
        for pid in sorted_parents:
            kept.extend(col_by_parent[pid])
        remaining = max_objects - len(kept)
        # Fill remaining with orphan columns
        if remaining > 0:
            kept.extend(orphan_cols[:remaining])
    else:
        # Not all columns fit — hybrid distribution:
        # Phase 1: Give exact-tier parents ALL their columns (they are
        #          the primary story-grounded tables).
        # Phase 2: Distribute remaining to other parents fairly.
        # Phase 3: Extras go to highest-priority parents.
        _MAX_COL_PARENTS = 8
        active_parents = sorted_parents[:_MAX_COL_PARENTS]

        # Identify high-priority parents (exact or entity-bridge tier)
        exact_parent_ids = set()
        for sn in kept:
            if sn.kind_priority == 0 and sn.tier == _TIER_PINNED and sn.sub_tier <= _SUB_ENTITY_BRIDGE:
                exact_parent_ids.add(sn.node_id)

        allocated: dict[str, list[_ScoredNode]] = {pid: [] for pid in active_parents}
        leftover = remaining

        # Phase 1: exact parents get all their columns
        for pid in active_parents:
            if pid not in exact_parent_ids:
                continue
            cols = col_by_parent[pid]
            take = min(len(cols), leftover)
            allocated[pid] = cols[:take]
            leftover -= take
            if leftover <= 0:
                break

        # Phase 2: fair distribution to remaining parents
        if leftover > 0:
            other_active = [p for p in active_parents if p not in exact_parent_ids]
            n_other = max(len(other_active), 1)
            per_parent = min(7, max(1, leftover // n_other))
            for pid in other_active:
                cols = col_by_parent[pid]
                take = min(per_parent, len(cols), leftover)
                allocated[pid] = cols[:take]
                leftover -= take
                if leftover <= 0:
                    break

        # Phase 3: extras to highest-priority parents
        if leftover > 0:
            for pid in active_parents:
                cols = col_by_parent[pid]
                already = len(allocated[pid])
                extra = cols[already:]
                take = min(len(extra), leftover)
                allocated[pid].extend(extra[:take])
                leftover -= take
                if leftover <= 0:
                    break

        for pid in active_parents:
            kept.extend(allocated[pid])

        remaining = max_objects - len(kept)
        if remaining > 0:
            kept.extend(orphan_cols[:remaining])

    kept_entries = kept
    # Re-sort for deterministic output
    kept_entries.sort(key=lambda s: s.sort_key())

    # Recompute total candidates after Phase C may have added unscored columns
    total_candidate_nodes = len(scored)

    all_entries = sorted(scored.values(), key=lambda s: s.sort_key())
    _kept_ids = {sn.node_id for sn in kept_entries}
    evicted_entries = [sn for sn in all_entries if sn.node_id not in _kept_ids]

    # Track per-tier statistics
    tier_candidates: dict[int, int] = {}
    tier_selected: dict[int, int] = {}
    for sn in all_entries:
        tier_candidates[sn.tier] = tier_candidates.get(sn.tier, 0) + 1
    for sn in kept_entries:
        tier_selected[sn.tier] = tier_selected.get(sn.tier, 0) + 1

    # Count how many pinned-tier entries were evicted
    pinned_evicted = sum(1 for sn in evicted_entries if sn.node_id in pinned)

    # Final selected set
    selected_ids: set[str] = {sn.node_id for sn in kept_entries}
    nodes_omitted = total_candidate_nodes - len(selected_ids)

    # 7. Include ALL edges between selected nodes
    all_candidate_edges = _collect_edges(graph, {sn.node_id for sn in scored.values()})
    total_candidate_edges = len(all_candidate_edges)

    selected_edges_list = _collect_edges(graph, selected_ids)
    edges_omitted = total_candidate_edges - len(selected_edges_list)

    # Build the final node list (includes synthetic nodes for schema-qualified
    # references and dynamic synonyms)
    _synthetic_by_id = {n.id: n for n in _synthetic_nodes}
    selected_node_list: list[DatabaseGraphNode] = []
    for node_id in selected_ids:
        node = idx.node_by_id.get(node_id) or _synthetic_by_id.get(node_id)
        if node is not None:
            selected_node_list.append(node)

    # Sort for deterministic output
    selected_nodes = tuple(sorted(selected_node_list, key=lambda n: n.qualified_name))
    selected_edges = tuple(
        sorted(selected_edges_list, key=lambda e: (e.from_node, e.to_node, e.kind))
    )
    story_terms_matched_t = tuple(matched_terms)
    story_terms_unmatched_t = tuple(unmatched_terms)

    omitted = OmittedCounts(
        nodes_omitted=nodes_omitted,
        edges_omitted=edges_omitted,
        total_candidate_nodes=total_candidate_nodes,
        total_candidate_edges=total_candidate_edges,
    )

    # Build per-tier selection details
    tier_details: list[SelectionDetail] = []
    all_tiers = sorted(set(tier_candidates) | set(tier_selected))
    for t in all_tiers:
        sel = tier_selected.get(t, 0)
        cand = tier_candidates.get(t, 0)
        tier_details.append(SelectionDetail(
            tier=t,
            tier_label=_TIER_LABELS.get(t, f"tier_{t}"),
            selected=sel,
            omitted=cand - sel,
        ))

    truncation = TruncationMetadata(
        was_truncated=nodes_omitted > 0,
        hard_cap=max_objects,
        total_candidates=total_candidate_nodes,
        total_selected=len(selected_ids),
        tier_details=tuple(tier_details),
        pinned_evicted=pinned_evicted,
    )

    ctx_fp = _context_fingerprint(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=story_terms_matched_t,
        story_terms_unmatched=story_terms_unmatched_t,
        full_graph_fingerprint=graph.fingerprint,
        max_hops=max_hops,
        max_objects=max_objects,
    )

    return DatabaseContextResult(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=story_terms_matched_t,
        story_terms_unmatched=story_terms_unmatched_t,
        omitted_counts=omitted,
        full_graph_fingerprint=graph.fingerprint,
        context_fingerprint=ctx_fp,
        max_hops=max_hops,
        max_objects=max_objects,
        truncation=truncation,
        selection_strategy=SELECTION_STRATEGY_LEGACY,
        uncertainties=(),
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_database_context_markdown(result: DatabaseContextResult) -> str:
    """Render a bounded database context as readable Markdown.

    Sections:
    - Summary (match counts, omission counts)
    - Matched/unmatched terms
    - Tables and views with their columns
    - Java entity mappings
    - Relationships (edges)
    - Fingerprints
    """
    lines: list[str] = []

    # --- Header ---
    lines.append("# Database Context")
    lines.append("")

    # --- Summary ---
    n_tables = sum(
        1 for n in result.selected_nodes
        if n.kind in (NodeKind.TABLE.value, NodeKind.VIEW.value, NodeKind.MATERIALIZED_VIEW.value)
    )
    n_columns = sum(
        1 for n in result.selected_nodes if n.kind == NodeKind.COLUMN.value
    )
    n_entities = sum(
        1 for n in result.selected_nodes if n.kind == NodeKind.JAVA_ENTITY.value
    )
    n_edges = len(result.selected_edges)

    lines.append(f"**{len(result.selected_nodes)}** nodes selected "
                 f"({n_tables} tables/views, {n_columns} columns, "
                 f"{n_entities} Java entities), "
                 f"**{n_edges}** relationships.")
    lines.append("")

    if result.omitted_counts.nodes_omitted > 0:
        lines.append(
            f"> ⚠ {result.omitted_counts.nodes_omitted} nodes and "
            f"{result.omitted_counts.edges_omitted} edges omitted "
            f"(cap: {result.max_objects} nodes, {result.max_hops} hops)."
        )
        if result.truncation.was_truncated:
            lines.append(
                f"> Selected {result.truncation.total_selected} of "
                f"{result.truncation.total_candidates} candidates."
            )
            if result.truncation.pinned_evicted > 0:
                lines.append(
                    f"> {result.truncation.pinned_evicted} pinned-tier nodes "
                    f"evicted to meet the hard cap."
                )
        lines.append("")

    # --- Matched terms ---
    if result.story_terms_matched:
        lines.append("## Matched Terms")
        lines.append("")
        lines.append(", ".join(f"`{t}`" for t in result.story_terms_matched))
        lines.append("")

    if result.story_terms_unmatched:
        lines.append("## Unmatched Terms")
        lines.append("")
        lines.append(", ".join(f"`{t}`" for t in result.story_terms_unmatched))
        lines.append("")

    # --- Build lookup structures ---
    node_map: dict[str, DatabaseGraphNode] = {
        n.id: n for n in result.selected_nodes
    }
    # Edges grouped by from_node
    edges_by_from: dict[str, list[DatabaseGraphEdge]] = {}
    for e in result.selected_edges:
        edges_by_from.setdefault(e.from_node, []).append(e)

    # --- Tables and Views ---
    table_nodes = [
        n for n in result.selected_nodes
        if n.kind in (NodeKind.TABLE.value, NodeKind.VIEW.value, NodeKind.MATERIALIZED_VIEW.value)
    ]
    if table_nodes:
        lines.append("## Tables and Views")
        lines.append("")

        for tbl in table_nodes:
            kind_label = tbl.kind.replace("_", " ").title()
            schema_prefix = f"{tbl.schema}." if tbl.schema else ""
            short_name = tbl.qualified_name.rsplit(".", 1)[-1]
            lines.append(f"### {schema_prefix}{short_name} ({kind_label})")
            lines.append("")

            # Find columns connected via HAS_COLUMN edges
            column_ids: list[str] = []
            for e in edges_by_from.get(tbl.id, []):
                if e.kind == EdgeKind.HAS_COLUMN.value:
                    column_ids.append(e.to_node)

            if column_ids:
                lines.append("| Column | Type | Nullable | Evidence |")
                lines.append("|--------|------|----------|----------|")
                for cid in column_ids:
                    col = node_map.get(cid)
                    if col is None:
                        continue
                    col_name = col.qualified_name.rsplit(".", 1)[-1]
                    col_type = col.get_property("data_type") or "—"
                    nullable = col.get_property("nullable")
                    nullable_str = "YES" if nullable else ("NO" if nullable is not None else "—")
                    evidence_str = col.evidence.status
                    lines.append(
                        f"| {col_name} | {col_type} | {nullable_str} | {evidence_str} |"
                    )
                lines.append("")

            # Foreign keys from this table
            fk_edges = [
                e for e in edges_by_from.get(tbl.id, [])
                if e.kind == EdgeKind.FOREIGN_KEY_TO.value
            ]
            # Also check edges from FK constraint nodes that belong to this table
            for n in result.selected_nodes:
                if n.kind == NodeKind.FOREIGN_KEY.value:
                    for e in edges_by_from.get(n.id, []):
                        if e.kind == EdgeKind.FOREIGN_KEY_TO.value:
                            fk_edges.append(e)

            if fk_edges:
                lines.append("**Foreign Keys:**")
                for fk in fk_edges:
                    target = node_map.get(fk.to_node)
                    target_name = target.qualified_name if target else fk.to_node
                    fk_cols = fk.get_property("columns") if hasattr(fk, "get_property") else None
                    if fk_cols:
                        lines.append(f"- → `{target_name}` (columns: {fk_cols})")
                    else:
                        lines.append(f"- → `{target_name}`")
                lines.append("")

    # --- Java Entities ---
    entity_nodes = [
        n for n in result.selected_nodes
        if n.kind == NodeKind.JAVA_ENTITY.value
    ]
    if entity_nodes:
        lines.append("## Java Entity Mappings")
        lines.append("")

        for ent in entity_nodes:
            lines.append(f"### {ent.qualified_name}")
            lines.append("")

            # Find MAPS_TO_TABLE edges
            mappings = [
                e for e in edges_by_from.get(ent.id, [])
                if e.kind == EdgeKind.MAPS_TO_TABLE.value
            ]
            for m in mappings:
                target = node_map.get(m.to_node)
                target_name = target.qualified_name if target else m.to_node
                lines.append(f"- Maps to table: `{target_name}`")

            # Find JAVA_RELATION_TO edges
            relations = [
                e for e in edges_by_from.get(ent.id, [])
                if e.kind == EdgeKind.JAVA_RELATION_TO.value
            ]
            for r in relations:
                target = node_map.get(r.to_node)
                target_name = target.qualified_name if target else r.to_node
                rel_type = ""
                for k, v in r.properties:
                    if k == "relation_type":
                        rel_type = f" ({v})"
                        break
                lines.append(f"- Relation to: `{target_name}`{rel_type}")

            lines.append("")

    # --- Other relationships ---
    other_edges = [
        e for e in result.selected_edges
        if e.kind not in (
            EdgeKind.HAS_COLUMN.value,
            EdgeKind.MAPS_TO_TABLE.value,
            EdgeKind.MAPS_TO_COLUMN.value,
            EdgeKind.JAVA_RELATION_TO.value,
        )
    ]
    if other_edges:
        lines.append("## Relationships")
        lines.append("")
        for e in other_edges:
            from_node = node_map.get(e.from_node)
            to_node = node_map.get(e.to_node)
            from_name = from_node.qualified_name if from_node else e.from_node
            to_name = to_node.qualified_name if to_node else e.to_node
            kind_label = e.kind.replace("_", " ").lower()
            lines.append(f"- `{from_name}` —{kind_label}→ `{to_name}`")
        lines.append("")

    # --- Fingerprints ---
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Full graph fingerprint: `{result.full_graph_fingerprint[:16]}…`")
    lines.append(f"- Context fingerprint: `{result.context_fingerprint[:16]}…`")
    lines.append(f"- Bounds: max_hops={result.max_hops}, max_objects={result.max_objects}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mermaid renderer
# ---------------------------------------------------------------------------

def _mermaid_safe(name: str) -> str:
    """Sanitise a name for Mermaid node labels."""
    return name.replace('"', "'").replace("[", "(").replace("]", ")")


def _mermaid_node_id(node_id: str) -> str:
    """Produce a short, Mermaid-safe node identifier."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
    if len(safe) > 16:
        safe = safe[:16]
    return f"n_{safe}"


def render_database_context_mermaid(result: DatabaseContextResult) -> str:
    """Render a bounded database context as a Mermaid ER / graph diagram.

    Uses ``graph LR`` with subgraphs for schemas and styled nodes by kind.
    """
    lines: list[str] = []
    lines.append("graph LR")

    node_map: dict[str, DatabaseGraphNode] = {
        n.id: n for n in result.selected_nodes
    }

    # Group nodes by schema for subgraphs
    schema_groups: dict[str, list[DatabaseGraphNode]] = {}
    for n in result.selected_nodes:
        schema_key = n.schema or "_default"
        schema_groups.setdefault(schema_key, []).append(n)

    # Emit nodes
    for schema_key in sorted(schema_groups):
        nodes = schema_groups[schema_key]
        if schema_key != "_default":
            lines.append(f"    subgraph {_mermaid_safe(schema_key)}")

        for n in sorted(nodes, key=lambda x: x.qualified_name):
            mid = _mermaid_node_id(n.id)
            short_name = n.qualified_name.rsplit(".", 1)[-1]
            label = _mermaid_safe(short_name)

            if n.kind in (NodeKind.TABLE.value, NodeKind.VIEW.value, NodeKind.MATERIALIZED_VIEW.value):
                lines.append(f"    {mid}[\"{label}\"]")
            elif n.kind == NodeKind.JAVA_ENTITY.value:
                lines.append(f"    {mid}(\"{label}\")")
            elif n.kind == NodeKind.COLUMN.value:
                lines.append(f"    {mid}[\"{label}\"]")
            elif n.kind in (NodeKind.FOREIGN_KEY.value, NodeKind.PRIMARY_KEY.value):
                lines.append(f"    {mid}{{\"{label}\"}}")
            else:
                lines.append(f"    {mid}[\"{label}\"]")

        if schema_key != "_default":
            lines.append("    end")

    # Emit edges
    _EDGE_LABELS: dict[str, str] = {
        EdgeKind.HAS_COLUMN.value: "has",
        EdgeKind.PRIMARY_KEY_OF.value: "PK",
        EdgeKind.FOREIGN_KEY_TO.value: "FK",
        EdgeKind.LOGICAL_REFERENCE_TO.value: "ref",
        EdgeKind.MAPS_TO_TABLE.value: "maps",
        EdgeKind.MAPS_TO_COLUMN.value: "maps",
        EdgeKind.JAVA_RELATION_TO.value: "rel",
        EdgeKind.READS_FROM.value: "reads",
        EdgeKind.WRITES_TO.value: "writes",
        EdgeKind.JOINS_TO.value: "joins",
        EdgeKind.DERIVED_FROM.value: "derived",
        EdgeKind.USES_SEQUENCE.value: "seq",
        EdgeKind.ALIAS_OF.value: "alias",
        EdgeKind.TRIGGERED_BY.value: "trigger",
        EdgeKind.CREATES.value: "creates",
        EdgeKind.ALTERS.value: "alters",
        EdgeKind.RENAMES.value: "renames",
        EdgeKind.DROPS.value: "drops",
        EdgeKind.DEFINED_IN.value: "in",
        EdgeKind.CONFIRMED_BY.value: "confirmed",
        EdgeKind.CONFLICTS_WITH.value: "conflicts",
    }

    for e in result.selected_edges:
        from_mid = _mermaid_node_id(e.from_node)
        to_mid = _mermaid_node_id(e.to_node)
        label = _EDGE_LABELS.get(e.kind, e.kind)
        lines.append(f"    {from_mid} -->|{label}| {to_mid}")

    # Style classes
    lines.append("")
    lines.append("    classDef tbl fill:#e1f5fe,stroke:#0277bd")
    lines.append("    classDef ent fill:#f3e5f5,stroke:#7b1fa2")
    lines.append("    classDef col fill:#f5f5f5,stroke:#9e9e9e")

    # Apply styles
    table_ids = [
        _mermaid_node_id(n.id) for n in result.selected_nodes
        if n.kind in (NodeKind.TABLE.value, NodeKind.VIEW.value, NodeKind.MATERIALIZED_VIEW.value)
    ]
    entity_ids = [
        _mermaid_node_id(n.id) for n in result.selected_nodes
        if n.kind == NodeKind.JAVA_ENTITY.value
    ]
    column_ids = [
        _mermaid_node_id(n.id) for n in result.selected_nodes
        if n.kind == NodeKind.COLUMN.value
    ]

    if table_ids:
        lines.append(f"    class {','.join(table_ids)} tbl")
    if entity_ids:
        lines.append(f"    class {','.join(entity_ids)} ent")
    if column_ids:
        lines.append(f"    class {','.join(column_ids)} col")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bundle-based selection (experimental)
# ---------------------------------------------------------------------------

def select_database_context_via_bundles(
    graph: DatabaseGraph,
    story_text: str,
    *,
    max_hops: int = _DEFAULT_MAX_HOPS,
    max_objects: int = _DEFAULT_MAX_OBJECTS,
) -> DatabaseContextResult:
    """Select database context using evidence-backed bundle selection.
    
    This is an alternative implementation that uses SelectionBundle for
    atomic table+column+relationship selection. It produces the same
    DatabaseContextResult format as select_database_context.
    
    Key differences from the standard selector:
    - Tables, columns, and relationships are grouped into atomic bundles
    - Family suppression prevents prefix flooding
    - FK neighbors of exact anchors become bridges, not concept-anchors
    - Bundles are evicted atomically (table + its columns together)
    
    Args:
        graph: The reconciled DatabaseGraph
        story_text: Story or impediment text
        max_hops: Maximum expansion depth (kept for API compatibility)
        max_objects: Maximum total objects in result
    
    Returns:
        DatabaseContextResult with bounded subgraph
    """
    from .bundle_selector import (
        build_and_select_bundles,
        _extract_terms,
        _ENGLISH_STOP_WORDS,
    )
    
    if max_hops < 0:
        raise ValueError(f"max_hops must be >= 0, got {max_hops}")
    if max_objects < 1:
        raise ValueError(f"max_objects must be >= 1, got {max_objects}")
    
    # Run bundle selection
    bundle_result = build_and_select_bundles(
        graph, story_text,
        max_objects=max_objects,
        max_per_family=2,
    )
    
    # Build node and edge indexes
    node_by_id = {n.id: n for n in graph.nodes}
    
    # Collect selected node IDs
    selected_ids: set[str] = set()
    
    for bundle in bundle_result.selected_bundles:
        # Add table
        selected_ids.add(bundle.table_id)
        
        # Add columns
        for col in bundle.columns:
            selected_ids.add(col.column_id)
    
    # Collect edges between selected nodes
    selected_edges_list = [
        e for e in graph.edges
        if e.from_node in selected_ids and e.to_node in selected_ids
    ]
    
    # Build final node list
    selected_node_list = [
        node_by_id[nid] for nid in selected_ids
        if nid in node_by_id
    ]
    
    # Sort for deterministic output
    selected_nodes = tuple(sorted(selected_node_list, key=lambda n: n.qualified_name))
    selected_edges = tuple(
        sorted(selected_edges_list, key=lambda e: (e.from_node, e.to_node, e.kind))
    )
    
    # Extract story terms for reporting
    raw_terms = _extract_terms(story_text)
    terms = [t for t in raw_terms if t.lower() not in _ENGLISH_STOP_WORDS]
    
    # Determine matched vs unmatched terms
    matched_terms: list[str] = []
    unmatched_terms: list[str] = []
    matched_set: set[str] = set()
    
    for bundle in bundle_result.selected_bundles:
        for term in bundle.story_terms_matched:
            matched_set.add(term.upper())
    
    for term in terms:
        if term in matched_set:
            matched_terms.append(term)
        else:
            unmatched_terms.append(term)
    
    # Compute omitted counts
    total_candidates = len(bundle_result.selected_bundles) + len(bundle_result.evicted_bundles)
    total_candidate_objects = sum(
        b.object_cost for b in bundle_result.selected_bundles
    ) + sum(
        b.object_cost for b in bundle_result.evicted_bundles
    )
    
    omitted = OmittedCounts(
        nodes_omitted=total_candidate_objects - len(selected_ids),
        edges_omitted=0,  # Not tracking edge omissions in bundle mode
        total_candidate_nodes=total_candidate_objects,
        total_candidate_edges=len(graph.edges),
    )
    
    # Build truncation metadata
    truncation = TruncationMetadata(
        was_truncated=len(bundle_result.evicted_bundles) > 0,
        hard_cap=max_objects,
        total_candidates=total_candidate_objects,
        total_selected=len(selected_ids),
        tier_details=(),  # Tiers don't map to bundle kinds directly
        pinned_evicted=0,  # Bundles don't have pinned concept
    )
    
    # Compute context fingerprint
    ctx_fp = _context_fingerprint(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=tuple(matched_terms),
        story_terms_unmatched=tuple(unmatched_terms),
        full_graph_fingerprint=graph.fingerprint,
        max_hops=max_hops,
        max_objects=max_objects,
    )
    
    return DatabaseContextResult(
        selected_nodes=selected_nodes,
        selected_edges=selected_edges,
        story_terms_matched=tuple(matched_terms),
        story_terms_unmatched=tuple(unmatched_terms),
        omitted_counts=omitted,
        full_graph_fingerprint=graph.fingerprint,
        context_fingerprint=ctx_fp,
        max_hops=max_hops,
        max_objects=max_objects,
        truncation=truncation,
        selection_strategy=SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1,
        uncertainties=(),
    )
