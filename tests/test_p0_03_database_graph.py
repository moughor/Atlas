"""Comprehensive tests for the Atlas database-graph pipeline.

Tests run against the real Sygma repository at /home/meskeda/git/sygma/sygma
(Git SHA aeb04bfd43711bd80a8db221910e45a09e1d74c4).  They skip gracefully
when the repository is unavailable.

Test classes:
    TestJailerIngest     — Jailer CSV parsing verification
    TestJpaExtraction    — JPA annotation extraction verification
    TestReconciliation   — Multi-source reconciliation verification
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Sygma repo location and availability guard
# ---------------------------------------------------------------------------

SYGMA_ROOT = Path("/home/meskeda/git/sygma/sygma")
SYGMA_SHA = "aeb04bfd43711bd80a8db221910e45a09e1d74c4"

_sygma_available = SYGMA_ROOT.is_dir() and (
    SYGMA_ROOT / "sygma-it" / "sygma-it-services" / "src" / "test" / "jailer" / "Sygma" / "table.csv"
).exists()

requires_sygma = pytest.mark.skipif(
    not _sygma_available,
    reason=f"Sygma repository not available at {SYGMA_ROOT}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jailer_result():
    """Run Jailer ingest once per module and cache the result."""
    from moughorai.database_graph.jailer_ingest import ingest_jailer

    return ingest_jailer(SYGMA_ROOT)


@pytest.fixture(scope="module")
def jpa_result():
    """Run JPA extraction once per module and cache the result."""
    from moughorai.database_graph.jpa_extractor import extract_jpa_entities

    return extract_jpa_entities(SYGMA_ROOT)


@pytest.fixture(scope="module")
def fixed_provenance():
    """Return a fixed provenance dict for deterministic tests."""
    return {
        "vcs": "git",
        "head_sha": SYGMA_SHA,
        "head_ref": "refs/heads/develop",
        "worktree_state": "clean",
        "captured_at": "2025-01-01T00:00:00Z",
        "verification": "exact",
    }


@pytest.fixture(scope="module")
def reconciled_graph(jailer_result, jpa_result, fixed_provenance):
    """Run reconciliation once per module and cache the result."""
    from moughorai.database_graph.reconciler import reconcile_database_graph

    return reconcile_database_graph(
        SYGMA_ROOT,
        jailer_result,
        jpa_result,
        provenance=fixed_provenance,
        workspace_fingerprint="test-ws-fp",
    )


# ===========================================================================
# TestJailerIngest
# ===========================================================================


@requires_sygma
class TestJailerIngest:
    """Verify Jailer CSV ingest against real Sygma data."""

    def test_jailer_table_count(self, jailer_result):
        """Verify ~1595 table-kind entities (matching 1596 CSV lines minus header)."""
        total = (
            jailer_result.table_count
            + jailer_result.view_count
            + jailer_result.materialized_view_count
        )
        assert total == 1595, (
            f"Expected 1595 table-kind entities, got {total} "
            f"(tables={jailer_result.table_count}, "
            f"views={jailer_result.view_count}, "
            f"mvs={jailer_result.materialized_view_count})"
        )

    def test_jailer_association_count(self, jailer_result):
        """Verify ~741 FK associations (742 CSV lines minus header)."""
        assert jailer_result.foreign_key_count == 741, (
            f"Expected 741 FK edges, got {jailer_result.foreign_key_count}"
        )

    def test_jailer_column_parsing(self, jailer_result):
        """Verify columns are parsed — expect >24,000 column nodes."""
        assert jailer_result.column_count > 24_000, (
            f"Expected >24,000 columns, got {jailer_result.column_count}"
        )
        # Verify column nodes exist in the node set
        column_nodes = [
            n for n in jailer_result.nodes if n.kind == "column"
        ]
        assert len(column_nodes) == jailer_result.column_count

    def test_jailer_version_captured(self, jailer_result):
        """Verify version.csv = '9.3.3'."""
        assert jailer_result.source_version == "9.3.3"

    def test_backup_tables_flagged(self, jailer_result):
        """BCK-prefixed tables are marked historical=True."""
        table_nodes = [
            n
            for n in jailer_result.nodes
            if n.kind in ("table", "view", "materialized_view")
        ]
        bck_nodes = [
            n for n in table_nodes if n.qualified_name.startswith("BCK")
        ]
        assert len(bck_nodes) == 5, (
            f"Expected 5 BCK tables, got {len(bck_nodes)}"
        )
        for n in bck_nodes:
            assert n.get_property("historical") is True, (
                f"BCK table {n.qualified_name} not marked historical"
            )

    def test_project_feature_associations(self, jailer_result):
        """TB_GRP_PF_FEATURE -> TB_GRP_PF via GROUP_PF_ID=ID FK."""
        # Build node-id → table-name lookup
        table_by_id = {
            n.id: n.qualified_name
            for n in jailer_result.nodes
            if n.kind in ("table", "view", "materialized_view")
        }

        fk_edges = [
            e for e in jailer_result.edges if e.kind == "FOREIGN_KEY_TO"
        ]
        # Find the specific FK edge by resolving from/to node ids
        found = False
        for e in fk_edges:
            from_name = table_by_id.get(e.from_node, "")
            to_name = table_by_id.get(e.to_node, "")
            if from_name == "TB_GRP_PF_FEATURE" and to_name == "TB_GRP_PF":
                props = dict(e.properties)
                assert props.get("join_condition") == "A.GROUP_PF_ID=B.ID"
                found = True
                break
        assert found, (
            "FK from TB_GRP_PF_FEATURE to TB_GRP_PF not found"
        )


# ===========================================================================
# TestJpaExtraction
# ===========================================================================


@requires_sygma
class TestJpaExtraction:
    """Verify JPA entity extraction against real Sygma data."""

    def _entities_by_class(self, jpa_result):
        """Build a class_name → entity lookup from production entities."""
        return {
            e.class_name: e
            for e in jpa_result.entities
            if not e.is_test
        }

    def test_entity_count(self, jpa_result):
        """Verify ~573+ entities with a resolved @Table name."""
        resolved = [
            e
            for e in jpa_result.entities
            if not e.is_test and e.table_name_resolved and e.table_name
        ]
        # 573 entities have resolved table names in this Sygma revision.
        assert len(resolved) >= 570, (
            f"Expected >=570 entities with resolved @Table, got {len(resolved)}"
        )
        assert len(resolved) <= 600, (
            f"Expected <=600 entities with resolved @Table, got {len(resolved)}"
        )

    def test_db_table_constant_resolution(self, jpa_result):
        """GroupVProjectFeatures.DB_TABLE resolves to 'TB_GRP_PF'."""
        idx = self._entities_by_class(jpa_result)
        gvpf = idx.get("GroupVProjectFeatures")
        assert gvpf is not None, "GroupVProjectFeatures not found"
        assert gvpf.table_name == "TB_GRP_PF"
        assert gvpf.table_name_resolved is True

    def test_project_feature_resolves(self, jpa_result):
        """ProjectFeature.DB_TABLE resolves to 'TB_GRP_PF_FEATURE'."""
        idx = self._entities_by_class(jpa_result)
        pf = idx.get("ProjectFeature")
        assert pf is not None, "ProjectFeature not found"
        assert pf.table_name == "TB_GRP_PF_FEATURE"
        assert pf.table_name_resolved is True

    def test_project_feature_property_resolves(self, jpa_result):
        """ProjectFeatureProperty.DB_TABLE resolves to 'TB_GRP_PF_FEATURE_P'."""
        idx = self._entities_by_class(jpa_result)
        pfp = idx.get("ProjectFeatureProperty")
        assert pfp is not None, "ProjectFeatureProperty not found"
        assert pfp.table_name == "TB_GRP_PF_FEATURE_P"
        assert pfp.table_name_resolved is True

    def test_lazy_set_provider_detected(self, jpa_result):
        """GroupVProjectFeatures has a LazySetProvider relationship to ProjectFeature."""
        idx = self._entities_by_class(jpa_result)
        gvpf = idx.get("GroupVProjectFeatures")
        assert gvpf is not None
        assert len(gvpf.relationships) >= 1, (
            f"Expected >=1 relationship, got {len(gvpf.relationships)}"
        )
        pf_rel = [
            r for r in gvpf.relationships if r.target_type == "ProjectFeature"
        ]
        assert len(pf_rel) == 1, (
            f"Expected 1 relationship to ProjectFeature, got {len(pf_rel)}"
        )
        rel = pf_rel[0]
        assert rel.provider_kind == "LazySetProvider"
        assert rel.java_field_name == "projectFeatures"

    def test_column_mappings_extracted(self, jpa_result):
        """ProjectFeature has GROUP_PF_ID column mapping."""
        idx = self._entities_by_class(jpa_result)
        pf = idx.get("ProjectFeature")
        assert pf is not None
        col_names = {c.column_name for c in pf.columns}
        assert "GROUP_PF_ID" in col_names, (
            f"GROUP_PF_ID not found in columns: {col_names}"
        )
        # Verify the mapping field
        gpf_col = [c for c in pf.columns if c.column_name == "GROUP_PF_ID"][0]
        assert gpf_col.java_field_name == "groupId"

    def test_sequence_extracted(self, jpa_result):
        """SQ_GRP_PF sequence found via GroupVProjectFeatures @SequenceGenerator."""
        idx = self._entities_by_class(jpa_result)
        gvpf = idx.get("GroupVProjectFeatures")
        assert gvpf is not None
        seq_names = [s.sequence_name for s in gvpf.sequences if s.sequence_name_resolved]
        assert "SQ_GRP_PF" in seq_names, (
            f"SQ_GRP_PF not found in sequences: {seq_names}"
        )

    def test_embedded_attribute_override(self, jpa_result):
        """DEF_CCM_ID column from @AttributeOverride in ProjectFeature."""
        idx = self._entities_by_class(jpa_result)
        pf = idx.get("ProjectFeature")
        assert pf is not None
        override_cols = {eo.column_name for eo in pf.embedded_overrides}
        assert "DEF_CCM_ID" in override_cols, (
            f"DEF_CCM_ID not found in embedded overrides: {override_cols}"
        )
        # Verify the specific override
        def_ccm = [
            eo for eo in pf.embedded_overrides if eo.column_name == "DEF_CCM_ID"
        ][0]
        assert def_ccm.attribute_name == "id"
        assert def_ccm.java_field_name == "feature"


# ===========================================================================
# TestReconciliation
# ===========================================================================


@requires_sygma
class TestReconciliation:
    """Verify multi-source reconciliation into DatabaseGraph."""

    def test_reconciled_graph_has_fingerprint(self, reconciled_graph):
        """Graph has a deterministic SHA-256 fingerprint that verifies."""
        assert reconciled_graph.fingerprint, "Fingerprint is empty"
        assert len(reconciled_graph.fingerprint) == 64, (
            f"Expected 64-char SHA-256, got {len(reconciled_graph.fingerprint)} chars"
        )
        assert reconciled_graph.verify_fingerprint(), (
            "Fingerprint verification failed"
        )

    def test_jailer_confirmed_by_jpa(self, reconciled_graph):
        """TB_GRP_PF appears in both Jailer and JPA → evidence status 'verified'
        with sources from both producers."""
        tb_grp_pf = [
            n
            for n in reconciled_graph.nodes
            if n.qualified_name == "TB_GRP_PF"
            and n.kind == "table"
        ]
        assert len(tb_grp_pf) == 1, "TB_GRP_PF table node not found"
        node = tb_grp_pf[0]

        # Promoted evidence should be verified with confidence 1.0
        assert node.evidence.status == "verified"
        assert node.evidence.confidence == 1.0

        # Should have sources from both jailer_csv and jpa_annotation
        source_kinds = {s.kind for s in node.evidence.sources}
        assert "jailer_csv" in source_kinds, (
            f"Expected jailer_csv in sources, got {source_kinds}"
        )
        assert "jpa_annotation" in source_kinds, (
            f"Expected jpa_annotation in sources, got {source_kinds}"
        )

    def test_backup_excluded_from_effective(self, reconciled_graph):
        """BCK tables are not in the effective graph (exclude_backup=True default)."""
        bck_nodes = [
            n
            for n in reconciled_graph.nodes
            if n.qualified_name.startswith("BCK")
        ]
        assert len(bck_nodes) == 0, (
            f"Expected 0 BCK nodes in effective graph, found {len(bck_nodes)}: "
            f"{[n.qualified_name for n in bck_nodes]}"
        )

    def test_project_feature_path_complete(self, reconciled_graph):
        """Full path: GroupVProjectFeatures -> TB_GRP_PF -> TB_GRP_PF_FEATURE
        -> TB_GRP_PF_FEATURE_P with FK edges.

        Verifies the entity-to-table mapping chain and physical FK chain.
        """
        graph = reconciled_graph

        # Build table-name → node-id lookup
        table_id_by_name = {
            n.qualified_name: n.id
            for n in graph.nodes
            if n.kind in ("table", "view", "materialized_view")
        }
        table_name_by_id = {v: k for k, v in table_id_by_name.items()}

        # 1. GroupVProjectFeatures entity node
        gvpf_nodes = [
            n
            for n in graph.nodes
            if n.kind == "java_entity"
            and n.qualified_name.endswith("GroupVProjectFeatures")
        ]
        assert len(gvpf_nodes) == 1, "GroupVProjectFeatures entity node not found"
        gvpf_id = gvpf_nodes[0].id

        # 2. MAPS_TO_TABLE: GroupVProjectFeatures -> TB_GRP_PF
        maps_edges = [
            e
            for e in graph.edges
            if e.kind == "MAPS_TO_TABLE" and e.from_node == gvpf_id
        ]
        assert len(maps_edges) == 1, (
            f"Expected 1 MAPS_TO_TABLE from GroupVProjectFeatures, got {len(maps_edges)}"
        )
        tb_grp_pf_id = maps_edges[0].to_node
        tb_grp_pf_node = graph.node_by_id(tb_grp_pf_id)
        assert tb_grp_pf_node is not None
        assert tb_grp_pf_node.qualified_name == "TB_GRP_PF"

        # 3. FK: TB_GRP_PF_FEATURE -> TB_GRP_PF (via A.GROUP_PF_ID=B.ID)
        # FK edges use table node IDs as from_node/to_node
        fk_to_grp_pf = [
            e
            for e in graph.edges
            if e.kind == "FOREIGN_KEY_TO" and e.to_node == tb_grp_pf_id
        ]
        feature_fk = [
            e
            for e in fk_to_grp_pf
            if table_name_by_id.get(e.from_node) == "TB_GRP_PF_FEATURE"
        ]
        assert len(feature_fk) == 1, (
            f"FK from TB_GRP_PF_FEATURE to TB_GRP_PF not found. "
            f"FK edges to TB_GRP_PF: {[(table_name_by_id.get(e.from_node, '?'), dict(e.properties)) for e in fk_to_grp_pf]}"
        )
        assert dict(feature_fk[0].properties).get("join_condition") == "A.GROUP_PF_ID=B.ID"

        # 4. Find TB_GRP_PF_FEATURE table node
        tb_feature_id = table_id_by_name.get("TB_GRP_PF_FEATURE")
        assert tb_feature_id is not None, "TB_GRP_PF_FEATURE table not found"

        # 5. FK: TB_GRP_PF_FEATURE_P -> TB_GRP_PF_FEATURE (via A.FEATURE_ID=B.ID)
        fk_to_feature = [
            e
            for e in graph.edges
            if e.kind == "FOREIGN_KEY_TO" and e.to_node == tb_feature_id
        ]
        feature_p_fk = [
            e
            for e in fk_to_feature
            if table_name_by_id.get(e.from_node) == "TB_GRP_PF_FEATURE_P"
        ]
        assert len(feature_p_fk) == 1, (
            "FK from TB_GRP_PF_FEATURE_P to TB_GRP_PF_FEATURE not found"
        )
        assert dict(feature_p_fk[0].properties).get("join_condition") == "A.FEATURE_ID=B.ID"

    def test_lazy_provider_connected_to_fk(self, reconciled_graph):
        """LazySetProvider relationship from GroupVProjectFeatures connects to
        the physical FK chain through the entity → table → FK path.

        GroupVProjectFeatures.projectFeatures (LazySetProvider<ProjectFeature>)
        → JAVA_RELATION_TO → ProjectFeature entity
        → MAPS_TO_TABLE → TB_GRP_PF_FEATURE
        And TB_GRP_PF_FEATURE has FK → TB_GRP_PF (the table mapped by GroupVProjectFeatures).
        """
        graph = reconciled_graph

        # Build table-name → node-id lookup
        table_id_by_name = {
            n.qualified_name: n.id
            for n in graph.nodes
            if n.kind in ("table", "view", "materialized_view")
        }

        # 1. GroupVProjectFeatures entity
        gvpf = [
            n
            for n in graph.nodes
            if n.kind == "java_entity"
            and n.qualified_name.endswith("GroupVProjectFeatures")
        ]
        assert len(gvpf) == 1
        gvpf_id = gvpf[0].id

        # 2. JAVA_RELATION_TO -> ProjectFeature
        rel_edges = [
            e
            for e in graph.edges
            if e.kind == "JAVA_RELATION_TO" and e.from_node == gvpf_id
        ]
        pf_rels = [
            e
            for e in rel_edges
            if dict(e.properties).get("target_type") == "ProjectFeature"
        ]
        assert len(pf_rels) == 1, (
            f"Expected 1 JAVA_RELATION_TO for ProjectFeature, got {len(pf_rels)}"
        )
        rel = pf_rels[0]
        assert dict(rel.properties).get("provider_kind") == "LazySetProvider"

        # 3. ProjectFeature entity -> MAPS_TO_TABLE -> TB_GRP_PF_FEATURE
        pf_entity_id = rel.to_node
        pf_entity_node = graph.node_by_id(pf_entity_id)
        assert pf_entity_node is not None
        assert pf_entity_node.qualified_name.endswith("ProjectFeature")

        maps_edges = [
            e
            for e in graph.edges
            if e.kind == "MAPS_TO_TABLE" and e.from_node == pf_entity_id
        ]
        assert len(maps_edges) == 1
        tb_feature_id = maps_edges[0].to_node
        tb_feature_node = graph.node_by_id(tb_feature_id)
        assert tb_feature_node is not None
        assert tb_feature_node.qualified_name == "TB_GRP_PF_FEATURE"

        # 4. TB_GRP_PF_FEATURE has FK -> TB_GRP_PF (the parent table)
        tb_grp_pf_id = table_id_by_name.get("TB_GRP_PF")
        assert tb_grp_pf_id is not None, "TB_GRP_PF table node not found"

        fk_from_feature = [
            e
            for e in graph.edges
            if e.kind == "FOREIGN_KEY_TO"
            and e.from_node == tb_feature_id
            and e.to_node == tb_grp_pf_id
        ]
        assert len(fk_from_feature) >= 1, (
            "FK from TB_GRP_PF_FEATURE to TB_GRP_PF not found"
        )

    def test_conflict_detection(self, reconciled_graph):
        """A JPA column exists that is not found in Jailer → produces a conflict."""
        assert len(reconciled_graph.conflicts) > 0, (
            "Expected conflicts (JPA columns not in Jailer), found none"
        )
        # All conflicts should describe a column not found in Jailer
        for c in reconciled_graph.conflicts:
            assert "not found in Jailer" in c.description, (
                f"Unexpected conflict type: {c.description}"
            )
            assert c.resolution == "unresolved"

    def test_deterministic_output(
        self, jailer_result, jpa_result, fixed_provenance
    ):
        """Same inputs produce byte-identical graph (same fingerprint)."""
        from moughorai.database_graph.reconciler import reconcile_database_graph

        graph1 = reconcile_database_graph(
            SYGMA_ROOT,
            jailer_result,
            jpa_result,
            provenance=fixed_provenance,
            workspace_fingerprint="test-ws-fp",
        )
        graph2 = reconcile_database_graph(
            SYGMA_ROOT,
            jailer_result,
            jpa_result,
            provenance=fixed_provenance,
            workspace_fingerprint="test-ws-fp",
        )
        assert graph1.fingerprint == graph2.fingerprint, (
            f"Fingerprints differ: {graph1.fingerprint} != {graph2.fingerprint}"
        )
        assert len(graph1.nodes) == len(graph2.nodes)
        assert len(graph1.edges) == len(graph2.edges)

        # Also verify canonical JSON round-trip is identical
        from moughorai.database_graph.models import canonical_json

        json1 = canonical_json(graph1.to_dict())
        json2 = canonical_json(graph2.to_dict())
        assert json1 == json2, "Canonical JSON representations differ"

    def test_provenance_bound_to_revision(self, reconciled_graph):
        """Graph carries the Git revision in provenance."""
        assert reconciled_graph.provenance is not None
        assert reconciled_graph.provenance.get("head_sha") == SYGMA_SHA, (
            f"Expected head_sha={SYGMA_SHA}, "
            f"got {reconciled_graph.provenance.get('head_sha')}"
        )
        assert reconciled_graph.provenance.get("vcs") == "git"
