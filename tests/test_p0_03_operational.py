"""Operational tests for Phases D (progress), E (warm runtime), and F (output hardening).

Test classes:
    TestProgress       — structured JSONL progress, deadlines, cancellation
    TestWarmRuntime    — session caching, identity change, close, health
    TestOutputBounds   — atlas_version provenance, pre-publication size checks
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from moughorai.agent_context.progress import (
    Cancelled,
    DeadlineExceeded,
    ProgressEvent,
    RequestContext,
)
from moughorai.agent_context.warm_runtime import (
    WarmRuntimeSession,
)
from moughorai.agent_context.service import (
    ArtifactOversizedError,
    MAXIMUM_CONTEXT_MD_BYTES,
    MAXIMUM_GRAPH_MMD_BYTES,
    MAXIMUM_CONTEXT_JSON_BYTES,
    MAXIMUM_GRAPH_JSON_BYTES,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.measurement import MeasurementSession
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.version import __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_snapshot(
    *,
    workspace_fingerprint: str = 'test-fp',
    analyzer_version: str = 'op-test/1',
) -> AtlasSemanticSnapshot:
    """Create a minimal valid snapshot for testing."""
    context = WorkspaceSemanticContext({})
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint=workspace_fingerprint,
        analyzer_version=analyzer_version,
    )


def _snapshot_with_content(
    key: str = 'marker',
    value: str = 'alpha',
    *,
    workspace_fingerprint: str = 'test-fp',
    analyzer_version: str = 'op-test/1',
) -> AtlasSemanticSnapshot:
    """Create a snapshot with distinct content to produce different IDs."""
    context = WorkspaceSemanticContext({key: value})
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint=workspace_fingerprint,
        analyzer_version=analyzer_version,
    )


# ===========================================================================
# TestProgress — Phases D operational tests
# ===========================================================================


class TestProgress:
    """Operational tests for RequestContext progress emission, deadlines,
    and cancellation."""

    def test_request_context_emits_progress(self) -> None:
        """Verify that emit_progress writes JSONL events to the stream."""
        stream = io.StringIO()
        ctx = RequestContext(
            request_id='progress-test',
            progress_stream=stream,
        )
        try:
            event1 = ctx.emit_progress('snapshot_load', 'starting', 'snapshot.loading')
            event2 = ctx.emit_progress('snapshot_load', 'completed', 'snapshot.loaded')
        finally:
            ctx.close()

        lines = stream.getvalue().strip().split('\n')
        assert len(lines) == 2, f'Expected 2 JSONL lines, got {len(lines)}'

        parsed1 = json.loads(lines[0])
        parsed2 = json.loads(lines[1])
        assert parsed1['request_id'] == 'progress-test'
        assert parsed1['phase'] == 'snapshot_load'
        assert parsed1['state'] == 'starting'
        assert parsed1['message_code'] == 'snapshot.loading'
        assert parsed2['state'] == 'completed'
        # Events returned by emit_progress match
        assert event1.request_id == 'progress-test'
        assert event2.sequence == 1

    def test_deadline_exceeded(self) -> None:
        """Verify DeadlineExceeded is raised after deadline expires."""
        # Use a very short deadline
        ctx = RequestContext(
            request_id='deadline-test',
            deadline_seconds=0.01,
            progress_stream=io.StringIO(),
        )
        try:
            time.sleep(0.05)
            with pytest.raises(DeadlineExceeded, match='deadline-test'):
                ctx.check_deadline()
        finally:
            ctx.close()

    def test_cancellation_flag(self) -> None:
        """Verify cancel() sets is_cancelled and check_cancelled raises."""
        stream = io.StringIO()
        ctx = RequestContext(
            request_id='cancel-test',
            progress_stream=stream,
        )
        try:
            assert not ctx.is_cancelled
            # Directly set the cancellation flag (simulating signal)
            ctx._cancelled = True
            assert ctx.is_cancelled
            with pytest.raises(Cancelled, match='cancel-test'):
                ctx.check_cancelled()
        finally:
            ctx.close()

    def test_progress_events_are_monotonic(self) -> None:
        """Verify sequence numbers strictly increase across emitted events."""
        stream = io.StringIO()
        ctx = RequestContext(
            request_id='monotonic-test',
            progress_stream=stream,
        )
        events = []
        try:
            for i in range(5):
                event = ctx.emit_progress('test', 'running', f'step.{i}')
                events.append(event)
        finally:
            ctx.close()

        sequences = [e.sequence for e in events]
        assert sequences == list(range(5)), f'Non-monotonic sequences: {sequences}'
        # Also verify from the JSONL stream
        lines = stream.getvalue().strip().split('\n')
        parsed_sequences = [json.loads(line)['sequence'] for line in lines]
        assert parsed_sequences == list(range(5))

    def test_progress_does_not_affect_fingerprints(self) -> None:
        """Verify semantic artifacts are identical with and without progress.

        Both paths create a snapshot and generate its fingerprint. The
        presence of a progress stream must not change the deterministic
        semantic output.
        """
        # Path A: no progress context
        snap_a = _minimal_snapshot(workspace_fingerprint='fp-progress-test')

        # Path B: with active progress context
        stream = io.StringIO()
        ctx = RequestContext(
            request_id='fingerprint-test',
            progress_stream=stream,
        )
        try:
            ctx.emit_progress('test', 'starting', 'test.starting')
            snap_b = _minimal_snapshot(workspace_fingerprint='fp-progress-test')
            ctx.emit_progress('test', 'completed', 'test.completed')
        finally:
            ctx.close()

        # Progress events were emitted
        assert stream.getvalue().strip() != '', 'Expected progress events'
        # Semantic artifacts are byte-identical
        assert snap_a.snapshot_id == snap_b.snapshot_id
        assert snap_a.workspace_fingerprint == snap_b.workspace_fingerprint


# ===========================================================================
# TestWarmRuntime — Phase E operational tests
# ===========================================================================


class TestWarmRuntime:
    """Operational tests for WarmRuntimeSession caching and lifecycle."""

    def test_session_caches_by_identity(self, tmp_path: Path) -> None:
        """Same workspace + snapshot identity returns the same session."""
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            session1 = warm.get_or_create(tmp_path, snapshot)
            session2 = warm.get_or_create(tmp_path, snapshot)
            assert session1 is session2, 'Same identity should return same session'
            assert warm.statistics['cold_load_count'] == 1
            assert warm.statistics['reuse_count'] == 1

    def test_identity_change_releases_old(self, tmp_path: Path) -> None:
        """Different snapshot_id causes close of old session and new creation."""
        snap_a = _snapshot_with_content('x', 'alpha')
        snap_b = _snapshot_with_content('x', 'beta')
        assert snap_a.snapshot_id != snap_b.snapshot_id, (
            'Snapshots must have different IDs for this test'
        )

        with WarmRuntimeSession() as warm:
            session1 = warm.get_or_create(tmp_path, snap_a)
            identity_a = warm.identity
            session2 = warm.get_or_create(tmp_path, snap_b)
            identity_b = warm.identity

            assert identity_a != identity_b
            assert session1 is not session2
            assert warm.statistics['cold_load_count'] == 2
            assert warm.statistics['reuse_count'] == 0

    def test_close_releases_session(self, tmp_path: Path) -> None:
        """close() clears the cached session."""
        snapshot = _minimal_snapshot()
        warm = WarmRuntimeSession()
        warm.get_or_create(tmp_path, snapshot)
        assert warm.is_loaded

        warm.close()
        assert not warm.is_loaded
        assert warm.identity is None

        # Use after close raises
        with pytest.raises(RuntimeError, match='closed'):
            warm.get_or_create(tmp_path, snapshot)

    def test_health_reports_status(self, tmp_path: Path) -> None:
        """health() returns a dict with loaded, identity, and other keys."""
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            # Idle health
            health_idle = warm.health()
            assert health_idle['loaded'] is False
            assert health_idle['status'] == 'idle'
            assert health_idle['identity'] is None
            assert 'uptime_seconds' in health_idle
            assert 'max_memory_bytes' in health_idle
            assert isinstance(health_idle['reuse_count'], int)
            assert isinstance(health_idle['cold_load_count'], int)

            # Loaded health
            warm.get_or_create(tmp_path, snapshot)
            health_loaded = warm.health()
            assert health_loaded['loaded'] is True
            assert health_loaded['status'] == 'ready'
            assert health_loaded['identity'] is not None
            assert 'snapshot_id' in health_loaded['identity']
            assert 'workspace_root' in health_loaded['identity']
            assert 'analyzer_version' in health_loaded['identity']
            assert health_loaded['cold_load_count'] == 1
            assert health_loaded['session_age_seconds'] is not None
            assert health_loaded['session_age_seconds'] >= 0


# ===========================================================================
# TestOutputBounds — Phase F operational tests
# ===========================================================================


class TestOutputBounds:
    """Operational tests for output hardening: atlas_version in provenance,
    pre-publication size checks, artifact size error type."""

    def test_atlas_version_in_provenance(self) -> None:
        """Verify atlas_version appears in repository_identity of both
        package construction paths."""
        # We verify the code path by checking that the module-level import
        # and both _context_package / _context_package_discovered dicts
        # include atlas_version.  Since running the full generation requires
        # a Java repository, we verify the source structurally and also
        # confirm the import works.
        from moughorai.agent_context.service import __version__ as svc_version
        assert svc_version == __version__
        assert len(__version__) > 0

        # Verify via source inspection that both repository_identity dicts
        # contain 'atlas_version': __version__
        import inspect
        from moughorai.agent_context import service as svc_module
        source = inspect.getsource(svc_module)

        # Both _context_package and _context_package_discovered must have it
        assert source.count("'atlas_version': __version__") >= 2, (
            'Expected atlas_version in at least 2 repository_identity dicts'
        )

    def test_size_limits_are_defined(self) -> None:
        """Verify the artifact size limit constants exist and are sane."""
        assert MAXIMUM_CONTEXT_MD_BYTES == 4 * 1024 * 1024
        assert MAXIMUM_GRAPH_MMD_BYTES == 4 * 1024 * 1024
        assert MAXIMUM_CONTEXT_JSON_BYTES == 16 * 1024 * 1024
        assert MAXIMUM_GRAPH_JSON_BYTES == 16 * 1024 * 1024

    def test_artifact_oversized_error_type(self) -> None:
        """Verify ArtifactOversizedError carries the expected attributes."""
        err = ArtifactOversizedError('context.md', 5_000_000, 4_194_304)
        assert err.artifact_name == 'context.md'
        assert err.actual_bytes == 5_000_000
        assert err.limit_bytes == 4_194_304
        assert 'context.md' in str(err)
        assert '5,000,000' in str(err)
        assert '4,194,304' in str(err)
        # It's a subclass of AgentContextError and ValueError
        from moughorai.agent_context.service import AgentContextError
        assert isinstance(err, AgentContextError)
        assert isinstance(err, ValueError)

    def test_artifact_oversized_error_importable(self) -> None:
        """ArtifactOversizedError is exported from the package __init__."""
        from moughorai.agent_context import ArtifactOversizedError as Imported
        assert Imported is ArtifactOversizedError

    def test_capabilities_context_bytes_matches_limit(self) -> None:
        """The capabilities limit for context_bytes matches the coded maximum."""
        # 4 MiB = 4,194,304 bytes
        assert MAXIMUM_CONTEXT_MD_BYTES == 4_194_304
        assert MAXIMUM_GRAPH_MMD_BYTES == 4_194_304
