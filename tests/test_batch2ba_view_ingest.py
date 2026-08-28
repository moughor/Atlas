"""Tests for Oracle view/MV SQL ingest and reconciler integration.

Batch 2B-A: view_sql_ingest parser unit tests + Sygma integration tests.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Sygma availability
# ---------------------------------------------------------------------------

SYGMA_ROOT = Path(
    os.environ.get("SYGMA_ROOT", "/home/meskeda/git/sygma/sygma")
)
_SYGMA_AVAILABLE = SYGMA_ROOT.is_dir()

requires_sygma = pytest.mark.skipif(
    not _SYGMA_AVAILABLE,
    reason=f"Sygma repository not found at {SYGMA_ROOT}",
)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from moughorai.database_graph.view_sql_ingest import (
    ViewIngestResult,
    ingest_view_sql,
    _parse_sql_file,
    _strip_plsql_wrappers,
    _strip_sql_comments,
    _extract_select_aliases,
    _extract_source_tables,
    _ParsedView,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sql_string(
    sql: str,
    *,
    is_mview_dir: bool = False,
    priority: int = 1,
    filename: str = "test.sql",
) -> tuple[list[_ParsedView], list[str]]:
    """Parse a SQL string by writing to a temp file and parsing it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        sql_file = root / filename
        sql_file.write_text(sql, encoding="utf-8")
        return _parse_sql_file(
            sql_file,
            root,
            is_mview_dir=is_mview_dir,
            priority=priority,
        )


# ===========================================================================
# General parser tests (NOT Sygma-specific)
# ===========================================================================


class TestParseSimpleView:
    """test_parse_simple_view: CREATE VIEW foo AS SELECT a, b FROM bar"""

    def test_basic_create_view(self):
        sql = "CREATE VIEW foo AS SELECT a, b FROM bar;"
        views, warnings = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.is_materialized is False
        assert set(v.columns) == {"A", "B"}
        assert ("BAR",) in [(t[1],) for t in v.source_tables]


class TestParseOrReplaceView:
    """test_parse_or_replace_view: CREATE OR REPLACE VIEW foo AS SELECT ..."""

    def test_or_replace(self):
        sql = "CREATE OR REPLACE VIEW foo AS SELECT x, y, z FROM baz;"
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.is_materialized is False
        assert set(v.columns) == {"X", "Y", "Z"}


class TestParseForceView:
    """test_parse_force_view: CREATE OR REPLACE FORCE VIEW foo AS ..."""

    def test_force_keyword(self):
        sql = "CREATE OR REPLACE FORCE VIEW foo AS SELECT id, name FROM tbl;"
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.is_materialized is False
        assert "ID" in v.columns
        assert "NAME" in v.columns


class TestParseMaterializedView:
    """test_parse_materialized_view: CREATE MATERIALIZED VIEW foo BUILD IMMEDIATE ... AS SELECT ..."""

    def test_mv_with_build_immediate(self):
        sql = textwrap.dedent("""\
            CREATE MATERIALIZED VIEW foo
            BUILD IMMEDIATE
            REFRESH FORCE ON DEMAND
            AS
            SELECT id, total FROM orders;
        """)
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.is_materialized is True
        assert "ID" in v.columns
        assert "TOTAL" in v.columns

    def test_mv_from_mview_dir(self):
        """A file in a materialized_views directory is always treated as MV."""
        sql = "CREATE VIEW foo AS SELECT a FROM t;"
        views, _ = _parse_sql_string(sql, is_mview_dir=True)

        assert len(views) == 1
        assert views[0].is_materialized is True


class TestParseSchemaQualified:
    """test_parse_schema_qualified: CREATE VIEW SCHEMA.foo AS ... -> name='FOO'"""

    def test_schema_stripped(self):
        sql = "CREATE VIEW MYSCHEMA.foo AS SELECT col1 FROM tbl1;"
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.schema == "MYSCHEMA"


