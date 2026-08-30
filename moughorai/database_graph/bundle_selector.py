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
    for entity_nodes in idx.entity_by_short_name.values():
        for entity_node in entity_nodes:
            entity_short = entity_node.qualified_name.rsplit(".", 1)[-1]
            entity_words = _split_camel_case(entity_short)
            
            # Check full name match
            full_match = entity_short.lower() in terms_lower
            
            # Count word matches
            word_hits = [w for w in entity_words if w in terms_lower or w in terms_normalized]
            
            if not full_match and len(word_hits) < 2:
                continue  # Need at least 2-word match for entity bridge
            
            # Find target table
            table_id = idx.entity_to_table.get(entity_node.id)
            if table_id is None:
                continue
            
            table_node = idx.node_by_id.get(table_id)
            if table_node is None:
                continue
            
            confidence = 1.0 if full_match else 0.7 + 0.1 * len(word_hits)
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
    
    # --- Phase 3: Domain segment matches ---
    for term in terms:
        term_variants = _normalize_plural(term.lower())
        term_variants_upper = {v.upper() for v in term_variants}
        
        for table_nodes in idx.table_by_short_name.values():
            for node in table_nodes:
                if node.id in candidates:
                    continue  # Already matched
                
                short = node.qualified_name.rsplit(".", 1)[-1].upper()
                segments = short.split("_")
                
                if term in segments or term_variants_upper.intersection(segments):
                    candidates[node.id] = _CandidateMatch(
                        table_id=node.id,
                        table_name=node.qualified_name,
                        match_type="domain",
                        matched_terms=[term],
                        confidence=0.5,
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
        columns: list[ColumnEvidence] = []
        
        # Get PK and FK columns (always include for data tables)
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
        
        # Story-matched columns: search ALL story terms, not just the terms
        # that matched the table name/entity. This ensures columns like CODE
        # and NAME are included when the story mentions them, even if the table
        # was matched via entity bridging (e.g., "Parent" -> PARENT_A).
        seen_col_ids: set[str] = set(pk_cols) | set(fk_cols)
        for term in terms:  # Use all story terms, not match.matched_terms
            col_ids = idx.column_by_name.get(term.upper(), [])
            for col_id in col_ids:
                if col_id in seen_col_ids:
                    continue
                col_node = idx.node_by_id.get(col_id)
                if col_node:
                    # Check if this column belongs to this table
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
        if match.entity_id:
            ent_node = idx.node_by_id.get(match.entity_id)
            if ent_node:
                entity_name = ent_node.qualified_name
        
        bundle = SelectionBundle(
            table_id=table_id,
            table_name=match.table_name,
            kind=kind,
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
    # For each anchor, check if its FK neighbors are already candidates.
    # If they are, promote them from weak_* to bridge_fk.
    # If they aren't, create new bridge bundles.
    anchor_ids = {m.table_id for m in candidates.values() 
                  if m.match_type in ("exact", "entity", "concept")}
    
    # First pass: promote existing candidates that are FK neighbors of anchors
    bundles_by_table: dict[str, SelectionBundle] = {}
    for bundle in bundles:
        bundles_by_table[bundle.table_id] = bundle
    
    for anchor_id in anchor_ids:
        for neighbor_id, edge in idx.get_fk_neighbors(anchor_id):
            if neighbor_id in anchor_ids:
                continue  # Don't demote anchors to bridges
            
            neighbor_node = idx.node_by_id.get(neighbor_id)
            if neighbor_node is None or neighbor_node.kind not in _TABLE_KINDS:
                continue
            
            # Skip BCK tables
            if neighbor_node.qualified_name.upper().startswith("BCK"):
                continue
            
            existing_bundle = bundles_by_table.get(neighbor_id)
            
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
            
            if existing_bundle is not None:
                # Promote from weak to bridge (if it's a weak bundle)
                if existing_bundle.kind in (BundleKind.WEAK_DOMAIN, BundleKind.WEAK_FUZZY):
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
                        match_reason=f"fk_bridge_promoted:{anchor_id}",
                        family_prefix=existing_bundle.family_prefix,
                    )
                    # Replace in bundles list
                    bundles_by_table[neighbor_id] = promoted
                    # Find and replace in bundles list
                    for i, b in enumerate(bundles):
                        if b.table_id == neighbor_id:
                            bundles[i] = promoted
                            break
            else:
                # Create new minimal bridge bundle
                pk_cols = idx.pk_columns.get(neighbor_id, set())
                fk_cols = idx.fk_columns.get(neighbor_id, set())
                
                columns: list[ColumnEvidence] = []
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
                    if col_node and col_id not in pk_cols:
                        columns.append(ColumnEvidence(
                            column_id=col_id,
                            column_name=col_node.qualified_name,
                            reason="fk_column",
                        ))
                
                family_prefix = compute_family_prefix(neighbor_node.qualified_name)
                
                bridge_bundle = SelectionBundle(
                    table_id=neighbor_id,
                    table_name=neighbor_node.qualified_name,
                    kind=BundleKind.BRIDGE_FK,
                    story_terms_matched=(),
                    concept_count=0,
                    confidence=0.4,
                    columns=tuple(columns),
                    relationships=(new_rel,),
                    marginal_benefit=compute_marginal_benefit(0, 0.4, 1 + len(columns), BundleKind.BRIDGE_FK),
                    match_reason=f"fk_bridge_of:{anchor_id}",
                    family_prefix=family_prefix,
                )
                bundles.append(bridge_bundle)
                bundles_by_table[neighbor_id] = bridge_bundle
    
    return bundles


# ---------------------------------------------------------------------------
# Bundle Selection with Family Suppression and Budget
# ---------------------------------------------------------------------------

def select_bundles(
    bundles: list[SelectionBundle],
    max_objects: int = 60,
    max_per_family: int = _MAX_PER_FAMILY,
) -> BundleSelectionResult:
    """Select bundles under budget with family suppression.
    
    Algorithm:
    1. Sort bundles by sort_key (anchors first, then by benefit)
    2. Select anchors (ANCHOR_* kinds) with family limits
    3. Select bridges only if they connect selected anchors
    4. Fill remaining budget with weak matches
    5. Evict lowest-marginal-benefit bundles if over budget
    """
    
    # Sort by quality (best first)
    sorted_bundles = sorted(bundles, key=lambda b: b.sort_key())
    
    selected: list[SelectionBundle] = []
    evicted: list[SelectionBundle] = []
    family_counts: dict[str, int] = {}
    family_suppressions = 0
    total_objects = 0
    selected_table_ids: set[str] = set()
    
    # --- Pass 1: Select anchors ---
    anchors: list[SelectionBundle] = []
    non_anchors: list[SelectionBundle] = []
    
    for bundle in sorted_bundles:
        if bundle.kind in (BundleKind.ANCHOR_EXACT, BundleKind.ANCHOR_ENTITY, BundleKind.ANCHOR_CONCEPT):
            anchors.append(bundle)
        else:
            non_anchors.append(bundle)
    
    for bundle in anchors:
        # Check family limit
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        # Check budget
        if total_objects + bundle.object_cost > max_objects:
            evicted.append(bundle)
            continue
        
        # Select this anchor
        selected.append(bundle)
        selected_table_ids.add(bundle.table_id)
        total_objects += bundle.object_cost
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # --- Pass 2: Select bridges that connect selected anchors ---
    bridges_to_consider: list[SelectionBundle] = []
    weak_matches: list[SelectionBundle] = []
    
    for bundle in non_anchors:
        if bundle.kind in (BundleKind.BRIDGE_FK, BundleKind.BRIDGE_VIEW, BundleKind.BRIDGE_SYNONYM):
            bridges_to_consider.append(bundle)
        else:
            weak_matches.append(bundle)
    
    for bundle in bridges_to_consider:
        # Only include bridge if it connects to a selected anchor
        connects_anchor = any(
            rel.target_table_id in selected_table_ids
            for rel in bundle.relationships
        )
        
        if not connects_anchor:
            evicted.append(bundle)
            continue
        
        # Check family limit
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        # Check budget
        if total_objects + bundle.object_cost > max_objects:
            evicted.append(bundle)
            continue
        
        selected.append(bundle)
        selected_table_ids.add(bundle.table_id)
        total_objects += bundle.object_cost
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
    # --- Pass 3: Fill with weak matches if budget allows ---
    for bundle in weak_matches:
        # Check family limit
        if bundle.family_prefix:
            count = family_counts.get(bundle.family_prefix, 0)
            if count >= max_per_family:
                evicted.append(bundle)
                family_suppressions += 1
                continue
        
        # Check budget
        if total_objects + bundle.object_cost > max_objects:
            evicted.append(bundle)
            continue
        
        selected.append(bundle)
        selected_table_ids.add(bundle.table_id)
        total_objects += bundle.object_cost
        if bundle.family_prefix:
            family_counts[bundle.family_prefix] = family_counts.get(bundle.family_prefix, 0) + 1
    
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

def build_and_select_bundles(
    graph: DatabaseGraph,
    story_text: str,
    *,
    max_objects: int = 60,
    max_per_family: int = _MAX_PER_FAMILY,
) -> BundleSelectionResult:
    """Build and select evidence-backed bundles for a story.
    
    This is the main entry point for bundle-based selection.
    
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
    return select_bundles(bundles, max_objects, max_per_family)
