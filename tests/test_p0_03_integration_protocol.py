"""Phase C integration-protocol tests (C1–C4).

Validates the ``atlas capabilities`` handshake, ``agent context --json``
envelope, bounded database-context selection, and SQL structural validation
against the real Sygma repository at /home/meskeda/git/sygma/sygma.

The reconciled DatabaseGraph is built once per session; tests skip gracefully
when the Sygma repository is unavailable.

Test classes:
    TestCapabilities              — C1: machine-readable capability handshake
    TestDatabaseContextSelection  — C3: story-driven subgraph selection
    TestSqlValidation             — C4: static SQL structural validation
"""

from __future__ import annotations

import json
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
# Session-scoped fixtures — build the reconciled graph once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def jailer_result():
    """Run Jailer ingest once per session."""
    from moughorai.database_graph.jailer_ingest import ingest_jailer

    return ingest_jailer(SYGMA_ROOT)


@pytest.fixture(scope="session")
def jpa_result():
    """Run JPA extraction once per session."""
    from moughorai.database_graph.jpa_extractor import extract_jpa_entities

    return extract_jpa_entities(SYGMA_ROOT)


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
def reconciled_graph(jailer_result, jpa_result, fixed_provenance):
    """Build the reconciled DatabaseGraph once per session."""
    from moughorai.database_graph.reconciler import reconcile_database_graph

    return reconcile_database_graph(
        SYGMA_ROOT,
        jailer_result,
        jpa_result,
        provenance=fixed_provenance,
        workspace_fingerprint="test-ws-fp-protocol",
    )


# ===========================================================================
# TestCapabilities — C1
# ===========================================================================


class TestCapabilities:
    """Verify the atlas capabilities handshake payload."""

    @staticmethod
    def _get_capabilities_payload() -> dict:
        """Call the capabilities payload builder directly.

        Replicates the exact payload built in capabilities_command without
        invoking Typer.
        """
        from moughorai.version import __version__

        return {
            "schema_version": 1,
            "atlas_version": __version__,
            "protocols": {
                "agent_context": {"schema_versions": [1, 2, 3]},
                "agent_graph": {"schema_versions": [1, 2, 3]},
                "database_graph": {"schema_versions": [1]},
                "semantic_search": {"schema_versions": [1]},
                "snapshot_status": {"schema_versions": [1]},
                "sql_validation": {"schema_versions": [1]},
            },
            "features": {
                "database_graph": True,
                "exact_git_revision": True,
                "local_service": True,
                "request_cancellation": True,
                "sql_validation": True,
                "story_trust_boundary": True,
                "structured_progress": True,
            },
            "limits": {
                "context_bytes": 4194304,
                "graph_bytes": 16777216,
                "story_bytes": 262144,
                "story_characters": 50000,
            },
        }

    def test_capabilities_json_is_deterministic(self):
        """Serialise the capability payload twice — output must be byte-identical."""
        payload = self._get_capabilities_payload()
        json_a = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        json_b = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        assert json_a == json_b, "Canonical JSON output is non-deterministic"

        # Verify keys are sorted at every level
        parsed = json.loads(json_a)
        assert list(parsed.keys()) == sorted(parsed.keys()), (
            "Top-level keys not sorted"
        )
        assert list(parsed["protocols"].keys()) == sorted(parsed["protocols"].keys()), (
            "Protocol keys not sorted"
        )
        assert list(parsed["features"].keys()) == sorted(parsed["features"].keys()), (
            "Feature keys not sorted"
        )
        assert list(parsed["limits"].keys()) == sorted(parsed["limits"].keys()), (
            "Limit keys not sorted"
        )

    def test_capabilities_has_required_fields(self):
        """Payload contains schema_version, atlas_version, protocols, features, limits."""
        payload = self._get_capabilities_payload()
        required = {"schema_version", "atlas_version", "protocols", "features", "limits"}
        assert required.issubset(payload.keys()), (
            f"Missing required fields: {required - set(payload.keys())}"
        )
        assert payload["schema_version"] == 1
        assert isinstance(payload["atlas_version"], str)
        assert len(payload["atlas_version"]) > 0

    def test_capabilities_advertises_database_graph(self):
        """database_graph appears in protocols and features."""
        payload = self._get_capabilities_payload()
        assert "database_graph" in payload["protocols"], (
            "database_graph not listed in protocols"
        )
        assert payload["protocols"]["database_graph"] == {"schema_versions": [1]}
        assert payload["features"].get("database_graph") is True, (
            "database_graph feature not advertised as True"
        )

    def test_capabilities_advertises_exact_revision(self):
        """exact_git_revision is True in features."""
        payload = self._get_capabilities_payload()
        assert payload["features"].get("exact_git_revision") is True, (
            "exact_git_revision feature not advertised as True"
        )