class TestParsePlsqlWrapper:
    """test_parse_plsql_wrapper: SET SERVEROUTPUT...DECLARE...BEGIN...END/ followed by CREATE MV"""

    def test_plsql_stripped_before_create(self):
        sql = textwrap.dedent("""\
            SET SERVEROUTPUT ON
            DECLARE
              v_count NUMBER;
            BEGIN
              SELECT COUNT(*) INTO v_count FROM user_mviews WHERE mview_name = 'FOO';
              IF v_count > 0 THEN
                EXECUTE IMMEDIATE 'DROP MATERIALIZED VIEW FOO';
              END IF;
            END;
            /
            CREATE MATERIALIZED VIEW foo
            BUILD IMMEDIATE
            REFRESH COMPLETE ON DEMAND
            AS
            SELECT id, name FROM source_table;
        """)
        views, _ = _parse_sql_string(sql, is_mview_dir=True)

        assert len(views) == 1
        v = views[0]
        assert v.name == "FOO"
        assert v.is_materialized is True
        assert "ID" in v.columns
        assert "NAME" in v.columns


class TestParseMultilineColumns:
    """test_parse_multiline_columns: columns spread across multiple lines"""

    def test_multiline_select(self):
        sql = textwrap.dedent("""\
            CREATE VIEW multi_col_view AS
            SELECT
                col_a,
                col_b,
                col_c,
                col_d
            FROM some_table;
        """)
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert set(v.columns) == {"COL_A", "COL_B", "COL_C", "COL_D"}


class TestParseCte:
    """test_parse_cte: WITH ... AS (...) SELECT ..."""

    def test_cte_columns(self):
        sql = textwrap.dedent("""\
            CREATE VIEW cte_view AS
            WITH base AS (
                SELECT id, name, status FROM raw_data
            )
            SELECT id, name FROM base WHERE status = 'ACTIVE';
        """)
        views, _ = _parse_sql_string(sql)

        assert len(views) == 1
        v = views[0]
        assert "ID" in v.columns
        assert "NAME" in v.columns


class TestWritableIsFalse:
    """test_writable_is_false: every view/MV node has writable=false"""

    def test_view_not_writable(self):
        """View nodes built from parsed views have writable=False."""
        from moughorai.database_graph.view_sql_ingest import _build_view_node

        sql = "CREATE VIEW wtest AS SELECT a FROM t;"
        views, _ = _parse_sql_string(sql)

        node = _build_view_node(views[0])
        props = dict(node.properties)
        assert props.get("writable") is False

    def test_mv_not_writable(self):
        """MV nodes built from parsed MVs have writable=False."""
        from moughorai.database_graph.view_sql_ingest import _build_view_node

        sql = "CREATE MATERIALIZED VIEW mvtest BUILD IMMEDIATE REFRESH FORCE ON DEMAND AS SELECT a FROM t;"
        views, _ = _parse_sql_string(sql)

        node = _build_view_node(views[0])
        props = dict(node.properties)
        assert props.get("writable") is False


class TestDuplicateDetection:
    """test_duplicate_detection: same view in two files -> conflict recorded"""

    def test_duplicate_with_different_body(self, tmp_path):
        """Two files defining the same view with different SQL produce a conflict."""
        # Create a minimal repo structure
        view_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "VIEWS"
        view_dir.mkdir(parents=True)

        migration_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "db" / "migration" / "views"
        migration_dir.mkdir(parents=True)

        # View definition 1 (priority=1)
        (view_dir / "VW_DUP_TEST.sql").write_text(
            "CREATE OR REPLACE VIEW VW_DUP_TEST AS SELECT a FROM t1;",
            encoding="utf-8",
        )
        # View definition 2 (priority=2, different body)
        (migration_dir / "VW_DUP_TEST.sql").write_text(
            "CREATE OR REPLACE VIEW VW_DUP_TEST AS SELECT a, b FROM t2;",
            encoding="utf-8",
        )

        result = ingest_view_sql(tmp_path)

        # Should have exactly one view node (duplicate resolved)
        view_nodes = [n for n in result.view_nodes if n.qualified_name == "VW_DUP_TEST"]
        assert len(view_nodes) == 1

        # Should have a conflict record
        conflicts = [c for c in result.conflicts if "VW_DUP_TEST" in c.description]
        assert len(conflicts) >= 1
        assert "resolved_priority" in conflicts[0].resolution


