"""Reconcile evidence from multiple sources into a single DatabaseGraph.

Merges Jailer CSV tables, JPA entity extractions, and (future) migration
evidence into one deterministic, frozen, fingerprinted ``DatabaseGraph``.

Reconciliation rules
--------------------
1. Jailer tables are authoritative for physical schema.
2. JPA entities matched to Jailer tables (by resolved table name) produce
   ``MAPS_TO_TABLE`` edges from the java_entity node to the table node and
   ``MAPS_TO_COLUMN`` edges from java_field nodes to column nodes.
3. A fact attested by **both** Jailer and JPA is promoted from ``inferred``
   to ``verified`` (confidence 1.0).
4. BCK/BACK_UP tables are flagged ``historical=True`` and excluded from
   the effective-current graph when ``exclude_backup=True``.
5. Contradictory facts between sources produce a ``ConflictRecord``.
6. Evidence is marked ``incomplete_evidence`` when any significant
   evidence category is missing: no sources, unresolved JPA constants,
   unconsumed FK edges, unscanned migrations, views, or synonyms.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moughorai.database_graph.jailer_ingest import JailerIngestResult
from moughorai.database_graph.jpa_extractor import (
    JpaEntity,
    JpaExtractionResult,
)
from .view_sql_ingest import ViewSqlIngestResult
from .migration_ingest import MigrationIngestResult
from moughorai.database_graph.models import (
    ConflictRecord,
    DatabaseGraph,
    DatabaseGraphCoverage,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
)

logger = logging.getLogger(__name__)

# Re-export for downstream use from provenance module if available.
try:
    from moughorai.semantic_snapshot.provenance import RepositoryProvenance
except ImportError:  # pragma: no cover
    RepositoryProvenance = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECONCILER_EVIDENCE_KIND = "reconciler"
_JPA_EVIDENCE_KIND = "jpa_annotation"
_JAILER_EVIDENCE_KIND = "jailer_csv"

# BCK / BACK_UP detection (same logic as Jailer ingest)
import re as _re

_BCK_PREFIX = _re.compile(r"^BCK", _re.IGNORECASE)
_BACKUP_TOKEN = _re.compile(r"BACK_UP", _re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_id(*parts: str) -> str:
    """Deterministic SHA-256 identifier from ordered parts."""
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_historical(name: str) -> bool:
    """Return True if the name matches BCK/BACK_UP naming convention."""
    upper = name.upper()
    return bool(_BCK_PREFIX.match(upper)) or bool(_BACKUP_TOKEN.search(upper))


def _make_reconciler_evidence(
    *,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
    sources: tuple[EvidenceSource, ...] = (),
    status: str = EvidenceStatus.VERIFIED.value,
    confidence: float = 1.0,
) -> EvidenceRecord:
    """Build a reconciler-stamped EvidenceRecord."""
    return EvidenceRecord(
        status=status,
        confidence=confidence,
        repository_revision=repository_revision,
        workspace_fingerprint=workspace_fingerprint,
        sources=sources,
    )


def _merge_evidence(
    *records: EvidenceRecord,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
) -> EvidenceRecord:
    """Merge multiple evidence records.

    - If all are verified → verified, confidence = max.
    - If any conflict → conflicting.
    - Otherwise → inferred.
    """
    all_sources: list[EvidenceSource] = []
    all_conflicts: list[ConflictRecord] = []
    max_confidence = 0.0
    any_conflicting = False

    for rec in records:
        all_sources.extend(rec.sources)
        all_conflicts.extend(rec.conflicts)
        max_confidence = max(max_confidence, rec.confidence)
        if rec.status == EvidenceStatus.CONFLICTING.value:
            any_conflicting = True

    if any_conflicting:
        status = EvidenceStatus.CONFLICTING.value
    elif len(records) >= 2:
        # Confirmed by multiple sources
        status = EvidenceStatus.VERIFIED.value
        max_confidence = 1.0
    elif len(records) == 1:
        status = records[0].status
    else:
        status = EvidenceStatus.UNKNOWN.value

    return EvidenceRecord(
        status=status,
        confidence=max_confidence,
        repository_revision=repository_revision,
        workspace_fingerprint=workspace_fingerprint,
        sources=tuple(all_sources),
        conflicts=tuple(all_conflicts),
    )


# ---------------------------------------------------------------------------
# JPA → graph nodes
# ---------------------------------------------------------------------------


def _jpa_entity_node(
    entity: JpaEntity,
    *,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
) -> DatabaseGraphNode:
    """Convert a JPA entity to a java_entity graph node."""
    node_id = _stable_id("jpa", "entity", entity.qualified_name)
    properties: list[tuple[str, Any]] = [
        ("class_name", entity.class_name),
        ("qualified_name", entity.qualified_name),
        ("source_path", entity.source_path),
        ("entity_line", entity.entity_line),
        ("is_test", entity.is_test),
    ]
    if entity.table_name:
        properties.append(("table_name", entity.table_name))
        properties.append(("table_name_resolved", entity.table_name_resolved))
    if entity.schema_name:
        properties.append(("schema_name", entity.schema_name))
    if entity.extends_class:
        properties.append(("extends_class", entity.extends_class))
    if entity.has_inheritance:
        properties.append(("has_inheritance", True))
        if entity.inheritance_strategy:
            properties.append(("inheritance_strategy", entity.inheritance_strategy))

    source = EvidenceSource(
        kind=_JPA_EVIDENCE_KIND,
        path=entity.source_path,
        start_line=entity.entity_line,
        end_line=entity.entity_line,
    )
    evidence = EvidenceRecord.verified(
        confidence=1.0,
        repository_revision=repository_revision,
        workspace_fingerprint=workspace_fingerprint,
        sources=(source,),
    )

    return DatabaseGraphNode(
        id=node_id,
        kind=NodeKind.JAVA_ENTITY.value,
        qualified_name=entity.qualified_name,
        schema=entity.schema_name,
        properties=tuple(properties),
        evidence=evidence,
    )


def _jpa_field_nodes(
    entity: JpaEntity,
    *,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
) -> list[tuple[DatabaseGraphNode, str | None]]:
    """Build java_field nodes for each @Column mapping.

    Returns list of (node, column_name_upper) tuples.
    """
    results: list[tuple[DatabaseGraphNode, str | None]] = []
    for col in entity.columns:
        field_qualified = f"{entity.qualified_name}.{col.java_field_name}"
        node_id = _stable_id("jpa", "field", field_qualified)

        properties: list[tuple[str, Any]] = [
            ("java_field_name", col.java_field_name),
            ("column_name", col.column_name),
            ("java_type", col.java_type),
            ("is_id", col.is_id),
            ("nullable", col.nullable),
        ]
        if col.is_lob:
            properties.append(("is_lob", True))

        src = col.source or EvidenceSource(
            kind=_JPA_EVIDENCE_KIND,
            path=entity.source_path,
            start_line=entity.entity_line,
            end_line=entity.entity_line,
        )
        evidence = EvidenceRecord.verified(
            confidence=1.0,
            repository_revision=repository_revision,
            workspace_fingerprint=workspace_fingerprint,
            sources=(src,),
        )

        node = DatabaseGraphNode(
            id=node_id,
            kind=NodeKind.JAVA_FIELD.value,
            qualified_name=field_qualified,
            schema=None,
            properties=tuple(properties),
            evidence=evidence,
        )
        results.append((node, col.column_name.upper() if col.column_name else None))

    # Also include embedded overrides as java_field nodes
    for emb in entity.embedded_overrides:
        field_qualified = (
            f"{entity.qualified_name}.{emb.java_field_name}.{emb.attribute_name}"
        )
        node_id = _stable_id("jpa", "field", field_qualified)

        properties_emb: list[tuple[str, Any]] = [
            ("java_field_name", emb.java_field_name),
            ("attribute_name", emb.attribute_name),
            ("embedded_type", emb.embedded_type),
            ("column_name", emb.column_name),
            ("nullable", emb.nullable),
        ]

        src_emb = emb.source or EvidenceSource(
            kind=_JPA_EVIDENCE_KIND,
            path=entity.source_path,
            start_line=entity.entity_line,
            end_line=entity.entity_line,
        )
        evidence_emb = EvidenceRecord.verified(
            confidence=1.0,
            repository_revision=repository_revision,
            workspace_fingerprint=workspace_fingerprint,
            sources=(src_emb,),
        )

        node = DatabaseGraphNode(
            id=node_id,
            kind=NodeKind.JAVA_FIELD.value,
            qualified_name=field_qualified,
            schema=None,
            properties=tuple(properties_emb),
            evidence=evidence_emb,
        )
        results.append((node, emb.column_name.upper() if emb.column_name else None))

    return results


def _jpa_sequence_nodes(
    entity: JpaEntity,
    *,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
) -> list[DatabaseGraphNode]:
    """Build sequence nodes from JPA @SequenceGenerator annotations."""
    nodes: list[DatabaseGraphNode] = []
    for seq in entity.sequences:
        if not seq.sequence_name_resolved or not seq.sequence_name:
            continue
        seq_name = seq.sequence_name.upper()
        node_id = _stable_id("jpa", "sequence", seq_name)
        properties: list[tuple[str, Any]] = [
            ("generator_name", seq.generator_name),
            ("sequence_name", seq.sequence_name),
            ("initial_value", seq.initial_value),
            ("allocation_size", seq.allocation_size),
            ("entity_class", entity.qualified_name),
        ]

        src = seq.source or EvidenceSource(
            kind=_JPA_EVIDENCE_KIND,
            path=entity.source_path,
            start_line=entity.entity_line,
            end_line=entity.entity_line,
        )
        evidence = EvidenceRecord.verified(
            confidence=1.0,
            repository_revision=repository_revision,
            workspace_fingerprint=workspace_fingerprint,
            sources=(src,),
        )
        node = DatabaseGraphNode(
            id=node_id,
            kind=NodeKind.SEQUENCE.value,
            qualified_name=seq_name,
            schema=None,
            properties=tuple(properties),
            evidence=evidence,
        )
        nodes.append(node)
    return nodes


def _jpa_relationship_edges(
    entity: JpaEntity,
    entity_node_id: str,
    entity_index: dict[str, JpaEntity],
    *,
    repository_revision: str | None = None,
    workspace_fingerprint: str | None = None,
) -> list[DatabaseGraphEdge]:
    """Build JAVA_RELATION_TO edges for LazySetProvider/LazyCollectionProvider."""
    edges: list[DatabaseGraphEdge] = []
    for rel in entity.relationships:
        # Find the target entity by class name
        target_entity: JpaEntity | None = None
        for candidate in entity_index.values():
            if candidate.class_name == rel.target_type:
                target_entity = candidate
                break

        if target_entity is None:
            continue

        target_node_id = _stable_id("jpa", "entity", target_entity.qualified_name)
        edge_id = _stable_id(
            "jpa", "relation",
            entity.qualified_name, rel.java_field_name,
            target_entity.qualified_name,
        )

        properties: list[tuple[str, Any]] = [
            ("java_field_name", rel.java_field_name),
            ("target_type", rel.target_type),
            ("foreign_key_field", rel.foreign_key_field),
            ("foreign_key_resolved", rel.foreign_key_resolved),
            ("collection_name", rel.collection_name),
            ("provider_kind", rel.provider_kind),
        ]

        src = rel.source or EvidenceSource(
            kind=_JPA_EVIDENCE_KIND,
            path=entity.source_path,
            start_line=entity.entity_line,
            end_line=entity.entity_line,
        )
        evidence = EvidenceRecord.verified(
            confidence=1.0,
            repository_revision=repository_revision,
            workspace_fingerprint=workspace_fingerprint,
            sources=(src,),
        )

        edge = DatabaseGraphEdge(
            id=edge_id,
            kind=EdgeKind.JAVA_RELATION_TO.value,
            from_node=entity_node_id,
            to_node=target_node_id,
            properties=tuple(properties),
            evidence=evidence,
        )
        edges.append(edge)

    return edges


# ---------------------------------------------------------------------------
# Matching / reconciliation
# ---------------------------------------------------------------------------


@dataclass
class _MatchResult:
    """Intermediate matching state for a single JPA entity → Jailer table."""

    entity: JpaEntity
    entity_node_id: str
    jailer_table_node: DatabaseGraphNode | None
    jailer_table_name: str  # upper
    matched: bool
    column_matches: list[tuple[str, str | None]]  # (col_name_upper, jailer_col_node_id | None)
    conflicts: list[ConflictRecord]


def _match_entity_to_table(
    entity: JpaEntity,
    entity_node_id: str,
    jailer_tables: dict[str, DatabaseGraphNode],
    jailer_columns: dict[str, DatabaseGraphNode],
) -> _MatchResult:
    """Match a JPA entity to a Jailer table and its columns.

    ``jailer_columns`` maps ``TABLE_NAME.COLUMN_NAME`` → column node.
    """
    table_name = (entity.table_name or "").upper()
    jailer_node = jailer_tables.get(table_name)
    matched = jailer_node is not None

    conflicts: list[ConflictRecord] = []
    column_matches: list[tuple[str, str | None]] = []

    if matched and jailer_node is not None:
        # Match each JPA column to a Jailer column
        jpa_col_names: set[str] = set()
        for col in entity.columns:
            col_upper = col.column_name.upper()
            jpa_col_names.add(col_upper)
            key = f"{table_name}.{col_upper}"
            jailer_col = jailer_columns.get(key)
            column_matches.append((col_upper, jailer_col.id if jailer_col else None))

            if jailer_col is None:
                # JPA column not in Jailer — potential conflict
                conflicts.append(ConflictRecord(
                    description=(
                        f"Column {col_upper} in JPA entity {entity.class_name} "
                        f"(@Table={table_name}) not found in Jailer column.csv"
                    ),
                    node_ids=(entity_node_id,),
                    sources=(
                        EvidenceSource(
                            kind=_JPA_EVIDENCE_KIND,
                            path=entity.source_path,
                            start_line=col.source.start_line if col.source else entity.entity_line,
                            end_line=col.source.end_line if col.source else entity.entity_line,
                        ),
                    ),
                    resolution="unresolved",
                ))

        # Also match embedded overrides
        for emb in entity.embedded_overrides:
            col_upper = emb.column_name.upper()
            jpa_col_names.add(col_upper)
            key = f"{table_name}.{col_upper}"
            jailer_col = jailer_columns.get(key)
            column_matches.append((col_upper, jailer_col.id if jailer_col else None))

            if jailer_col is None:
                conflicts.append(ConflictRecord(
                    description=(
                        f"Embedded column {col_upper} in JPA entity {entity.class_name} "
                        f"(@Table={table_name}) not found in Jailer column.csv"
                    ),
                    node_ids=(entity_node_id,),
                    sources=(
                        EvidenceSource(
                            kind=_JPA_EVIDENCE_KIND,
                            path=entity.source_path,
                            start_line=emb.source.start_line if emb.source else entity.entity_line,
                            end_line=emb.source.end_line if emb.source else entity.entity_line,
                        ),
                    ),
                    resolution="unresolved",
                ))

    return _MatchResult(
        entity=entity,
        entity_node_id=entity_node_id,
        jailer_table_node=jailer_node,
        jailer_table_name=table_name,
        matched=matched,
        column_matches=column_matches,
        conflicts=conflicts,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reconcile_database_graph(
    repository_root: Path,
    jailer_result: JailerIngestResult | None,
    jpa_result: JpaExtractionResult | None,
    view_result: ViewSqlIngestResult | None = None,
    provenance: Any | None = None,
    workspace_fingerprint: str = "",
    exclude_backup: bool = True,
    migration_result: MigrationIngestResult | None = None,
    synonym_result: "SynonymIngestResult | None" = None,
) -> DatabaseGraph:
    """Reconcile Jailer and JPA evidence into a single DatabaseGraph.

    Args:
        repository_root: Absolute path to the repository root.
        jailer_result: Jailer CSV ingest result, or None.
        jpa_result: JPA extraction result, or None.
        provenance: RepositoryProvenance instance or None.
        workspace_fingerprint: Atlas workspace fingerprint string.
        exclude_backup: When True, BCK/BACK_UP tables are excluded from the
            effective graph (they are still recorded in metadata).

    Returns:
        A frozen, fingerprinted :class:`DatabaseGraph`.
    """
    repository_root = Path(repository_root)

    # Provenance dict for the graph
    if provenance is not None and hasattr(provenance, "to_dict"):
        provenance_dict: dict[str, Any] = provenance.to_dict()
    elif provenance is not None and isinstance(provenance, dict):
        provenance_dict = provenance
    else:
        provenance_dict = {
            "vcs": "none",
            "head_sha": None,
            "head_ref": None,
            "worktree_state": "unknown",
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verification": "unavailable",
        }

    repo_revision = provenance_dict.get("head_sha")
    ws_fp = workspace_fingerprint or None

    # Collect everything
    all_nodes: list[DatabaseGraphNode] = []
    all_edges: list[DatabaseGraphEdge] = []
    all_conflicts: list[ConflictRecord] = []

    # -----------------------------------------------------------------------
    # Phase 1: Jailer nodes and edges
    # -----------------------------------------------------------------------
    jailer_tables: dict[str, DatabaseGraphNode] = {}   # UPPER name → node
    jailer_columns: dict[str, DatabaseGraphNode] = {}  # TABLE.COLUMN → node
    jailer_fk_table_pairs: dict[tuple[str, str], DatabaseGraphEdge] = {}

    historical_table_names: set[str] = set()

    if jailer_result is not None:
        for node in jailer_result.nodes:
            kind_val = node.kind
            qname_upper = node.qualified_name.upper()

            if kind_val in (
                NodeKind.TABLE.value,
                NodeKind.VIEW.value,
                NodeKind.MATERIALIZED_VIEW.value,
            ):
                jailer_tables[qname_upper] = node
                if node.get_property("historical") is True:
                    historical_table_names.add(qname_upper)
            elif kind_val == NodeKind.COLUMN.value:
                # qualified_name is TABLE.COLUMN
                jailer_columns[qname_upper] = node

            # All Jailer nodes go into the graph (may be filtered later)
            all_nodes.append(node)

        for edge in jailer_result.edges:
            all_edges.append(edge)
            # Track FK pairs for later matching
            if edge.kind == EdgeKind.FOREIGN_KEY_TO.value:
                src_table = None
                tgt_table = None
                for k, v in edge.properties:
                    if k == "source_table":
                        src_table = v
                    elif k == "target_table":
                        tgt_table = v
                if src_table and tgt_table:
                    jailer_fk_table_pairs[(src_table, tgt_table)] = edge

    # -----------------------------------------------------------------------
    # Phase 1b: View/MV SQL source nodes and edges
    # -----------------------------------------------------------------------
    if view_result is not None:
        for node in view_result.nodes:
            node_upper = node.qualified_name.upper()
            short = node_upper.rsplit('.', 1)[-1]
            # Check if already exists from Jailer
            if short in jailer_tables:
                # View SQL is authoritative for views — replace Jailer node
                # but only if this is actually a view/MV (not a column)
                if node.kind in ('view', 'materialized_view'):
                    jailer_tables[short] = node
                    all_nodes.append(node)
            else:
                all_nodes.append(node)
                if node.kind in ('view', 'materialized_view', 'table'):
                    jailer_tables[short] = node
        for edge in view_result.edges:
            all_edges.append(edge)

    # -----------------------------------------------------------------------
    # Phase 1c: Migration DDL nodes and edges
    # -----------------------------------------------------------------------
    if migration_result is not None:
        for node in migration_result.nodes:
            node_upper = node.qualified_name.upper()
            short = node_upper.rsplit('.', 1)[-1]
            props = dict(node.properties)
            # Skip dropped columns — they get a special marker
            if props.get('dropped'):
                # Still add to graph but mark as dropped
                all_nodes.append(node)
                continue
            # For tables: if already in Jailer, migration wins (more recent)
            if short in jailer_tables and node.kind == 'table':
                # Migration evidence supersedes stale Jailer — replace
                jailer_tables[short] = node
                all_nodes.append(node)
            elif short not in jailer_tables:
                all_nodes.append(node)
                if node.kind == 'table':
                    jailer_tables[short] = node
            else:
                # Column or other node kind — just add
                all_nodes.append(node)
        for edge in migration_result.edges:
            all_edges.append(edge)

    # -----------------------------------------------------------------------
    # Phase 1d: Synonym nodes and edges
    # -----------------------------------------------------------------------
    if synonym_result is not None:
        for node in synonym_result.nodes:
            all_nodes.append(node)
        for edge in synonym_result.edges:
            all_edges.append(edge)

    # -----------------------------------------------------------------------
    # Phase 2: JPA entity nodes, field nodes, sequence nodes, relation edges
    # -----------------------------------------------------------------------
    entity_index: dict[str, JpaEntity] = {}  # qualified_name → entity
    entity_node_ids: dict[str, str] = {}      # qualified_name → node_id
    jpa_table_to_entities: dict[str, list[JpaEntity]] = {}  # TABLE_UPPER → [entities]

    entities_resolved = 0
    entities_unresolved = 0

    if jpa_result is not None:
        # Build lookup index (skip test entities for graph)
        for entity in jpa_result.entities:
            if entity.is_test:
                continue
            entity_index[entity.qualified_name] = entity
            if entity.table_name_resolved and entity.table_name:
                table_upper = entity.table_name.upper()
                jpa_table_to_entities.setdefault(table_upper, []).append(entity)

        # Create nodes and edges for each production entity
        for entity in entity_index.values():
            # Entity node
            e_node = _jpa_entity_node(
                entity,
                repository_revision=repo_revision,
                workspace_fingerprint=ws_fp,
            )
            entity_node_ids[entity.qualified_name] = e_node.id
            all_nodes.append(e_node)

            # Field nodes
            field_nodes = _jpa_field_nodes(
                entity,
                repository_revision=repo_revision,
                workspace_fingerprint=ws_fp,
            )
            for f_node, _ in field_nodes:
                all_nodes.append(f_node)

            # Sequence nodes
            seq_nodes = _jpa_sequence_nodes(
                entity,
                repository_revision=repo_revision,
                workspace_fingerprint=ws_fp,
            )
            all_nodes.extend(seq_nodes)

        # Relationship edges (after all entities are indexed)
        for entity in entity_index.values():
            e_node_id = entity_node_ids[entity.qualified_name]
            rel_edges = _jpa_relationship_edges(
                entity, e_node_id, entity_index,
                repository_revision=repo_revision,
                workspace_fingerprint=ws_fp,
            )
            all_edges.extend(rel_edges)

    # -----------------------------------------------------------------------
    # Phase 3: Match JPA entities to Jailer tables — MAPS_TO edges
    # -----------------------------------------------------------------------
    if jpa_result is not None and jailer_result is not None:
        for entity in entity_index.values():
            if not entity.table_name_resolved or not entity.table_name:
                entities_unresolved += 1
                continue

            e_node_id = entity_node_ids[entity.qualified_name]
            match = _match_entity_to_table(
                entity, e_node_id, jailer_tables, jailer_columns,
            )
            all_conflicts.extend(match.conflicts)

            if match.matched and match.jailer_table_node is not None:
                entities_resolved += 1

                # MAPS_TO_TABLE edge: entity → table
                maps_edge_id = _stable_id(
                    "reconciler", "maps_to_table",
                    entity.qualified_name, match.jailer_table_name,
                )
                maps_evidence = _merge_evidence(
                    match.jailer_table_node.evidence,
                    # Pull the entity node evidence
                    EvidenceRecord.verified(
                        confidence=1.0,
                        repository_revision=repo_revision,
                        workspace_fingerprint=ws_fp,
                        sources=(
                            EvidenceSource(
                                kind=_JPA_EVIDENCE_KIND,
                                path=entity.source_path,
                                start_line=entity.entity_line,
                                end_line=entity.entity_line,
                            ),
                        ),
                    ),
                    repository_revision=repo_revision,
                    workspace_fingerprint=ws_fp,
                )
                maps_edge = DatabaseGraphEdge(
                    id=maps_edge_id,
                    kind=EdgeKind.MAPS_TO_TABLE.value,
                    from_node=e_node_id,
                    to_node=match.jailer_table_node.id,
                    properties=(
                        ("entity_class", entity.qualified_name),
                        ("table_name", match.jailer_table_name),
                    ),
                    evidence=maps_evidence,
                )
                all_edges.append(maps_edge)

                # MAPS_TO_COLUMN edges: field → column
                field_nodes = _jpa_field_nodes(
                    entity,
                    repository_revision=repo_revision,
                    workspace_fingerprint=ws_fp,
                )
                for f_node, col_name_upper in field_nodes:
                    if col_name_upper is None:
                        continue
                    col_key = f"{match.jailer_table_name}.{col_name_upper}"
                    jailer_col = jailer_columns.get(col_key)
                    if jailer_col is not None:
                        maps_col_edge_id = _stable_id(
                            "reconciler", "maps_to_column",
                            f_node.qualified_name, col_key,
                        )
                        maps_col_evidence = _merge_evidence(
                            jailer_col.evidence,
                            f_node.evidence,
                            repository_revision=repo_revision,
                            workspace_fingerprint=ws_fp,
                        )
                        maps_col_edge = DatabaseGraphEdge(
                            id=maps_col_edge_id,
                            kind=EdgeKind.MAPS_TO_COLUMN.value,
                            from_node=f_node.id,
                            to_node=jailer_col.id,
                            properties=(
                                ("java_field", f_node.qualified_name),
                                ("column", col_key),
                            ),
                            evidence=maps_col_evidence,
                        )
                        all_edges.append(maps_col_edge)
            else:
                entities_unresolved += 1
    elif jpa_result is not None:
        # No Jailer data — all JPA entities are unresolved against physical schema
        for entity in entity_index.values():
            if entity.table_name_resolved and entity.table_name:
                entities_unresolved += 1

    # -----------------------------------------------------------------------
    # Phase 4: Promote evidence — nodes/edges confirmed by both sources
    # -----------------------------------------------------------------------
    # A Jailer table that also appears in JPA gets its evidence merged.
    # We achieve this by rebuilding promoted table nodes.
    if jpa_result is not None and jailer_result is not None:
        promoted_nodes: dict[str, DatabaseGraphNode] = {}
        for table_upper, entities in jpa_table_to_entities.items():
            jailer_node = jailer_tables.get(table_upper)
            if jailer_node is None:
                continue
            # Merge evidence from JPA source into the Jailer node evidence
            jpa_sources: list[EvidenceSource] = []
            for ent in entities:
                jpa_sources.append(EvidenceSource(
                    kind=_JPA_EVIDENCE_KIND,
                    path=ent.source_path,
                    start_line=ent.entity_line,
                    end_line=ent.entity_line,
                ))

            merged_ev = _merge_evidence(
                jailer_node.evidence,
                EvidenceRecord.verified(
                    confidence=1.0,
                    repository_revision=repo_revision,
                    workspace_fingerprint=ws_fp,
                    sources=tuple(jpa_sources),
                ),
                repository_revision=repo_revision,
                workspace_fingerprint=ws_fp,
            )

            promoted = DatabaseGraphNode(
                id=jailer_node.id,
                kind=jailer_node.kind,
                qualified_name=jailer_node.qualified_name,
                schema=jailer_node.schema,
                properties=jailer_node.properties,
                evidence=merged_ev,
            )
            promoted_nodes[jailer_node.id] = promoted

        # Replace in all_nodes
        if promoted_nodes:
            all_nodes = [
                promoted_nodes.get(n.id, n) for n in all_nodes
            ]

    # -----------------------------------------------------------------------
    # Phase 5: Exclude backup tables (if requested)
    # -----------------------------------------------------------------------
    excluded_node_ids: set[str] = set()
    if exclude_backup and historical_table_names:
        for name in historical_table_names:
            node = jailer_tables.get(name)
            if node:
                excluded_node_ids.add(node.id)
        # Also exclude columns of backup tables
        for col_key, col_node in jailer_columns.items():
            parts = col_key.split(".", 1)
            if len(parts) == 2 and parts[0] in historical_table_names:
                excluded_node_ids.add(col_node.id)

        all_nodes = [n for n in all_nodes if n.id not in excluded_node_ids]
        all_edges = [
            e for e in all_edges
            if e.from_node not in excluded_node_ids
            and e.to_node not in excluded_node_ids
        ]

    # -----------------------------------------------------------------------
    # Phase 6: Sort for determinism
    # -----------------------------------------------------------------------
    all_nodes.sort(key=lambda n: (n.kind, n.qualified_name, n.id))
    all_edges.sort(key=lambda e: (e.kind, e.from_node, e.to_node, e.id))
    all_conflicts.sort(key=lambda c: c.description)

    # -----------------------------------------------------------------------
    # Phase 7: Coverage statistics
    # -----------------------------------------------------------------------
    jailer_table_count = jailer_result.table_count if jailer_result else 0
    jailer_view_count = jailer_result.view_count if jailer_result else 0
    jailer_col_count = jailer_result.column_count if jailer_result else 0
    jailer_constraint_count = (
        (jailer_result.primary_key_count + jailer_result.foreign_key_count)
        if jailer_result else 0
    )

    # Adjust for excluded backup tables
    excluded_table_count = len(historical_table_names) if exclude_backup else 0
    excluded_col_count = 0
    if exclude_backup and jailer_result is not None:
        for col_key in jailer_columns:
            parts = col_key.split(".", 1)
            if len(parts) == 2 and parts[0] in historical_table_names:
                excluded_col_count += 1

    seq_count = 0
    if jpa_result is not None:
        for entity in entity_index.values():
            seq_count += sum(
                1 for s in entity.sequences if s.sequence_name_resolved
            )

    # FK consumption: count how many FK edges reference tables that exist
    # in the reconciled graph (i.e. both source and target tables are known).
    fk_resolved = 0
    fk_unresolved = 0
    if jailer_fk_table_pairs:
        for (src_tbl, tgt_tbl), _fk_edge in jailer_fk_table_pairs.items():
            src_known = src_tbl in jailer_tables
            tgt_known = tgt_tbl in jailer_tables
            if src_known and tgt_known:
                fk_resolved += 1
            else:
                fk_unresolved += 1
    elif jailer_result is not None:
        # FK edges existed but none had parseable source_table/target_table
        fk_unresolved = jailer_result.foreign_key_count

    # Migration / view / synonym scanning status — currently not implemented,
    # so report honestly as not scanned.
    migrations_scanned = migration_result is not None
    views_scanned = (jailer_result is not None and jailer_result.view_count > 0) or view_result is not None
    synonyms_scanned = synonym_result is not None and (
        synonym_result.static_count > 0 or synonym_result.dynamic_generator_count > 0
    )

    # Add view/MV counts from view_result
    view_sql_view_count = view_result.view_count if view_result is not None else 0
    view_sql_mv_count = view_result.mv_count if view_result is not None else 0
    view_sql_col_count = view_result.column_count if view_result is not None else 0

    coverage = DatabaseGraphCoverage(
        tables_resolved=jailer_table_count - excluded_table_count,
        tables_unresolved=0,
        views_resolved=jailer_view_count + view_sql_view_count + view_sql_mv_count,
        views_unresolved=0,
        columns_resolved=jailer_col_count - excluded_col_count + view_sql_col_count,
        columns_unresolved=0,
        constraints_resolved=jailer_constraint_count,
        constraints_unresolved=0,
        sequences_resolved=seq_count,
        sequences_unresolved=0,
        java_entities_resolved=entities_resolved,
        java_entities_unresolved=entities_unresolved,
        foreign_keys_resolved=fk_resolved,
        foreign_keys_unresolved=fk_unresolved,
        migrations_scanned=migrations_scanned,
        views_scanned=views_scanned,
        synonyms_scanned=synonyms_scanned,
        total_nodes=len(all_nodes),
        total_edges=len(all_edges),
    )

    # -----------------------------------------------------------------------
    # Phase 8: Metadata
    # -----------------------------------------------------------------------
    has_jailer = jailer_result is not None
    has_jpa = jpa_result is not None

    # Comprehensive incomplete_evidence assessment.
    # Evidence is incomplete when ANY significant evidence category is
    # missing, not only when both Jailer and JPA are entirely absent.
    incomplete_reasons: list[str] = []

    if not has_jailer and not has_jpa:
        incomplete_reasons.append("no_sources")
    else:
        if not has_jailer:
            incomplete_reasons.append("no_jailer_schema")
        if not has_jpa:
            incomplete_reasons.append("no_jpa_entities")

        # JPA entities with many unresolved constants indicate the extractor
        # could not resolve table-name references (e.g. Spring constant
        # expressions), so the mapping is unreliable.
        if has_jpa and jpa_result is not None:
            unresolved_const_count = len(jpa_result.unresolved_constants)
            if unresolved_const_count > 0:
                incomplete_reasons.append(
                    f"jpa_unresolved_constants:{unresolved_const_count}"
                )

        # FK edges that could not be consumed (source/target tables unknown)
        if fk_unresolved > 0:
            incomplete_reasons.append(f"fk_unresolved:{fk_unresolved}")

        # Unconsumed FK table pairs — Jailer produced FK edges but the
        # reconciler could not match them to graph tables
        if jailer_fk_table_pairs and fk_resolved == 0:
            incomplete_reasons.append("fk_edges_not_consumed")

        # Migration data was not scanned
        if not migrations_scanned:
            incomplete_reasons.append("migrations_not_scanned")

        # Views were not scanned (only incomplete if Jailer was present but
        # reported zero views — could genuinely be none, but flag it)
        if not views_scanned and has_jailer:
            incomplete_reasons.append("views_not_scanned")

        # Synonyms were not scanned
        if not synonyms_scanned:
            incomplete_reasons.append("synonyms_not_scanned")

    # Remove reasons that are resolved by new ingest results
    if view_result is not None and "views_not_scanned" in incomplete_reasons:
        incomplete_reasons.remove("views_not_scanned")
    if migration_result is not None and "migrations_not_scanned" in incomplete_reasons:
        incomplete_reasons.remove("migrations_not_scanned")

    incomplete = len(incomplete_reasons) > 0

    metadata: dict[str, Any] = {
        "sources": {
            "jailer": has_jailer,
            "jpa": has_jpa,
        },
        "incomplete_evidence": incomplete,
        "incomplete_reasons": incomplete_reasons,
        "exclude_backup": exclude_backup,
        "excluded_backup_tables": sorted(historical_table_names) if exclude_backup else [],
        "excluded_backup_count": excluded_table_count,
        "repository_root": str(repository_root),
    }
    if has_jailer and jailer_result is not None:
        metadata["jailer_version"] = jailer_result.source_version
        metadata["jailer_timestamp"] = jailer_result.model_timestamp
    if has_jpa and jpa_result is not None:
        metadata["jpa_entities_total"] = len(jpa_result.entities)
        metadata["jpa_entities_production"] = len(entity_index)
        metadata["jpa_unresolved_constants"] = len(jpa_result.unresolved_constants)

    # -----------------------------------------------------------------------
    # Phase 9: Build the graph
    # -----------------------------------------------------------------------
    graph = DatabaseGraph.create(
        provenance=provenance_dict,
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
        coverage=coverage,
        conflicts=tuple(all_conflicts),
        metadata=metadata,
    )

    logger.info(
        "Reconciled database graph: %d nodes, %d edges, %d conflicts, "
        "fingerprint=%s",
        len(all_nodes),
        len(all_edges),
        len(all_conflicts),
        graph.fingerprint[:12],
    )

    return graph
