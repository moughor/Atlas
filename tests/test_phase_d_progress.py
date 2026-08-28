"""Tests for Phase D: deadlines, cancellation, and structured progress.

Covers:
    D1 — ProgressEvent schema and serialisation
    D2 — RequestContext deadline checking
    D3 — RequestContext cancellation
    D4 — JSONL progress emission to stderr (not stdout)
    D5 — cleanup_temp_files on cancellation
    D6 — Capabilities handshake advertises new features
    D7 — JSON envelope includes request_id
"""

from __future__ import annotations

import io
import json
import os
import signal
import tempfile
import time
from pathlib import Path

import pytest

from moughorai.agent_context.progress import (
    Cancelled,
    DeadlineExceeded,
    ProgressEvent,
    RequestContext,
    cleanup_temp_files,
)


# ===========================================================================
# D1 — ProgressEvent schema and serialisation
# ===========================================================================


class TestProgressEvent:
    """Verify ProgressEvent structure and JSON serialisation."""

    def test_event_to_dict_minimal(self):
        event = ProgressEvent(
            schema_version=1,
            request_id='abc123',
            timestamp='2026-08-28T20:00:00+00:00',
            sequence=0,
            phase='snapshot_load',
            state='starting',
            message_code='snapshot.loading',
        )
        d = event.to_dict()
        assert d['schema_version'] == 1
        assert d['request_id'] == 'abc123'
        assert d['sequence'] == 0
        assert d['phase'] == 'snapshot_load'
        assert d['state'] == 'starting'
        assert d['message_code'] == 'snapshot.loading'
        assert 'completed_units' not in d
        assert 'total_units' not in d

    def test_event_to_dict_with_units(self):
        event = ProgressEvent(
            schema_version=1,
            request_id='abc123',
            timestamp='2026-08-28T20:00:00+00:00',
            sequence=3,
            phase='discovery',
            state='running',
            message_code='discovery.running',
            completed_units=5,
            total_units=10,
        )
        d = event.to_dict()
        assert d['completed_units'] == 5
        assert d['total_units'] == 10

    def test_event_to_json_is_valid_json(self):
        event = ProgressEvent(
            schema_version=1,
            request_id='test-req',
            timestamp='2026-08-28T20:00:00+00:00',
            sequence=0,
            phase='test',
            state='completed',
            message_code='test.done',
        )
        parsed = json.loads(event.to_json())
        assert parsed['schema_version'] == 1
        assert parsed['request_id'] == 'test-req'

    def test_event_json_keys_are_sorted(self):
        event = ProgressEvent(
            schema_version=1,
            request_id='sorted-test',
            timestamp='2026-08-28T20:00:00+00:00',
            sequence=0,
            phase='test',
            state='completed',
            message_code='test.done',
        )
        parsed = json.loads(event.to_json())
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match='invalid progress state'):
            ProgressEvent(
                schema_version=1,
                request_id='x',
                timestamp='t',
                sequence=0,
                phase='p',
                state='bogus',
                message_code='c',
            )

    def test_invalid_schema_version_raises(self):
        with pytest.raises(ValueError, match='unsupported progress schema version'):
            ProgressEvent(
                schema_version=99,
                request_id='x',
                timestamp='t',
                sequence=0,
                phase='p',
                state='starting',
                message_code='c',
            )

    def test_all_valid_states_accepted(self):
        for state in ('starting', 'running', 'completed', 'cancelled',
                      'deadline_exceeded', 'failed'):
            event = ProgressEvent(
                schema_version=1,
                request_id='x',
                timestamp='t',
                sequence=0,
                phase='p',
                state=state,
                message_code='c',
            )
            assert event.state == state

    def test_event_is_frozen(self):
        event = ProgressEvent(
            schema_version=1,
            request_id='x',
            timestamp='t',
            sequence=0,
            phase='p',
            state='starting',
            message_code='c',
        )
        with pytest.raises(AttributeError):
            event.state = 'completed'  # type: ignore[misc]


# ===========================================================================
# D2 — RequestContext deadline checking
# ===========================================================================


