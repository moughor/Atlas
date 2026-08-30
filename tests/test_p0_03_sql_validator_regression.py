"""Phase C regression tests for SQL structural validation.

These tests use **synthetic graphs** — no Sygma or external repository required.
They verify:

  - JOIN with unknown table produces only unknown_table, not unsupported_join
  - JOIN with known tables but no FK produces unsupported_join
  - JOIN with known tables and FK produces structurally_valid
  - Schema-qualified unknown table in JOIN
  - Empty / whitespace / comment-only SQL → unsupported_sql
  - Backup-prefixed table → backup_object
  - Unknown column detection
  - Valid SELECT / UPDATE / INSERT / DELETE on known tables
  - Multi-statement validation
  - Round-trip serialisation of validation results
"""

from __future__ import annotations

import pytest

from moughorai.database_graph.models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    NodeKind,
)
from moughorai.database_graph.sql_validator import validate_sql

# ---------------------------------------------------------------------------
# Helpers — synthetic graph builders
# ---------------------------------------------------------------------------

_VERIFIED = EvidenceRecord.verified()
_edge_id = 0


def _node(kind: str, qname: str, *, schema: str | None = None,
          props: tuple[tuple[str, object], ...] = ()) -> DatabaseGraphNode:
    return DatabaseGraphNode(
        id=qname.lower().replace(".", "_"),
        kind=kind,
        qualified_name=qname,
        schema=schema,
        properties=props,
        evidence=_VERIFIED,
    )


def _edge(kind: str, from_id: str, to_id: str,
          props: tuple[tuple[str, object], ...] = ()) -> DatabaseGraphEdge:
    global _edge_id
    _edge_id += 1
    return DatabaseGraphEdge(
        id=f"e_sql_{_edge_id}",
        kind=kind,
        from_node=from_id,
        to_node=to_id,
        properties=props,
        evidence=_VERIFIED,
    )


def _col(table_qname: str, col_name: str) -> DatabaseGraphNode:
    return _node(NodeKind.COLUMN.value, f"{table_qname}.{col_name}")


def _build_fk_graph() -> DatabaseGraph:
    """Two tables with FK and columns.

    TB_ORDERS(ID, CUSTOMER_ID)
    TB_CUSTOMERS(ID, NAME)
    FK: TB_ORDERS.CUSTOMER_ID → TB_CUSTOMERS.ID
    """
    orders = _node(NodeKind.TABLE.value, "TB_ORDERS")
    customers = _node(NodeKind.TABLE.value, "TB_CUSTOMERS")
    o_id = _col("TB_ORDERS", "ID")
    o_cust = _col("TB_ORDERS", "CUSTOMER_ID")
    c_id = _col("TB_CUSTOMERS", "ID")
    c_name = _col("TB_CUSTOMERS", "NAME")

    edges = [
        _edge(EdgeKind.HAS_COLUMN.value, orders.id, o_id.id),
        _edge(EdgeKind.HAS_COLUMN.value, orders.id, o_cust.id),
        _edge(EdgeKind.HAS_COLUMN.value, customers.id, c_id.id),
        _edge(EdgeKind.HAS_COLUMN.value, customers.id, c_name.id),
        _edge(EdgeKind.FOREIGN_KEY_TO.value, orders.id, customers.id,
              props=(
                  ("source_table", "TB_ORDERS"),
                  ("target_table", "TB_CUSTOMERS"),
                  ("source_column", "CUSTOMER_ID"),
                  ("target_column", "ID"),
              )),
    ]

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "sql_regr"},
        nodes=(orders, customers, o_id, o_cust, c_id, c_name),
        edges=tuple(edges),
    )


def _build_no_fk_graph() -> DatabaseGraph:
    """Two tables WITHOUT FK.

    TB_PRODUCTS(ID, NAME)
    TB_CATEGORIES(ID, LABEL)
    No FK between them.
    """
    prods = _node(NodeKind.TABLE.value, "TB_PRODUCTS")
    cats = _node(NodeKind.TABLE.value, "TB_CATEGORIES")
    p_id = _col("TB_PRODUCTS", "ID")
    p_name = _col("TB_PRODUCTS", "NAME")
    c_id = _col("TB_CATEGORIES", "ID")
    c_label = _col("TB_CATEGORIES", "LABEL")

    edges = [
        _edge(EdgeKind.HAS_COLUMN.value, prods.id, p_id.id),
        _edge(EdgeKind.HAS_COLUMN.value, prods.id, p_name.id),
        _edge(EdgeKind.HAS_COLUMN.value, cats.id, c_id.id),
        _edge(EdgeKind.HAS_COLUMN.value, cats.id, c_label.id),
    ]

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "sql_nofk"},
        nodes=(prods, cats, p_id, p_name, c_id, c_label),
        edges=tuple(edges),
    )


