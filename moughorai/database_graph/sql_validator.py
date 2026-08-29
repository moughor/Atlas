"""Phase C4: Oracle SQL structural validation against a reconciled DatabaseGraph.

Static, regex-based SQL validator.  Does NOT execute SQL, connect to a database,
or use sqlparse.  It parses common Oracle DML patterns (SELECT, INSERT, UPDATE,
DELETE, MERGE) and validates every table, column, join, and sequence reference
against the graph's canonical nodes and edges.

Subqueries, PL/SQL blocks, DDL (CREATE/ALTER/DROP), analytic functions, CONNECT
BY, and MODEL clauses are explicitly reported as ``unsupported_sql``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceStatus,
    NodeKind,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQL_VALIDATOR_VERSION: str = "1.0.0"

MUTATION_WARNING: str = "BUSINESS_REVIEW_REQUIRED"

# Overall statuses
STATUS_VALID: str = "structurally_valid"
STATUS_INVALID: str = "structurally_invalid"
STATUS_INCOMPLETE: str = "incomplete_evidence"
STATUS_UNSUPPORTED: str = "unsupported_sql"

# Statement classifications
CLASS_READ_ONLY: str = "read_only"
CLASS_MUTATING: str = "mutating"
CLASS_DDL: str = "ddl"
CLASS_UNKNOWN: str = "unknown"

# Issue types
ISSUE_UNKNOWN_TABLE: str = "unknown_table"
ISSUE_UNKNOWN_COLUMN: str = "unknown_column"
ISSUE_BACKUP_OBJECT: str = "backup_object"
ISSUE_VIEW_MUTATION: str = "view_mutation"
ISSUE_UNSUPPORTED_JOIN: str = "unsupported_join"
ISSUE_INVALID_JOIN_COLUMNS: str = "invalid_join_columns"
ISSUE_HISTORICAL_OBJECT: str = "historical_object"
ISSUE_SEQUENCE_UNKNOWN: str = "sequence_unknown"

# Fix 5: Semantic error codes
ISSUE_DENORMALIZED_REFERENCE: str = "denormalized_reference_not_fk"
ISSUE_DROPPED_COLUMN: str = "dropped_column"
ISSUE_SOURCE_CONFLICT: str = "source_conflict"
ISSUE_DYNAMIC_SYNONYM: str = "dynamic_synonym_target_unproven"
ISSUE_MV_MUTATION: str = "materialized_view_mutation"

# Denormalized reference detection patterns
_DENORM_FK_SUFFIX = re.compile(r"_ID$|_INSTANCES$|_FK$|_REF$", re.IGNORECASE)

# Backup / historical detection — mirrors reconciler logic
_BCK_PREFIX = re.compile(r"^BCK", re.IGNORECASE)
_BACKUP_TOKEN = re.compile(r"BACK_UP", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SqlValidationIssue:
    """A single validation issue found in a SQL statement."""

    issue_type: str
    object_name: str
    detail: str
    severity: str = "error"  # 'error' | 'warning'

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "object_name": self.object_name,
            "detail": self.detail,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SqlValidationIssue:
        return cls(
            issue_type=data["issue_type"],
            object_name=data["object_name"],
            detail=data["detail"],
            severity=data.get("severity", "error"),
        )


@dataclass(frozen=True, slots=True)
class TableReference:
    """A resolved or unresolved table/view reference in a statement."""

    name: str
    alias: str | None = None
    resolved: bool = False
    node_kind: str | None = None
    node_id: str | None = None
    resolution: str | None = None  # 'qualified', 'short', or None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "alias": self.alias,
            "resolved": self.resolved,
            "node_kind": self.node_kind,
        }
        if self.node_id is not None:
            d["node_id"] = self.node_id
        if self.resolution is not None:
            d["resolution"] = self.resolution
        return d


@dataclass(frozen=True, slots=True)
class ColumnReference:
    """A resolved or unresolved column reference."""

    name: str
    table_name: str | None = None
    resolved: bool = False
    node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table_name": self.table_name,
            "resolved": self.resolved,
            "node_id": self.node_id,
        }


@dataclass(frozen=True, slots=True)
class JoinValidation:
    """Validation result for a single JOIN condition."""

    left_table: str
    right_table: str
    condition_text: str
    supported_by_evidence: bool
    evidence_kind: str | None = None  # 'foreign_key', 'logical_reference', None

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_table": self.left_table,
            "right_table": self.right_table,
            "condition_text": self.condition_text,
            "supported_by_evidence": self.supported_by_evidence,
            "evidence_kind": self.evidence_kind,
        }


@dataclass(frozen=True, slots=True)
class SqlStatementResult:
    """Validation result for a single SQL statement."""

    status: str
    classification: str
    sql_text: str
    table_references: tuple[TableReference, ...] = ()
    column_references: tuple[ColumnReference, ...] = ()
    join_validations: tuple[JoinValidation, ...] = ()
    issues: tuple[SqlValidationIssue, ...] = ()
    mutation_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "classification": self.classification,
            "sql_text": self.sql_text,
            "table_references": [t.to_dict() for t in self.table_references],
            "column_references": [c.to_dict() for c in self.column_references],
            "join_validations": [j.to_dict() for j in self.join_validations],
            "issues": [i.to_dict() for i in self.issues],
        }
        if self.mutation_warning is not None:
            d["mutation_warning"] = self.mutation_warning
        return d


@dataclass(frozen=True, slots=True)
class SqlValidationResult:
    """Top-level validation result across all statements."""

    overall_status: str
    statements: tuple[SqlStatementResult, ...]
    graph_fingerprint: str
    mutation_warning: str | None = None
    validator_version: str = _SQL_VALIDATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "overall_status": self.overall_status,
            "statements": [s.to_dict() for s in self.statements],
            "graph_fingerprint": self.graph_fingerprint,
            "validator_version": self.validator_version,
        }
        if self.mutation_warning is not None:
            d["mutation_warning"] = self.mutation_warning
        return d


# ---------------------------------------------------------------------------
# Graph index — lightweight lookup structures built once per validation
# ---------------------------------------------------------------------------

class _GraphIndex:
    """Pre-built indexes over a DatabaseGraph for fast validation lookups.

    All name lookups are case-insensitive (UPPER).
    """

    __slots__ = (
        "_table_nodes",
        "_column_nodes",
        "_sequence_nodes",
        "_historical_names",
        "_backup_names",
        "_fk_pairs",
        "_fk_column_pairs",
        "_logical_ref_pairs",
        "_edges_by_kind",
        "_dropped_columns",
        "_conflicting_columns",
        "_dynamic_synonyms",
        "_read_only_nodes",
        "_synonym_targets",
    )

    def __init__(self, graph: DatabaseGraph) -> None:
        # TABLE/VIEW/MATERIALIZED_VIEW by UPPER(qualified_name)
        self._table_nodes: dict[str, DatabaseGraphNode] = {}
        # COLUMN by UPPER(qualified_name)  — key is TABLE.COLUMN
        self._column_nodes: dict[str, DatabaseGraphNode] = {}
        # SEQUENCE by UPPER(qualified_name)
        self._sequence_nodes: dict[str, DatabaseGraphNode] = {}
        # Historical / backup name sets
        self._historical_names: set[str] = set()
        self._backup_names: set[str] = set()
        # (UPPER_FROM, UPPER_TO) table-level pairs backed by FK or logical reference
        self._fk_pairs: set[tuple[str, str]] = set()
        # Column-level FK index: (src_table, src_col, tgt_table, tgt_col) all UPPER
        self._fk_column_pairs: set[tuple[str, str, str, str]] = set()
        self._logical_ref_pairs: set[tuple[str, str]] = set()
        # Fix 5: Dropped columns by UPPER(qualified_name)
        self._dropped_columns: set[str] = set()
        # Fix 5: Columns with conflicting evidence by UPPER(qualified_name)
        self._conflicting_columns: set[str] = set()
        # Fix 5: Dynamic/generated synonym UPPER(qualified_name)
        self._dynamic_synonyms: set[str] = set()
        # Fix 5: Read-only nodes UPPER(qualified_name)
        self._read_only_nodes: set[str] = set()
        # Fix 5: Synonym target mapping: UPPER(synonym_qname) → target node
        self._synonym_targets: dict[str, DatabaseGraphNode] = {}

        _table_like = {
            NodeKind.TABLE.value,
            NodeKind.VIEW.value,
            NodeKind.MATERIALIZED_VIEW.value,
        }

        # Index nodes
        for node in graph.nodes:
            qname = node.qualified_name.upper()
            kind = node.kind
            if kind in _table_like:
                self._table_nodes[qname] = node
                # Also index without schema prefix  (SCHEMA.TABLE → TABLE)
                if "." in qname:
                    short = qname.rsplit(".", 1)[-1]
                    if short not in self._table_nodes:
                        self._table_nodes[short] = node
                # Check historical
                if node.get_property("historical") is True:
                    self._historical_names.add(qname)
                if _is_backup_name(node.qualified_name):
                    self._backup_names.add(qname)
                # Stale evidence ⇒ historical
                if node.evidence.status == EvidenceStatus.STALE.value:
                    self._historical_names.add(qname)
            elif kind == NodeKind.COLUMN.value:
                self._column_nodes[qname] = node
                # Also store SHORT_TABLE.COLUMN
                if qname.count(".") >= 2:
                    parts = qname.split(".", 1)
                    short_key = parts[-1]  # TABLE.COLUMN without schema
                    if short_key not in self._column_nodes:
                        self._column_nodes[short_key] = node
                # Fix 5: Track dropped columns
                if node.get_property("dropped") is True:
                    self._dropped_columns.add(qname)
                    if qname.count(".") >= 2:
                        parts = qname.split(".", 1)
                        self._dropped_columns.add(parts[-1])
                # Fix 5: Track conflicting evidence columns
                if node.evidence.status == EvidenceStatus.CONFLICTING.value:
                    self._conflicting_columns.add(qname)
                    if qname.count(".") >= 2:
                        parts = qname.split(".", 1)
                        self._conflicting_columns.add(parts[-1])
            elif kind == NodeKind.SEQUENCE.value:
                self._sequence_nodes[qname] = node
                if "." in qname:
                    short = qname.rsplit(".", 1)[-1]
                    if short not in self._sequence_nodes:
                        self._sequence_nodes[short] = node
            elif kind == NodeKind.SYNONYM.value:
                # Fix 5: Track dynamic/generated synonyms
                if (
                    node.get_property("dynamic") is True
                    or node.get_property("generated") is True
                ):
                    self._dynamic_synonyms.add(qname)
                    if "." in qname:
                        short = qname.rsplit(".", 1)[-1]
                        self._dynamic_synonyms.add(short)

            # Fix 5: Track read_only property on any node
            if node.get_property("read_only") is True:
                self._read_only_nodes.add(qname)
                if "." in qname:
                    short = qname.rsplit(".", 1)[-1]
                    self._read_only_nodes.add(short)

        # Index FK and logical-reference edges
        for edge in graph.edges:
            if edge.kind == EdgeKind.FOREIGN_KEY_TO.value:
                src = edge.get_property("source_table", "")
                tgt = edge.get_property("target_table", "")
                src_col = edge.get_property("source_column", "")
                tgt_col = edge.get_property("target_column", "")
                if src and tgt:
                    src_u = src.upper()
                    tgt_u = tgt.upper()
                    self._fk_pairs.add((src_u, tgt_u))
                    self._fk_pairs.add((tgt_u, src_u))  # bidirectional for join
                    # Store column-level pairs (both directions for join matching)
                    if src_col and tgt_col:
                        src_col_u = src_col.upper()
                        tgt_col_u = tgt_col.upper()
                        self._fk_column_pairs.add(
                            (src_u, src_col_u, tgt_u, tgt_col_u)
                        )
                        # Reverse direction: target side's column paired with source
                        self._fk_column_pairs.add(
                            (tgt_u, tgt_col_u, src_u, src_col_u)
                        )
            elif edge.kind == EdgeKind.LOGICAL_REFERENCE_TO.value:
                src = self._node_table_name(edge.from_node, graph)
                tgt = self._node_table_name(edge.to_node, graph)
                if src and tgt:
                    self._logical_ref_pairs.add((src, tgt))
                    self._logical_ref_pairs.add((tgt, src))
            elif edge.kind == EdgeKind.JAVA_RELATION_TO.value:
                src = self._node_table_name(edge.from_node, graph)
                tgt = self._node_table_name(edge.to_node, graph)
                if src and tgt:
                    self._logical_ref_pairs.add((src, tgt))
                    self._logical_ref_pairs.add((tgt, src))
            elif edge.kind == EdgeKind.ALIAS_OF.value:
                # Fix 5: Track synonym → target mappings
                from_node = graph.node_by_id(edge.from_node)
                to_node = graph.node_by_id(edge.to_node)
                if from_node is not None and to_node is not None:
                    syn_qname = from_node.qualified_name.upper()
                    self._synonym_targets[syn_qname] = to_node
                    if "." in syn_qname:
                        short = syn_qname.rsplit(".", 1)[-1]
                        if short not in self._synonym_targets:
                            self._synonym_targets[short] = to_node
                    # Also register synonyms as table lookup targets
                    tgt_qname = to_node.qualified_name.upper()
                    if to_node.kind in _table_like:
                        if syn_qname not in self._table_nodes:
                            self._table_nodes[syn_qname] = to_node
                        if "." in syn_qname:
                            short = syn_qname.rsplit(".", 1)[-1]
                            if short not in self._table_nodes:
                                self._table_nodes[short] = to_node

    # -- helpers --

    @staticmethod
    def _node_table_name(
        node_id: str, graph: DatabaseGraph,
    ) -> str | None:
        node = graph.node_by_id(node_id)
        if node is None:
            return None
        # If node is a column, extract the table portion
        qn = node.qualified_name.upper()
        if node.kind == NodeKind.COLUMN.value:
            parts = qn.rsplit(".", 1)
            return parts[0] if len(parts) >= 2 else None
        return qn

    # -- public lookups --

    def resolve_table(self, name: str) -> DatabaseGraphNode | None:
        """Resolve a table name, supporting schema-qualified references.

        Tries the full name first, then falls back to the short (unqualified)
        name for schema-prefixed references like 'SYGMA.TB_GRP_PF'.
        """
        upper = name.upper()
        node = self._table_nodes.get(upper)
        if node is not None:
            return node
        # If schema-qualified, try the short name as fallback
        if "." in upper:
            short = upper.rsplit(".", 1)[-1]
            return self._table_nodes.get(short)
        return None

    def resolve_table_with_method(
        self, name: str,
    ) -> tuple[DatabaseGraphNode | None, str | None]:
        """Resolve a table name and report which resolution was used.

        Returns (node, 'qualified'|'short'|None).
        """
        upper = name.upper()
        node = self._table_nodes.get(upper)
        if node is not None:
            return node, "qualified"
        if "." in upper:
            short = upper.rsplit(".", 1)[-1]
            node = self._table_nodes.get(short)
            if node is not None:
                return node, "short"
        return None, None

    def resolve_column(self, table_name: str, col_name: str) -> DatabaseGraphNode | None:
        key = f"{table_name.upper()}.{col_name.upper()}"
        return self._column_nodes.get(key)

    def resolve_sequence(self, name: str) -> DatabaseGraphNode | None:
        return self._sequence_nodes.get(name.upper())

    def is_historical(self, name: str) -> bool:
        upper = name.upper()
        return upper in self._historical_names

    def is_backup(self, name: str) -> bool:
        upper = name.upper()
        return upper in self._backup_names

    def has_relationship(self, table_a: str, table_b: str) -> tuple[bool, str | None]:
        """Check if two tables have an FK or logical relationship (table-level).

        Returns (True, evidence_kind) or (False, None).
        """
        a, b = table_a.upper(), table_b.upper()
        if (a, b) in self._fk_pairs:
            return True, "foreign_key"
        if (a, b) in self._logical_ref_pairs:
            return True, "logical_reference"
        return False, None

    def has_fk_column_match(
        self,
        table_a: str,
        col_a: str,
        table_b: str,
        col_b: str,
    ) -> bool:
        """Check if a specific column pair matches a declared FK.

        Checks both (a.col_a → b.col_b) and (b.col_b → a.col_a).
        """
        a = table_a.upper()
        ca = col_a.upper()
        b = table_b.upper()
        cb = col_b.upper()
        return (a, ca, b, cb) in self._fk_column_pairs

    # -- Fix 5: new lookup methods --

    def is_dropped_column(self, table_name: str, col_name: str) -> bool:
        """Check if a column is marked as dropped in the graph."""
        key = f"{table_name.upper()}.{col_name.upper()}"
        return key in self._dropped_columns

    def is_conflicting_column(self, table_name: str, col_name: str) -> bool:
        """Check if a column has conflicting evidence status."""
        key = f"{table_name.upper()}.{col_name.upper()}"
        return key in self._conflicting_columns

    def get_column_node(self, table_name: str, col_name: str) -> DatabaseGraphNode | None:
        """Get the column node (including dropped ones) for property inspection."""
        key = f"{table_name.upper()}.{col_name.upper()}"
        return self._column_nodes.get(key)

    def is_dynamic_synonym(self, name: str) -> bool:
        """Check if a name is a dynamic/generated synonym."""
        return name.upper() in self._dynamic_synonyms

    def is_read_only(self, name: str) -> bool:
        """Check if a node has the read_only property set."""
        return name.upper() in self._read_only_nodes

    def get_synonym_target(self, name: str) -> DatabaseGraphNode | None:
        """Get the target node for a synonym, if any."""
        return self._synonym_targets.get(name.upper())

    def resolve_table_via_synonym(self, name: str) -> tuple[DatabaseGraphNode | None, bool]:
        """Check if a table was resolved via a synonym alias.

        Returns (target_node, is_synonym_resolution).
        """
        upper = name.upper()
        syn_target = self._synonym_targets.get(upper)
        if syn_target is not None:
            return syn_target, True
        return None, False


# ---------------------------------------------------------------------------
# Regex-based SQL parser
# ---------------------------------------------------------------------------

# Comment stripping
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# DDL keywords
_DDL_PATTERN = re.compile(
    r"^\s*(CREATE|ALTER|DROP)\s+", re.IGNORECASE,
)

# PL/SQL block detection
_PLSQL_PATTERN = re.compile(
    r"^\s*(DECLARE|BEGIN)\s+", re.IGNORECASE,
)

# Subquery in FROM clause detection — parenthesised SELECT used as a derived table
# Only match (SELECT inside the FROM…WHERE region, not scalar subqueries in WHERE/ON
_SUBQUERY_IN_FROM_PATTERN = re.compile(
    r"\bFROM\s+\(\s*SELECT\b|\bJOIN\s+\(\s*SELECT\b", re.IGNORECASE,
)

# Unsupported clause detection
_UNSUPPORTED_CLAUSE = re.compile(
    r"\bCONNECT\s+BY\b|\bMODEL\b|\bOVER\s*\(", re.IGNORECASE,
)

# WITH clause (CTE) detection
_WITH_CTE_PATTERN = re.compile(
    r"^\s*WITH\s+", re.IGNORECASE,
)

# CTE stripping: WITH name AS (...) [, name AS (...)]* <main query>
# Removes WITH ... AS (...) prefix(es) and returns the main query body
def _strip_cte(sql: str) -> str:
    """Strip WITH ... AS (...) prefix(es) from a SQL statement.

    Returns the main query body after all CTE definitions.
    """
    if not _WITH_CTE_PATTERN.match(sql):
        return sql
    # Walk past "WITH", then past each CTE: name AS (balanced-parens) [,]
    pos = re.match(r"\s*WITH\s+", sql, re.IGNORECASE)
    if pos is None:
        return sql
    idx = pos.end()
    while idx < len(sql):
        # Skip whitespace
        while idx < len(sql) and sql[idx] in " \t\r\n":
            idx += 1
        # Skip CTE name
        m = re.match(r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$#]*)\s+', sql[idx:], re.IGNORECASE)
        if m is None:
            break
        idx += m.end()
        # Expect AS
        am = re.match(r'AS\s*', sql[idx:], re.IGNORECASE)
        if am is None:
            break
        idx += am.end()
        # Expect opening paren — find balanced closing paren
        if idx < len(sql) and sql[idx] == '(':
            depth = 1
            idx += 1
            while idx < len(sql) and depth > 0:
                if sql[idx] == '(':
                    depth += 1
                elif sql[idx] == ')':
                    depth -= 1
                idx += 1
        else:
            break
        # Skip whitespace after closing paren
        while idx < len(sql) and sql[idx] in " \t\r\n":
            idx += 1
        # Check for comma (another CTE) or the main query
        if idx < len(sql) and sql[idx] == ',':
            idx += 1
            continue
        else:
            # Remaining text is the main query
            break
    return sql[idx:]

# Statement kind detection (first keyword)
_SELECT_PATTERN = re.compile(r"^\s*SELECT\s+", re.IGNORECASE)
_INSERT_PATTERN = re.compile(r"^\s*INSERT\s+INTO\s+", re.IGNORECASE)
_UPDATE_PATTERN = re.compile(r"^\s*UPDATE\s+", re.IGNORECASE)
_DELETE_PATTERN = re.compile(r"^\s*DELETE\s+FROM\s+", re.IGNORECASE)
_MERGE_PATTERN = re.compile(r"^\s*MERGE\s+INTO\s+", re.IGNORECASE)

# Oracle identifier: optionally schema-prefixed, quoted or unquoted
_IDENT = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$#]*)'
_QUALIFIED_IDENT = rf'(?:{_IDENT}\.)?{_IDENT}'

# Table reference extraction patterns

# FROM clause: FROM table [alias] [, table2 [alias2]]
_FROM_CLAUSE = re.compile(
    r"\bFROM\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?",
    re.IGNORECASE,
)

# Additional comma-separated tables in FROM
_FROM_COMMA_TABLES = re.compile(
    r"\bFROM\s+(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bUNION\b|$)",
    re.IGNORECASE | re.DOTALL,
)

# JOIN clause
_JOIN_CLAUSE = re.compile(
    r"\bJOIN\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?"
    r"\s+ON\s+(.*?)(?=\bJOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

# INSERT INTO table (col1, col2, ...)
_INSERT_TABLE = re.compile(
    r"\bINSERT\s+INTO\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s*\(\s*(.*?)\s*\))?",
    re.IGNORECASE | re.DOTALL,
)

# UPDATE table SET col1 = ...
_UPDATE_TABLE = re.compile(
    r"\bUPDATE\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?"
    r"\s+SET\s+",
    re.IGNORECASE,
)

# SET columns: col = value [, col2 = value2]
_SET_COLUMNS = re.compile(
    r"\bSET\s+(.*?)(?:\bWHERE\b|\bRETURNING\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

# DELETE FROM table
_DELETE_TABLE = re.compile(
    r"\bDELETE\s+FROM\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?",
    re.IGNORECASE,
)

# MERGE INTO table
_MERGE_TABLE = re.compile(
    r"\bMERGE\s+INTO\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?",
    re.IGNORECASE,
)

# MERGE USING table
_MERGE_USING = re.compile(
    r"\bUSING\s+(" + _QUALIFIED_IDENT + r")"
    r"(?:\s+(?:AS\s+)?(" + _IDENT + r"))?",
    re.IGNORECASE,
)

# SELECT column list  (between SELECT and FROM)
_SELECT_COLUMNS = re.compile(
    r"\bSELECT\s+(.*?)\bFROM\b",
    re.IGNORECASE | re.DOTALL,
)

# WHERE column references  (simple: col = / col IN / col IS / col LIKE / col > etc.)
_WHERE_CLAUSE = re.compile(
    r"\bWHERE\s+(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|\bUNION\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

# Sequence references — .NEXTVAL / .CURRVAL
_SEQUENCE_REF = re.compile(
    r"(" + _QUALIFIED_IDENT + r")\s*\.\s*(?:NEXTVAL|CURRVAL)\b",
    re.IGNORECASE,
)

# ON clause column pair: alias.col = alias.col  (used for join validation)
_ON_COLUMN_PAIR = re.compile(
    r"(" + _IDENT + r")\s*\.\s*(" + _IDENT + r")"
    r"\s*=\s*"
    r"(" + _IDENT + r")\s*\.\s*(" + _IDENT + r")",
    re.IGNORECASE,
)

# SQL keywords that cannot be aliases or table names
_SQL_KEYWORDS = frozenset({
    "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL",
    "OUTER", "CROSS", "ON", "AND", "OR", "NOT", "IN", "IS", "NULL",
    "LIKE", "BETWEEN", "EXISTS", "HAVING", "GROUP", "ORDER", "BY",
    "ASC", "DESC", "UNION", "ALL", "INSERT", "INTO", "VALUES", "UPDATE",
    "SET", "DELETE", "MERGE", "USING", "WHEN", "MATCHED", "THEN",
    "AS", "DISTINCT", "CASE", "END", "ELSE", "NATURAL", "RETURNING",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_backup_name(name: str) -> bool:
    """Check if a table name matches BCK/BACK_UP naming convention."""
    upper = name.upper()
    return bool(_BCK_PREFIX.match(upper)) or bool(_BACKUP_TOKEN.search(upper))


def _strip_comments(sql: str) -> str:
    """Remove SQL comments (line and block)."""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    return sql


def _clean_identifier(ident: str) -> str:
    """Remove quotes and normalise a SQL identifier to uppercase."""
    ident = ident.strip()
    if ident.startswith('"') and ident.endswith('"'):
        # Quoted identifier: preserve exact case but strip quotes
        return ident[1:-1]
    return ident.upper()


def _split_statements(sql: str) -> list[str]:
    """Split SQL text on semicolons, excluding empty fragments."""
    parts = sql.split(";")
    return [p.strip() for p in parts if p.strip()]


def _is_keyword(word: str) -> bool:
    return word.upper() in _SQL_KEYWORDS


def _extract_simple_column_names(
    text: str,
) -> list[tuple[str, str | None]]:
    """Extract (column_name, table_qualifier_or_None) from a comma-separated
    SELECT expression list.

    Handles: col, table.col, alias.col, col AS alias, expressions.
    Skips *, function calls, literals, and complex expressions.
    """
    columns: list[tuple[str, str | None]] = []
    if not text or not text.strip():
        return columns

    # Split on commas (not inside parentheses)
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        part = part.strip()
        if not part or part == "*":
            continue
        # Skip function calls
        if "(" in part:
            continue
        # Skip numeric/string literals
        if part[0] in ("'", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
            continue

        # Handle "col AS alias" — take the col part
        as_match = re.match(
            r"(" + _QUALIFIED_IDENT + r")\s+AS\s+",
            part,
            re.IGNORECASE,
        )
        if as_match:
            part = as_match.group(1)

        # Handle qualified.name.col — extract col and table qualifier
        clean = _clean_identifier(part.split()[-1] if " " in part else part)
        if "." in clean:
            qualifier, col_name = clean.rsplit(".", 1)
            columns.append((col_name, qualifier))
        else:
            if not _is_keyword(clean):
                columns.append((clean, None))

    return columns


def _extract_column_names_with_qualifiers(
    text: str,
) -> list[tuple[str, str | None]]:
    """Extract (column_name, table_qualifier_or_None) from expression text.

    Used for WHERE clauses and SET clauses.
    """
    results: list[tuple[str, str | None]] = []
    if not text:
        return results

    # Find all identifier references that look like column refs
    # Match: [qualifier.]column_name (followed by operator or keyword)
    ident_pattern = re.compile(
        r"(?<![.\w])(" + _QUALIFIED_IDENT + r")(?=\s*(?:[=<>!]|\bIN\b|\bIS\b|\bLIKE\b|\bBETWEEN\b|\bNOT\b))",
        re.IGNORECASE,
    )
    for m in ident_pattern.finditer(text):
        raw = m.group(1)
        clean = _clean_identifier(raw)
        if _is_keyword(clean):
            continue
        if "." in clean:
            parts = clean.rsplit(".", 1)
            results.append((parts[1], parts[0]))
        else:
            results.append((clean, None))

    return results


def _parse_from_tables(sql: str) -> list[tuple[str, str | None]]:
    """Extract (table_name, alias) pairs from the FROM clause.

    Handles comma-separated tables.
    """
    tables: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    m = _FROM_COMMA_TABLES.search(sql)
    if not m:
        return tables

    from_body = m.group(1).strip()

    # Remove JOIN portions (handled separately)
    from_body = re.sub(
        r"\b(?:INNER|LEFT|RIGHT|FULL|CROSS|NATURAL)?\s*(?:OUTER\s+)?JOIN\b.*",
        "",
        from_body,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Split on commas
    parts = from_body.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Match table [alias]
        tm = re.match(
            r"(" + _QUALIFIED_IDENT + r")(?:\s+(?:AS\s+)?(" + _IDENT + r"))?",
            part,
            re.IGNORECASE,
        )
        if tm:
            tname = _clean_identifier(tm.group(1))
            alias = _clean_identifier(tm.group(2)) if tm.group(2) else None
            if alias and _is_keyword(alias):
                alias = None
            key = tname
            if key not in seen:
                seen.add(key)
                tables.append((tname, alias))

    return tables


def _parse_join_clauses(
    sql: str,
) -> list[tuple[str, str | None, str]]:
    """Extract (table_name, alias, on_condition) from JOIN clauses."""
    results: list[tuple[str, str | None, str]] = []
    for m in _JOIN_CLAUSE.finditer(sql):
        tname = _clean_identifier(m.group(1))
        alias = _clean_identifier(m.group(2)) if m.group(2) else None
        if alias and _is_keyword(alias):
            alias = None
        condition = m.group(3).strip() if m.group(3) else ""
        results.append((tname, alias, condition))
    return results


def _parse_on_column_pairs(
    condition: str,
    alias_map: dict[str, str],
) -> list[tuple[str, str, str, str]]:
    """Parse all column pairs from a JOIN ON condition.

    Returns list of (left_table, left_column, right_table, right_column)
    with aliases resolved to actual table names.
    """
    pairs: list[tuple[str, str, str, str]] = []
    for m in _ON_COLUMN_PAIR.finditer(condition):
        left_alias = _clean_identifier(m.group(1))
        left_col = _clean_identifier(m.group(2))
        right_alias = _clean_identifier(m.group(3))
        right_col = _clean_identifier(m.group(4))
        # Resolve aliases to real table names
        left_table = alias_map.get(left_alias, left_alias)
        right_table = alias_map.get(right_alias, right_alias)
        pairs.append((left_table, left_col, right_table, right_col))
    return pairs


# ---------------------------------------------------------------------------
# Per-statement parse result (internal)
# ---------------------------------------------------------------------------

@dataclass
class _ParsedStatement:
    """Internal parse result for a single SQL statement."""

    classification: str = CLASS_UNKNOWN
    tables: list[tuple[str, str | None]] = field(default_factory=list)
    # (table_name, alias_or_None)
    joins: list[tuple[str, str | None, str]] = field(default_factory=list)
    # (table_name, alias_or_None, on_condition)
    columns: list[tuple[str, str | None]] = field(default_factory=list)
    # (column_name, table_qualifier_or_None)
    sequences: list[str] = field(default_factory=list)
    unsupported_reason: str | None = None
    is_mutating: bool = False


def _parse_statement(sql: str) -> _ParsedStatement:
    """Parse a single SQL statement into a _ParsedStatement."""
    result = _ParsedStatement()

    # Detect unsupported patterns
    if _DDL_PATTERN.match(sql):
        result.classification = CLASS_DDL
        result.unsupported_reason = "DDL statements are not validated"
        return result

    if _PLSQL_PATTERN.match(sql):
        result.classification = CLASS_UNKNOWN
        result.unsupported_reason = "PL/SQL blocks are not validated"
        return result

    # Strip CTE prefix (WITH ... AS (...)) so the main query is parsed normally
    effective_sql = _strip_cte(sql)

    if _SUBQUERY_IN_FROM_PATTERN.search(effective_sql):
        result.classification = CLASS_UNKNOWN
        result.unsupported_reason = "Subqueries in FROM clause are not validated"
        return result

    if _UNSUPPORTED_CLAUSE.search(effective_sql):
        result.classification = CLASS_UNKNOWN
        result.unsupported_reason = "CONNECT BY, MODEL, or analytic clauses are not validated"
        return result

    # Classify and parse (use effective_sql which has CTE prefix stripped)
    if _SELECT_PATTERN.match(effective_sql):
        result.classification = CLASS_READ_ONLY
        _parse_select(effective_sql, result)
    elif _INSERT_PATTERN.match(effective_sql):
        result.classification = CLASS_MUTATING
        result.is_mutating = True
        _parse_insert(effective_sql, result)
    elif _UPDATE_PATTERN.match(effective_sql):
        result.classification = CLASS_MUTATING
        result.is_mutating = True
        _parse_update(effective_sql, result)
    elif _DELETE_PATTERN.match(effective_sql):
        result.classification = CLASS_MUTATING
        result.is_mutating = True
        _parse_delete(effective_sql, result)
    elif _MERGE_PATTERN.match(effective_sql):
        result.classification = CLASS_MUTATING
        result.is_mutating = True
        _parse_merge(effective_sql, result)
    else:
        result.classification = CLASS_UNKNOWN
        result.unsupported_reason = "Unrecognised statement type"

    # Extract sequence references from anywhere
    for m in _SEQUENCE_REF.finditer(effective_sql):
        seq_name = _clean_identifier(m.group(1))
        result.sequences.append(seq_name)

    return result


def _parse_select(sql: str, result: _ParsedStatement) -> None:
    """Parse SELECT ... FROM ... [JOIN ...] [WHERE ...]."""
    # Tables from FROM clause
    result.tables.extend(_parse_from_tables(sql))

    # Tables from JOIN clauses
    result.joins.extend(_parse_join_clauses(sql))
    for tname, alias, _ in result.joins:
        result.tables.append((tname, alias))

    # SELECT column list — now returns (col, qualifier) tuples
    col_match = _SELECT_COLUMNS.search(sql)
    if col_match:
        col_text = col_match.group(1)
        result.columns.extend(_extract_simple_column_names(col_text))

    # WHERE column references
    where_match = _WHERE_CLAUSE.search(sql)
    if where_match:
        result.columns.extend(
            _extract_column_names_with_qualifiers(where_match.group(1))
        )


def _parse_insert(sql: str, result: _ParsedStatement) -> None:
    """Parse INSERT INTO table (col1, col2) VALUES (...)."""
    m = _INSERT_TABLE.search(sql)
    if m:
        tname = _clean_identifier(m.group(1))
        result.tables.append((tname, None))
        # Column list
        if m.group(2):
            col_text = m.group(2)
            for col_raw in col_text.split(","):
                col_raw = col_raw.strip()
                if col_raw:
                    result.columns.append((_clean_identifier(col_raw), tname))


def _parse_update(sql: str, result: _ParsedStatement) -> None:
    """Parse UPDATE table SET col1 = ... [WHERE ...]."""
    m = _UPDATE_TABLE.search(sql)
    if m:
        tname = _clean_identifier(m.group(1))
        alias = _clean_identifier(m.group(2)) if m.group(2) else None
        if alias and _is_keyword(alias):
            alias = None
        result.tables.append((tname, alias))

        # SET columns
        set_match = _SET_COLUMNS.search(sql)
        if set_match:
            set_text = set_match.group(1)
            # Extract column names from "col = value" patterns
            for assignment in set_text.split(","):
                eq_pos = assignment.find("=")
                if eq_pos > 0:
                    col_raw = assignment[:eq_pos].strip()
                    clean = _clean_identifier(col_raw)
                    if "." in clean:
                        clean = clean.rsplit(".", 1)[-1]
                    if not _is_keyword(clean):
                        result.columns.append((clean, tname))

    # WHERE columns
    where_match = _WHERE_CLAUSE.search(sql)
    if where_match:
        result.columns.extend(
            _extract_column_names_with_qualifiers(where_match.group(1))
        )


def _parse_delete(sql: str, result: _ParsedStatement) -> None:
    """Parse DELETE FROM table [WHERE ...]."""
    m = _DELETE_TABLE.search(sql)
    if m:
        tname = _clean_identifier(m.group(1))
        alias = _clean_identifier(m.group(2)) if m.group(2) else None
        if alias and _is_keyword(alias):
            alias = None
        result.tables.append((tname, alias))

    # WHERE columns
    where_match = _WHERE_CLAUSE.search(sql)
    if where_match:
        result.columns.extend(
            _extract_column_names_with_qualifiers(where_match.group(1))
        )


def _parse_merge(sql: str, result: _ParsedStatement) -> None:
    """Parse MERGE INTO target USING source ON ... ."""
    m = _MERGE_TABLE.search(sql)
    if m:
        tname = _clean_identifier(m.group(1))
        alias = _clean_identifier(m.group(2)) if m.group(2) else None
        if alias and _is_keyword(alias):
            alias = None
        result.tables.append((tname, alias))

    um = _MERGE_USING.search(sql)
    if um:
        tname = _clean_identifier(um.group(1))
        alias = _clean_identifier(um.group(2)) if um.group(2) else None
        if alias and _is_keyword(alias):
            alias = None
        result.tables.append((tname, alias))


# ---------------------------------------------------------------------------
# Validation against graph
# ---------------------------------------------------------------------------

def _validate_statement(
    sql: str,
    parsed: _ParsedStatement,
    index: _GraphIndex,
) -> SqlStatementResult:
    """Validate a single parsed statement against the graph index."""

    # Unsupported statement → return immediately
    if parsed.unsupported_reason is not None:
        return SqlStatementResult(
            status=STATUS_UNSUPPORTED,
            classification=parsed.classification,
            sql_text=sql,
            issues=(
                SqlValidationIssue(
                    issue_type="unsupported_sql",
                    object_name="",
                    detail=parsed.unsupported_reason,
                    severity="warning",
                ),
            ),
        )

    issues: list[SqlValidationIssue] = []
    table_refs: list[TableReference] = []
    column_refs: list[ColumnReference] = []
    join_vals: list[JoinValidation] = []

    # Build alias → real table name map
    alias_map: dict[str, str] = {}
    seen_tables: set[str] = set()
    # Also track the canonical (graph-resolved) name for each table reference
    resolved_canonical: dict[str, str] = {}  # UPPER(tname) → canonical UPPER name

    # --- Table validation ---
    for tname, alias in parsed.tables:
        if tname in seen_tables:
            # Still register the alias even for duplicates
            if alias:
                alias_map[alias.upper()] = tname
            continue
        seen_tables.add(tname)

        if alias:
            alias_map[alias.upper()] = tname

        node, resolution_method = index.resolve_table_with_method(tname)

        if node is None:
            # Check if it's a backup/historical name pattern
            if _is_backup_name(tname):
                # CB2-6: backup_object is an error and counts as structurally_invalid
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_BACKUP_OBJECT,
                    object_name=tname,
                    detail=f"Table '{tname}' matches backup naming convention (BCK/BACK_UP)",
                    severity="error",
                ))
                table_refs.append(TableReference(
                    name=tname, alias=alias, resolved=False,
                ))
            else:
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_UNKNOWN_TABLE,
                    object_name=tname,
                    detail=f"Table '{tname}' not found in database graph",
                ))
                table_refs.append(TableReference(
                    name=tname, alias=alias, resolved=False,
                ))
        else:
            # Table exists — track canonical name for column/join resolution
            qname_upper = node.qualified_name.upper()
            resolved_canonical[tname.upper()] = qname_upper

            # CB2-6: historical_object is an error and counts as structurally_invalid
            if index.is_historical(qname_upper):
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_HISTORICAL_OBJECT,
                    object_name=tname,
                    detail=f"Table '{tname}' is flagged as historical/dropped/renamed",
                    severity="error",
                ))

            # CB2-6: backup_object is an error and counts as structurally_invalid
            if index.is_backup(qname_upper):
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_BACKUP_OBJECT,
                    object_name=tname,
                    detail=f"Table '{tname}' matches backup naming convention",
                    severity="error",
                ))

            # Fix 5D: Check if resolved via a dynamic/generated synonym
            if index.is_dynamic_synonym(tname):
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_DYNAMIC_SYNONYM,
                    object_name=tname,
                    detail=(
                        f"Table '{tname}' resolved via a dynamic/generated synonym; "
                        f"target may not be stable"
                    ),
                    severity="warning",
                ))

            # Check view/materialized_view mutation
            # CB2-6: MATERIALIZED_VIEW mutation is also invalid
            # Fix 5E: Also check read_only property
            if parsed.is_mutating and (
                node.kind in (
                    NodeKind.VIEW.value,
                    NodeKind.MATERIALIZED_VIEW.value,
                )
                or index.is_read_only(qname_upper)
            ):
                _mv_issue_type = (
                    ISSUE_MV_MUTATION
                    if node.kind == NodeKind.MATERIALIZED_VIEW.value
                    else ISSUE_VIEW_MUTATION
                )
                _mv_label = (
                    "materialized view"
                    if node.kind == NodeKind.MATERIALIZED_VIEW.value
                    else "view"
                    if node.kind == NodeKind.VIEW.value
                    else "read-only object"
                )
                issues.append(SqlValidationIssue(
                    issue_type=_mv_issue_type,
                    object_name=tname,
                    detail=f"Cannot perform mutating operation on {_mv_label} '{tname}'",
                ))

            table_refs.append(TableReference(
                name=tname,
                alias=alias,
                resolved=True,
                node_kind=node.kind,
                node_id=node.id,
                resolution=resolution_method,
            ))

    # --- Column validation with alias resolution (Fix 6) ---
    def _resolve_table_for_column(qualifier: str | None) -> str | None:
        """Resolve a column qualifier to its actual table name.

        Steps:
        1. If no qualifier and exactly one table, use that table.
        2. If qualifier is an alias, resolve through alias_map.
        3. If qualifier is a table name directly, use it.
        4. Try canonical name resolution.
        """
        if qualifier is None:
            # If there's exactly one table, use it
            real_names = [t for t, _ in parsed.tables]
            unique_names = list(dict.fromkeys(real_names))
            if len(unique_names) == 1:
                return unique_names[0]
            return None
        upper_q = qualifier.upper()
        # Check alias map first
        resolved = alias_map.get(upper_q)
        if resolved is not None:
            return resolved
        # It might be the table name directly
        return upper_q

    seen_cols: set[tuple[str, str | None]] = set()
    for col_name, qualifier in parsed.columns:
        table_for_col = _resolve_table_for_column(qualifier)
        col_key = (col_name, table_for_col)
        if col_key in seen_cols:
            continue
        seen_cols.add(col_key)

        if table_for_col:
            # Try the canonical name first for column resolution
            canonical = resolved_canonical.get(table_for_col.upper(), table_for_col)
            col_node = index.resolve_column(canonical, col_name)
            if col_node is None and canonical != table_for_col:
                # Fallback: try with the original name
                col_node = index.resolve_column(table_for_col, col_name)

            if col_node is not None:
                # Fix 5C: Check for source conflict on found columns
                _col_qname = col_node.qualified_name.upper()
                _is_conflicting = (
                    col_node.evidence.status == EvidenceStatus.CONFLICTING.value
                    or col_name.upper().endswith("_TODROP")
                    or index.is_conflicting_column(canonical, col_name)
                )
                if _is_conflicting:
                    issues.append(SqlValidationIssue(
                        issue_type=ISSUE_SOURCE_CONFLICT,
                        object_name=f"{table_for_col}.{col_name}",
                        detail=(
                            f"Column '{col_name}' on table '{table_for_col}' has "
                            f"conflicting evidence sources"
                        ),
                        severity="warning",
                    ))
                column_refs.append(ColumnReference(
                    name=col_name,
                    table_name=table_for_col,
                    resolved=True,
                    node_id=col_node.id,
                ))
            else:
                # Only report unknown_column if the table itself was resolved
                tbl_node = index.resolve_table(table_for_col)
                if tbl_node is not None:
                    # Fix 5B: Check if column is dropped
                    if index.is_dropped_column(canonical, col_name):
                        issues.append(SqlValidationIssue(
                            issue_type=ISSUE_DROPPED_COLUMN,
                            object_name=f"{table_for_col}.{col_name}",
                            detail=(
                                f"Column '{col_name}' on table '{table_for_col}' "
                                f"was dropped"
                            ),
                            severity="error",
                        ))
                    else:
                        # Table exists but column doesn't → incomplete evidence or real issue
                        issues.append(SqlValidationIssue(
                            issue_type=ISSUE_UNKNOWN_COLUMN,
                            object_name=f"{table_for_col}.{col_name}",
                            detail=f"Column '{col_name}' not found on table '{table_for_col}'",
                        ))
                    column_refs.append(ColumnReference(
                        name=col_name,
                        table_name=table_for_col,
                        resolved=False,
                    ))
                else:
                    # Table not resolved either — already reported as unknown_table
                    column_refs.append(ColumnReference(
                        name=col_name,
                        table_name=table_for_col,
                        resolved=False,
                    ))
        else:
            # Cannot determine which table → mark as unresolved, no error
            column_refs.append(ColumnReference(
                name=col_name,
                table_name=None,
                resolved=False,
            ))

    # --- Join validation (CB2-3: column-level FK checking) ---
    # Build complete alias map including join aliases
    all_alias_map: dict[str, str] = dict(alias_map)
    for tname, alias in parsed.tables:
        if alias:
            all_alias_map[alias.upper()] = tname

    for join_tname, join_alias, condition in parsed.joins:
        # Parse the actual ON clause column pairs
        col_pairs = _parse_on_column_pairs(condition, all_alias_map)

        if col_pairs:
            # We have explicit column pairs from the ON clause
            left_t = col_pairs[0][0]
            right_t = col_pairs[0][2]

            # Skip join validation when either table is unresolved — the
            # unknown_table issue already covers that case and
            # unsupported_join would be redundant.
            left_resolved = left_t.upper() in resolved_canonical
            right_resolved = right_t.upper() in resolved_canonical
            if not left_resolved or not right_resolved:
                join_vals.append(JoinValidation(
                    left_table=left_t,
                    right_table=right_t,
                    condition_text=condition or "",
                    supported_by_evidence=False,
                    evidence_kind=None,
                ))
                continue

            # First: check if any relationship exists between these tables
            has_table_rel, table_evidence_kind = index.has_relationship(left_t, right_t)

            if not has_table_rel:
                # No relationship at all → unsupported_join (Fix 4: error, not warning)
                # Fix 5A: Check for denormalized reference pattern
                _issue_type = ISSUE_UNSUPPORTED_JOIN
                _detail = (
                    f"Join between '{left_t}' and '{right_t}' is not supported "
                    f"by FK or inferred relationship evidence"
                )
                for lt, lc, rt, rc in col_pairs:
                    if _DENORM_FK_SUFFIX.search(lc):
                        # Check if the column name matches the other table's short name
                        rt_short = rt.rsplit(".", 1)[-1] if "." in rt else rt
                        if lc.upper().startswith(rt_short.upper().replace("TB_", "").replace("T_", "")):
                            _issue_type = ISSUE_DENORMALIZED_REFERENCE
                            _detail = (
                                f"Join column '{lt}.{lc}' references '{rt}' by naming "
                                f"convention but no declared FK exists"
                            )
                            break
                    if _DENORM_FK_SUFFIX.search(rc):
                        lt_short = lt.rsplit(".", 1)[-1] if "." in lt else lt
                        if rc.upper().startswith(lt_short.upper().replace("TB_", "").replace("T_", "")):
                            _issue_type = ISSUE_DENORMALIZED_REFERENCE
                            _detail = (
                                f"Join column '{rt}.{rc}' references '{lt}' by naming "
                                f"convention but no declared FK exists"
                            )
                            break
                issues.append(SqlValidationIssue(
                    issue_type=_issue_type,
                    object_name=f"{left_t} ↔ {right_t}",
                    detail=_detail,
                    severity="error",
                ))
                join_vals.append(JoinValidation(
                    left_table=left_t,
                    right_table=right_t,
                    condition_text=condition,
                    supported_by_evidence=False,
                ))
            else:
                # Tables have a relationship — now check if columns match
                all_cols_match = True
                for lt, lc, rt, rc in col_pairs:
                    if not index.has_fk_column_match(lt, lc, rt, rc):
                        all_cols_match = False
                        break

                if all_cols_match:
                    join_vals.append(JoinValidation(
                        left_table=left_t,
                        right_table=right_t,
                        condition_text=condition,
                        supported_by_evidence=True,
                        evidence_kind=table_evidence_kind,
                    ))
                else:
                    # Tables related but columns don't match FK evidence
                    # For logical_reference evidence, column-level checking
                    # isn't meaningful — accept it at table level
                    if table_evidence_kind == "logical_reference":
                        join_vals.append(JoinValidation(
                            left_table=left_t,
                            right_table=right_t,
                            condition_text=condition,
                            supported_by_evidence=True,
                            evidence_kind=table_evidence_kind,
                        ))
                    else:
                        # FK relationship but wrong columns → invalid_join_columns
                        col_desc = ", ".join(
                            f"{lt}.{lc}={rt}.{rc}" for lt, lc, rt, rc in col_pairs
                        )
                        issues.append(SqlValidationIssue(
                            issue_type=ISSUE_INVALID_JOIN_COLUMNS,
                            object_name=f"{left_t} ↔ {right_t}",
                            detail=(
                                f"Tables '{left_t}' and '{right_t}' have an FK "
                                f"relationship but the join columns ({col_desc}) "
                                f"do not match declared FK evidence"
                            ),
                            severity="error",
                        ))
                        join_vals.append(JoinValidation(
                            left_table=left_t,
                            right_table=right_t,
                            condition_text=condition,
                            supported_by_evidence=False,
                        ))
        else:
            # No column pairs parseable from ON clause — fall back to table-level check
            left_candidates = [
                t for t, _ in parsed.tables if t != join_tname
            ]

            if not left_candidates:
                join_vals.append(JoinValidation(
                    left_table="",
                    right_table=join_tname,
                    condition_text=condition,
                    supported_by_evidence=False,
                ))
                continue

            # Fall back to first FROM table
            left_t = left_candidates[0]
            right_t = join_tname

            has_rel, evidence_kind = index.has_relationship(left_t, right_t)
            if has_rel:
                join_vals.append(JoinValidation(
                    left_table=left_t,
                    right_table=right_t,
                    condition_text=condition,
                    supported_by_evidence=True,
                    evidence_kind=evidence_kind,
                ))
            else:
                issues.append(SqlValidationIssue(
                    issue_type=ISSUE_UNSUPPORTED_JOIN,
                    object_name=f"{left_t} ↔ {right_t}",
                    detail=(
                        f"Join between '{left_t}' and '{right_t}' is not supported "
                        f"by FK or inferred relationship evidence"
                    ),
                    severity="error",
                ))
                join_vals.append(JoinValidation(
                    left_table=left_t,
                    right_table=right_t,
                    condition_text=condition,
                    supported_by_evidence=False,
                ))

    # --- Sequence validation ---
    for seq_name in parsed.sequences:
        if not index.resolve_sequence(seq_name):
            issues.append(SqlValidationIssue(
                issue_type=ISSUE_SEQUENCE_UNKNOWN,
                object_name=seq_name,
                detail=f"Sequence '{seq_name}' not found in database graph",
                severity="warning",
            ))

    # --- Compute overall statement status ---
    error_issues = [i for i in issues if i.severity == "error"]
    warning_issues = [i for i in issues if i.severity == "warning"]

    # Any unresolved columns where the table was resolved → could be
    # incomplete evidence (columns not in graph)
    has_unresolved_cols_on_resolved_tables = any(
        not cr.resolved and cr.table_name and index.resolve_table(cr.table_name)
        for cr in column_refs
    )

    if error_issues:
        status = STATUS_INVALID
    elif has_unresolved_cols_on_resolved_tables or warning_issues:
        status = STATUS_INCOMPLETE
    else:
        status = STATUS_VALID

    mutation_warning = MUTATION_WARNING if parsed.is_mutating else None

    return SqlStatementResult(
        status=status,
        classification=parsed.classification,
        sql_text=sql,
        table_references=tuple(table_refs),
        column_references=tuple(column_refs),
        join_validations=tuple(join_vals),
        issues=tuple(issues),
        mutation_warning=mutation_warning,
    )


def _extract_join_table_pair(
    condition: str,
    alias_map: dict[str, str],
) -> tuple[str, str] | None:
    """Extract (left_table, right_table) from a JOIN ON condition.

    Looks for patterns like alias1.col = alias2.col.
    """
    eq_match = re.search(
        r"(" + _QUALIFIED_IDENT + r")\s*\.\s*" + _IDENT
        + r"\s*=\s*"
        + r"(" + _QUALIFIED_IDENT + r")\s*\.\s*" + _IDENT,
        condition,
        re.IGNORECASE,
    )
    if eq_match:
        left_raw = _clean_identifier(eq_match.group(1))
        right_raw = _clean_identifier(eq_match.group(2))
        left = alias_map.get(left_raw, left_raw)
        right = alias_map.get(right_raw, right_raw)
        return left, right
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_sql(
    sql_text: str,
    graph: DatabaseGraph,
    context: Any | None = None,
) -> SqlValidationResult:
    """Validate Oracle SQL statements against a reconciled DatabaseGraph.

    This is a **static** validator.  It does not execute SQL, connect to a
    database, or use any external SQL parsing library.  Regex-based parsing
    handles common Oracle DML patterns (SELECT, INSERT, UPDATE, DELETE, MERGE).

    Args:
        sql_text: One or more SQL statements separated by semicolons.
        graph: A reconciled ``DatabaseGraph`` to validate against.
        context: Optional ``DatabaseContextResult`` — reserved for future use.

    Returns:
        A ``SqlValidationResult`` containing per-statement results, issues,
        and an overall status.
    """
    if not sql_text or not sql_text.strip():
        return SqlValidationResult(
            overall_status=STATUS_UNSUPPORTED,
            statements=(),
            graph_fingerprint=graph.fingerprint,
        )

    # Build graph index once
    index = _GraphIndex(graph)

    # Strip comments, split statements
    cleaned = _strip_comments(sql_text)
    raw_statements = _split_statements(cleaned)

    if not raw_statements:
        return SqlValidationResult(
            overall_status=STATUS_UNSUPPORTED,
            statements=(),
            graph_fingerprint=graph.fingerprint,
        )

    statement_results: list[SqlStatementResult] = []
    has_mutation = False

    for stmt_sql in raw_statements:
        parsed = _parse_statement(stmt_sql)
        result = _validate_statement(stmt_sql, parsed, index)
        statement_results.append(result)
        if parsed.is_mutating:
            has_mutation = True

    # Compute overall status — worst status wins
    _STATUS_PRIORITY = {
        STATUS_INVALID: 0,
        STATUS_UNSUPPORTED: 1,
        STATUS_INCOMPLETE: 2,
        STATUS_VALID: 3,
    }
    worst = min(
        (r.status for r in statement_results),
        key=lambda s: _STATUS_PRIORITY.get(s, 99),
    )

    mutation_warning = MUTATION_WARNING if has_mutation else None

    return SqlValidationResult(
        overall_status=worst,
        statements=tuple(statement_results),
        graph_fingerprint=graph.fingerprint,
        mutation_warning=mutation_warning,
    )