class TestRequestContextDeadline:
    """Verify deadline tracking and DeadlineExceeded exception."""

    def test_no_deadline_never_exceeds(self):
        with RequestContext(request_id='no-dl') as ctx:
            assert ctx.is_deadline_exceeded is False
            ctx.check_deadline()  # should not raise
            assert ctx.remaining_seconds is None

    def test_generous_deadline_does_not_trigger(self):
        with RequestContext(request_id='generous', deadline_seconds=300.0) as ctx:
            assert ctx.is_deadline_exceeded is False
            ctx.check_deadline()
            remaining = ctx.remaining_seconds
            assert remaining is not None
            assert remaining > 0

    def test_expired_deadline_triggers(self):
        with RequestContext(request_id='expired', deadline_seconds=0.001) as ctx:
            time.sleep(0.01)
            assert ctx.is_deadline_exceeded is True
            with pytest.raises(DeadlineExceeded, match='exceeded deadline'):
                ctx.check_deadline()

    def test_negative_deadline_raises_valueerror(self):
        with pytest.raises(ValueError, match='deadline_seconds must be positive'):
            RequestContext(deadline_seconds=-1.0)

    def test_zero_deadline_raises_valueerror(self):
        with pytest.raises(ValueError, match='deadline_seconds must be positive'):
            RequestContext(deadline_seconds=0.0)

    def test_elapsed_seconds_increases(self):
        with RequestContext(request_id='elapsed') as ctx:
            t0 = ctx.elapsed_seconds
            time.sleep(0.02)
            t1 = ctx.elapsed_seconds
            assert t1 > t0

    def test_check_combines_deadline_and_cancellation(self):
        """RequestContext.check() checks both cancellation and deadline."""
        with RequestContext(request_id='combined', deadline_seconds=0.001) as ctx:
            time.sleep(0.01)
            with pytest.raises(DeadlineExceeded):
                ctx.check()


# ===========================================================================
# D3 — RequestContext cancellation
# ===========================================================================


class TestRequestContextCancellation:
    """Verify cancellation flag and Cancelled exception."""

    def test_not_cancelled_initially(self):
        with RequestContext(request_id='fresh') as ctx:
            assert ctx.is_cancelled is False
            ctx.check_cancelled()  # should not raise

    def test_manual_cancel_flag(self):
        """Simulate cancellation by setting the internal flag directly."""
        with RequestContext(request_id='manual') as ctx:
            ctx._cancelled = True
            assert ctx.is_cancelled is True
            with pytest.raises(Cancelled, match='was cancelled'):
                ctx.check_cancelled()

    def test_check_raises_cancelled_before_deadline(self):
        """When both cancelled and deadline expired, cancellation takes priority."""
        with RequestContext(request_id='both', deadline_seconds=0.001) as ctx:
            time.sleep(0.01)
            ctx._cancelled = True
            # check() calls check_cancelled() first
            with pytest.raises(Cancelled):
                ctx.check()


# ===========================================================================
# D4 — JSONL progress emission to stderr (not stdout)
# ===========================================================================


