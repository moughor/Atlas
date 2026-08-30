"""Versioned, frozen, deterministic models for the Atlas database semantic graph.

Schema version 1. Every node, edge, and property carries an evidence record
with provenance, confidence, source references, and conflict tracking.

All dataclasses are frozen=True, slots=True. Fingerprints use SHA-256 of
canonical JSON. Round-trip serialisation is guaranteed via to_dict()/from_dict().
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Schema constant
# ---------------------------------------------------------------------------

DATABASE_GRAPH_SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Canonical JSON — deterministic serialisation for fingerprinting
# ---------------------------------------------------------------------------

def canonical_json(value: object, *, indent: int | None = None) -> str:
    """Deterministic JSON string.  sort_keys=True, compact separators."""
    if indent is not None:
        return json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Node kinds
# ---------------------------------------------------------------------------

class NodeKind(str, enum.Enum):
    """Canonical database-graph node kinds."""

    DATABASE_SCHEMA = "database_schema"
    TABLE = "table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    COLUMN = "column"
    PRIMARY_KEY = "primary_key"
    FOREIGN_KEY = "foreign_key"
    UNIQUE_CONSTRAINT = "unique_constraint"
    INDEX = "index"
    SEQUENCE = "sequence"
    SYNONYM = "synonym"
    TRIGGER = "trigger"
    PACKAGE = "package"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    JAVA_ENTITY = "java_entity"
    JAVA_FIELD = "java_field"
    SQL_STATEMENT = "sql_statement"
    MIGRATION = "migration"
    SOURCE_FILE = "source_file"
    DOMAIN_CONCEPT = "domain_concept"


# ---------------------------------------------------------------------------
# Edge kinds
# ---------------------------------------------------------------------------

class EdgeKind(str, enum.Enum):
    """Canonical database-graph edge kinds."""

    HAS_COLUMN = "HAS_COLUMN"
    PRIMARY_KEY_OF = "PRIMARY_KEY_OF"
    FOREIGN_KEY_TO = "FOREIGN_KEY_TO"
    LOGICAL_REFERENCE_TO = "LOGICAL_REFERENCE_TO"
    MAPS_TO_TABLE = "MAPS_TO_TABLE"
    MAPS_TO_COLUMN = "MAPS_TO_COLUMN"
    JAVA_RELATION_TO = "JAVA_RELATION_TO"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    JOINS_TO = "JOINS_TO"
    DERIVED_FROM = "DERIVED_FROM"
    USES_SEQUENCE = "USES_SEQUENCE"
    ALIAS_OF = "ALIAS_OF"
    TRIGGERED_BY = "TRIGGERED_BY"
    CREATES = "CREATES"
    ALTERS = "ALTERS"
    RENAMES = "RENAMES"
    DROPS = "DROPS"
    DEFINED_IN = "DEFINED_IN"
    CONFIRMED_BY = "CONFIRMED_BY"
    CONFLICTS_WITH = "CONFLICTS_WITH"


# ---------------------------------------------------------------------------
# Evidence status
# ---------------------------------------------------------------------------

class EvidenceStatus(str, enum.Enum):
    """Observation status of an evidence record."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    CONFLICTING = "conflicting"
    STALE = "stale"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# EvidenceSource
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """A single provenance reference for an observed fact.

    Attributes:
        kind: Producer kind, e.g. 'ddl_file', 'jpa_annotation', 'liquibase_changelog',
              'flyway_migration', 'sql_query', 'hibernate_mapping'.
        path: Repository-relative path of the source artefact.
        start_line: First line in the source (1-based), or None if not applicable.
        end_line: Last line in the source (1-based, inclusive), or None.
        fingerprint: SHA-256 of the relevant source fragment content, or None.
        observed_version: Schema/migration version observed, or None.
    """

    kind: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    fingerprint: str | None = None
    observed_version: str | None = None

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("evidence source kind must not be empty")
        if not self.path:
            raise ValueError("evidence source path must not be empty")
        if self.start_line is not None and self.start_line < 1:
            raise ValueError(f"start_line must be >= 1, got {self.start_line}")
        if self.end_line is not None and self.end_line < 1:
            raise ValueError(f"end_line must be >= 1, got {self.end_line}")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "path": self.path}
        if self.start_line is not None:
            d["start_line"] = self.start_line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        if self.fingerprint is not None:
            d["fingerprint"] = self.fingerprint
        if self.observed_version is not None:
            d["observed_version"] = self.observed_version
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceSource:
        if not isinstance(data, dict):
            raise ValueError("evidence source must be an object")
        return cls(
            kind=data["kind"],
            path=data["path"],
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
            fingerprint=data.get("fingerprint"),
            observed_version=data.get("observed_version"),
        )


