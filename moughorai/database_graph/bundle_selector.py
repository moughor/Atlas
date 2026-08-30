"""
Bundle-based context selector.

Replaces fixed quota allocation with evidence-backed bundle selection:
1. Build candidate bundles for all tables with story evidence
2. Score bundles by concept coverage, confidence, and evidence strength
3. Select anchors first (high-confidence, multi-concept tables)
4. Add bridge bundles only when connecting selected anchors
5. Enforce family limits to prevent prefix flooding
6. Evict lowest-marginal-benefit bundles atomically under budget
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    NodeKind,
)
from .selection_bundle import (
    BundleKind,
    BundleSelectionResult,
    ColumnEvidence,
    RelationshipEvidence,
    SelectionBundle,
    compute_family_prefix,
    compute_marginal_benefit,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TABLE_KINDS: frozenset[str] = frozenset({
    NodeKind.TABLE.value,
    NodeKind.VIEW.value,
    NodeKind.MATERIALIZED_VIEW.value,
})

_ENTITY_KINDS: frozenset[str] = frozenset({
    NodeKind.JAVA_ENTITY.value,
})

# Maximum bundles per family prefix (prevents 40 TB_GRP_PR_* consuming budget)
_MAX_PER_FAMILY: int = 2

# Minimum confidence for anchor promotion
_ANCHOR_MIN_CONFIDENCE: float = 0.6

# Minimum concept count for concept-anchor promotion
_ANCHOR_MIN_CONCEPTS: int = 2

# ---------------------------------------------------------------------------
# Evidence Quality Thresholds (STEP 5B: Stop Table/Entity Flooding)
# ---------------------------------------------------------------------------

# Maximum entity nodes (prevents entity flooding from common terms)
_MAX_ENTITY_NODES: int = 3

# Maximum bridges per anchor (prevents FK flooding)
_MAX_BRIDGES_PER_ANCHOR: int = 2

# Minimum IDF for entity word matches (higher = rarer terms preferred)
_ENTITY_MIN_IDF: float = 1.0

# Minimum IDF for bridge table name terms (bridge must have some rare term)
_BRIDGE_MIN_IDF: float = 0.5

# Reserve a portion of budget for columns of anchors
_ANCHOR_COLUMN_BUDGET_FRACTION: float = 0.3

# Maximum tables (soft cap to leave room for columns)
_MAX_TABLES_FRACTION: float = 0.5  # At most 50% of budget for tables

# Minimum evidence score for weak matches
_WEAK_MIN_EVIDENCE: float = 0.3

# FK expansion edges
_FK_EDGE_KINDS: frozenset[str] = frozenset({
    EdgeKind.FOREIGN_KEY_TO.value,
    EdgeKind.LOGICAL_REFERENCE_TO.value,
    EdgeKind.JAVA_RELATION_TO.value,
})

# View/synonym expansion edges
_VIEW_EDGE_KINDS: frozenset[str] = frozenset({
    EdgeKind.DERIVED_FROM.value,
    EdgeKind.READS_FROM.value,
})

_SYNONYM_EDGE_KINDS: frozenset[str] = frozenset({
    EdgeKind.ALIAS_OF.value,
})

# Known table name prefixes to strip for domain matching
_TABLE_PREFIXES = (
    "TB_RT_", "TB_APP_", "TB_GRP_", "TB_MDL_", "TB_LOG_",
    "TB_GRP_PR_", "TB_GRP_PL_", "TB_GRP_C_",
    "VW_HD_", "VW_", "MV_A_", "MV_", "TB_",
)

# Term extraction patterns
_SPLIT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_CAMEL_SPLIT_RE = re.compile(
    r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|_"
)
_MIN_TERM_LENGTH: int = 3

# Database object patterns
_DB_OBJECT_RE = re.compile(
    r"\b(TB_[A-Z0-9_]+|VW_[A-Z0-9_]+|MV_[A-Z0-9_]+|SQ_[A-Z0-9_]+"
    r"|MV_A_[A-Z0-9_]+|BCK_[A-Z0-9_]+)\b"
)

# Stop words
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
# Graph Index for Bundle Building
# ---------------------------------------------------------------------------

class _BundleGraphIndex:
    """Pre-built indexes for efficient bundle construction."""
    
    __slots__ = (
        "graph",
        "node_by_id",
        "table_by_short_name",
        "entity_by_short_name",
        "entity_to_table",
        "table_to_entities",
        "columns_by_table",
        "outgoing_edges",
        "incoming_edges",
        "table_evidence_terms",
        "column_by_name",
        "pk_columns",
        "fk_columns",
    )
    
    def __init__(self, graph: DatabaseGraph) -> None:
        self.graph = graph
        self.node_by_id: dict[str, DatabaseGraphNode] = {}
        self.table_by_short_name: dict[str, list[DatabaseGraphNode]] = {}
        self.entity_by_short_name: dict[str, list[DatabaseGraphNode]] = {}
        self.entity_to_table: dict[str, str] = {}  # entity_id -> table_id
        self.table_to_entities: dict[str, list[str]] = {}  # table_id -> [entity_ids]
        self.columns_by_table: dict[str, list[str]] = {}  # table_id -> [column_ids]
        self.outgoing_edges: dict[str, list[DatabaseGraphEdge]] = {}
        self.incoming_edges: dict[str, list[DatabaseGraphEdge]] = {}
        self.table_evidence_terms: dict[str, set[str]] = {}  # table_id -> {terms}
        self.column_by_name: dict[str, list[str]] = {}  # column_short_name -> [column_ids]
        self.pk_columns: dict[str, set[str]] = {}  # table_id -> {pk_column_ids}
        self.fk_columns: dict[str, set[str]] = {}  # table_id -> {fk_column_ids}
        
        self._build_indexes(graph)
    
    def _build_indexes(self, graph: DatabaseGraph) -> None:
        # Build node indexes
        for node in graph.nodes:
            self.node_by_id[node.id] = node
            short = node.qualified_name.rsplit(".", 1)[-1].upper()
            
            if node.kind in _TABLE_KINDS:
                self.table_by_short_name.setdefault(short, []).append(node)
            elif node.kind in _ENTITY_KINDS:
                self.entity_by_short_name.setdefault(short, []).append(node)
            elif node.kind == NodeKind.COLUMN.value:
                col_short = short.upper()
                self.column_by_name.setdefault(col_short, []).append(node.id)
        
        # Build edge indexes
        for edge in graph.edges:
            self.outgoing_edges.setdefault(edge.from_node, []).append(edge)
            self.incoming_edges.setdefault(edge.to_node, []).append(edge)
            
            # Track entity->table mappings
            if edge.kind == EdgeKind.MAPS_TO_TABLE.value:
                self.entity_to_table[edge.from_node] = edge.to_node
                self.table_to_entities.setdefault(edge.to_node, []).append(edge.from_node)
            
            # Track table columns
            if edge.kind == EdgeKind.HAS_COLUMN.value:
                self.columns_by_table.setdefault(edge.from_node, []).append(edge.to_node)
            
            # Track PK columns (simplified: look for ID, *_ID naming convention)
            # A proper implementation would check constraints
            
            # Track FK columns by checking FK edges
            if edge.kind == EdgeKind.FOREIGN_KEY_TO.value:
                # The FK edge typically originates from the table with the FK column
                self.fk_columns.setdefault(edge.from_node, set())
        
        # Identify PK and FK columns by naming convention
        for table_id, col_ids in self.columns_by_table.items():
            pk_set: set[str] = set()
            fk_set: set[str] = set()
            for col_id in col_ids:
                col_node = self.node_by_id.get(col_id)
                if col_node is None:
                    continue
                col_short = col_node.qualified_name.rsplit(".", 1)[-1].upper()
                # Simple PK heuristic: column named 'ID' or ends with '_ID' and table name prefix
                if col_short == "ID":
                    pk_set.add(col_id)
                # FK heuristic: ends with '_ID' but not the PK
                elif col_short.endswith("_ID") and col_short != "ID":
                    fk_set.add(col_id)
            self.pk_columns[table_id] = pk_set
            self.fk_columns[table_id] = fk_set
        
        # Build evidence term documents for each table
        self._build_evidence_terms(graph)
    
    def _build_evidence_terms(self, graph: DatabaseGraph) -> None:
        """Build semantic evidence documents for IDF computation."""
        for node in graph.nodes:
            if node.kind not in _TABLE_KINDS:
                continue
            
            terms: set[str] = set()
            short = node.qualified_name.rsplit(".", 1)[-1].upper()
            
            # Table name segments after prefix stripping
            stripped = short
            for prefix in _TABLE_PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    break
            for seg in stripped.split("_"):
                if len(seg) >= 2:
                    terms.add(seg.lower())
            
            # Entity class name words
            for ent_id in self.table_to_entities.get(node.id, []):
                ent_node = self.node_by_id.get(ent_id)
                if ent_node:
                    ent_short = ent_node.qualified_name.rsplit(".", 1)[-1]
                    for w in _split_camel_case(ent_short):
                        terms.add(w)
            
            self.table_evidence_terms[node.id] = terms
    
    def get_fk_neighbors(self, table_id: str) -> list[tuple[str, DatabaseGraphEdge]]:
        """Get (neighbor_table_id, edge) for FK connections."""
        result: list[tuple[str, DatabaseGraphEdge]] = []
        for e in self.outgoing_edges.get(table_id, []):
            if e.kind in _FK_EDGE_KINDS:
                result.append((e.to_node, e))
        for e in self.incoming_edges.get(table_id, []):
            if e.kind in _FK_EDGE_KINDS:
                result.append((e.from_node, e))
        return result


# ---------------------------------------------------------------------------
# Term extraction helpers
# ---------------------------------------------------------------------------

def _split_camel_case(name: str) -> list[str]:
    """Split camelCase name into lowercase words."""
    parts = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).split()
    return [p.lower() for p in parts if len(p) >= _MIN_TERM_LENGTH]


def _normalize_plural(word: str) -> set[str]:
    """Return singular/plural variants of a word."""
    forms = {word}
    if word.endswith("ies"):
        forms.add(word[:-3] + "y")
    elif word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        forms.add(word[:-2])
    elif word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])
    if word.endswith("y") and len(word) > 3 and word[-2] not in "aeiou":
        forms.add(word[:-1] + "ies")
    else:
        forms.add(word + "s")
    return forms


# Minimum abbreviation length for prefix matching
_MIN_ABBREV_LEN: int = 3
# Maximum abbreviation length (longer segments are unlikely to be abbreviations)
_MAX_ABBREV_LEN: int = 4


def _is_likely_abbreviation(short: str, long: str) -> bool:
    """Check if short is a likely abbreviation of long using generic corpus rules.

    A short segment is considered a likely abbreviation if:
    1. short is 3-4 characters (typical abbreviation length)
    2. short is a prefix of long
    3. long is significantly longer than short (at least 2+ more chars)

    This is a generic, corpus-derived rule—not a static abbreviation dictionary.

    Examples:
        DOC → DOCUMENT (prefix match, length ratio good)
        GEN → GENERATION (prefix match, length ratio good)
        APP → APPLICATION (prefix match)
        HD → HELPDESK (too short, not matched)
        FAILED → FAILED (exact match, handled elsewhere)
    """
    short_upper = short.upper()
    long_upper = long.upper()

    # Length constraints
    if len(short_upper) < _MIN_ABBREV_LEN:
        return False
    if len(short_upper) > _MAX_ABBREV_LEN:
        return False
    if len(long_upper) <= len(short_upper) + 1:
        # Long must be at least 2 chars longer
        return False

    # Prefix match
    return long_upper.startswith(short_upper)


def _expand_abbreviations(segments: list[str], terms: list[str]) -> dict[str, str]:
    """Find abbreviation expansions from segments to story terms.

    Returns a dict mapping segment -> expanded term for matched abbreviations.
    Only includes unambiguous matches (segment matches exactly one term).
    """
    terms_upper = {t.upper() for t in terms}
    expansions: dict[str, str] = {}

    for seg in segments:
        seg_upper = seg.upper()
        # Skip segments that are already exact matches
        if seg_upper in terms_upper:
            continue

        # Find potential expansions
        matches: list[str] = []
        for term in terms:
            if _is_likely_abbreviation(seg, term):
                matches.append(term.upper())

        # Only use unambiguous single matches
        if len(matches) == 1:
            expansions[seg_upper] = matches[0]

    return expansions


def _extract_terms(text: str) -> list[str]:
    """Extract domain terms from story text."""
    raw_tokens = _SPLIT_RE.split(text)
    seen: set[str] = set()
    terms: list[str] = []
    
    for token in raw_tokens:
        if not token:
            continue
        
        upper_full = token.upper()
        if len(upper_full) >= _MIN_TERM_LENGTH and upper_full not in seen:
            # Skip pure stop words
            if upper_full.lower() not in _ENGLISH_STOP_WORDS:
                seen.add(upper_full)
                terms.append(upper_full)
        
        # Split camelCase/underscore
        sub_parts = _CAMEL_SPLIT_RE.split(token)
        for part in sub_parts:
            upper_part = part.upper()
            if len(upper_part) >= _MIN_TERM_LENGTH and upper_part not in seen:
                if upper_part.lower() not in _ENGLISH_STOP_WORDS:
                    seen.add(upper_part)
                    terms.append(upper_part)
    
    # Also extract DB object patterns
    for m in _DB_OBJECT_RE.finditer(text.upper()):
        token = m.group(1)
        if token not in seen:
            seen.add(token)
            terms.append(token)
    
    return terms


def _compute_idf(terms: list[str], idx: _BundleGraphIndex) -> dict[str, float]:
    """Compute IDF weights for story terms."""
    n_tables = max(len(idx.table_evidence_terms), 1)
    idf: dict[str, float] = {}
    
    for term in terms:
        t_lower = term.lower()
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


# ---------------------------------------------------------------------------
# Bundle Builder
# ---------------------------------------------------------------------------

@dataclass
class _CandidateMatch:
    """Intermediate match result before bundle construction."""
    table_id: str
    table_name: str
    match_type: str  # 'exact', 'entity', 'concept', 'domain', 'fuzzy'
    matched_terms: list[str]
    entity_id: str | None = None
    confidence: float = 0.0
    concept_count: int = 0


def _build_candidate_bundles(
    terms: list[str],
    idx: _BundleGraphIndex,
    idf: dict[str, float],
) -> list[SelectionBundle]:
    """Build candidate bundles for all tables with story evidence."""
    
    candidates: dict[str, _CandidateMatch] = {}
    terms_lower = {t.lower() for t in terms}
    terms_normalized: set[str] = set()
    for t in terms_lower:
        terms_normalized.update(_normalize_plural(t))
    
    # --- Phase 1: Exact table name matches ---
    for term in terms:
        nodes = idx.table_by_short_name.get(term, [])
        for node in nodes:
            if node.id not in candidates:
                candidates[node.id] = _CandidateMatch(
                    table_id=node.id,
                    table_name=node.qualified_name,
                    match_type="exact",
                    matched_terms=[term],
                    confidence=1.0,
                )
            else:
                candidates[node.id].matched_terms.append(term)
    
    # --- Phase 2: Entity -> table bridging ---
    # Only create ANCHOR_ENTITY for high-quality matches:
    # - Full entity name match (e.g., "ProjectFeature" in story)
    # - OR: Multiple word matches with high IDF (rare terms)
    for entity_nodes in idx.entity_by_short_name.values():
        for entity_node in entity_nodes:
            entity_short = entity_node.qualified_name.rsplit(".", 1)[-1]
            entity_words = _split_camel_case(entity_short)
            
            # Check full name match
            full_match = entity_short.lower() in terms_lower
            
            # Count word matches with IDF weighting
            word_hits: list[str] = []
            word_idf_sum = 0.0
            for w in entity_words:
                if w in terms_lower or w in terms_normalized:
                    word_hits.append(w)
                    word_idf_sum += idf.get(w, 0.0)
            
            # Quality check: require either full match OR high-IDF word matches
            if full_match:
                # Full match is always high-quality
                pass
            elif len(word_hits) >= 2 and word_idf_sum >= _ENTITY_MIN_IDF * len(word_hits):
                # Multiple word matches with sufficient IDF
                pass
            else:
                # Low-quality match - skip
                continue
            
            # Find target table
            table_id = idx.entity_to_table.get(entity_node.id)
            if table_id is None:
                continue
            
            table_node = idx.node_by_id.get(table_id)
            if table_node is None:
                continue
            
            # Confidence: higher for full match, weighted by IDF for partial
            if full_match:
                confidence = 1.0
            else:
                # IDF-weighted confidence
                avg_idf = word_idf_sum / len(word_hits) if word_hits else 0.0
                confidence = min(0.95, 0.6 + 0.1 * len(word_hits) + 0.05 * avg_idf)
            
            matched_terms = [entity_short] if full_match else word_hits
            
            if table_id not in candidates:
                candidates[table_id] = _CandidateMatch(
                    table_id=table_id,
                    table_name=table_node.qualified_name,
                    match_type="entity",
                    matched_terms=matched_terms,
                    entity_id=entity_node.id,
                    confidence=confidence,
                )
            elif candidates[table_id].confidence < confidence:
                candidates[table_id].match_type = "entity"
                candidates[table_id].entity_id = entity_node.id
                candidates[table_id].confidence = confidence
                candidates[table_id].matched_terms.extend(matched_terms)
    
    # --- Phase 3: Domain segment matches (with abbreviation expansion) ---
    # For each table, check if any segment matches a story term directly OR
    # via abbreviation expansion (e.g., DOC→DOCUMENT, GEN→GENERATION)
    
    for table_nodes in idx.table_by_short_name.values():
        for node in table_nodes:
            if node.id in candidates:
                continue  # Already matched via exact or entity
            
            short = node.qualified_name.rsplit(".", 1)[-1].upper()
            segments = short.split("_")
            
            # Find all matching terms: direct segment match OR abbreviation
            matched: list[str] = []
            abbrev_expansions = _expand_abbreviations(segments, terms)
            
            for term in terms:
                term_upper = term.upper()
                term_variants = _normalize_plural(term.lower())
                term_variants_upper = {v.upper() for v in term_variants}
                
                # Direct segment match
                if term_upper in segments or term_variants_upper.intersection(segments):
                    matched.append(term_upper)
                    continue
                
                # Abbreviation match: a segment is an abbreviation of this term
                for seg, expanded in abbrev_expansions.items():
                    if expanded == term_upper:
                        matched.append(term_upper)
                        break
            
            if matched:
                # Confidence scales with number of matched concepts
                # 1 term = 0.5, 2 terms = 0.65, 3+ terms = 0.75+
                base_conf = 0.5
                if len(matched) >= 2:
                    base_conf = 0.65 + 0.05 * (len(matched) - 2)
                base_conf = min(base_conf, 0.85)
                
                candidates[node.id] = _CandidateMatch(
                    table_id=node.id,
                    table_name=node.qualified_name,
                    match_type="domain",
                    matched_terms=matched,
                    confidence=base_conf,
                )
    
    # --- Phase 4: Compute concept counts using IDF ---
    _IDF_THRESHOLD = 1.5  # Only count terms with IDF >= 1.5 as distinct concepts
    
    # First, identify exact anchor table IDs
    exact_anchor_ids = {m.table_id for m in candidates.values() 
                        if m.match_type == "exact"}
    
    # Build set of FK neighbors of exact anchors - these shouldn't become concept-anchors
    fk_neighbors_of_exact: set[str] = set()
    for anchor_id in exact_anchor_ids:
        for neighbor_id, _edge in idx.get_fk_neighbors(anchor_id):
            fk_neighbors_of_exact.add(neighbor_id)
    
    for table_id, match in candidates.items():
        ev_terms = idx.table_evidence_terms.get(table_id, set())
        rare_matches: set[str] = set()
        
        for term in terms:
            t_lower = term.lower()
            if idf.get(t_lower, 0.0) >= _IDF_THRESHOLD:
                variants = _normalize_plural(t_lower)
                if variants & ev_terms:
                    rare_matches.add(t_lower)
        
        match.concept_count = len(rare_matches)
        
        # Promote to concept-anchor ONLY if:
        # 1. Multiple rare concepts match
        # 2. Not already exact or entity match
        # 3. NOT an FK neighbor of an exact anchor (those stay as bridges)
        is_fk_of_exact = table_id in fk_neighbors_of_exact
        if (match.concept_count >= _ANCHOR_MIN_CONCEPTS 
            and match.match_type not in ("exact", "entity")
            and not is_fk_of_exact):
            match.match_type = "concept"
            match.confidence = max(match.confidence, 0.6 + 0.05 * match.concept_count)
    
    # --- Phase 5: Build bundles from candidates ---
    bundles: list[SelectionBundle] = []
    
    for table_id, match in candidates.items():
        # Skip BCK_ prefixed tables
        if match.table_name.upper().startswith("BCK") or "_BCK_" in match.table_name.upper():
            continue
        
        # Determine bundle kind
        if match.match_type == "exact":
            kind = BundleKind.ANCHOR_EXACT
        elif match.match_type == "entity":
            kind = BundleKind.ANCHOR_ENTITY
        elif match.match_type == "concept" and match.concept_count >= _ANCHOR_MIN_CONCEPTS:
            kind = BundleKind.ANCHOR_CONCEPT
        elif match.match_type == "domain":
            kind = BundleKind.WEAK_DOMAIN
        else:
            kind = BundleKind.WEAK_FUZZY
        
        # Build column evidence
        # NOTE: verified_complete logic was removed because blindly including
        # ALL columns for tables with <=20 columns causes:
        # 1. Budget overflow (total nodes exceed max_objects)
        # 2. Pack-specific overfitting (matching expected column counts)
        #
        # Column selection is now evidence-based only:
        # - PK columns (identity)
        # - FK columns (relationships)
        # - Story-matched columns (explicit story evidence)
        columns: list[ColumnEvidence] = []
        
        pk_cols = idx.pk_columns.get(table_id, set())
        fk_cols = idx.fk_columns.get(table_id, set())
        
        for col_id in pk_cols:
            col_node = idx.node_by_id.get(col_id)
            if col_node:
                columns.append(ColumnEvidence(
                    column_id=col_id,
                    column_name=col_node.qualified_name,
                    reason="pk_column",
                ))
        
        for col_id in fk_cols:
            col_node = idx.node_by_id.get(col_id)
            if col_node:
                columns.append(ColumnEvidence(
                    column_id=col_id,
                    column_name=col_node.qualified_name,
                    reason="fk_column",
                ))
        
        # Story-matched columns: search ALL story terms
        seen_col_ids: set[str] = set(pk_cols) | set(fk_cols)
        for term in terms:
            col_ids = idx.column_by_name.get(term.upper(), [])
            for col_id in col_ids:
                if col_id in seen_col_ids:
                    continue
                col_node = idx.node_by_id.get(col_id)
                if col_node:
                    table_cols = idx.columns_by_table.get(table_id, [])
                    if col_id in table_cols:
                        columns.append(ColumnEvidence(
                            column_id=col_id,
                            column_name=col_node.qualified_name,
                            reason="story_matched",
                            story_term=term,
                        ))
                        seen_col_ids.add(col_id)
        
        # Build relationship evidence
        relationships: list[RelationshipEvidence] = []
        for neighbor_id, edge in idx.get_fk_neighbors(table_id):
            neighbor_node = idx.node_by_id.get(neighbor_id)
            if neighbor_node:
                direction = "outgoing" if edge.from_node == table_id else "incoming"
                relationships.append(RelationshipEvidence(
                    edge_id=edge.id,
                    edge_kind=edge.kind,
                    target_table_id=neighbor_id,
                    target_table_name=neighbor_node.qualified_name,
                    direction=direction,
                ))
        
        # Compute family prefix and marginal benefit
        family_prefix = compute_family_prefix(match.table_name)
        marginal = compute_marginal_benefit(
            match.concept_count,
            match.confidence,
            1 + len(columns),  # object_cost
            kind,
        )
        
        entity_name = None
        entity_id = match.entity_id  # Store entity ID for MAPS_TO_TABLE edge
        if match.entity_id:
            ent_node = idx.node_by_id.get(match.entity_id)
            if ent_node:
                entity_name = ent_node.qualified_name
        
        bundle = SelectionBundle(
            table_id=table_id,
            table_name=match.table_name,
            kind=kind,
            entity_id=entity_id,
            entity_evidence=entity_name,
            story_terms_matched=tuple(set(match.matched_terms)),
            concept_count=match.concept_count,
            confidence=match.confidence,
            columns=tuple(columns),
            relationships=tuple(relationships),
            marginal_benefit=marginal,
            match_reason=f"{match.match_type}:{','.join(match.matched_terms[:3])}",
            family_prefix=family_prefix,
        )
        bundles.append(bundle)
    
    # --- Phase 6: Promote FK neighbors of anchors to bridge bundles ---
    # STEP 5B: Limit bridges per anchor to prevent FK flooding.
    # Only create bridges for high-value neighbors with evidence.
    anchor_ids = {m.table_id for m in candidates.values() 
                  if m.match_type in ("exact", "entity", "concept")}
    
    # First pass: promote existing candidates that are FK neighbors of anchors
    bundles_by_table: dict[str, SelectionBundle] = {}
    for bundle in bundles:
        bundles_by_table[bundle.table_id] = bundle
    
    # Track bridges per anchor to enforce limit
    bridges_per_anchor: dict[str, int] = {aid: 0 for aid in anchor_ids}
    
    # First handle existing candidates (promotion) - these have evidence already
    for anchor_id in anchor_ids:
        if bridges_per_anchor[anchor_id] >= _MAX_BRIDGES_PER_ANCHOR:
            continue
            
        for neighbor_id, edge in idx.get_fk_neighbors(anchor_id):
            if bridges_per_anchor[anchor_id] >= _MAX_BRIDGES_PER_ANCHOR:
                break
                
            if neighbor_id in anchor_ids:
                continue  # Don't demote anchors to bridges
            
            neighbor_node = idx.node_by_id.get(neighbor_id)
            if neighbor_node is None or neighbor_node.kind not in _TABLE_KINDS:
                continue
            
            # Skip BCK tables
            if neighbor_node.qualified_name.upper().startswith("BCK"):
                continue
            
            existing_bundle = bundles_by_table.get(neighbor_id)
            if existing_bundle is None:
                continue  # Only promote existing candidates in this pass
            
            # Only promote weak bundles that have some evidence
            if existing_bundle.kind not in (BundleKind.WEAK_DOMAIN, BundleKind.WEAK_FUZZY):
                continue
            
            # Require minimum evidence for promotion
            if existing_bundle.confidence < _WEAK_MIN_EVIDENCE:
                continue
            
            # Build relationship evidence pointing to the anchor
            direction = "outgoing" if edge.from_node == neighbor_id else "incoming"
            anchor_node = idx.node_by_id.get(anchor_id)
            new_rel = RelationshipEvidence(
                edge_id=edge.id,
                edge_kind=edge.kind,
                target_table_id=anchor_id,
                target_table_name=anchor_node.qualified_name if anchor_node else anchor_id,
                direction=direction,
            )
            
            # Create new bridge bundle with existing columns plus relationship
            existing_rels = list(existing_bundle.relationships)
            # Add the relationship to anchor if not already there
            if not any(r.target_table_id == anchor_id for r in existing_rels):
                existing_rels.append(new_rel)
            
            promoted = SelectionBundle(
                table_id=existing_bundle.table_id,
                table_name=existing_bundle.table_name,
                kind=BundleKind.BRIDGE_FK,  # Promoted!
                entity_evidence=existing_bundle.entity_evidence,
                story_terms_matched=existing_bundle.story_terms_matched,
                concept_count=existing_bundle.concept_count,
                confidence=max(existing_bundle.confidence, 0.5),  # Boost confidence
                columns=existing_bundle.columns,
                relationships=tuple(existing_rels),
                marginal_benefit=compute_marginal_benefit(
                    existing_bundle.concept_count,
                    0.5,  # Bridge confidence
                    existing_bundle.object_cost,
                    BundleKind.BRIDGE_FK,
                ),
                match_reason=f"fk_bridge_promoted:{anchor_id[:20]}",
                family_prefix=existing_bundle.family_prefix,
            )
            # Replace in bundles list
            bundles_by_table[neighbor_id] = promoted
            # Find and replace in bundles list
            for i, b in enumerate(bundles):
                if b.table_id == neighbor_id:
                    bundles[i] = promoted
                    break
            
            bridges_per_anchor[anchor_id] += 1
    
    # Second pass: create new bridge bundles only for high-value neighbors
    # SKIP this for now - only use bridges that have existing evidence (promotion)
    # This prevents FK flooding from pure structural neighbors
    
    return bundles


# ---------------------------------------------------------------------------
# Bundle Selection with Family Suppression and Budget
# ---------------------------------------------------------------------------

def _classify_columns(columns: tuple[ColumnEvidence, ...]) -> tuple[
    list[ColumnEvidence],  # story_matched (truly mandatory)
    list[ColumnEvidence],  # pk_columns (important but can be trimmed)
    list[ColumnEvidence],  # fk_columns (needed for relationships)
    list[ColumnEvidence],  # optional (descriptive only)
]:
    """Classify columns by priority.
    
    Story-matched columns (highest priority, truly mandatory):
    - story_matched: Explicitly mentioned in story
    
    PK columns (important, included when budget allows):
    - pk_column: Primary key for identity
    
    FK columns (included only if relationship is selected):
    - fk_column: Foreign key columns
    
    Optional columns:
    - Any other descriptive columns
    
    NOTE: verified_complete category was removed because blindly including
    ALL columns causes budget overflow and pack-specific overfitting.
    """
    story_matched = []
    pk_cols = []
    fk_cols = []
    optional = []
    for col in columns:
        if col.reason == "story_matched":
            story_matched.append(col)
        elif col.reason == "pk_column":
            pk_cols.append(col)
        elif col.reason == "fk_column":
            fk_cols.append(col)
        else:
            optional.append(col)
    return story_matched, pk_cols, fk_cols, optional


def _compute_mandatory_closure_cost(
    bundle: SelectionBundle,
    include_entity: bool,
    include_pk_columns: bool,
    include_fk_columns: bool,
) -> int:
    """Compute the cost of a bundle's closure.
    
    Closure includes:
    - 1 table node (always)
    - 1 entity node (only if include_entity=True AND bundle has entity_id)
    - Story-matched columns (always included)
    - PK columns (if include_pk_columns=True)
    - FK columns (if include_fk_columns=True)
    """
    cost = 1  # Table node
    
    if include_entity and bundle.entity_id:
        cost += 1
    
    story_matched, pk_cols, fk_cols, _ = _classify_columns(bundle.columns)
    cost += len(story_matched)  # Always include story-matched
    
    if include_pk_columns:
        cost += len(pk_cols)
    
    if include_fk_columns:
        cost += len(fk_cols)
    
    return cost


def _create_bundle_with_closure(
    bundle: SelectionBundle,
    include_entity: bool,
    include_pk_columns: bool,
    include_fk_columns: bool,
) -> SelectionBundle:
    """Create a bundle with specified closure level."""
    story_matched, pk_cols, fk_cols, _ = _classify_columns(bundle.columns)
    
    # Include story-matched columns (always mandatory)
    columns_to_keep = list(story_matched)
    if include_pk_columns:
        columns_to_keep.extend(pk_cols)
    if include_fk_columns:
        columns_to_keep.extend(fk_cols)
    
    return SelectionBundle(
        table_id=bundle.table_id,
        table_name=bundle.table_name,
        kind=bundle.kind,
        entity_id=bundle.entity_id if include_entity else None,
        entity_evidence=bundle.entity_evidence,
        story_terms_matched=bundle.story_terms_matched,
        concept_count=bundle.concept_count,
        confidence=bundle.confidence,
        columns=tuple(columns_to_keep),
        relationships=bundle.relationships,
        marginal_benefit=bundle.marginal_benefit,
        match_reason=bundle.match_reason,
        family_prefix=bundle.family_prefix,
    )


def select_bundles(
    bundles: list[SelectionBundle],
    max_objects: int = 60,
    max_per_family: int = _MAX_PER_FAMILY,
) -> BundleSelectionResult:
    """Select bundles under budget with family suppression and entity limits.
    
    STEP 5B: Evidence-based selection to prevent table/entity flooding.
    
    BUDGET ALLOCATION:
    - Max 50% of budget for tables (30 out of 60)
    - Max 3 entity nodes total
    - Remaining budget for columns of high-value anchors
    
    SELECTION PRIORITY:
    1. ANCHOR_EXACT (explicit table names in story) - always include
    2. ANCHOR_ENTITY (high-IDF entity matches) - limit entity nodes
    3. ANCHOR_CONCEPT (multiple rare concepts) - require evidence
    4. BRIDGE_FK (promoted from weak) - only if connects anchors
    5. WEAK_DOMAIN (domain segment match) - fill remaining budget
    
    Pass 2: Enrich selected anchors with columns (PK, FK, story-matched)
    """
    if max_objects <= 0:
        return BundleSelectionResult(
            selected_bundles=(),
            evicted_bundles=tuple(bundles),
            total_objects=0,
            budget_used=0.0,
            family_suppressions=0,
        )
    
    # Budget allocation
    # For very small budgets (<= 10), don't apply table cap (allow all budget for exact matches)
    # For larger budgets, reserve 50% for columns
    if max_objects <= 10:
        max_tables = max_objects  # Use full budget for exact matches in small contexts
    else:
        max_tables = max(10, int(max_objects * _MAX_TABLES_FRACTION))
    max_entities = _MAX_ENTITY_NODES
    
    # Sort by quality (best first)
    sorted_bundles = sorted(bundles, key=lambda b: b.sort_key())
    
    selected_cores: list[tuple[SelectionBundle, bool, bool]] = []  # (bundle, include_entity, is_bridge)
    evicted: list[SelectionBundle] = []
    family_counts: dict[str, int] = {}
    family_suppressions = 0
    table_count = 0
    entity_count = 0
    selected_table_ids: set[str] = set()
    
    # --- Pass 1: Select bundle cores with limits ---
    
    # Separate by kind
    exact_anchors: list[SelectionBundle] = []
    entity_anchors: list[SelectionBundle] = []
    concept_anchors: list[SelectionBundle] = []
    bridges: list[SelectionBundle] = []
    weak_matches: list[SelectionBundle] = []
    
    for bundle in sorted_bundles:
        if bundle.kind == BundleKind.ANCHOR_EXACT:
            exact_anchors.append(bundle)
        elif bundle.kind == BundleKind.ANCHOR_ENTITY:
            entity_anchors.append(bundle)
        elif bundle.kind == BundleKind.ANCHOR_CONCEPT:
            concept_anchors.append(bundle)
        elif bundle.kind in (BundleKind.BRIDGE_FK, BundleKind.BRIDGE_VIEW, BundleKind.BRIDGE_SYNONYM):
            bridges.append(bundle)
        else:
            weak_matches.append(bundle)
    
    # 1. Select exact anchors (always include, no entity node)
    for bundle in exact_anchors:
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        if table_count >= max_tables:
            evicted.append(bundle)
            continue
        
        # Hard cap check: ensure total nodes don't exceed max_objects
        if (table_count + entity_count + 1) > max_objects:
            evicted.append(bundle)
            continue
        
        selected_cores.append((bundle, False, False))  # No entity for exact matches
        selected_table_ids.add(bundle.table_id)
        table_count += 1
        
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # 2. Select entity anchors (limit entity nodes)
    for bundle in entity_anchors:
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        if table_count >= max_tables:
            evicted.append(bundle)
            continue
        
        # Check entity limit and hard cap
        # Entity adds 1 extra node, so check if total would exceed max_objects
        include_entity = (
            bundle.entity_id is not None 
            and entity_count < max_entities
            and (table_count + entity_count + 2) <= max_objects  # +2 for this table + entity
        )
        
        # If adding this table would exceed budget, skip
        if (table_count + entity_count + 1) > max_objects:
            evicted.append(bundle)
            continue
        
        selected_cores.append((bundle, include_entity, False))
        selected_table_ids.add(bundle.table_id)
        table_count += 1
        if include_entity:
            entity_count += 1
        
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # 3. Select concept anchors (require evidence)
    for bundle in concept_anchors:
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        # Require minimum evidence (concept_count >= 2)
        if bundle.concept_count < _ANCHOR_MIN_CONCEPTS:
            evicted.append(bundle)
            continue
        
        if table_count >= max_tables:
            evicted.append(bundle)
            continue
        
        # Hard cap check
        if (table_count + entity_count + 1) > max_objects:
            evicted.append(bundle)
            continue
        
        selected_cores.append((bundle, False, False))
        selected_table_ids.add(bundle.table_id)
        table_count += 1
        
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # 4. Select bridges (only if connects anchors)
    for bundle in bridges:
        connects_anchor = any(rel.target_table_id in selected_table_ids for rel in bundle.relationships)
        if not connects_anchor:
            evicted.append(bundle)
            continue
        
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        if table_count >= max_tables:
            evicted.append(bundle)
            continue
        
        # Hard cap check
        if (table_count + entity_count + 1) > max_objects:
            evicted.append(bundle)
            continue
        
        selected_cores.append((bundle, False, True))  # Bridges marked as is_bridge=True
        selected_table_ids.add(bundle.table_id)
        table_count += 1
        
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # 5. Select weak matches (fill remaining table budget)
    for bundle in weak_matches:
        # Skip weak matches with very low confidence
        if bundle.confidence < _WEAK_MIN_EVIDENCE:
            evicted.append(bundle)
            continue
        
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        if table_count >= max_tables:
            evicted.append(bundle)
            continue
        
        # Hard cap check
        if (table_count + entity_count + 1) > max_objects:
            evicted.append(bundle)
            continue
        
        selected_cores.append((bundle, False, False))
        selected_table_ids.add(bundle.table_id)
        table_count += 1
        
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # --- Pass 2: Enrich with columns ---
    # Budget for columns = max_objects - table_count - entity_count
    column_budget = max_objects - table_count - entity_count
    
    # Collect all column candidates
    # Priority: story-matched > PK > FK
    story_matched_cols: list[tuple[int, ColumnEvidence]] = []
    pk_candidates: list[tuple[int, ColumnEvidence]] = []
    fk_candidates: list[tuple[int, ColumnEvidence]] = []
    
    for i, (bundle, _include_entity, is_bridge) in enumerate(selected_cores):
        story_matched, pk_cols, fk_cols, _ = _classify_columns(bundle.columns)
        
        for col in story_matched:
            story_matched_cols.append((i, col))
        
        for col in pk_cols:
            pk_candidates.append((i, col))
        
        # FK columns for all bundles (not just bridges)
        for col in fk_cols:
            fk_candidates.append((i, col))
    
    # Sort by column name for determinism
    story_matched_cols.sort(key=lambda x: x[1].column_name)
    pk_candidates.sort(key=lambda x: x[1].column_name)
    fk_candidates.sort(key=lambda x: x[1].column_name)
    
    # Allocate columns
    columns_by_core: dict[int, list[ColumnEvidence]] = {i: [] for i in range(len(selected_cores))}
    columns_added = 0
    
    # Story-matched columns first (highest priority)
    for core_idx, col in story_matched_cols:
        if columns_added >= column_budget:
            break
        columns_by_core[core_idx].append(col)
        columns_added += 1
    
    # Then PK columns
    for core_idx, col in pk_candidates:
        if columns_added >= column_budget:
            break
        columns_by_core[core_idx].append(col)
        columns_added += 1
    
    # Then FK columns
    for core_idx, col in fk_candidates:
        if columns_added >= column_budget:
            break
        columns_by_core[core_idx].append(col)
        columns_added += 1
    
    # Build final bundles
    selected: list[SelectionBundle] = []
    total_objects = table_count + entity_count + columns_added
    
    for i, (bundle, include_entity, _is_bridge) in enumerate(selected_cores):
        all_columns = columns_by_core[i]
        
        final_bundle = SelectionBundle(
            table_id=bundle.table_id,
            table_name=bundle.table_name,
            kind=bundle.kind,
            entity_id=bundle.entity_id if include_entity else None,
            entity_evidence=bundle.entity_evidence,
            story_terms_matched=bundle.story_terms_matched,
            concept_count=bundle.concept_count,
            confidence=bundle.confidence,
            columns=tuple(all_columns),
            relationships=bundle.relationships,
            marginal_benefit=bundle.marginal_benefit,
            match_reason=bundle.match_reason,
            family_prefix=bundle.family_prefix,
        )
        selected.append(final_bundle)
    
    return BundleSelectionResult(
        selected_bundles=tuple(selected),
        evicted_bundles=tuple(evicted),
        total_objects=total_objects,
        budget_used=total_objects / max_objects if max_objects > 0 else 0.0,
        family_suppressions=family_suppressions,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _expand_view_dependencies(
    selected_bundles: list[SelectionBundle],
    idx: _BundleGraphIndex,
    max_view_deps_primary: int = 15,
    max_view_deps_other: int = 3,
) -> list[SelectionBundle]:
    """Expand view/MV bundles to include their source table dependencies.

    For each selected view or materialized view, find its READS_FROM edges
    and create bundles for the source tables. This materializes the view's
    evidence closure.

    Primary views (those with 2+ matched story terms) get more dependency
    expansion than secondary views.

    Args:
        selected_bundles: Already-selected bundles
        idx: Graph index
        max_view_deps_primary: Max dependencies for primary views (2+ terms)
        max_view_deps_other: Max dependencies for secondary views

    Returns:
        List of dependency bundles to add
    """
    from .models import EdgeKind, NodeKind

    dependency_bundles: list[SelectionBundle] = []
    selected_table_ids = {b.table_id for b in selected_bundles}

    # Sort bundles to process primary (multi-term) views first
    sorted_bundles = sorted(
        selected_bundles,
        key=lambda b: (-len(b.story_terms_matched), -b.confidence),
    )

    for bundle in sorted_bundles:
        table_node = idx.node_by_id.get(bundle.table_id)
        if table_node is None:
            continue

        # Only expand views and materialized views
        if table_node.kind not in (NodeKind.VIEW.value, NodeKind.MATERIALIZED_VIEW.value):
            continue

        # Determine max deps based on term match quality
        is_primary = len(bundle.story_terms_matched) >= 2
        max_deps = max_view_deps_primary if is_primary else max_view_deps_other

        # Find READS_FROM edges from this view
        outgoing = idx.outgoing_edges.get(bundle.table_id, [])
        
        # Sort edges deterministically by source table name
        reads_from_edges = [
            e for e in outgoing if e.kind == EdgeKind.READS_FROM.value
        ]
        reads_from_edges.sort(
            key=lambda e: dict(e.properties).get("source_table", "")
        )
        
        dep_count = 0
        for edge in reads_from_edges:
            if dep_count >= max_deps:
                break

            # Get source table name from edge properties
            props = dict(edge.properties)
            source_table = props.get("source_table")
            if not source_table:
                continue

            # Find the actual table node by name
            source_upper = source_table.upper()
            source_nodes = idx.table_by_short_name.get(source_upper, [])
            if not source_nodes:
                continue

            source_node = source_nodes[0]

            # Skip if already selected
            if source_node.id in selected_table_ids:
                continue

            # Create a dependency bundle for this source table
            dep_bundle = SelectionBundle(
                table_id=source_node.id,
                table_name=source_node.qualified_name,
                kind=BundleKind.BRIDGE_VIEW,
                entity_id=None,
                entity_evidence=None,
                story_terms_matched=bundle.story_terms_matched,  # Inherit from parent view
                concept_count=0,
                confidence=0.8,  # High confidence - it's a verified view dependency
                columns=(),  # Columns will be added later
                relationships=(),
                object_cost=1,
                marginal_benefit=bundle.marginal_benefit * 0.9,  # Slightly lower than parent
                match_reason=f"source_table_of:{bundle.table_name}",
                family_prefix=compute_family_prefix(source_node.qualified_name),
            )

            dependency_bundles.append(dep_bundle)
            selected_table_ids.add(source_node.id)
            dep_count += 1

    return dependency_bundles


def build_and_select_bundles(
    graph: DatabaseGraph,
    story_text: str,
    *,
    max_objects: int = 60,
    max_per_family: int = _MAX_PER_FAMILY,
) -> BundleSelectionResult:
    """Build and select evidence-backed bundles for a story.
    
    This is the main entry point for bundle-based selection.
    
    When views are selected, their source table dependencies are automatically
    included to materialize the view's evidence closure.
    
    Args:
        graph: The reconciled DatabaseGraph
        story_text: Story or impediment text
        max_objects: Maximum total objects in selection
        max_per_family: Maximum bundles per family prefix
    
    Returns:
        BundleSelectionResult with selected and evicted bundles
    """
    idx = _BundleGraphIndex(graph)
    terms = _extract_terms(story_text)
    idf = _compute_idf(terms, idx)
    bundles = _build_candidate_bundles(terms, idx, idf)
    result = select_bundles(bundles, max_objects, max_per_family)

    # Expand view dependencies
    dep_bundles = _expand_view_dependencies(list(result.selected_bundles), idx)
    if dep_bundles:
        # Add dependency bundles to selected list
        all_selected = list(result.selected_bundles) + dep_bundles
        return BundleSelectionResult(
            selected_bundles=tuple(all_selected),
            evicted_bundles=result.evicted_bundles,
            total_objects=result.total_objects + len(dep_bundles),
            budget_used=result.budget_used,
            family_suppressions=result.family_suppressions,
        )

    return result