class TestReconcilerViewIntegration:
    """Test that the reconciler properly integrates view_result."""

    def test_reconciler_with_view_result_only(self, tmp_path):
        """Reconciler accepts view_result without Jailer or JPA."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        # Create a view-only repo
        view_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "VIEWS"
        view_dir.mkdir(parents=True)
        (view_dir / "VW_TEST.sql").write_text(
            "CREATE VIEW VW_TEST AS SELECT x, y FROM some_table;",
            encoding="utf-8",
        )

        view_result = ingest_view_sql(tmp_path)
        graph = reconcile_database_graph(
            tmp_path,
            jailer_result=None,
            jpa_result=None,
            view_result=view_result,
        )

        # Graph should contain view nodes
        node_names = {n.qualified_name for n in graph.nodes}
        assert "VW_TEST" in node_names

        # Coverage should reflect views
        assert graph.coverage.views_scanned is True
        assert graph.coverage.views_resolved >= 1

    def test_reconciler_views_scanned_flag(self, tmp_path):
        """views_scanned is True when view_result is provided."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        view_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "VIEWS"
        view_dir.mkdir(parents=True)
        (view_dir / "VW_FLAG.sql").write_text(
            "CREATE VIEW VW_FLAG AS SELECT id FROM flags;",
            encoding="utf-8",
        )

        view_result = ingest_view_sql(tmp_path)
        graph = reconcile_database_graph(
            tmp_path,
            jailer_result=None,
            jpa_result=None,
            view_result=view_result,
        )

        assert graph.coverage.views_scanned is True

    def test_reconciler_has_column_edges(self, tmp_path):
        """Reconciler graph includes HAS_COLUMN edges from view_result."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        view_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "VIEWS"
        view_dir.mkdir(parents=True)
        (view_dir / "VW_COLS.sql").write_text(
            "CREATE VIEW VW_COLS AS SELECT a, b, c FROM t1;",
            encoding="utf-8",
        )

        view_result = ingest_view_sql(tmp_path)
        graph = reconcile_database_graph(
            tmp_path,
            jailer_result=None,
            jpa_result=None,
            view_result=view_result,
        )

        has_col_edges = [e for e in graph.edges if e.kind == "HAS_COLUMN"]
        assert len(has_col_edges) >= 3  # a, b, c

    def test_reconciler_derived_from_edges(self, tmp_path):
        """Reconciler graph includes DERIVED_FROM/READS_FROM edges."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        mv_dir = tmp_path / "sygma-db" / "src" / "main" / "resources" / "MATERIALIZED_VIEWS"
        mv_dir.mkdir(parents=True)
        (mv_dir / "MV_TEST.sql").write_text(
            "CREATE MATERIALIZED VIEW MV_TEST BUILD IMMEDIATE REFRESH FORCE ON DEMAND "
            "AS SELECT x FROM source_tbl;",
            encoding="utf-8",
        )

        view_result = ingest_view_sql(tmp_path)
        graph = reconcile_database_graph(
            tmp_path,
            jailer_result=None,
            jpa_result=None,
            view_result=view_result,
        )

        dep_edges = [
            e for e in graph.edges
            if e.kind in ("DERIVED_FROM", "READS_FROM")
        ]
        assert len(dep_edges) >= 1


# ===========================================================================
# Sygma integration tests
# ===========================================================================