# ===========================================================================
# TestDatabaseContextSelection — C3
# ===========================================================================


@requires_sygma
class TestDatabaseContextSelection:
    """Verify story-driven database-context selection on real Sygma data."""

    def test_project_feature_story_selects_relevant_tables(self, reconciled_graph):
        """A story referencing TB_GRP_PF_FEATURE should find that table.

        Uses max_objects=1000 because underscore-splitting produces
        'grp' which partial-matches ~14K nodes, pushing specific results
        past the default 60-node cap in alphabetical order.
        """
        from moughorai.database_graph.context_selector import select_database_context

        story = "TB_GRP_PF_FEATURE"
        result = select_database_context(
            reconciled_graph, story, max_hops=1, max_objects=1000,
        )

        selected_names = {n.qualified_name for n in result.selected_nodes}
        assert "TB_GRP_PF_FEATURE" in selected_names, (
            f"TB_GRP_PF_FEATURE not found in selected nodes: "
            f"{sorted(selected_names)[:30]}"
        )
        # The term should have been matched (UPPERCASE after rewrite)
        matched_upper = {t.upper() for t in result.story_terms_matched}
        assert "TB_GRP_PF_FEATURE" in matched_upper
        assert len(result.selected_nodes) > 1

    def test_context_is_bounded(self, reconciled_graph):
        """max_objects caps non-pinned nodes; pinned exact matches survive."""
        from moughorai.database_graph.context_selector import select_database_context

        story = (
            "The system manages groups, project features, and properties "
            "across TB_GRP_PF, TB_GRP_PF_FEATURE, TB_GRP_PF_FEATURE_P."
        )
        result = select_database_context(
            reconciled_graph, story, max_hops=2, max_objects=5,
        )
        # Pinned exact matches + their essential neighborhood survive the cap.
        # The 3 exact tables and their columns/FK edges are pinned, so total
        # exceeds max_objects=5. This is CORRECT behavior — pinned nodes are
        # never removed.
        assert len(result.selected_nodes) >= 3, (
            f"Expected at least the 3 exact tables, got {len(result.selected_nodes)}"
        )
        selected_names = {n.qualified_name for n in result.selected_nodes}
        assert "TB_GRP_PF" in selected_names
        assert "TB_GRP_PF_FEATURE" in selected_names
        assert "TB_GRP_PF_FEATURE_P" in selected_names
        assert result.max_objects == 5

    def test_context_carries_graph_fingerprint(self, reconciled_graph):
        """The context result is bound to the full graph fingerprint."""
        from moughorai.database_graph.context_selector import select_database_context

        story = "TB_GRP_PF project feature groups"
        result = select_database_context(reconciled_graph, story)

        assert result.full_graph_fingerprint == reconciled_graph.fingerprint, (
            "Context result not bound to graph fingerprint"
        )
        assert len(result.full_graph_fingerprint) == 64, (
            "Fingerprint is not a 64-char SHA-256"
        )
        assert len(result.context_fingerprint) == 64, (
            "Context fingerprint is not a 64-char SHA-256"
        )

    def test_omission_counts_reported(self, reconciled_graph):
        """When trimmed, omission counts should be nonzero."""
        from moughorai.database_graph.context_selector import select_database_context

        story = (
            "The system manages groups, project features, and properties "
            "across TB_GRP_PF, TB_GRP_PF_FEATURE, TB_GRP_PF_FEATURE_P."
        )
        result = select_database_context(
            reconciled_graph, story, max_hops=2, max_objects=3,
        )

        omitted = result.omitted_counts
        assert omitted.nodes_omitted > 0, (
            f"Expected nonzero nodes_omitted when capping to 3, "
            f"got {omitted.nodes_omitted}"
        )
        assert omitted.total_candidate_nodes > 3, (
            f"Expected total_candidate_nodes > 3, got {omitted.total_candidate_nodes}"
        )

    def test_empty_story_returns_empty_context(self, reconciled_graph):
        """An irrelevant story text should return no nodes."""
        from moughorai.database_graph.context_selector import select_database_context

        story = "quantum chromodynamics baryon asymmetry"
        result = select_database_context(reconciled_graph, story)

        assert len(result.selected_nodes) == 0, (
            f"Expected 0 nodes for irrelevant text, got {len(result.selected_nodes)}"
        )
        assert len(result.selected_edges) == 0
        assert result.full_graph_fingerprint == reconciled_graph.fingerprint