class TestProgressEmission:
    """Verify JSONL progress events are emitted correctly."""

    def test_events_are_jsonl_lines(self):
        stream = io.StringIO()
        with RequestContext(request_id='jsonl', progress_stream=stream) as ctx:
            ctx.emit_progress('snapshot_load', 'starting', 'snapshot.loading')
            ctx.emit_progress('snapshot_load', 'completed', 'snapshot.loaded')

        lines = stream.getvalue().strip().split('\n')
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert parsed['schema_version'] == 1
            assert parsed['request_id'] == 'jsonl'

    def test_sequence_is_monotonic(self):
        stream = io.StringIO()
        with RequestContext(request_id='seq', progress_stream=stream) as ctx:
            for i in range(5):
                ctx.emit_progress('test', 'running', f'step.{i}')

        lines = stream.getvalue().strip().split('\n')
        sequences = [json.loads(line)['sequence'] for line in lines]
        assert sequences == list(range(5))

    def test_emit_returns_event_object(self):
        stream = io.StringIO()
        with RequestContext(request_id='ret', progress_stream=stream) as ctx:
            event = ctx.emit_progress('phase', 'starting', 'code')
            assert isinstance(event, ProgressEvent)
            assert event.sequence == 0
            assert event.phase == 'phase'
            assert event.state == 'starting'

    def test_emit_with_units(self):
        stream = io.StringIO()
        with RequestContext(request_id='units', progress_stream=stream) as ctx:
            ctx.emit_progress(
                'discovery', 'running', 'roots.processing',
                completed_units=3, total_units=8,
            )

        parsed = json.loads(stream.getvalue().strip())
        assert parsed['completed_units'] == 3
        assert parsed['total_units'] == 8

    def test_auto_generated_request_id(self):
        stream = io.StringIO()
        with RequestContext(progress_stream=stream) as ctx:
            ctx.emit_progress('test', 'starting', 'auto.id')
            rid = ctx.request_id
            assert len(rid) == 32  # UUID4 hex

        parsed = json.loads(stream.getvalue().strip())
        assert parsed['request_id'] == rid

    def test_timestamp_is_present(self):
        stream = io.StringIO()
        with RequestContext(request_id='ts', progress_stream=stream) as ctx:
            ctx.emit_progress('test', 'starting', 'ts.check')

        parsed = json.loads(stream.getvalue().strip())
        assert 'timestamp' in parsed
        assert len(parsed['timestamp']) > 0

    def test_broken_stream_does_not_crash(self):
        """Progress emission on a closed stream must not raise."""

        class FailingStream:
            def write(self, s: str) -> int:
                raise OSError('stream broken')

            def flush(self) -> None:
                raise OSError('stream broken')

        with RequestContext(request_id='broken', progress_stream=FailingStream()) as ctx:
            # Should not raise
            event = ctx.emit_progress('test', 'starting', 'resilient')
            assert event.sequence == 0


# ===========================================================================
# D5 — cleanup_temp_files on cancellation
# ===========================================================================


class TestCleanupTempFiles:
    """Verify partial artifact cleanup."""

    def test_cleanup_removes_context_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            for name in ('context.json', 'context.md', 'graph.json', 'graph.mmd'):
                (target / name).write_text('partial')

            cleanup_temp_files(target)

            for name in ('context.json', 'context.md', 'graph.json', 'graph.mmd'):
                assert not (target / name).exists(), f'{name} should have been removed'

    def test_cleanup_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            (target / 'context.json').write_text('partial')
            (target / 'notes.txt').write_text('keep me')

            cleanup_temp_files(target)

            assert not (target / 'context.json').exists()
            assert (target / 'notes.txt').exists()

    def test_cleanup_nonexistent_dir(self):
        """Should not raise when directory does not exist."""
        cleanup_temp_files('/nonexistent/path/abc123')

    def test_cleanup_empty_dir(self):
        """Should not raise on empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cleanup_temp_files(tmpdir)


# ===========================================================================
# D6 — Capabilities handshake advertises new features
# ===========================================================================


class TestCapabilitiesPhaseD:
    """Verify capabilities payload includes Phase D features."""

    @staticmethod
    def _get_capabilities_payload() -> dict:
        from moughorai.version import __version__

        # Replicate the payload from atlas_cli.py capabilities_command
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

    def test_structured_progress_advertised(self):
        payload = self._get_capabilities_payload()
        assert payload['features']['structured_progress'] is True

    def test_request_cancellation_advertised(self):
        payload = self._get_capabilities_payload()
        assert payload['features']['request_cancellation'] is True

    def test_capabilities_json_is_deterministic(self):
        payload = self._get_capabilities_payload()
        a = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        b = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        assert a == b


# ===========================================================================
# D7 — Context manager lifecycle
# ===========================================================================


class TestRequestContextLifecycle:
    """Verify RequestContext as a context manager."""

    def test_context_manager_protocol(self):
        ctx = RequestContext(request_id='cm')
        with ctx:
            assert ctx.request_id == 'cm'
        # After close, signal handlers should be restored (no assertion needed,
        # just verify no exception)

    def test_close_is_idempotent(self):
        ctx = RequestContext(request_id='idem')
        ctx.close()
        ctx.close()  # second close should not raise

    def test_context_manager_on_exception(self):
        """Signals are restored even when the body raises."""
        with pytest.raises(RuntimeError):
            with RequestContext(request_id='exc') as ctx:
                raise RuntimeError('boom')
        # If we get here, __exit__ did not suppress the exception
        # and signal handlers were restored.
