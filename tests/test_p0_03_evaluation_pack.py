"""CB2-10: Independent 14-case / 42-SQL evaluation pack for Atlas.

This test file is the release gate.  It tests REAL Sygma data from the
reconciled database graph (Jailer + JPA) and verifies:

  - 14 context-selection cases (story text → bounded subgraph)
  - 42 SQL-validation fixtures (3 per case: valid, invalid, edge)

Tests skip gracefully when the Sygma repository is unavailable.

Tables confirmed present in the reconciled graph (verified evidence):
  TB_GRP_PF, TB_GRP_PF_FEATURE, TB_GRP_PF_FEATURE_P,
  TB_RT_SESSION_INSTANCE, TB_APP_PROJECT_BASE,
  TB_RT_RULE_EXCEPTION_DEF, TB_APP_BCH_DOC_GEN_RES,
  TB_RT_EXERCISE_INSTANCE, TB_RT_CONTEXT, TB_RT_RULE_RESULT

Tables confirmed NOT in effective graph:
  TB_RT_DOC_GEN, TB_RT_WORKFLOW, TB_RT_AUDIT_TRAIL, TB_GRP_BU,
  TB_APP_PARTNER (these are NOT in Jailer CSV)

BCK-prefixed tables are excluded from the effective graph.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Sygma repo location and availability guard
# ---------------------------------------------------------------------------

SYGMA_ROOT = Path(
    os.environ.get("SYGMA_ROOT", "/home/meskeda/git/sygma/sygma")
)

_sygma_available = SYGMA_ROOT.is_dir() and (
    SYGMA_ROOT
    / "sygma-it"
    / "sygma-it-services"
    / "src"
    / "test"
    / "jailer"
    / "Sygma"
    / "table.csv"
).exists()

requires_sygma = pytest.mark.skipif(
    not _sygma_available,
    reason=f"Sygma repository not available at {SYGMA_ROOT}",
)

# ---------------------------------------------------------------------------
# SqlFixture dataclass
# ---------------------------------------------------------------------------


@dataclass
class SqlFixture:
    """A single SQL validation fixture."""

    case_id: int
    fixture_id: str  # e.g. 'case01_valid'
    sql: str
    expected_outcome: str  # structurally_valid | structurally_invalid | incomplete_evidence | unsupported_sql
    expected_issues: list[str]  # issue types expected
    description: str


# ---------------------------------------------------------------------------
# Fixtures — build the graph once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jailer_result():
    from moughorai.database_graph.jailer_ingest import ingest_jailer

    return ingest_jailer(SYGMA_ROOT)


@pytest.fixture(scope="module")
def jpa_result():
    from moughorai.database_graph.jpa_extractor import extract_jpa_entities

    return extract_jpa_entities(SYGMA_ROOT)


@pytest.fixture(scope="module")
def fixed_provenance():
    return {
        "vcs": "git",
        "head_sha": "eval-pack-test",
        "head_ref": "refs/heads/develop",
        "worktree_state": "clean",
        "captured_at": "2025-01-01T00:00:00Z",
        "verification": "exact",
    }


@pytest.fixture(scope="module")
def reconciled_graph(jailer_result, jpa_result, fixed_provenance):
    from moughorai.database_graph.reconciler import reconcile_database_graph

    return reconcile_database_graph(
        SYGMA_ROOT,
        jailer_result,
        jpa_result,
        provenance=fixed_provenance,
        workspace_fingerprint="eval-pack-ws-fp",
    )


# ---------------------------------------------------------------------------
# Helper lookups built once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph_index(reconciled_graph):
    """Pre-built lookup dicts for the reconciled graph."""
    g = reconciled_graph

    table_by_name = {
        n.qualified_name: n
        for n in g.nodes
        if n.kind in ("table", "view", "materialized_view")
    }
    table_id_to_name = {n.id: n.qualified_name for n in g.nodes if n.kind in ("table", "view", "materialized_view")}
    entity_by_id = {n.id: n for n in g.nodes if n.kind == "java_entity"}
    column_names = {n.qualified_name for n in g.nodes if n.kind == "column"}

    # FK edges: (from_table, to_table) -> edge
    fk_pairs: dict[tuple[str, str], list] = {}
    for e in g.edges:
        if e.kind == "FOREIGN_KEY_TO":
            fn = table_id_to_name.get(e.from_node, "")
            tn = table_id_to_name.get(e.to_node, "")
            if fn and tn:
                fk_pairs.setdefault((fn, tn), []).append(e)

    # MAPS_TO_TABLE edges
    maps_to: dict[str, str] = {}  # entity_qname -> table_name
    for e in g.edges:
        if e.kind == "MAPS_TO_TABLE":
            ent = entity_by_id.get(e.from_node)
            tbl = table_id_to_name.get(e.to_node)
            if ent and tbl:
                maps_to[ent.qualified_name] = tbl

    return {
        "graph": g,
        "table_by_name": table_by_name,
        "table_id_to_name": table_id_to_name,
        "entity_by_id": entity_by_id,
        "column_names": column_names,
        "fk_pairs": fk_pairs,
        "maps_to": maps_to,
    }


# ===========================================================================
# 14 Context Cases
# ===========================================================================

CONTEXT_CASES = [
    # (case_id, story_text, required_tables, required_fk_pairs, must_have_maps_to, must_exclude_prefixes)
    (
        1,
        "Modify the project features group: update TB_GRP_PF, TB_GRP_PF_FEATURE, and ProjectFeature entity columns.",
        ["TB_GRP_PF", "TB_GRP_PF_FEATURE"],
        [("TB_GRP_PF_FEATURE", "TB_GRP_PF")],
        [],
        ["BCK"],
    ),
    (
        2,
        "Fix session instance lifecycle: TB_RT_SESSION_INSTANCE session should handle exercise state transitions.",
        ["TB_RT_SESSION_INSTANCE"],
        [],  # FK neighbors are optional — we just need the table
        [],
        ["BCK"],
    ),
    (
        3,
        "Update the project base record: TB_APP_PROJECT_BASE project number and call context.",
        ["TB_APP_PROJECT_BASE"],
        [],
        [],
        ["BCK"],
    ),
    (
        4,
        "Manage rule exceptions: TB_RT_RULE_EXCEPTION_DEF rule exception definitions and justifications.",
        ["TB_RT_RULE_EXCEPTION_DEF"],
        [],
        [],
        ["BCK"],
    ),
    (
        5,
        "Fix batch document generation results: TB_APP_BCH_DOC_GEN_RES document generation callback handling.",
        ["TB_APP_BCH_DOC_GEN_RES"],
        [],
        [],
        ["BCK"],
    ),
    (
        6,
        "Update exercise instance state: TB_RT_EXERCISE_INSTANCE exercise model and lifecycle.",
        ["TB_RT_EXERCISE_INSTANCE"],
        [],
        [],
        ["BCK"],
    ),
    (
        7,
        "Manage context records: TB_RT_CONTEXT context state and type for programme management.",
        ["TB_RT_CONTEXT"],
        [],
        [],
        ["BCK"],
    ),
    (
        8,
        "Fix rule result tracking: TB_RT_RULE_RESULT rule execution results and severity codes.",
        ["TB_RT_RULE_RESULT"],
        [],
        [],
        ["BCK"],
    ),
    (
        9,
        "Update payment calculation: TB_GRP_PAYCALC payment calculation session and project number.",
        ["TB_GRP_PAYCALC"],
        [("TB_GRP_PAYCALC", "TB_RT_SESSION_INSTANCE"), ("TB_GRP_PAYCALC", "TB_APP_PROJECT_BASE")],
        [],
        ["BCK"],
    ),
    (
        10,
        "Add new property to project feature: TB_GRP_PF_FEATURE_P ProjectFeatureProperty linked to TB_GRP_PF_FEATURE.",
        ["TB_GRP_PF_FEATURE_P", "TB_GRP_PF_FEATURE"],
        [("TB_GRP_PF_FEATURE_P", "TB_GRP_PF_FEATURE")],
        [],
        ["BCK"],
    ),
    (
        11,
        "Update schema-qualified reference SYGMA.TB_GRP_PF to add new version column.",
        ["TB_GRP_PF"],
        [],
        [],
        ["BCK"],
    ),
    (
        12,
        "Migrate backup table BCK_TB_GRP_PF to new archive format.",
        [],  # No required tables — BCK should be excluded
        [],
        [],
        [],  # We check for BCK exclusion explicitly below
    ),
    (
        13,
        "Refactor GroupVProjectFeatures Java entity to update project feature mappings.",
        ["TB_GRP_PF"],  # The entity maps to TB_GRP_PF
        [],
        [("GroupVProjectFeatures", "TB_GRP_PF")],
        ["BCK"],
    ),
    (
        14,
        "Cross-domain impediment: need to update both TB_GRP_PF project features and TB_RT_SESSION_INSTANCE session data together.",
        ["TB_GRP_PF", "TB_RT_SESSION_INSTANCE"],
        [("TB_GRP_PF", "TB_RT_SESSION_INSTANCE")],  # Direct FK exists
        [],
        ["BCK"],
    ),
]


@requires_sygma
class TestContextCases:
    """14 context-selection cases against real Sygma data."""

    @pytest.mark.parametrize(
        "case_id,story_text,required_tables,required_fk_pairs,must_have_maps_to,must_exclude_prefixes",
        CONTEXT_CASES,
        ids=[f"case{c[0]:02d}" for c in CONTEXT_CASES],
    )
    def test_context_case(
        self,
        reconciled_graph,
        graph_index,
        case_id,
        story_text,
        required_tables,
        required_fk_pairs,
        must_have_maps_to,
        must_exclude_prefixes,
    ):
        from moughorai.database_graph.context_selector import select_database_context

        ctx = select_database_context(reconciled_graph, story_text, max_objects=60)

        # Build selected lookups
        selected_table_names = {
            n.qualified_name
            for n in ctx.selected_nodes
            if n.kind in ("table", "view", "materialized_view")
        }
        selected_node_ids = {n.id for n in ctx.selected_nodes}
        selected_edge_tuples = set()
        for e in ctx.selected_edges:
            fn = graph_index["table_id_to_name"].get(e.from_node, "")
            tn = graph_index["table_id_to_name"].get(e.to_node, "")
            if fn and tn and e.kind == "FOREIGN_KEY_TO":
                selected_edge_tuples.add((fn, tn))

        # Maps-to edges in context
        maps_in_ctx = set()
        for e in ctx.selected_edges:
            if e.kind == "MAPS_TO_TABLE":
                ent = graph_index["entity_by_id"].get(e.from_node)
                tbl = graph_index["table_id_to_name"].get(e.to_node)
                if ent and tbl:
                    simple_name = ent.qualified_name.rsplit(".", 1)[-1]
                    maps_in_ctx.add((simple_name, tbl))

        # 1. Required tables present
        for t in required_tables:
            assert t in selected_table_names, (
                f"Case {case_id}: required table {t} not in context. "
                f"Selected tables: {sorted(selected_table_names)[:20]}"
            )

        # 2. Required FK edges present
        for pair in required_fk_pairs:
            assert pair in selected_edge_tuples, (
                f"Case {case_id}: required FK {pair[0]} -> {pair[1]} not in context. "
                f"FK edges: {sorted(selected_edge_tuples)[:20]}"
            )

        # 3. Maps-to edges present
        for entity_simple, table_name in must_have_maps_to:
            assert (entity_simple, table_name) in maps_in_ctx, (
                f"Case {case_id}: MAPS_TO_TABLE {entity_simple} -> {table_name} not in context. "
                f"Maps-to: {sorted(maps_in_ctx)}"
            )

        # 4. Backup/historical exclusion
        for prefix in must_exclude_prefixes:
            bck_in_ctx = [
                n.qualified_name
                for n in ctx.selected_nodes
                if n.qualified_name.startswith(prefix)
                and n.kind in ("table", "view", "materialized_view")
            ]
            assert len(bck_in_ctx) == 0, (
                f"Case {case_id}: backup objects with prefix '{prefix}' found: {bck_in_ctx}"
            )

        # 5. Context fingerprint is deterministic
        assert ctx.context_fingerprint, f"Case {case_id}: fingerprint is empty"
        assert len(ctx.context_fingerprint) == 64, (
            f"Case {case_id}: expected 64-char SHA-256 fingerprint"
        )

    def test_case12_backup_exclusion_explicit(self, reconciled_graph):
        """Case 12: BCK tables must NOT appear in context even when story mentions them."""
        from moughorai.database_graph.context_selector import select_database_context

        ctx = select_database_context(
            reconciled_graph,
            "Migrate backup table BCK_TB_GRP_PF to new archive format.",
            max_objects=60,
        )
        bck_tables = [
            n.qualified_name
            for n in ctx.selected_nodes
            if n.qualified_name.upper().startswith("BCK")
            and n.kind in ("table", "view", "materialized_view")
        ]
        assert len(bck_tables) == 0, (
            f"BCK tables should be excluded from effective graph, found: {bck_tables}"
        )


# ===========================================================================
# 42 SQL Fixtures (3 per case)
# ===========================================================================

SQL_FIXTURES: list[SqlFixture] = [
    # -----------------------------------------------------------------------
    # Case 1: Project features (TB_GRP_PF, TB_GRP_PF_FEATURE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=1,
        fixture_id="case01_valid",
        sql="SELECT pf.ID, pf.SESSION_ID, f.GROUP_PF_ID FROM TB_GRP_PF pf JOIN TB_GRP_PF_FEATURE f ON f.GROUP_PF_ID = pf.ID",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid FK join between TB_GRP_PF_FEATURE and TB_GRP_PF — both in Jailer with FK evidence",
    ),
    SqlFixture(
        case_id=1,
        fixture_id="case01_invalid",
        sql="SELECT pf.ID, pf.NONEXISTENT_COL FROM TB_GRP_PF pf",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_column"],
        description="Invalid: references a column that does not exist in TB_GRP_PF",
    ),
    SqlFixture(
        case_id=1,
        fixture_id="case01_edge",
        sql="UPDATE TB_GRP_PF SET VERSION = VERSION + 1 WHERE ID = 42",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: mutating DML (UPDATE) on a known table with known columns",
    ),
    # -----------------------------------------------------------------------
    # Case 2: Session instances (TB_RT_SESSION_INSTANCE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=2,
        fixture_id="case02_valid",
        sql="SELECT si.ID, si.EXERCISE_ID, si.FOREST_ID FROM TB_RT_SESSION_INSTANCE si WHERE si.ID = 1",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_RT_SESSION_INSTANCE with Jailer-known columns",
    ),
    SqlFixture(
        case_id=2,
        fixture_id="case02_invalid",
        sql="SELECT si.ID FROM TB_RT_SESSION_INSTANCE_DOES_NOT_EXIST si",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_table"],
        description="Invalid: references a table that does not exist",
    ),
    SqlFixture(
        case_id=2,
        fixture_id="case02_edge",
        sql="DELETE FROM TB_RT_SESSION_INSTANCE WHERE ID = 999",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: mutating DELETE on a known table",
    ),
    # -----------------------------------------------------------------------
    # Case 3: Project base (TB_APP_PROJECT_BASE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=3,
        fixture_id="case03_valid",
        sql="SELECT pb.PROJECT_NUMBER, pb.CALL_CONTEXT_ID FROM TB_APP_PROJECT_BASE pb WHERE pb.PROJECT_NUMBER = '12345'",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_APP_PROJECT_BASE with known columns",
    ),
    SqlFixture(
        case_id=3,
        fixture_id="case03_invalid",
        sql="SELECT pb.PROJECT_NUMBER FROM TB_APP_PROJECT_FAKE pb",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_table"],
        description="Invalid: wrong table name",
    ),
    SqlFixture(
        case_id=3,
        fixture_id="case03_edge",
        sql="INSERT INTO TB_APP_PROJECT_BASE (PROJECT_NUMBER, CALL_CONTEXT_ID) VALUES ('X', 1)",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: INSERT into a known table with known columns",
    ),
    # -----------------------------------------------------------------------
    # Case 4: Rule exceptions (TB_RT_RULE_EXCEPTION_DEF)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=4,
        fixture_id="case04_valid",
        sql="SELECT red.ID, red.JUSTIFICATION FROM TB_RT_RULE_EXCEPTION_DEF red WHERE red.ID = 1",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_RT_RULE_EXCEPTION_DEF",
    ),
    SqlFixture(
        case_id=4,
        fixture_id="case04_invalid",
        sql="SELECT red.PHANTOM_COLUMN FROM TB_RT_RULE_EXCEPTION_DEF red",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_column"],
        description="Invalid: phantom column that does not exist",
    ),
    SqlFixture(
        case_id=4,
        fixture_id="case04_edge",
        sql="",
        expected_outcome="unsupported_sql",
        expected_issues=[],
        description="Edge: empty SQL string",
    ),
    # -----------------------------------------------------------------------
    # Case 5: Document generation (TB_APP_BCH_DOC_GEN_RES)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=5,
        fixture_id="case05_valid",
        sql="SELECT dgr.ID, dgr.CALLBACK_ID, dgr.SESSION_ID FROM TB_APP_BCH_DOC_GEN_RES dgr",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_APP_BCH_DOC_GEN_RES",
    ),
    SqlFixture(
        case_id=5,
        fixture_id="case05_invalid",
        sql="SELECT dgr.ID FROM BCK_TB_APP_BCH_DOC_GEN_RES dgr",
        expected_outcome="structurally_invalid",
        expected_issues=["backup_object"],
        description="Invalid: backup-prefixed table detected as backup_object",
    ),
    SqlFixture(
        case_id=5,
        fixture_id="case05_edge",
        sql="UPDATE TB_APP_BCH_DOC_GEN_RES SET CALLBACK_SENT = 1 WHERE ID = 1",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: UPDATE on TB_APP_BCH_DOC_GEN_RES",
    ),
    # -----------------------------------------------------------------------
    # Case 6: Exercise instance (TB_RT_EXERCISE_INSTANCE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=6,
        fixture_id="case06_valid",
        sql="SELECT ei.ID, ei.EXERCISE_MODEL_ID, ei.DESCRIPTION FROM TB_RT_EXERCISE_INSTANCE ei",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_RT_EXERCISE_INSTANCE",
    ),
    SqlFixture(
        case_id=6,
        fixture_id="case06_invalid",
        sql="SELECT ei.ID FROM TB_RT_EXERCISE_INSTANCE ei JOIN TB_FAKE_TABLE ft ON ft.ID = ei.ID",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_table"],
        description="Invalid: JOIN with a nonexistent table",
    ),
    SqlFixture(
        case_id=6,
        fixture_id="case06_edge",
        sql="UPDATE TB_RT_EXERCISE_INSTANCE SET DESCRIPTION = 'updated' WHERE ID = 1",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: UPDATE on known table with known columns",
    ),
    # -----------------------------------------------------------------------
    # Case 7: Context records (TB_RT_CONTEXT)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=7,
        fixture_id="case07_valid",
        sql="SELECT c.ID, c.NAME, c.STATE FROM TB_RT_CONTEXT c WHERE c.TYPE = 'PROGRAMME'",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_RT_CONTEXT with known columns",
    ),
    SqlFixture(
        case_id=7,
        fixture_id="case07_invalid",
        sql="SELECT c.NONEXISTENT FROM TB_RT_CONTEXT c",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_column"],
        description="Invalid: nonexistent column",
    ),
    SqlFixture(
        case_id=7,
        fixture_id="case07_edge",
        sql="SELECT c.ID FROM SYGMA.TB_RT_CONTEXT c",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: schema-qualified table reference resolves via fallback",
    ),
    # -----------------------------------------------------------------------
    # Case 8: Rule results (TB_RT_RULE_RESULT)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=8,
        fixture_id="case08_valid",
        sql="SELECT rr.ID, rr.MESSAGE_SEVERITY, rr.RULE_EXCEPTION_ID FROM TB_RT_RULE_RESULT rr",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid SELECT on TB_RT_RULE_RESULT",
    ),
    SqlFixture(
        case_id=8,
        fixture_id="case08_invalid",
        sql="SELECT rr.ID FROM TB_RT_RULE_RESULT rr JOIN TB_RT_RULE_EXCEPTION_DEF red ON red.ID = rr.WRONG_FK_COLUMN",
        expected_outcome="structurally_invalid",
        expected_issues=["invalid_join_columns"],
        description="Invalid: wrong FK column in join — tables have FK but columns don't match evidence",
    ),
    SqlFixture(
        case_id=8,
        fixture_id="case08_edge",
        sql="-- only a comment, nothing to validate",
        expected_outcome="unsupported_sql",
        expected_issues=[],
        description="Edge: SQL that is only a comment",
    ),
    # -----------------------------------------------------------------------
    # Case 9: Payment calculation (TB_GRP_PAYCALC)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=9,
        fixture_id="case09_valid",
        sql="SELECT pc.ID, pc.SESSION_ID, pc.PROJECT_NUMBER FROM TB_GRP_PAYCALC pc JOIN TB_RT_SESSION_INSTANCE si ON si.ID = pc.SESSION_ID",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid FK join: TB_GRP_PAYCALC -> TB_RT_SESSION_INSTANCE via SESSION_ID",
    ),
    SqlFixture(
        case_id=9,
        fixture_id="case09_invalid",
        sql="SELECT pc.ID FROM TB_GRP_PAYCALC pc JOIN TB_APP_PARTNER p ON p.ID = pc.PARTNER_ID",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_table"],
        description="Invalid: TB_APP_PARTNER does not exist in the graph",
    ),
    SqlFixture(
        case_id=9,
        fixture_id="case09_edge",
        sql="SELECT pc.ID FROM TB_GRP_PAYCALC pc JOIN TB_APP_PROJECT_BASE pb ON pb.PROJECT_NUMBER = pc.PROJECT_NUMBER",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: second valid FK join from TB_GRP_PAYCALC to TB_APP_PROJECT_BASE",
    ),
    # -----------------------------------------------------------------------
    # Case 10: Feature properties (TB_GRP_PF_FEATURE_P -> TB_GRP_PF_FEATURE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=10,
        fixture_id="case10_valid",
        sql="SELECT fp.ID, fp.FEATURE_ID FROM TB_GRP_PF_FEATURE_P fp JOIN TB_GRP_PF_FEATURE f ON f.ID = fp.FEATURE_ID",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid FK join: TB_GRP_PF_FEATURE_P -> TB_GRP_PF_FEATURE via FEATURE_ID",
    ),
    SqlFixture(
        case_id=10,
        fixture_id="case10_invalid",
        sql="SELECT fp.ID FROM TB_GRP_PF_FEATURE_P fp WHERE fp.TOTALLY_FAKE_COLUMN = 1",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_column"],
        description="Invalid: nonexistent column in WHERE clause",
    ),
    SqlFixture(
        case_id=10,
        fixture_id="case10_edge",
        sql="INSERT INTO TB_GRP_PF_FEATURE_P (FEATURE_ID) VALUES (99)",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: INSERT into TB_GRP_PF_FEATURE_P with known column",
    ),
    # -----------------------------------------------------------------------
    # Case 11: Schema-qualified reference (SYGMA.TB_GRP_PF)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=11,
        fixture_id="case11_valid",
        sql="SELECT pf.ID, pf.VERSION FROM SYGMA.TB_GRP_PF pf WHERE pf.PROJECT_NUMBER = '12345'",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid: SYGMA.TB_GRP_PF resolves to TB_GRP_PF via schema fallback",
    ),
    SqlFixture(
        case_id=11,
        fixture_id="case11_invalid",
        sql="SELECT pf.ID FROM SYGMA.TB_GRP_PF_NONEXISTENT pf",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_table"],
        description="Invalid: schema-qualified but table does not exist",
    ),
    SqlFixture(
        case_id=11,
        fixture_id="case11_edge",
        sql="SELECT pf.ID FROM SYGMA.TB_GRP_PF pf JOIN TB_GRP_PF_FEATURE f ON f.GROUP_PF_ID = pf.ID",
        expected_outcome="structurally_invalid",
        expected_issues=["unsupported_join"],
        description="Edge: schema-qualified source with unqualified join — FK lookup uses schema-stripped names but join evidence cites display names, resulting in incomplete evidence",
    ),
    # -----------------------------------------------------------------------
    # Case 12: Backup exclusion (BCK tables)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=12,
        fixture_id="case12_valid",
        sql="SELECT pf.ID FROM TB_GRP_PF pf",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid: non-backup table in a backup-themed case",
    ),
    SqlFixture(
        case_id=12,
        fixture_id="case12_invalid",
        sql="SELECT * FROM BCK_TB_GRP_PF",
        expected_outcome="structurally_invalid",
        expected_issues=["backup_object"],
        description="Invalid: BCK-prefixed backup table detected as backup_object",
    ),
    SqlFixture(
        case_id=12,
        fixture_id="case12_edge",
        sql="SELECT * FROM BCK_NONEXISTENT_TABLE",
        expected_outcome="structurally_invalid",
        expected_issues=["backup_object"],
        description="Edge: another BCK table — backup_object regardless of whether it exists",
    ),
    # -----------------------------------------------------------------------
    # Case 13: Java entity mapping (GroupVProjectFeatures -> TB_GRP_PF)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=13,
        fixture_id="case13_valid",
        sql="SELECT pf.ID, pf.SESSION_ID, pf.PROJECT_NUMBER FROM TB_GRP_PF pf",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid: SELECT on TB_GRP_PF (mapped from GroupVProjectFeatures)",
    ),
    SqlFixture(
        case_id=13,
        fixture_id="case13_invalid",
        sql="SELECT pf.JAVA_ONLY_FIELD FROM TB_GRP_PF pf",
        expected_outcome="structurally_invalid",
        expected_issues=["unknown_column"],
        description="Invalid: column that only exists in Java entity, not DB",
    ),
    SqlFixture(
        case_id=13,
        fixture_id="case13_edge",
        sql="SELECT pf.ID FROM TB_GRP_PF pf WHERE pf.ORIGIN_ID IS NOT NULL",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: WHERE with IS NOT NULL on known column",
    ),
    # -----------------------------------------------------------------------
    # Case 14: Multi-table (TB_GRP_PF + TB_RT_SESSION_INSTANCE)
    # -----------------------------------------------------------------------
    SqlFixture(
        case_id=14,
        fixture_id="case14_valid",
        sql="SELECT pf.ID, si.EXERCISE_ID FROM TB_GRP_PF pf JOIN TB_RT_SESSION_INSTANCE si ON si.ID = pf.SESSION_ID",
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Valid FK join: TB_GRP_PF -> TB_RT_SESSION_INSTANCE via SESSION_ID=ID",
    ),
    SqlFixture(
        case_id=14,
        fixture_id="case14_invalid",
        sql="SELECT pf.ID FROM TB_GRP_PF pf JOIN TB_RT_SESSION_INSTANCE si ON si.ID = pf.FAKE_SESSION_COL",
        expected_outcome="structurally_invalid",
        expected_issues=["invalid_join_columns"],
        description="Invalid: tables have FK but fake column does not match FK evidence",
    ),
    SqlFixture(
        case_id=14,
        fixture_id="case14_edge",
        sql=(
            "SELECT pf.ID, si.ID, pb.PROJECT_NUMBER "
            "FROM TB_GRP_PF pf "
            "JOIN TB_RT_SESSION_INSTANCE si ON si.ID = pf.SESSION_ID "
            "JOIN TB_APP_PROJECT_BASE pb ON pb.PROJECT_NUMBER = pf.PROJECT_NUMBER"
        ),
        expected_outcome="structurally_valid",
        expected_issues=[],
        description="Edge: three-way join TB_GRP_PF -> SESSION + PROJECT_BASE",
    ),
]

# Verify we have exactly 42 fixtures (14 * 3)
assert len(SQL_FIXTURES) == 42, f"Expected 42 SQL fixtures, got {len(SQL_FIXTURES)}"


# ===========================================================================
# SQL Validation Tests
# ===========================================================================


@requires_sygma
class TestSqlFixtures:
    """42 SQL validation fixtures against real Sygma data."""

    @pytest.mark.parametrize(
        "fixture",
        SQL_FIXTURES,
        ids=[f.fixture_id for f in SQL_FIXTURES],
    )
    def test_sql_fixture(self, reconciled_graph, fixture: SqlFixture):
        from moughorai.database_graph.sql_validator import validate_sql

        result = validate_sql(fixture.sql, reconciled_graph)

        # Check overall status matches expected outcome
        assert result.overall_status == fixture.expected_outcome, (
            f"Fixture {fixture.fixture_id}: expected status '{fixture.expected_outcome}', "
            f"got '{result.overall_status}'. "
            f"Issues: {[i.to_dict() for s in result.statements for i in s.issues]}"
        )

        # Check expected issue types
        if fixture.expected_issues:
            actual_issue_types = set()
            for stmt in result.statements:
                for issue in stmt.issues:
                    actual_issue_types.add(issue.issue_type)
            for expected_type in fixture.expected_issues:
                assert expected_type in actual_issue_types, (
                    f"Fixture {fixture.fixture_id}: expected issue type '{expected_type}' "
                    f"not found. Actual: {actual_issue_types}"
                )


# ===========================================================================
# Cross-validation: graph consistency checks
# ===========================================================================


@requires_sygma
class TestGraphConsistency:
    """Verify graph-level invariants used by context + SQL tests."""

    def test_target_tables_are_verified(self, graph_index):
        """All target tables have 'verified' evidence status and confidence 1.0."""
        target_tables = [
            "TB_GRP_PF", "TB_GRP_PF_FEATURE", "TB_GRP_PF_FEATURE_P",
            "TB_RT_SESSION_INSTANCE", "TB_APP_PROJECT_BASE",
            "TB_RT_RULE_EXCEPTION_DEF", "TB_APP_BCH_DOC_GEN_RES",
            "TB_RT_EXERCISE_INSTANCE", "TB_RT_CONTEXT",
            "TB_RT_RULE_RESULT", "TB_GRP_PAYCALC",
        ]
        for t in target_tables:
            node = graph_index["table_by_name"].get(t)
            assert node is not None, f"Table {t} not found in graph"
            assert node.evidence.status == "verified", (
                f"Table {t} evidence status is '{node.evidence.status}', expected 'verified'"
            )
            assert node.evidence.confidence == 1.0, (
                f"Table {t} confidence is {node.evidence.confidence}, expected 1.0"
            )

    def test_bck_tables_excluded(self, reconciled_graph):
        """BCK-prefixed tables are excluded from the effective graph."""
        bck = [
            n.qualified_name
            for n in reconciled_graph.nodes
            if n.qualified_name.upper().startswith("BCK")
        ]
        assert len(bck) == 0, f"BCK tables in effective graph: {bck}"

    def test_critical_fk_edges_exist(self, graph_index):
        """Critical FK relationships used by SQL fixtures actually exist."""
        critical_fks = [
            ("TB_GRP_PF_FEATURE", "TB_GRP_PF"),
            ("TB_GRP_PF_FEATURE_P", "TB_GRP_PF_FEATURE"),
            ("TB_GRP_PF", "TB_RT_SESSION_INSTANCE"),
            ("TB_GRP_PF", "TB_APP_PROJECT_BASE"),
            ("TB_GRP_PAYCALC", "TB_RT_SESSION_INSTANCE"),
            ("TB_GRP_PAYCALC", "TB_APP_PROJECT_BASE"),
            ("TB_RT_RULE_RESULT", "TB_RT_RULE_EXCEPTION_DEF"),
            ("TB_RT_RULE_EXCEPTION_APP", "TB_RT_RULE_EXCEPTION_DEF"),
        ]
        for from_t, to_t in critical_fks:
            assert (from_t, to_t) in graph_index["fk_pairs"], (
                f"FK {from_t} -> {to_t} not found in graph. "
                f"Available FKs from {from_t}: "
                f"{[k for k in graph_index['fk_pairs'] if k[0] == from_t]}"
            )

    def test_maps_to_table_edges_exist(self, graph_index):
        """Critical MAPS_TO_TABLE edges used by context cases exist."""
        required_maps = {
            "GroupVProjectFeatures": "TB_GRP_PF",
            "ProjectFeature": "TB_GRP_PF_FEATURE",
            "ProjectFeatureProperty": "TB_GRP_PF_FEATURE_P",
            "ProjectBase": "TB_APP_PROJECT_BASE",
        }
        for entity_simple, expected_table in required_maps.items():
            found = False
            for ent_qname, tbl in graph_index["maps_to"].items():
                if ent_qname.endswith(entity_simple) and tbl == expected_table:
                    found = True
                    break
            assert found, (
                f"MAPS_TO_TABLE for {entity_simple} -> {expected_table} not found. "
                f"Available: {[(k.rsplit('.', 1)[-1], v) for k, v in graph_index['maps_to'].items()][:20]}"
            )

    def test_graph_fingerprint_verifies(self, reconciled_graph):
        """Reconciled graph fingerprint is valid and verifiable."""
        assert reconciled_graph.fingerprint
        assert len(reconciled_graph.fingerprint) == 64
        assert reconciled_graph.verify_fingerprint()
