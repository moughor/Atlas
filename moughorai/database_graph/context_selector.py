"""Bounded database context selection for story/impediment analysis.

Phase C3 — selects a relevant subgraph from a reconciled DatabaseGraph
by extracting domain terms from story text, matching them against graph
nodes with a weighted scoring system, pinning exact matches and their
essential neighbourhood, expanding via FK connectivity, and capping the
result at a bounded size while preserving pinned nodes.

All outputs are frozen dataclasses with deterministic fingerprints and
full round-trip serialisation (to_dict / from_dict).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
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

# Tier constants for ranking
_TIER_PINNED: int = 0         # Pinned nodes (exact match + essential neighborhood)
_TIER_FK_CONNECTED: int = 1   # FK-connected tables of pinned nodes
_TIER_FK_COLUMNS: int = 2     # Columns of tier-1 tables
_TIER_DOMAIN: int = 3         # Domain phrase matches
_TIER_FUZZY: int = 4          # Fuzzy/substring matches

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_nodes", tuple(self.selected_nodes))
        object.__setattr__(self, "selected_edges", tuple(self.selected_edges))
        object.__setattr__(self, "story_terms_matched", tuple(self.story_terms_matched))
        object.__setattr__(self, "story_terms_unmatched", tuple(self.story_terms_unmatched))
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseContextResult:
        if not isinstance(data, dict):
            raise ValueError("database context result must be an object")
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

    def edges_from(self, node_id: str, kind: str | None = None) -> list[DatabaseGraphEdge]:
        """Return outgoing edges, optionally filtered by kind."""
        edges = self.outgoing.get(node_id, [])
        if kind is not None:
            return [e for e in edges if e.kind == kind]
        return edges

    def edges_to(self, node_id: str, kind: str | None = None) -> list[DatabaseGraphEdge]:
        """Return incoming edges, optionally filtered by kind."""
        edges = self.incoming.get(node_id, [])
        if kind is not None:
            return [e for e in edges if e.kind == kind]
        return edges

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

    def sort_key(self) -> tuple[int, int, str]:
        """Sort: tier ascending, score descending, then name for determinism."""
        return (self.tier, -self.score, self.node_id)


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

    def _upsert(node_id: str, score: int, tier: int, reason: str) -> None:
        existing = scored.get(node_id)
        if existing is None or score > existing.score:
            scored[node_id] = _ScoredNode(
                node_id=node_id, score=score, tier=min(tier, existing.tier) if existing else tier, reason=reason,
            )
        elif existing is not None and tier < existing.tier:
            # Promote tier if new tier is better, keep higher score
            scored[node_id] = _ScoredNode(
                node_id=node_id, score=existing.score, tier=tier, reason=existing.reason,
            )

    for term in terms:
        found = False

        # --- 1. Exact full identifier match (score 100) ---
        # Check against short names (the last segment of qualified_name)
        exact_nodes = idx.short_name_to_nodes.get(term, [])
        for node in exact_nodes:
            if node.kind in _TABLE_KINDS:
                _upsert(node.id, _SCORE_EXACT_IDENTIFIER, _TIER_PINNED, f"exact_table:{term}")
                found = True
            elif node.kind in _ENTITY_KINDS:
                _upsert(node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED, f"exact_entity:{term}")
                found = True
            elif node.kind == NodeKind.COLUMN.value:
                # Column exact match — scored as FK/column neighbor level
                _upsert(node.id, _SCORE_FK_COLUMN_NEIGHBOR, _TIER_PINNED, f"exact_column:{term}")
                found = True
            else:
                # Other node kinds (sequence, synonym, etc.)
                _upsert(node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED, f"exact_other:{term}")
                found = True

        # Also check full qualified name exact match
        qn_node = idx.qname_upper_to_nodes.get(term)
        if qn_node is not None:
            if qn_node.kind in _TABLE_KINDS:
                _upsert(qn_node.id, _SCORE_EXACT_IDENTIFIER, _TIER_PINNED, f"exact_qname_table:{term}")
            elif qn_node.kind in _ENTITY_KINDS:
                _upsert(qn_node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED, f"exact_qname_entity:{term}")
            else:
                _upsert(qn_node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED, f"exact_qname_other:{term}")
            found = True

        # --- 2. Normalized domain phrase match (score 50) ---
        # The term appears as a complete segment within an underscore-delimited
        # qualified_name. E.g. term "FEATURE" matches "TB_GRP_PF_FEATURE"
        # because "FEATURE" is one of the underscore-delimited segments.
        if not found:
            for node in idx.graph.nodes:
                qn_upper = node.qualified_name.upper()
                short_upper = qn_upper.rsplit(".", 1)[-1]
                # Split on underscores to get segments
                segments = short_upper.split("_")
                if term in segments:
                    _upsert(node.id, _SCORE_DOMAIN_PHRASE, _TIER_DOMAIN, f"domain_segment:{term}")
                    found = True

        # --- 3. Fuzzy/substring match (score 20, min 5 chars) ---
        if not found and len(term) >= _MIN_SUBSTRING_LENGTH:
            for node in idx.graph.nodes:
                qn_upper = node.qualified_name.upper()
                if term in qn_upper:
                    _upsert(node.id, _SCORE_FUZZY_SUBSTRING, _TIER_FUZZY, f"substring:{term}")
                    found = True

        if found:
            matched_terms.append(term)
        else:
            unmatched_terms.append(term)

    # --- Fix 3B: Entity→table bridging ---
    # For each JPA entity, check if any extracted term matches the entity's
    # class name (case-insensitive camelCase split). If yes, follow
    # MAPS_TO_TABLE edges to find the target table and pin it.
    for entity_node in idx.entity_nodes:
        entity_short = entity_node.qualified_name.rsplit(".", 1)[-1]
        entity_words = _split_camel_case(entity_short)
        entity_upper = entity_short.upper()

        for term in terms:
            term_lower = term.lower()
            # Match if the term matches the full entity name or any camelCase word
            if term_lower == entity_upper.lower() or term_lower in entity_words:
                # Pin the entity
                _upsert(entity_node.id, _SCORE_EXACT_ENTITY, _TIER_PINNED,
                         f"entity_bridge:{term}")
                # Follow MAPS_TO_TABLE to find and pin the target table
                target_id = idx.maps_to_target(entity_node.id)
                if target_id is not None:
                    _upsert(target_id, _SCORE_MAPS_TO_TARGET, _TIER_PINNED,
                             f"entity_bridge_table:{entity_short}")
                # Mark term as matched if not already
                if term not in matched_terms:
                    matched_terms.append(term)
                    if term in unmatched_terms:
                        unmatched_terms.remove(term)
                break  # Only need one term to match per entity

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

    Returns the set of pinned node IDs. These are NEVER removed by the cap.
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
            if target_table_id not in scored:
                scored[target_table_id] = _ScoredNode(
                    node_id=target_table_id,
                    score=_SCORE_MAPS_TO_TARGET,
                    tier=_TIER_PINNED,
                    reason=f"maps_to_target_of:{ent_id}",
                )
            exact_table_ids.append(target_table_id)

    # For each pinned table: pin columns and FK neighbors
    for tbl_id in exact_table_ids:
        # Columns
        for col_id in idx.columns_of(tbl_id):
            pinned.add(col_id)
            if col_id not in scored:
                scored[col_id] = _ScoredNode(
                    node_id=col_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_PINNED,
                    reason=f"column_of_pinned:{tbl_id}",
                )

        # FK neighbors — just mark the neighboring table IDs
        for neighbor_id, _fk_edge in idx.fk_neighbors_of(tbl_id):
            pinned.add(neighbor_id)
            if neighbor_id not in scored:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_PINNED,
                    reason=f"fk_neighbor_of_pinned:{tbl_id}",
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
            if neighbor_id not in scored:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_FK_CONNECTED,
                    reason=f"expand_{edge.kind}_from:{node_id}",
                )
                tier1_table_ids.append(neighbor_id)
            elif scored[neighbor_id].tier > _TIER_FK_CONNECTED:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=max(scored[neighbor_id].score, _SCORE_FK_COLUMN_NEIGHBOR),
                    tier=_TIER_FK_CONNECTED,
                    reason=scored[neighbor_id].reason,
                )

        for edge in idx.edges_to(node_id):
            if edge.kind not in _EXPANSION_EDGE_KINDS:
                continue
            neighbor_id = edge.from_node
            if neighbor_id not in scored:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=_SCORE_FK_COLUMN_NEIGHBOR,
                    tier=_TIER_FK_CONNECTED,
                    reason=f"expand_{edge.kind}_to:{node_id}",
                )
                tier1_table_ids.append(neighbor_id)
            elif scored[neighbor_id].tier > _TIER_FK_CONNECTED:
                scored[neighbor_id] = _ScoredNode(
                    node_id=neighbor_id,
                    score=max(scored[neighbor_id].score, _SCORE_FK_COLUMN_NEIGHBOR),
                    tier=_TIER_FK_CONNECTED,
                    reason=scored[neighbor_id].reason,
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
                )


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

    Algorithm:
    1. Build a pre-computed graph index.
    2. Extract and filter domain terms from story_text.
    3. Score nodes against terms with a weighted system.
    4. Pin exact matches and their essential neighbourhood.
    5. Expand FK tiers (tier 1: FK-connected tables, tier 2: their columns).
    6. Cap at max_objects — pinned nodes (tier 0) are never removed.
    7. Include ALL edges between selected nodes.
    8. Compute a deterministic context fingerprint.

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

    # 3. Score nodes against terms
    scored, matched_terms, unmatched_terms = _score_and_match(terms, idx)

    # 4. Pin exact matches + essential neighbourhood
    pinned = _pin_essential_neighbourhood(scored, idx)

    # 5. Expand FK tiers
    _expand_fk_tiers(pinned, scored, idx)

    # 6. Cap at max_objects — pinned nodes are never removed
    total_candidate_nodes = len(scored)

    # Separate pinned from cappable
    pinned_entries = []
    cappable_entries = []
    for node_id, sn in scored.items():
        if node_id in pinned:
            pinned_entries.append(sn)
        else:
            cappable_entries.append(sn)

    # Sort cappable by tier ascending, score descending, id for determinism
    cappable_entries.sort(key=lambda s: s.sort_key())

    # How many cappable slots remain after pinned nodes?
    remaining_slots = max(0, max_objects - len(pinned_entries))
    kept_cappable = cappable_entries[:remaining_slots]

    # Final selected set
    selected_ids: set[str] = set()
    for sn in pinned_entries:
        selected_ids.add(sn.node_id)
    for sn in kept_cappable:
        selected_ids.add(sn.node_id)

    nodes_omitted = total_candidate_nodes - len(selected_ids)

    # 7. Include ALL edges between selected nodes
    all_candidate_edges = _collect_edges(graph, {sn.node_id for sn in scored.values()})
    total_candidate_edges = len(all_candidate_edges)

    selected_edges_list = _collect_edges(graph, selected_ids)
    edges_omitted = total_candidate_edges - len(selected_edges_list)

    # Build the final node list
    selected_node_list: list[DatabaseGraphNode] = []
    for node_id in selected_ids:
        node = idx.node_by_id.get(node_id)
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