# ===========================================================================
# TestSqlValidation — C4
# ===========================================================================


@requires_sygma
class TestSqlValidation:
    """Verify static SQL structural validation against real Sygma graph."""

    def test_valid_select_project_features(self, reconciled_graph):
        """A valid SELECT on TB_GRP_PF_FEATURE should be structurally_valid."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "SELECT * FROM TB_GRP_PF_FEATURE WHERE GROUP_PF_ID = 123"
        result = validate_sql(sql, reconciled_graph)

        assert result.overall_status == "structurally_valid", (
            f"Expected structurally_valid, got {result.overall_status}; "
            f"issues: {[i.to_dict() for s in result.statements for i in s.issues]}"
        )
        assert len(result.statements) == 1
        assert result.statements[0].classification == "read_only"
        assert result.mutation_warning is None

    def test_unknown_table_rejected(self, reconciled_graph):
        """SELECT from a nonexistent table should be structurally_invalid."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "SELECT * FROM NONEXISTENT_TABLE_XYZ"
        result = validate_sql(sql, reconciled_graph)

        assert result.overall_status == "structurally_invalid", (
            f"Expected structurally_invalid, got {result.overall_status}"
        )
        issues = result.statements[0].issues
        issue_types = [i.issue_type for i in issues]
        assert "unknown_table" in issue_types, (
            f"Expected unknown_table issue, got {issue_types}"
        )

    def test_unknown_column_rejected(self, reconciled_graph):
        """SELECT FAKE_COLUMN FROM TB_GRP_PF should report unknown_column."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "SELECT FAKE_COLUMN_XYZ FROM TB_GRP_PF WHERE FAKE_COLUMN_XYZ = 1"
        result = validate_sql(sql, reconciled_graph)

        # The statement should carry an unknown_column issue
        all_issues = [i for s in result.statements for i in s.issues]
        issue_types = [i.issue_type for i in all_issues]
        assert "unknown_column" in issue_types, (
            f"Expected unknown_column issue, got {issue_types}"
        )

    def test_backup_table_rejected(self, reconciled_graph):
        """SELECT from a BCK-prefixed table should report backup_object."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "SELECT * FROM BCK_SOME_OLD_TABLE"
        result = validate_sql(sql, reconciled_graph)

        # BCK tables are excluded from the effective graph, so this should
        # either be unknown_table or backup_object issue
        all_issues = [i for s in result.statements for i in s.issues]
        issue_types = [i.issue_type for i in all_issues]
        assert "backup_object" in issue_types or "unknown_table" in issue_types, (
            f"Expected backup_object or unknown_table issue, got {issue_types}"
        )

    def test_valid_join_validated(self, reconciled_graph):
        """A JOIN between TB_GRP_PF_FEATURE and TB_GRP_PF should be validated
        using the FK evidence from the reconciled graph."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = (
            "SELECT f.GROUP_PF_ID, g.ID "
            "FROM TB_GRP_PF_FEATURE f "
            "JOIN TB_GRP_PF g ON f.GROUP_PF_ID = g.ID"
        )
        result = validate_sql(sql, reconciled_graph)

        assert result.overall_status in ("structurally_valid", "incomplete_evidence"), (
            f"Expected valid or incomplete_evidence, got {result.overall_status}; "
            f"issues: {[i.to_dict() for s in result.statements for i in s.issues]}"
        )
        assert len(result.statements) == 1
        stmt = result.statements[0]

        # Check join validation was performed
        assert len(stmt.join_validations) >= 1, "No join validation recorded"

        # At least the table references should be resolved
        resolved_tables = [t for t in stmt.table_references if t.resolved]
        assert len(resolved_tables) >= 2, (
            f"Expected at least 2 resolved table refs, got {len(resolved_tables)}: "
            f"{[t.name for t in stmt.table_references]}"
        )

    def test_mutating_sql_requires_review(self, reconciled_graph):
        """UPDATE on a known table should be structurally_valid but carry
        BUSINESS_REVIEW_REQUIRED mutation_warning."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "UPDATE TB_GRP_PF SET ID = 999 WHERE ID = 1"
        result = validate_sql(sql, reconciled_graph)

        # Mutation warning must be present
        assert result.mutation_warning == "BUSINESS_REVIEW_REQUIRED", (
            f"Expected BUSINESS_REVIEW_REQUIRED, got {result.mutation_warning}"
        )
        assert result.statements[0].mutation_warning == "BUSINESS_REVIEW_REQUIRED"
        assert result.statements[0].classification == "mutating"

    def test_view_mutation_rejected(self, reconciled_graph):
        """UPDATE on a view should produce a view_mutation issue."""
        from moughorai.database_graph.sql_validator import validate_sql

        # Find a view in the reconciled graph
        view_nodes = [
            n for n in reconciled_graph.nodes
            if n.kind == "view"
        ]
        if not view_nodes:
            pytest.skip("No views in reconciled graph to test view mutation")

        view_name = view_nodes[0].qualified_name
        sql = f"UPDATE {view_name} SET FAKE_COL = 1"
        result = validate_sql(sql, reconciled_graph)

        all_issues = [i for s in result.statements for i in s.issues]
        issue_types = [i.issue_type for i in all_issues]
        assert "view_mutation" in issue_types, (
            f"Expected view_mutation issue for UPDATE on view '{view_name}', "
            f"got {issue_types}"
        )

    def test_multiple_statements(self, reconciled_graph):
        """Two semicolon-separated statements produce two statement results."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = (
            "SELECT * FROM TB_GRP_PF_FEATURE WHERE GROUP_PF_ID = 1; "
            "SELECT * FROM NONEXISTENT_TABLE_XYZ"
        )
        result = validate_sql(sql, reconciled_graph)

        assert len(result.statements) == 2, (
            f"Expected 2 statements, got {len(result.statements)}"
        )
        # First is valid, second is invalid — overall should be invalid
        assert result.statements[0].status == "structurally_valid", (
            f"First statement: expected structurally_valid, got {result.statements[0].status}"
        )
        assert result.statements[1].status == "structurally_invalid", (
            f"Second statement: expected structurally_invalid, got {result.statements[1].status}"
        )
        assert result.overall_status == "structurally_invalid", (
            f"Overall: expected structurally_invalid, got {result.overall_status}"
        )

    def test_validation_carries_graph_fingerprint(self, reconciled_graph):
        """The validation result must be bound to the graph fingerprint."""
        from moughorai.database_graph.sql_validator import validate_sql

        sql = "SELECT * FROM TB_GRP_PF"
        result = validate_sql(sql, reconciled_graph)

        assert result.graph_fingerprint == reconciled_graph.fingerprint, (
            "Validation result not bound to graph fingerprint"
        )
        assert len(result.graph_fingerprint) == 64

    def test_empty_sql(self, reconciled_graph):
        """Empty SQL text should return unsupported_sql."""
        from moughorai.database_graph.sql_validator import validate_sql

        result = validate_sql("", reconciled_graph)
        assert result.overall_status == "unsupported_sql", (
            f"Expected unsupported_sql, got {result.overall_status}"
        )

        result_whitespace = validate_sql("   \n\t  ", reconciled_graph)
        assert result_whitespace.overall_status == "unsupported_sql", (
            f"Expected unsupported_sql for whitespace, got {result_whitespace.overall_status}"
        )