@requires_sygma
class TestSygmaViewIngest:
    """Integration tests against the real Sygma repository."""

    @pytest.fixture(scope="class")
    def sygma_view_result(self) -> ViewIngestResult:
        """Run view ingest once and cache for the class."""
        return ingest_view_sql(SYGMA_ROOT)

    @pytest.fixture(scope="class")
    def sygma_graph(self, sygma_view_result):
        """Build a reconciled graph with view result for Sygma tests."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        return reconcile_database_graph(
            SYGMA_ROOT,
            jailer_result=None,
            jpa_result=None,
            view_result=sygma_view_result,
        )

    # -------------------------------------------------------------------
    # test_sygma_vw_hd_failed_doc_gen_found
    # -------------------------------------------------------------------
    def test_sygma_vw_hd_failed_doc_gen_found(self, sygma_view_result):
        """VW_HD_FAILED_DOC_GEN is found in the graph with correct columns."""
        names = {n.qualified_name for n in sygma_view_result.view_nodes}
        assert "VW_HD_FAILED_DOC_GEN" in names

        # Find the parsed view node and check columns
        node = next(
            n for n in sygma_view_result.view_nodes
            if n.qualified_name == "VW_HD_FAILED_DOC_GEN"
        )
        assert node.kind == "view"

        # Check column nodes
        col_names = {
            n.qualified_name.split(".", 1)[1]
            for n in sygma_view_result.column_nodes
            if n.qualified_name.startswith("VW_HD_FAILED_DOC_GEN.")
        }
        assert len(col_names) >= 10  # known to have 14 columns

    # -------------------------------------------------------------------
    # test_sygma_vw_latest_closed_rep_sessions_found
    # -------------------------------------------------------------------
    def test_sygma_vw_latest_closed_rep_sessions_found(self, sygma_view_result):
        """VW_LATEST_CLOSED_REP_SESSIONS is found in the graph."""
        names = {n.qualified_name for n in sygma_view_result.view_nodes}
        assert "VW_LATEST_CLOSED_REP_SESSIONS" in names

    # -------------------------------------------------------------------
    # test_sygma_vw_bam_amendments_found
    # -------------------------------------------------------------------
    def test_sygma_vw_bam_amendments_found(self, sygma_view_result):
        """VW_BAM_AMENDMENTS is found in the graph."""
        names = {n.qualified_name for n in sygma_view_result.view_nodes}
        assert "VW_BAM_AMENDMENTS" in names

    # -------------------------------------------------------------------
    # test_sygma_mv_a_reporting_periods_found
    # -------------------------------------------------------------------
    def test_sygma_mv_a_reporting_periods_found(self, sygma_view_result):
        """MV_A_REPORTING_PERIODS is found as a materialized_view."""
        mv_nodes = {
            n.qualified_name: n
            for n in sygma_view_result.view_nodes
            if n.kind == "materialized_view"
        }
        assert "MV_A_REPORTING_PERIODS" in mv_nodes
        assert mv_nodes["MV_A_REPORTING_PERIODS"].kind == "materialized_view"

    # -------------------------------------------------------------------
    # test_sygma_mv_a_project_data_found
    # -------------------------------------------------------------------
    def test_sygma_mv_a_project_data_found(self, sygma_view_result):
        """MV_A_PROJECT_DATA is found in the graph."""
        names = {n.qualified_name for n in sygma_view_result.view_nodes}
        assert "MV_A_PROJECT_DATA" in names

    # -------------------------------------------------------------------
    # test_sygma_view_has_dependencies
    # -------------------------------------------------------------------
    def test_sygma_view_has_dependencies(self, sygma_view_result):
        """VW_HD_FAILED_DOC_GEN references TB_APP_BCH_DOC_GEN_RES etc."""
        # Find the view node ID
        vw_node = next(
            n for n in sygma_view_result.view_nodes
            if n.qualified_name == "VW_HD_FAILED_DOC_GEN"
        )

        # Get dependency edges originating from this view
        dep_edges = [
            e for e in sygma_view_result.dependency_edges
            if e.from_node == vw_node.id
        ]
        assert len(dep_edges) >= 5  # known to have ~15 table deps

        # Check that at least one references a known table
        dep_tables = set()
        for e in dep_edges:
            props = dict(e.properties)
            if "source_table" in props:
                dep_tables.add(props["source_table"])
        assert "TB_APP_BCH_DOC_GEN_RES" in dep_tables or any(
            "DOC_GEN" in t for t in dep_tables
        )

    # -------------------------------------------------------------------
    # test_sygma_view_column_count
    # -------------------------------------------------------------------
    def test_sygma_view_column_count(self, sygma_view_result):
        """Views have projected columns."""
        assert sygma_view_result.column_count > 100  # expect ~7000+

    # -------------------------------------------------------------------
    # test_sygma_views_not_writable
    # -------------------------------------------------------------------
    def test_sygma_views_not_writable(self, sygma_view_result):
        """All view/MV nodes have writable=False."""
        for node in sygma_view_result.view_nodes:
            props = dict(node.properties)
            assert props.get("writable") is False, (
                f"{node.qualified_name} has writable={props.get('writable')}"
            )

    # -------------------------------------------------------------------
    # Overall counts sanity
    # -------------------------------------------------------------------
    def test_sygma_view_count(self, sygma_view_result):
        """At least 90+ regular views."""
        assert sygma_view_result.view_count >= 90

    def test_sygma_mv_count(self, sygma_view_result):
        """At least 100+ materialized views."""
        assert sygma_view_result.mv_count >= 100

    def test_sygma_total_nodes(self, sygma_view_result):
        """Total nodes include views + columns."""
        assert len(sygma_view_result.all_nodes) > 1000

    def test_sygma_total_edges(self, sygma_view_result):
        """Total edges include dependencies + HAS_COLUMN."""
        assert len(sygma_view_result.all_edges) > 1000

    def test_sygma_graph_coverage(self, sygma_graph):
        """Reconciled graph has views_scanned=True."""
        assert sygma_graph.coverage.views_scanned is True
        assert sygma_graph.coverage.views_resolved >= 100
