"""
Selection Bundles for evidence-backed database context selection.

A SelectionBundle represents a complete, atomic unit of selection:
a table/view with its matched evidence, required columns, and relationships.
Bundles are never partially evicted - the entire bundle survives or is removed.

This replaces fixed quota splits (75/25) with dynamic budget allocation
based on evidence strength and incremental cost.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, FrozenSet

from .models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    NodeKind,
    canonical_json,
)


class BundleKind(Enum):
    """Classification of selection bundles by evidence and role."""
    
    # High-confidence anchors: story-matched tables with strong evidence
    ANCHOR_EXACT = "anchor_exact"       # Exact table name match in story
    ANCHOR_ENTITY = "anchor_entity"     # JPA entity match → table mapping
    ANCHOR_CONCEPT = "anchor_concept"   # Multi-concept evidence match
    
    # Bridge bundles: connect anchors via relationships
    BRIDGE_FK = "bridge_fk"             # FK-connected to anchor
    BRIDGE_VIEW = "bridge_view"         # View derived from anchor
    BRIDGE_SYNONYM = "bridge_synonym"   # Synonym alias of anchor
    
    # Weak matches: single-term or fuzzy matches
    WEAK_DOMAIN = "weak_domain"         # Single domain term match
    WEAK_FUZZY = "weak_fuzzy"           # Substring/fuzzy match only


@dataclass(frozen=True, slots=True)
class ColumnEvidence:
    """Evidence for why a column is included in a bundle."""
    
    column_id: str
    column_name: str
    reason: str  # 'story_matched', 'pk_column', 'fk_column', 'join_column'
    story_term: str | None = None  # The term that matched, if any
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "column_id": self.column_id,
            "column_name": self.column_name,
            "reason": self.reason,
            "story_term": self.story_term,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnEvidence:
        return cls(
            column_id=str(data["column_id"]),
            column_name=str(data["column_name"]),
            reason=str(data["reason"]),
            story_term=data.get("story_term"),
        )


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    """Evidence for a relationship included in a bundle."""
    
    edge_id: str
    edge_kind: str  # FOREIGN_KEY_TO, DERIVED_FROM, etc.
    target_table_id: str
    target_table_name: str
    direction: str  # 'outgoing' or 'incoming'
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_kind": self.edge_kind,
            "target_table_id": self.target_table_id,
            "target_table_name": self.target_table_name,
            "direction": self.direction,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelationshipEvidence:
        return cls(
            edge_id=str(data["edge_id"]),
            edge_kind=str(data["edge_kind"]),
            target_table_id=str(data["target_table_id"]),
            target_table_name=str(data["target_table_name"]),
            direction=str(data["direction"]),
        )


@dataclass(frozen=True, slots=True)
class SelectionBundle:
    """An atomic selection unit: table + evidence + required columns + relationships.
    
    Bundles are the unit of selection and eviction. A bundle is never partially
    selected - all its components (table, columns, relationships) survive or are
    evicted together.
    
    Attributes:
        table_id: Node ID of the primary table/view
        table_name: Qualified name of the table/view
        kind: Classification of the bundle (anchor, bridge, weak)
        
        # Evidence fields
        entity_evidence: JPA entity that maps to this table (if any)
        story_terms_matched: Story terms that matched this table's evidence
        concept_count: Number of distinct story concepts covered
        confidence: Confidence score (0.0-1.0) based on evidence strength
        
        # Required columns (not all table columns, just essential ones)
        columns: Story-matched and structurally-required columns
        
        # Relationships
        relationships: FK/view/synonym relationships to include
        
        # Cost and scoring
        object_cost: Total objects in this bundle (1 table + N columns)
        marginal_benefit: Benefit per incremental cost (higher = better)
        
        # Provenance
        match_reason: Human-readable explanation of why matched
        family_prefix: 4-segment prefix for family grouping (TB_GRP_PR_AI)
    """
    
    table_id: str
    table_name: str
    kind: BundleKind
    
    # Evidence
    entity_id: str | None = None  # Node ID of the entity (for MAPS_TO_TABLE edge)
    entity_evidence: str | None = None  # Entity qualified name
    story_terms_matched: tuple[str, ...] = ()
    concept_count: int = 0
    confidence: float = 0.0
    
    # Required columns
    columns: tuple[ColumnEvidence, ...] = ()
    
    # Relationships
    relationships: tuple[RelationshipEvidence, ...] = ()
    
    # Cost and scoring
    object_cost: int = 1  # At minimum, the table itself
    marginal_benefit: float = 0.0
    
    # Provenance
    match_reason: str = ""
    family_prefix: str = ""
    
    def __post_init__(self) -> None:
        # Ensure tuples
        object.__setattr__(self, "story_terms_matched", tuple(self.story_terms_matched))
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "relationships", tuple(self.relationships))
        
        # Compute object cost: table + columns
        # (relationships don't count as objects, only their endpoints do)
        cost = 1 + len(self.columns)
        object.__setattr__(self, "object_cost", cost)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "table_name": self.table_name,
            "kind": self.kind.value,
            "entity_id": self.entity_id,
            "entity_evidence": self.entity_evidence,
            "story_terms_matched": list(self.story_terms_matched),
            "concept_count": self.concept_count,
            "confidence": self.confidence,
            "columns": [c.to_dict() for c in self.columns],
            "relationships": [r.to_dict() for r in self.relationships],
            "object_cost": self.object_cost,
            "marginal_benefit": self.marginal_benefit,
            "match_reason": self.match_reason,
            "family_prefix": self.family_prefix,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionBundle:
        return cls(
            table_id=str(data["table_id"]),
            table_name=str(data["table_name"]),
            kind=BundleKind(data["kind"]),
            entity_id=data.get("entity_id"),
            entity_evidence=data.get("entity_evidence"),
            story_terms_matched=tuple(data.get("story_terms_matched", ())),
            concept_count=int(data.get("concept_count", 0)),
            confidence=float(data.get("confidence", 0.0)),
            columns=tuple(
                ColumnEvidence.from_dict(c) for c in data.get("columns", ())
            ),
            relationships=tuple(
                RelationshipEvidence.from_dict(r) for r in data.get("relationships", ())
            ),
            marginal_benefit=float(data.get("marginal_benefit", 0.0)),
            match_reason=str(data.get("match_reason", "")),
            family_prefix=str(data.get("family_prefix", "")),
        )
    
    def sort_key(self) -> tuple[int, int, float, float, int, str]:
        """Sort key for bundle selection: kind priority, -concept_count, -confidence, -benefit, cost, id.
        
        Lower kind value = higher priority:
        - ANCHOR_EXACT (0) > ANCHOR_ENTITY (1) > ANCHOR_CONCEPT (2)
        - BRIDGE_* (3-5) > WEAK_* (6-7)
        """
        kind_priority = {
            BundleKind.ANCHOR_EXACT: 0,
            BundleKind.ANCHOR_ENTITY: 1,
            BundleKind.ANCHOR_CONCEPT: 2,
            BundleKind.BRIDGE_FK: 3,
            BundleKind.BRIDGE_VIEW: 4,
            BundleKind.BRIDGE_SYNONYM: 5,
            BundleKind.WEAK_DOMAIN: 6,
            BundleKind.WEAK_FUZZY: 7,
        }.get(self.kind, 99)
        
        return (
            kind_priority,
            -self.concept_count,
            -self.confidence,
            -self.marginal_benefit,
            self.object_cost,  # Lower cost is better (tie-break)
            self.table_id,     # Deterministic tie-break
        )


@dataclass(frozen=True, slots=True)
class BundleSelectionResult:
    """Result of bundle-based context selection.
    
    Attributes:
        selected_bundles: Bundles included in the final selection
        evicted_bundles: Bundles that were considered but evicted
        total_objects: Total object count in selected bundles
        budget_used: Percentage of max_objects budget used
        family_suppressions: Count of bundles suppressed by family limits
    """
    
    selected_bundles: tuple[SelectionBundle, ...]
    evicted_bundles: tuple[SelectionBundle, ...]
    total_objects: int
    budget_used: float
    family_suppressions: int
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_bundles": [b.to_dict() for b in self.selected_bundles],
            "evicted_bundles": [b.to_dict() for b in self.evicted_bundles],
            "total_objects": self.total_objects,
            "budget_used": self.budget_used,
            "family_suppressions": self.family_suppressions,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleSelectionResult:
        return cls(
            selected_bundles=tuple(
                SelectionBundle.from_dict(b) for b in data.get("selected_bundles", ())
            ),
            evicted_bundles=tuple(
                SelectionBundle.from_dict(b) for b in data.get("evicted_bundles", ())
            ),
            total_objects=int(data.get("total_objects", 0)),
            budget_used=float(data.get("budget_used", 0.0)),
            family_suppressions=int(data.get("family_suppressions", 0)),
        )


def compute_family_prefix(table_name: str) -> str:
    """Extract 3-segment underscore prefix for family grouping.
    
    Examples:
        TB_GRP_PR_AI_GR -> TB_GRP_PR
        TB_GRP_PAYCALC_CFS -> TB_GRP_PAYCALC
        TB_GRP_PF_FEATURE -> TB_GRP_PF
        TB_RT_SESSION -> (empty, only 3 segments)
    
    Returns empty string for names with fewer than 4 segments.
    """
    short = table_name.rsplit(".", 1)[-1].upper()
    parts = short.split("_")
    if len(parts) >= 4:
        return "_".join(parts[:3])
    return ""


def compute_marginal_benefit(
    concept_count: int,
    confidence: float,
    object_cost: int,
    kind: BundleKind,
) -> float:
    """Compute marginal benefit per incremental cost.
    
    Formula: (concept_weight * concept_count + confidence_weight * confidence + kind_bonus) / cost
    
    Higher values indicate better value per object.
    """
    # Weights
    CONCEPT_WEIGHT = 10.0
    CONFIDENCE_WEIGHT = 5.0
    
    # Kind bonuses (anchors get bonus, weak matches get penalty)
    kind_bonus = {
        BundleKind.ANCHOR_EXACT: 20.0,
        BundleKind.ANCHOR_ENTITY: 15.0,
        BundleKind.ANCHOR_CONCEPT: 12.0,
        BundleKind.BRIDGE_FK: 5.0,
        BundleKind.BRIDGE_VIEW: 5.0,
        BundleKind.BRIDGE_SYNONYM: 3.0,
        BundleKind.WEAK_DOMAIN: 0.0,
        BundleKind.WEAK_FUZZY: -5.0,
    }.get(kind, 0.0)
    
    benefit = (
        CONCEPT_WEIGHT * concept_count +
        CONFIDENCE_WEIGHT * confidence +
        kind_bonus
    )
    
    # Avoid division by zero
    cost = max(object_cost, 1)
    
    return benefit / cost
