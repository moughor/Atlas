"""Anti-overfitting guarantees for database context selection.

These tests prevent pack-specific leakage by verifying:
1. Story word alone cannot create a semantic uncertainty
2. Renaming a story keyword does not alter repository evidence truth
3. Removing the underlying repository evidence removes the uncertainty
4. No production module contains pack expected text

These are structural tests that do NOT require the Sygma repository.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


def _make_test_graph(nodes, edges=()):
    """Create a minimal DatabaseGraph for testing."""
    from moughorai.database_graph.models import (
        DatabaseGraph,
        DATABASE_GRAPH_SCHEMA_VERSION,
    )
    return DatabaseGraph(
        schema_version=DATABASE_GRAPH_SCHEMA_VERSION,
        fingerprint="test_fingerprint_" + "0" * 48,  # 64 char hex
        provenance={"type": "test", "version": "1.0"},
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


# ---------------------------------------------------------------------------
# Test 1: Story word alone cannot create semantic uncertainty
# ---------------------------------------------------------------------------

class TestStoryWordCannotCreateUncertainty:
    """Verify that story text alone cannot prove or create semantic uncertainties.
    
    Uncertainties must derive from repository evidence (schema, constraints,
    migrations), not from pattern-matching story keywords.
    """
    
    def test_backup_word_alone_insufficient(self):
        """The word 'backup' in a story cannot prove backup classification."""
        # If a story says "backup" but no BCK-prefixed table exists,
        # no BACKUP_CLASSIFICATION_UNPROVEN uncertainty should be generated.
        from moughorai.database_graph.models import (
            DatabaseGraphNode,
            NodeKind,
            EvidenceRecord,
        )
        from moughorai.database_graph.context_selector import (
            select_database_context,
        )
        
        # Create a minimal graph with a canonical table but NO BCK table
        nodes = [
            DatabaseGraphNode(
                id="tb_test",
                kind=NodeKind.TABLE.value,
                qualified_name="TB_TEST",
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph = _make_test_graph(nodes)
        
        # Story mentions "backup" but graph has no BCK evidence
        story = "Check the backup status of TB_TEST."
        
        # Run selection
        result = select_database_context(graph, story)
        
        # No BACKUP_CLASSIFICATION_UNPROVEN uncertainty should exist
        backup_uncs = [
            u for u in result.uncertainties
            if u.code == "BACKUP_CLASSIFICATION_UNPROVEN"
        ]
        assert len(backup_uncs) == 0, (
            "Story word 'backup' alone should NOT create uncertainty. "
            "Uncertainties must derive from repository evidence."
        )
    
    def test_failed_word_alone_insufficient(self):
        """The word 'failed' in a story cannot prove view semantic filtering."""
        from moughorai.database_graph.models import (
            DatabaseGraphNode,
            NodeKind,
            EvidenceRecord,
        )
        from moughorai.database_graph.context_selector import (
            select_database_context,
        )
        
        # Create a minimal graph with a view that does NOT filter states
        nodes = [
            DatabaseGraphNode(
                id="vw_test",
                kind=NodeKind.VIEW.value,
                qualified_name="VW_TEST_DATA",  # No state indicator in name
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph = _make_test_graph(nodes)
        
        # Story mentions "failed" but view doesn't filter states
        story = "Show failed records from VW_TEST_DATA."
        
        # Run selection
        result = select_database_context(graph, story)
        
        # No VIEW_SEMANTIC_FILTERING uncertainty should exist
        view_uncs = [
            u for u in result.uncertainties
            if u.code == "VIEW_SEMANTIC_FILTERING"
        ]
        assert len(view_uncs) == 0, (
            "Story word 'failed' alone should NOT create uncertainty. "
            "View filtering uncertainties require evidence of actual predicates."
        )


# ---------------------------------------------------------------------------
# Test 2: Renaming story keyword does not alter repository truth
# ---------------------------------------------------------------------------

class TestKeywordRenameInvariance:
    """Verify that renaming keywords in story doesn't change evidence truth.
    
    If story says "backup" → uncertainty, then changing to "copy" with the
    same repository evidence should produce the same uncertainty (or lack
    thereof) since uncertainty derives from evidence, not keyword.
    """
    
    def test_backup_vs_copy_same_evidence(self):
        """Replacing 'backup' with 'copy' should not change uncertainty state."""
        from moughorai.database_graph.models import (
            DatabaseGraphNode,
            NodeKind,
            EvidenceRecord,
        )
        from moughorai.database_graph.context_selector import (
            select_database_context,
        )
        
        # Create graph with canonical table only (no BCK evidence)
        nodes = [
            DatabaseGraphNode(
                id="tb_data",
                kind=NodeKind.TABLE.value,
                qualified_name="TB_DATA",
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph = _make_test_graph(nodes)
        
        # Two stories with different keywords, same meaning
        story_backup = "Check the backup of TB_DATA."
        story_copy = "Check the copy of TB_DATA."
        
        result_backup = select_database_context(graph, story_backup)
        result_copy = select_database_context(graph, story_copy)
        
        # Both should have same uncertainty state (none, since no BCK evidence)
        backup_unc_codes = {u.code for u in result_backup.uncertainties}
        copy_unc_codes = {u.code for u in result_copy.uncertainties}
        
        # BACKUP_CLASSIFICATION_UNPROVEN should be absent in both
        # (since no BCK table exists)
        assert "BACKUP_CLASSIFICATION_UNPROVEN" not in backup_unc_codes
        assert "BACKUP_CLASSIFICATION_UNPROVEN" not in copy_unc_codes
    
    def test_failed_vs_error_same_evidence(self):
        """Replacing 'failed' with 'error' should not change view uncertainty."""
        from moughorai.database_graph.models import (
            DatabaseGraphNode,
            NodeKind,
            EvidenceRecord,
        )
        from moughorai.database_graph.context_selector import (
            select_database_context,
        )
        
        # Create graph with a plain view (no state filtering evidence)
        nodes = [
            DatabaseGraphNode(
                id="vw_report",
                kind=NodeKind.VIEW.value,
                qualified_name="VW_REPORT",
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph = _make_test_graph(nodes)
        
        story_failed = "Show failed records from VW_REPORT."
        story_error = "Show error records from VW_REPORT."
        
        result_failed = select_database_context(graph, story_failed)
        result_error = select_database_context(graph, story_error)
        
        # Neither should have VIEW_SEMANTIC_FILTERING uncertainty
        failed_unc_codes = {u.code for u in result_failed.uncertainties}
        error_unc_codes = {u.code for u in result_error.uncertainties}
        
        assert "VIEW_SEMANTIC_FILTERING" not in failed_unc_codes
        assert "VIEW_SEMANTIC_FILTERING" not in error_unc_codes


# ---------------------------------------------------------------------------
# Test 3: Removing repository evidence removes uncertainty
# ---------------------------------------------------------------------------

class TestEvidenceRemovalRemovesUncertainty:
    """Verify that uncertainties are tied to repository evidence.
    
    If a dynamic synonym causes DYNAMIC_SYNONYM_TARGET_UNPROVEN, removing
    that synonym from the graph should remove the uncertainty.
    """
    
    def test_dynamic_synonym_removal(self):
        """Removing dynamic synonym node removes its uncertainty."""
        from moughorai.database_graph.models import (
            DatabaseGraphNode,
            NodeKind,
            EvidenceRecord,
        )
        from moughorai.database_graph.context_selector import (
            select_database_context,
        )
        
        # Graph WITH dynamic synonym
        nodes_with_syn = [
            DatabaseGraphNode(
                id="syn_dynamic",
                kind=NodeKind.SYNONYM.value,
                qualified_name="SYN_DYNAMIC_TARGET",
                evidence=EvidenceRecord(status="unknown", confidence=0.0),
                properties=(("dynamic", True),),
            ),
            DatabaseGraphNode(
                id="tb_target",
                kind=NodeKind.TABLE.value,
                qualified_name="TB_TARGET",
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph_with = _make_test_graph(nodes_with_syn)
        
        # Graph WITHOUT dynamic synonym
        nodes_without = [
            DatabaseGraphNode(
                id="tb_target",
                kind=NodeKind.TABLE.value,
                qualified_name="TB_TARGET",
                evidence=EvidenceRecord(status="verified", confidence=1.0),
            ),
        ]
        graph_without = _make_test_graph(nodes_without)
        
        story = "Check SYN_DYNAMIC_TARGET and TB_TARGET."
        
        result_with = select_database_context(graph_with, story)
        result_without = select_database_context(graph_without, story)
        
        # With dynamic synonym → may have DYNAMIC_SYNONYM_TARGET_UNPROVEN
        # Without dynamic synonym → should NOT have it
        
        with_dyn_uncs = [
            u for u in result_with.uncertainties
            if u.code == "DYNAMIC_SYNONYM_TARGET_UNPROVEN"
        ]
        without_dyn_uncs = [
            u for u in result_without.uncertainties
            if u.code == "DYNAMIC_SYNONYM_TARGET_UNPROVEN"
        ]
        
        # The "without" graph definitely should have no dynamic synonym uncertainty
        assert len(without_dyn_uncs) == 0, (
            "Removing dynamic synonym evidence should remove its uncertainty."
        )


# ---------------------------------------------------------------------------
# Test 4: No production module contains pack expected text
# ---------------------------------------------------------------------------

class TestNoPackExpectedTextInProduction:
    """Verify production code does not contain hardcoded pack expected strings.
    
    Pack expected uncertainty texts like:
    - "business meaning of every state value"
    - "deployment retention policy is not known"
    - "Backup classification is based on explicit BCK naming"
    
    These are evaluation pack assertions and must NOT appear in production
    code as they indicate pack-fitting.
    """
    
    # Pack-specific expected uncertainty text patterns
    FORBIDDEN_PATTERNS = [
        # From SYGMA-DB-005 expected uncertainty
        "business meaning of every state value",
        "filters a specific set of generation states",
        
        # From SYGMA-DB-013 expected uncertainty  
        "deployment retention policy is not known",
        "Backup classification is based on explicit BCK naming",
        
        # From various pack cases - these are case-specific
        "predates the inspected",
        "revision-aware reconciliation",
        "MAX(ID) as latest snapshot",
        "application guidance, not a general database invariant",
        "No current non-BACK_UP repository definition",
        "VARCHAR2(2000), not a declared numeric foreign key",
        "wildcard or multiple session identifiers",
        "Live session/exercise state and deployment drift",
        "query-specific latest-session logic",
        "universal latest-record rule",
        "ROW_NUMBER ordering and the UNION branch",
        "amendment semantics, not universal history rules",
        "Materialized-view freshness and refresh status",
        "runtime facts not available",
        "LazySetProvider relations",
        "direction must be corroborated",
        "scale 7 while Jailer 9.3.3 reports",
        "type/scale-sensitive SQL",
        "duration derivable from dates",
        "Jailer 9.3.3 snapshot predates",
        "stale for this object",
        "lacks TPL_INFO_CONDITIONAL",
        "HAS_DYNAMIC_TEMPLATES",
        "migration/entity include them",
        "retain source version and conflict metadata",
        "generator queries live ALL_OBJECTS",
        "executes dynamic DDL",
        "which synonyms exist",
        "which consumer schema",
        "whether each creation succeeded",
    ]
    
    def test_production_modules_clean(self):
        """No production module contains pack expected uncertainty text."""
        # Find the production module directory
        project_root = Path(__file__).parent.parent
        production_dir = project_root / "moughorai" / "database_graph"
        
        if not production_dir.exists():
            pytest.skip("Production directory not found")
        
        violations = []
        
        for py_file in production_dir.glob("*.py"):
            content = py_file.read_text()
            content_lower = content.lower()
            
            for pattern in self.FORBIDDEN_PATTERNS:
                if pattern.lower() in content_lower:
                    violations.append((py_file.name, pattern))
        
        if violations:
            msg = "Production code contains pack-specific expected text:\n"
            for filename, pattern in violations:
                msg += f"  - {filename}: '{pattern}'\n"
            msg += "\nThese patterns indicate pack-fitting and must be removed."
            pytest.fail(msg)
    
    def test_no_case_specific_logic(self):
        """No production module contains case ID specific logic."""
        # Case IDs like SYGMA-DB-001 through SYGMA-DB-014
        import re
        
        project_root = Path(__file__).parent.parent
        production_dir = project_root / "moughorai" / "database_graph"
        
        if not production_dir.exists():
            pytest.skip("Production directory not found")
        
        case_id_pattern = re.compile(r'\bSYGMA-DB-\d{3}\b', re.IGNORECASE)
        
        violations = []
        
        for py_file in production_dir.glob("*.py"):
            content = py_file.read_text()
            matches = case_id_pattern.findall(content)
            if matches:
                violations.append((py_file.name, matches))
        
        if violations:
            msg = "Production code references specific case IDs:\n"
            for filename, matches in violations:
                msg += f"  - {filename}: {matches}\n"
            msg += "\nCase-specific logic indicates overfitting to the evaluation pack."
            pytest.fail(msg)
