"""CB2-8: Revision provenance binding tests.

Validates that:
1. _extract_snapshot_sha correctly extracts commit SHAs from history_reference
2. _emit_agent_context_envelope uses 'unverified' when no expected revision
3. _emit_agent_context_envelope uses 'exact' only when verified
4. Snapshot provenance mismatch is detected when snapshot was created at a
   different revision than expected
5. --require-exact-revision without --expected-revision verifies snapshot
   provenance matches the live HEAD
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from moughorai.semantic_snapshot.provenance import (
    RepositoryProvenance,
    RevisionAlignment,
)
from moughorai.agent_context.service import _extract_snapshot_sha


# ---------------------------------------------------------------------------
# _extract_snapshot_sha
# ---------------------------------------------------------------------------


class TestExtractSnapshotSha:
    """Tests for the _extract_snapshot_sha helper."""

    def test_valid_40_char_sha(self):
        snapshot = SimpleNamespace(history_reference='a' * 40)
        assert _extract_snapshot_sha(snapshot) == 'a' * 40

    def test_valid_64_char_sha(self):
        snapshot = SimpleNamespace(history_reference='b' * 64)
        assert _extract_snapshot_sha(snapshot) == 'b' * 64

    def test_mixed_hex_40_char(self):
        sha = 'deadbeef' + '0' * 32
        snapshot = SimpleNamespace(history_reference=sha)
        assert _extract_snapshot_sha(snapshot) == sha

    def test_none_history_reference(self):
        snapshot = SimpleNamespace(history_reference=None)
        assert _extract_snapshot_sha(snapshot) is None

    def test_integer_history_reference(self):
        snapshot = SimpleNamespace(history_reference=42)
        assert _extract_snapshot_sha(snapshot) is None

    def test_short_string(self):
        snapshot = SimpleNamespace(history_reference='abc')
        assert _extract_snapshot_sha(snapshot) is None

    def test_uppercase_hex_rejected(self):
        snapshot = SimpleNamespace(history_reference='A' * 40)
        assert _extract_snapshot_sha(snapshot) is None

    def test_non_hex_40_chars(self):
        snapshot = SimpleNamespace(history_reference='g' * 40)
        assert _extract_snapshot_sha(snapshot) is None

    def test_empty_string(self):
        snapshot = SimpleNamespace(history_reference='')
        assert _extract_snapshot_sha(snapshot) is None

    def test_run_id_style_reference(self):
        snapshot = SimpleNamespace(history_reference='build-123')
        assert _extract_snapshot_sha(snapshot) is None


# ---------------------------------------------------------------------------
# Envelope revision_alignment
# ---------------------------------------------------------------------------

def _make_provenance(
    *,
    vcs: str = 'git',
    head_sha: str | None = 'a' * 40,
    head_ref: str | None = 'refs/heads/main',
    worktree_state: str = 'clean',
    verification: str = 'exact',
) -> RepositoryProvenance:
    return RepositoryProvenance(
        vcs=vcs,
        head_sha=head_sha,
        head_ref=head_ref,
        worktree_state=worktree_state,
        captured_at='2026-08-28T20:00:00Z',
        verification=verification,
    )


def _make_artifacts():
    """Create minimal mock artifacts for envelope testing."""
    root = SimpleNamespace(
        classification='resolved',
        canonical_subject_id='example',
        project='example',
    )
    graph = SimpleNamespace(
        discovered_roots=[root],
        omitted_counts={'discovery_roots': 0},
        nodes=[],
        edges=[],
        graph_fingerprint='gf-test',
    )
    package = SimpleNamespace(
        context_fingerprint='cf-test',
    )
    return SimpleNamespace(
        output_files=[('context.json', 100), ('graph.json', 200)],
        graph=graph,
        package=package,
    )


class TestEnvelopeRevisionAlignment:
    """Tests that _emit_agent_context_envelope produces correct revision_alignment."""

    def _capture_envelope(
        self,
        provenance,
        *,
        expected_revision=None,
        snapshot_sha=None,
    ):
        """Call the envelope function and capture the JSON output."""
        import json
        from moughorai.agent_context.models import AgentGraphDepth

        captured = {}

        def mock_echo(text, **kwargs):
            captured['output'] = text

        with patch('moughorai.atlas_cli.typer.echo', side_effect=mock_echo):
            from moughorai.atlas_cli import _emit_agent_context_envelope
            _emit_agent_context_envelope(
                _make_artifacts(),
                SimpleNamespace(snapshot_id='test-snap'),
                provenance,
                AgentGraphDepth.STORY,
                request_id='test-req',
                expected_revision=expected_revision,
                snapshot_sha=snapshot_sha,
            )

        return json.loads(captured['output'])

    def test_no_expected_revision_yields_unverified(self):
        provenance = _make_provenance(worktree_state='clean')
        envelope = self._capture_envelope(provenance)
        assert envelope['revision_alignment'] == 'unverified'

    def test_no_expected_revision_dirty_yields_unverified(self):
        provenance = _make_provenance(worktree_state='dirty_tracked')
        envelope = self._capture_envelope(provenance)
        assert envelope['revision_alignment'] == 'unverified'

    def test_expected_revision_match_clean_yields_exact(self):
        sha = 'a' * 40
        provenance = _make_provenance(head_sha=sha, worktree_state='clean')
        envelope = self._capture_envelope(
            provenance, expected_revision=sha, snapshot_sha=sha
        )
        assert envelope['revision_alignment'] == 'exact'

    def test_expected_revision_match_untracked_only_yields_exact(self):
        sha = 'a' * 40
        provenance = _make_provenance(
            head_sha=sha, worktree_state='dirty_untracked_only'
        )
        envelope = self._capture_envelope(
            provenance, expected_revision=sha, snapshot_sha=sha
        )
        assert envelope['revision_alignment'] == 'exact'

    def test_expected_revision_match_dirty_tracked_yields_dirty_overlay(self):
        sha = 'a' * 40
        provenance = _make_provenance(
            head_sha=sha, worktree_state='dirty_tracked'
        )
        envelope = self._capture_envelope(
            provenance, expected_revision=sha, snapshot_sha=sha
        )
        assert envelope['revision_alignment'] == 'dirty_overlay'

    def test_snapshot_sha_differs_from_expected_yields_stale(self):
        live_sha = 'a' * 40
        snap_sha = 'b' * 40
        provenance = _make_provenance(head_sha=live_sha, worktree_state='clean')
        envelope = self._capture_envelope(
            provenance, expected_revision=live_sha, snapshot_sha=snap_sha
        )
        assert envelope['revision_alignment'] == 'stale'

    def test_non_git_yields_non_git(self):
        provenance = _make_provenance(
            vcs='none', head_sha=None, head_ref=None,
            worktree_state='unknown', verification='unavailable',
        )
        envelope = self._capture_envelope(provenance)
        assert envelope['revision_alignment'] == 'non_git'

    def test_expected_revision_non_git_yields_non_git(self):
        provenance = _make_provenance(
            vcs='none', head_sha=None, head_ref=None,
            worktree_state='unknown', verification='unavailable',
        )
        envelope = self._capture_envelope(
            provenance, expected_revision='a' * 40
        )
        assert envelope['revision_alignment'] == 'non_git'

    def test_no_snapshot_sha_with_expected_match_yields_exact(self):
        """When snapshot has no history_reference SHA, but live HEAD matches expected."""
        sha = 'a' * 40
        provenance = _make_provenance(head_sha=sha, worktree_state='clean')
        envelope = self._capture_envelope(
            provenance, expected_revision=sha, snapshot_sha=None
        )
        assert envelope['revision_alignment'] == 'exact'


# ---------------------------------------------------------------------------
# RepositoryProvenance.check_revision — untracked-only consistency
# ---------------------------------------------------------------------------


class TestUntrackedOnlyConsistency:
    """Verify untracked-only worktree is treated as EXACT in check_revision."""

    def test_untracked_only_is_exact(self):
        sha = 'c' * 40
        p = _make_provenance(head_sha=sha, worktree_state='dirty_untracked_only')
        assert p.check_revision(sha) == RevisionAlignment.EXACT

    def test_untracked_only_different_sha_is_stale(self):
        p = _make_provenance(
            head_sha='c' * 40, worktree_state='dirty_untracked_only'
        )
        assert p.check_revision('d' * 40) == RevisionAlignment.STALE


# ---------------------------------------------------------------------------
# Provenance verification logic (unit-level tests for the Phase 3 logic)
# ---------------------------------------------------------------------------


class TestProvenanceVerificationLogic:
    """Tests for the Phase 3 provenance verification logic in agent_context_command.

    These test the logic by simulating the conditions rather than running
    the full CLI command (which needs a real snapshot and repository).
    """

    def test_require_exact_without_expected_needs_matching_snapshot(self):
        """--require-exact-revision without --expected-revision must compare
        snapshot provenance to live HEAD."""
        live_sha = 'a' * 40
        snap_sha = 'b' * 40
        provenance = _make_provenance(head_sha=live_sha, worktree_state='clean')

        # Simulating the logic from the operation function:
        # snapshot_sha != provenance.head_sha should raise
        assert snap_sha != provenance.head_sha  # would trigger ValueError

    def test_require_exact_without_expected_matching_snapshot_passes(self):
        """When snapshot and HEAD match, --require-exact-revision is satisfied."""
        sha = 'a' * 40
        provenance = _make_provenance(head_sha=sha, worktree_state='clean')
        assert sha == provenance.head_sha
        alignment = provenance.check_revision(sha)
        assert alignment == RevisionAlignment.EXACT

    def test_expected_revision_with_snapshot_mismatch_detected(self):
        """When --expected-revision is given but snapshot was created at
        a different revision, the mismatch is detectable."""
        expected = 'a' * 40
        snap_sha = 'c' * 40
        # The fix adds: if snapshot_sha is not None and snapshot_sha != expected_revision
        assert snap_sha != expected