# ---------------------------------------------------------------------------
# Tests: JOIN with unknown table — the corrected construct
# ---------------------------------------------------------------------------


class TestJoinWithUnknownTable:
    """Verify that JOIN with a nonexistent table produces only unknown_table."""

    def test_join_unknown_right_table(self):
        """JOIN with unknown right table → unknown_table only, no unsupported_join."""
        g = _build_fk_graph()
        result = validate_sql(
            "SELECT o.ID FROM TB_ORDERS o JOIN TB_NONEXISTENT x ON x.ID = o.ID", g
        )
        assert result.overall_status == "structurally_invalid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unknown_table" in issue_types
        assert "unsupported_join" not in issue_types

    def test_join_unknown_left_table(self):
        """JOIN with unknown left table → unknown_table only."""
        g = _build_fk_graph()
        result = validate_sql(
            "SELECT x.ID FROM TB_PHANTOM x JOIN TB_ORDERS o ON o.ID = x.ID", g
        )
        assert result.overall_status == "structurally_invalid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unknown_table" in issue_types
        assert "unsupported_join" not in issue_types

    def test_join_both_tables_unknown(self):
        """JOIN with both tables unknown → unknown_table for both, no unsupported_join."""
        g = _build_fk_graph()
        result = validate_sql(
            "SELECT a.ID FROM TB_FAKE_A a JOIN TB_FAKE_B b ON b.ID = a.ID", g
        )
        assert result.overall_status == "structurally_invalid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unknown_table" in issue_types
        assert "unsupported_join" not in issue_types


# ---------------------------------------------------------------------------
# Tests: JOIN with known tables — positive and negative
# ---------------------------------------------------------------------------


class TestJoinWithKnownTables:
    """Verify JOIN validation when both tables are resolved."""

    def test_join_with_fk_is_valid(self):
        """JOIN between FK-related tables → structurally_valid."""
        g = _build_fk_graph()
        result = validate_sql(
            "SELECT o.ID, c.NAME FROM TB_ORDERS o JOIN TB_CUSTOMERS c ON c.ID = o.CUSTOMER_ID", g
        )
        assert result.overall_status == "structurally_valid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unsupported_join" not in issue_types
        assert "unknown_table" not in issue_types

    def test_join_without_fk_is_unsupported(self):
        """JOIN between tables with no FK → unsupported_join."""
        g = _build_no_fk_graph()
        result = validate_sql(
            "SELECT p.ID FROM TB_PRODUCTS p JOIN TB_CATEGORIES c ON c.ID = p.ID", g
        )
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unsupported_join" in issue_types
        assert "unknown_table" not in issue_types


# ---------------------------------------------------------------------------
# Tests: empty / comment / unsupported SQL
# ---------------------------------------------------------------------------


class TestUnsupportedSql:
    """Verify unsupported_sql classification for empty/comment/whitespace."""

    def test_empty_string(self):
        g = _build_fk_graph()
        result = validate_sql("", g)
        assert result.overall_status == "unsupported_sql"

    def test_whitespace_only(self):
        g = _build_fk_graph()
        result = validate_sql("   \n\t  ", g)
        assert result.overall_status == "unsupported_sql"

    def test_comment_only(self):
        g = _build_fk_graph()
        result = validate_sql("-- only a comment, nothing to validate", g)
        assert result.overall_status == "unsupported_sql"


# ---------------------------------------------------------------------------
# Tests: backup table detection
# ---------------------------------------------------------------------------