# ---------------------------------------------------------------------------
# ConflictRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """Describes contradictory evidence between two or more sources.

    Attributes:
        description: Human-readable explanation of the conflict.
        node_ids: Node identifiers involved in the conflict.
        edge_ids: Edge identifiers involved in the conflict.
        sources: Evidence sources that disagree.
        resolution: Current resolution status — 'unresolved', 'resolved_manual',
                     'resolved_latest_wins', or 'resolved_priority'.
        resolved_value: The chosen value if resolved, or None.
    """

    description: str
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    sources: tuple[EvidenceSource, ...] = ()
    resolution: str = "unresolved"
    resolved_value: str | None = None

    _VALID_RESOLUTIONS = frozenset(
        {"unresolved", "resolved_manual", "resolved_latest_wins", "resolved_priority"}
    )

    def __post_init__(self) -> None:
        if not self.description:
            raise ValueError("conflict description must not be empty")
        if self.resolution not in self._VALID_RESOLUTIONS:
            raise ValueError(f"invalid conflict resolution: {self.resolution!r}")
        # Ensure tuple types (defensive against list arguments)
        object.__setattr__(self, "node_ids", tuple(self.node_ids))
        object.__setattr__(self, "edge_ids", tuple(self.edge_ids))
        object.__setattr__(self, "sources", tuple(self.sources))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "description": self.description,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "sources": [s.to_dict() for s in self.sources],
            "resolution": self.resolution,
        }
        if self.resolved_value is not None:
            d["resolved_value"] = self.resolved_value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictRecord:
        if not isinstance(data, dict):
            raise ValueError("conflict record must be an object")
        return cls(
            description=data["description"],
            node_ids=tuple(data.get("node_ids", ())),
            edge_ids=tuple(data.get("edge_ids", ())),
            sources=tuple(
                EvidenceSource.from_dict(s) for s in data.get("sources", ())
            ),
            resolution=data.get("resolution", "unresolved"),
            resolved_value=data.get("resolved_value"),
        )


# ---------------------------------------------------------------------------
# EvidenceRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Evidence backing a node property or edge.

    Attributes:
        status: Observation status of the evidence.
        confidence: Confidence in the range [0.0, 1.0].
        repository_revision: Full Git object id, or None if not in a Git workspace.
        workspace_fingerprint: Atlas workspace fingerprint, or None.
        sources: Ordered provenance references.
        conflicts: Conflicts detected for this evidence.
    """

    status: str
    confidence: float
    repository_revision: str | None = None
    workspace_fingerprint: str | None = None
    sources: tuple[EvidenceSource, ...] = ()
    conflicts: tuple[ConflictRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {s.value for s in EvidenceStatus}:
            raise ValueError(f"invalid evidence status: {self.status!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "repository_revision": self.repository_revision,
            "workspace_fingerprint": self.workspace_fingerprint,
            "sources": [s.to_dict() for s in self.sources],
            "conflicts": [c.to_dict() for c in self.conflicts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRecord:
        if not isinstance(data, dict):
            raise ValueError("evidence record must be an object")
        return cls(
            status=data["status"],
            confidence=float(data["confidence"]),
            repository_revision=data.get("repository_revision"),
            workspace_fingerprint=data.get("workspace_fingerprint"),
            sources=tuple(
                EvidenceSource.from_dict(s) for s in data.get("sources", ())
            ),
            conflicts=tuple(
                ConflictRecord.from_dict(c) for c in data.get("conflicts", ())
            ),
        )

    @classmethod
    def unknown(cls) -> EvidenceRecord:
        """Create a minimal unknown evidence record."""
        return cls(status=EvidenceStatus.UNKNOWN.value, confidence=0.0)

    @classmethod
    def verified(
        cls,
        *,
        confidence: float = 1.0,
        repository_revision: str | None = None,
        workspace_fingerprint: str | None = None,
        sources: tuple[EvidenceSource, ...] = (),
    ) -> EvidenceRecord:
        """Create a verified evidence record with the given sources."""
        return cls(
            status=EvidenceStatus.VERIFIED.value,
            confidence=confidence,
            repository_revision=repository_revision,
            workspace_fingerprint=workspace_fingerprint,
            sources=sources,
        )


# ---------------------------------------------------------------------------
# DatabaseGraphNode
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseGraphNode:
    """A single node in the database semantic graph.

    Attributes:
        id: Stable unique identifier (typically a canonical hash).
        kind: The canonical node kind.
        qualified_name: Fully-qualified canonical name (e.g. 'SCHEMA.TABLE.COLUMN').
        schema: Database schema name, or None for schemaless entities.
        properties: Arbitrary typed properties with evidence.
        evidence: Evidence record for the node itself.
    """

    id: str
    kind: str
    qualified_name: str
    schema: str | None = None
    properties: tuple[tuple[str, Any], ...] = ()
    evidence: EvidenceRecord = field(default_factory=EvidenceRecord.unknown)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("node id must not be empty")
        if self.kind not in {k.value for k in NodeKind}:
            raise ValueError(f"invalid node kind: {self.kind!r}")
        if not self.qualified_name:
            raise ValueError("node qualified_name must not be empty")
        # Coerce properties to a stable tuple-of-tuples
        object.__setattr__(self, "properties", tuple(
            (k, v) if isinstance(p, (list, tuple)) and len(p) == 2
            else p
            for p in self.properties
            for k, v in [p]
        ))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "schema": self.schema,
            "properties": {k: v for k, v in self.properties},
            "evidence": self.evidence.to_dict(),
        }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseGraphNode:
        if not isinstance(data, dict):
            raise ValueError("database graph node must be an object")
        raw_props = data.get("properties", {})
        if isinstance(raw_props, dict):
            props = tuple(sorted(raw_props.items()))
        elif isinstance(raw_props, (list, tuple)):
            props = tuple(tuple(p) for p in raw_props)
        else:
            props = ()
        return cls(
            id=data["id"],
            kind=data["kind"],
            qualified_name=data["qualified_name"],
            schema=data.get("schema"),
            properties=props,
            evidence=EvidenceRecord.from_dict(data["evidence"])
            if "evidence" in data
            else EvidenceRecord.unknown(),
        )

    def get_property(self, key: str) -> Any | None:
        """Retrieve a property value by key, or None."""
        for k, v in self.properties:
            if k == key:
                return v
        return None


# ---------------------------------------------------------------------------
# DatabaseGraphEdge
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseGraphEdge:
    """A single directed edge in the database semantic graph.

    Attributes:
        id: Stable unique identifier.
        kind: The canonical edge kind.
        from_node: Source node id.
        to_node: Target node id.
        properties: Arbitrary typed properties.
        evidence: Evidence record for this edge.
    """

    id: str
    kind: str
    from_node: str
    to_node: str
    properties: tuple[tuple[str, Any], ...] = ()
    evidence: EvidenceRecord = field(default_factory=EvidenceRecord.unknown)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("edge id must not be empty")
        if self.kind not in {k.value for k in EdgeKind}:
            raise ValueError(f"invalid edge kind: {self.kind!r}")
        if not self.from_node:
            raise ValueError("edge from_node must not be empty")
        if not self.to_node:
            raise ValueError("edge to_node must not be empty")
        object.__setattr__(self, "properties", tuple(
            (k, v) if isinstance(p, (list, tuple)) and len(p) == 2
            else p
            for p in self.properties
            for k, v in [p]
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "properties": {k: v for k, v in self.properties},
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseGraphEdge:
        if not isinstance(data, dict):
            raise ValueError("database graph edge must be an object")
        raw_props = data.get("properties", {})
        if isinstance(raw_props, dict):
            props = tuple(sorted(raw_props.items()))
        elif isinstance(raw_props, (list, tuple)):
            props = tuple(tuple(p) for p in raw_props)
        else:
            props = ()
        return cls(
            id=data["id"],
            kind=data["kind"],
            from_node=data["from_node"],
            to_node=data["to_node"],
            properties=props,
            evidence=EvidenceRecord.from_dict(data["evidence"])
            if "evidence" in data
            else EvidenceRecord.unknown(),
        )

    def get_property(self, key: str, default: Any = None) -> Any:
        """Retrieve a property value by key, or *default*."""
        for k, v in self.properties:
            if k == key:
                return v
        return default


# ---------------------------------------------------------------------------
# DatabaseGraphCoverage
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseGraphCoverage:
    """Counts of entities resolved and unresolved in the database graph.

    All counts default to zero. Unresolved counts reflect entities that were
    referenced but could not be matched to a concrete definition.

    Attributes:
        tables_resolved: Tables with confirmed DDL/entity evidence.
        tables_unresolved: Table references that could not be resolved.
        views_resolved: Views with confirmed definitions.
        views_unresolved: Unresolved view references.
        columns_resolved: Columns matched to a table/view.
        columns_unresolved: Column references without a parent table.
        constraints_resolved: Constraints (PK, FK, unique) confirmed.
        constraints_unresolved: Constraint references unresolved.
        indexes_resolved: Indexes with confirmed definitions.
        indexes_unresolved: Unresolved index references.
        sequences_resolved: Sequences confirmed.
        sequences_unresolved: Sequence references unresolved.
        triggers_resolved: Triggers confirmed.
        triggers_unresolved: Unresolved trigger references.
        stored_programs_resolved: Procedures/functions/packages confirmed.
        stored_programs_unresolved: Unresolved stored program references.
        java_entities_resolved: JPA/Hibernate entities matched to tables.
        java_entities_unresolved: Java entities without a table match.
        sql_statements_resolved: SQL statements with resolved targets.
        sql_statements_unresolved: SQL statements with unresolved targets.
        migrations_resolved: Migration files processed.
        migrations_unresolved: Migration files that could not be parsed.
        foreign_keys_resolved: Foreign keys matched to known tables.
        foreign_keys_unresolved: Foreign key references that could not be resolved.
        migrations_scanned: Whether migration files were scanned.
        views_scanned: Whether database views were scanned.
        synonyms_scanned: Whether database synonyms were scanned.
        total_nodes: Total node count in the graph.
        total_edges: Total edge count in the graph.
    """

    tables_resolved: int = 0
    tables_unresolved: int = 0
    views_resolved: int = 0
    views_unresolved: int = 0
    columns_resolved: int = 0
    columns_unresolved: int = 0
    constraints_resolved: int = 0
    constraints_unresolved: int = 0
    indexes_resolved: int = 0
    indexes_unresolved: int = 0
    sequences_resolved: int = 0
    sequences_unresolved: int = 0
    triggers_resolved: int = 0
    triggers_unresolved: int = 0
    stored_programs_resolved: int = 0
    stored_programs_unresolved: int = 0
    java_entities_resolved: int = 0
    java_entities_unresolved: int = 0
    sql_statements_resolved: int = 0
    sql_statements_unresolved: int = 0
    migrations_resolved: int = 0
    migrations_unresolved: int = 0
    foreign_keys_resolved: int = 0
    foreign_keys_unresolved: int = 0
    migrations_scanned: bool = False
    views_scanned: bool = False
    synonyms_scanned: bool = False
    total_nodes: int = 0
    total_edges: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables_resolved": self.tables_resolved,
            "tables_unresolved": self.tables_unresolved,
            "views_resolved": self.views_resolved,
            "views_unresolved": self.views_unresolved,
            "columns_resolved": self.columns_resolved,
            "columns_unresolved": self.columns_unresolved,
            "constraints_resolved": self.constraints_resolved,
            "constraints_unresolved": self.constraints_unresolved,
            "indexes_resolved": self.indexes_resolved,
            "indexes_unresolved": self.indexes_unresolved,
            "sequences_resolved": self.sequences_resolved,
            "sequences_unresolved": self.sequences_unresolved,
            "triggers_resolved": self.triggers_resolved,
            "triggers_unresolved": self.triggers_unresolved,
            "stored_programs_resolved": self.stored_programs_resolved,
            "stored_programs_unresolved": self.stored_programs_unresolved,
            "java_entities_resolved": self.java_entities_resolved,
            "java_entities_unresolved": self.java_entities_unresolved,
            "sql_statements_resolved": self.sql_statements_resolved,
            "sql_statements_unresolved": self.sql_statements_unresolved,
            "migrations_resolved": self.migrations_resolved,
            "migrations_unresolved": self.migrations_unresolved,
            "foreign_keys_resolved": self.foreign_keys_resolved,
            "foreign_keys_unresolved": self.foreign_keys_unresolved,
            "migrations_scanned": self.migrations_scanned,
            "views_scanned": self.views_scanned,
            "synonyms_scanned": self.synonyms_scanned,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseGraphCoverage:
        if not isinstance(data, dict):
            raise ValueError("database graph coverage must be an object")
        return cls(
            tables_resolved=int(data.get("tables_resolved", 0)),
            tables_unresolved=int(data.get("tables_unresolved", 0)),
            views_resolved=int(data.get("views_resolved", 0)),
            views_unresolved=int(data.get("views_unresolved", 0)),
            columns_resolved=int(data.get("columns_resolved", 0)),
            columns_unresolved=int(data.get("columns_unresolved", 0)),
            constraints_resolved=int(data.get("constraints_resolved", 0)),
            constraints_unresolved=int(data.get("constraints_unresolved", 0)),
            indexes_resolved=int(data.get("indexes_resolved", 0)),
            indexes_unresolved=int(data.get("indexes_unresolved", 0)),
            sequences_resolved=int(data.get("sequences_resolved", 0)),
            sequences_unresolved=int(data.get("sequences_unresolved", 0)),
            triggers_resolved=int(data.get("triggers_resolved", 0)),
            triggers_unresolved=int(data.get("triggers_unresolved", 0)),
            stored_programs_resolved=int(data.get("stored_programs_resolved", 0)),
            stored_programs_unresolved=int(data.get("stored_programs_unresolved", 0)),
            java_entities_resolved=int(data.get("java_entities_resolved", 0)),
            java_entities_unresolved=int(data.get("java_entities_unresolved", 0)),
            sql_statements_resolved=int(data.get("sql_statements_resolved", 0)),
            sql_statements_unresolved=int(data.get("sql_statements_unresolved", 0)),
            migrations_resolved=int(data.get("migrations_resolved", 0)),
            migrations_unresolved=int(data.get("migrations_unresolved", 0)),
            foreign_keys_resolved=int(data.get("foreign_keys_resolved", 0)),
            foreign_keys_unresolved=int(data.get("foreign_keys_unresolved", 0)),
            migrations_scanned=bool(data.get("migrations_scanned", False)),
            views_scanned=bool(data.get("views_scanned", False)),
            synonyms_scanned=bool(data.get("synonyms_scanned", False)),
            total_nodes=int(data.get("total_nodes", 0)),
            total_edges=int(data.get("total_edges", 0)),
        )


# ---------------------------------------------------------------------------
# DatabaseGraph — top-level container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseGraph:
    """Immutable, source-free database semantic graph.

    Bound to a RepositoryProvenance from moughorai.semantic_snapshot.provenance.
    The fingerprint is computed as the SHA-256 of the canonical JSON of the full
    graph payload (excluding the fingerprint itself).

    Attributes:
        schema_version: Contract schema version (currently 1).
        fingerprint: SHA-256 of the canonical serialised payload.
        provenance: Repository provenance dict (RepositoryProvenance.to_dict()).
        nodes: All graph nodes.
        edges: All graph edges.
        coverage: Resolution coverage statistics.
        conflicts: Top-level conflict records.
        excluded_paths: Repository paths excluded from analysis.
        metadata: Arbitrary graph-level metadata (e.g. analyzer info).
    """

    schema_version: int
    fingerprint: str
    provenance: dict[str, Any]
    nodes: tuple[DatabaseGraphNode, ...]
    edges: tuple[DatabaseGraphEdge, ...]
    coverage: DatabaseGraphCoverage = field(default_factory=DatabaseGraphCoverage)
    conflicts: tuple[ConflictRecord, ...] = ()
    excluded_paths: tuple[str, ...] = ()
    metadata: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != DATABASE_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema version: {self.schema_version}, "
                f"expected {DATABASE_GRAPH_SCHEMA_VERSION}"
            )
        if not self.fingerprint:
            raise ValueError("fingerprint must not be empty")
        # Coerce mutable sequences to tuples
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(self, "excluded_paths", tuple(self.excluded_paths))
        object.__setattr__(self, "metadata", tuple(self.metadata))

    @classmethod
    def create(
        cls,
        *,
        provenance: dict[str, Any],
        nodes: tuple[DatabaseGraphNode, ...] | list[DatabaseGraphNode] = (),
        edges: tuple[DatabaseGraphEdge, ...] | list[DatabaseGraphEdge] = (),
        coverage: DatabaseGraphCoverage | None = None,
        conflicts: tuple[ConflictRecord, ...] | list[ConflictRecord] = (),
        excluded_paths: tuple[str, ...] | list[str] = (),
        metadata: tuple[tuple[str, Any], ...] | list[tuple[str, Any]] | dict[str, Any] | None = None,
    ) -> DatabaseGraph:
        """Build a DatabaseGraph and compute its deterministic fingerprint."""
        _nodes = tuple(nodes)
        _edges = tuple(edges)
        _coverage = coverage or DatabaseGraphCoverage()
        _conflicts = tuple(conflicts)
        _excluded = tuple(excluded_paths)
        if metadata is None:
            _meta: tuple[tuple[str, Any], ...] = ()
        elif isinstance(metadata, dict):
            _meta = tuple(sorted(metadata.items()))
        else:
            _meta = tuple(metadata)

        payload = _graph_payload(
            provenance=provenance,
            nodes=_nodes,
            edges=_edges,
            coverage=_coverage,
            conflicts=_conflicts,
            excluded_paths=_excluded,
            metadata=_meta,
        )
        fingerprint = _sha256(payload)

        return cls(
            schema_version=DATABASE_GRAPH_SCHEMA_VERSION,
            fingerprint=fingerprint,
            provenance=provenance,
            nodes=_nodes,
            edges=_edges,
            coverage=_coverage,
            conflicts=_conflicts,
            excluded_paths=_excluded,
            metadata=_meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "provenance": self.provenance,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "coverage": self.coverage.to_dict(),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "excluded_paths": list(self.excluded_paths),
            "metadata": {k: v for k, v in self.metadata},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseGraph:
        """Deserialise and verify a database graph from a dict.

        Raises ValueError if the schema version is unsupported or the
        fingerprint does not match the canonical payload.
        """
        if not isinstance(data, dict):
            raise ValueError("database graph must be an object")
        schema_version = data.get("schema_version")
        if schema_version != DATABASE_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported database graph schema: {schema_version}"
            )

        nodes = tuple(DatabaseGraphNode.from_dict(n) for n in data.get("nodes", ()))
        edges = tuple(DatabaseGraphEdge.from_dict(e) for e in data.get("edges", ()))
        coverage = DatabaseGraphCoverage.from_dict(data["coverage"]) if "coverage" in data else DatabaseGraphCoverage()
        conflicts = tuple(ConflictRecord.from_dict(c) for c in data.get("conflicts", ()))
        excluded_paths = tuple(data.get("excluded_paths", ()))
        raw_meta = data.get("metadata", {})
        if isinstance(raw_meta, dict):
            metadata = tuple(sorted(raw_meta.items()))
        elif isinstance(raw_meta, (list, tuple)):
            metadata = tuple(tuple(m) for m in raw_meta)
        else:
            metadata = ()

        provenance = data.get("provenance", {})
        stored_fingerprint = data.get("fingerprint", "")

        # Verify fingerprint integrity
        payload = _graph_payload(
            provenance=provenance,
            nodes=nodes,
            edges=edges,
            coverage=coverage,
            conflicts=conflicts,
            excluded_paths=excluded_paths,
            metadata=metadata,
        )
        expected_fingerprint = _sha256(payload)
        if stored_fingerprint != expected_fingerprint:
            raise ValueError(
                f"database graph fingerprint mismatch: "
                f"stored={stored_fingerprint!r}, "
                f"expected={expected_fingerprint!r}"
            )

        return cls(
            schema_version=DATABASE_GRAPH_SCHEMA_VERSION,
            fingerprint=stored_fingerprint,
            provenance=provenance,
            nodes=nodes,
            edges=edges,
            coverage=coverage,
            conflicts=conflicts,
            excluded_paths=excluded_paths,
            metadata=metadata,
        )

    def verify_fingerprint(self) -> bool:
        """Return True if the current fingerprint matches the payload."""
        payload = _graph_payload(
            provenance=self.provenance,
            nodes=self.nodes,
            edges=self.edges,
            coverage=self.coverage,
            conflicts=self.conflicts,
            excluded_paths=self.excluded_paths,
            metadata=self.metadata,
        )
        return self.fingerprint == _sha256(payload)

    def node_by_id(self, node_id: str) -> DatabaseGraphNode | None:
        """Look up a node by its identifier."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def edges_from(self, node_id: str) -> tuple[DatabaseGraphEdge, ...]:
        """Return all edges originating from the given node."""
        return tuple(e for e in self.edges if e.from_node == node_id)

    def edges_to(self, node_id: str) -> tuple[DatabaseGraphEdge, ...]:
        """Return all edges targeting the given node."""
        return tuple(e for e in self.edges if e.to_node == node_id)


# ---------------------------------------------------------------------------
# Internal: canonical payload for fingerprinting
# ---------------------------------------------------------------------------

# Provenance fields that are volatile/execution-specific and should not
# affect the semantic fingerprint (graph content identity).
_VOLATILE_PROVENANCE_FIELDS = frozenset({
    "captured_at",      # Timestamp of analysis run
    "analysis_id",      # Run-specific identifier
    "workspace_path",   # Local filesystem path
    "temp_path",        # Temporary working directory
})


def _semantic_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    """Extract semantic-only provenance fields for deterministic fingerprinting.

    Excludes volatile execution-time fields like captured_at, workspace_path.
    """
    return {
        k: v for k, v in sorted(provenance.items())
        if k not in _VOLATILE_PROVENANCE_FIELDS
    }


def _graph_payload(
    *,
    provenance: dict[str, Any],
    nodes: tuple[DatabaseGraphNode, ...],
    edges: tuple[DatabaseGraphEdge, ...],
    coverage: DatabaseGraphCoverage,
    conflicts: tuple[ConflictRecord, ...],
    excluded_paths: tuple[str, ...],
    metadata: tuple[tuple[str, Any], ...],
) -> dict[str, Any]:
    """Build the canonical dict used for fingerprint computation.

    The schema_version is included; the fingerprint itself is excluded.
    Uses semantic provenance (excluding volatile fields) for determinism.
    """
    return {
        "schema_version": DATABASE_GRAPH_SCHEMA_VERSION,
        "provenance": _semantic_provenance(provenance),
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
        "coverage": coverage.to_dict(),
        "conflicts": [c.to_dict() for c in conflicts],
        "excluded_paths": list(excluded_paths),
        "metadata": {k: v for k, v in metadata},
    }