class TestBackupTableDetection:
    """Verify backup_object detection for BCK-prefixed tables."""

    def test_bck_prefixed_table(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM BCK_TB_ORDERS", g)
        assert result.overall_status == "structurally_invalid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "backup_object" in issue_types

    def test_bck_nonexistent_table(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM BCK_NONEXISTENT_TABLE", g)
        assert result.overall_status == "structurally_invalid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "backup_object" in issue_types


# ---------------------------------------------------------------------------
# Tests: unknown column detection
# ---------------------------------------------------------------------------


class TestUnknownColumnDetection:
    """Verify unknown_column for references to nonexistent columns."""

    def test_unknown_column_on_known_table(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT o.PHANTOM_COL FROM TB_ORDERS o", g)
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unknown_column" in issue_types

    def test_known_column_on_known_table(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT o.ID FROM TB_ORDERS o", g)
        assert result.overall_status == "structurally_valid"
        issue_types = {i.issue_type for s in result.statements for i in s.issues}
        assert "unknown_column" not in issue_types


# ---------------------------------------------------------------------------
# Tests: DML classification
# ---------------------------------------------------------------------------


class TestDmlClassification:
    """Verify SQL classification for different statement types."""

    def test_select_is_read_only(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM TB_ORDERS", g)
        assert result.statements[0].classification == "read_only"

    def test_update_is_mutating(self):
        g = _build_fk_graph()
        result = validate_sql("UPDATE TB_ORDERS SET ID = 1 WHERE ID = 2", g)
        assert result.statements[0].classification == "mutating"
        assert result.mutation_warning == "BUSINESS_REVIEW_REQUIRED"

    def test_insert_is_mutating(self):
        g = _build_fk_graph()
        result = validate_sql("INSERT INTO TB_ORDERS (ID) VALUES (1)", g)
        assert result.statements[0].classification == "mutating"

    def test_delete_is_mutating(self):
        g = _build_fk_graph()
        result = validate_sql("DELETE FROM TB_ORDERS WHERE ID = 1", g)
        assert result.statements[0].classification == "mutating"


# ---------------------------------------------------------------------------
# Tests: multi-statement validation
# ---------------------------------------------------------------------------


class TestMultiStatement:
    """Verify multi-statement SQL handling."""

    def test_two_statements_mixed(self):
        g = _build_fk_graph()
        result = validate_sql(
            "SELECT * FROM TB_ORDERS; SELECT * FROM TB_NONEXISTENT", g
        )
        assert len(result.statements) == 2
        assert result.statements[0].status == "structurally_valid"
        assert result.statements[1].status == "structurally_invalid"
        assert result.overall_status == "structurally_invalid"


# ---------------------------------------------------------------------------
# Tests: graph fingerprint binding
# ---------------------------------------------------------------------------


class TestGraphFingerprint:
    """Verify validation result is bound to graph fingerprint."""

    def test_result_carries_fingerprint(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM TB_ORDERS", g)
        assert result.graph_fingerprint == g.fingerprint
        assert len(result.graph_fingerprint) == 64


# ---------------------------------------------------------------------------
# Tests: serialisation round-trip
# ---------------------------------------------------------------------------


class TestValidationRoundTrip:
    """Verify to_dict round-trip for validation results."""

    def test_result_round_trip(self):
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM TB_ORDERS", g)
        d = result.to_dict()
        assert d["overall_status"] == "structurally_valid"
        assert d["graph_fingerprint"] == g.fingerprint
        assert len(d["statements"]) == 1


# ---------------------------------------------------------------------------
# Tests: schema-qualified dynamic synonym detection (STEP 4 regression)
# ---------------------------------------------------------------------------


class TestSchemaFallbackDynamicSynonym:
    """Verify schema fallback raises DYNAMIC_SYNONYM_TARGET_UNPROVEN.
    
    This test covers SYGMA-DB-014-NEG-01 pattern: when SQL references a table
    with a non-native schema prefix (e.g., CONSUMER.TB_GRP_PF) and the table
    is resolved via schema fallback (ignoring the prefix), the resolution is
    unproven because a dynamic synonym would be needed to make it work.
    """

    def test_consumer_schema_raises_dynamic_synonym_unproven(self):
        """Non-native schema prefix triggers DYNAMIC_SYNONYM_TARGET_UNPROVEN."""
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM CONSUMER.TB_ORDERS", g)
        
        # Should be incomplete_evidence due to warning
        assert result.overall_status == "incomplete_evidence"
        
        # Check for the specific issue
        stmt = result.statements[0]
        issue_types = {i.issue_type for i in stmt.issues}
        assert "dynamic_synonym_target_unproven" in issue_types
        
        # Verify the issue detail mentions schema fallback
        for issue in stmt.issues:
            if issue.issue_type == "dynamic_synonym_target_unproven":
                assert "CONSUMER" in issue.object_name.upper()
                assert "schema fallback" in issue.detail.lower()

    def test_sygma_schema_does_not_raise(self):
        """Native SYGMA schema prefix does NOT trigger the warning."""
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM SYGMA.TB_ORDERS", g)
        
        # No warnings expected for native schema
        stmt = result.statements[0]
        issue_types = {i.issue_type for i in stmt.issues}
        assert "dynamic_synonym_target_unproven" not in issue_types

    def test_unqualified_table_does_not_raise(self):
        """Unqualified table references do NOT trigger the warning."""
        g = _build_fk_graph()
        result = validate_sql("SELECT * FROM TB_ORDERS", g)
        
        # No warnings for unqualified references
        stmt = result.statements[0]
        issue_types = {i.issue_type for i in stmt.issues}
        assert "dynamic_synonym_target_unproven" not in issue_types
        assert result.overall_status == "structurally_valid"
