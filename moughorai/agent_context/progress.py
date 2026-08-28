"""Deadlines, cooperative cancellation, and structured JSONL progress events.

Progress events are emitted to stderr as newline-delimited JSON and never
affect semantic artifacts or stdout output.  A ``RequestContext`` tracks
deadline expiry, SIGINT/SIGTERM cancellation, and monotonically increasing
progress sequences for a single ``atlas agent context`` invocation.

Schema version 1 event fields::

    schema_version  int       always 1
    request_id      str       caller-supplied or auto-generated UUID4
    timestamp       str       ISO-8601 UTC
    sequence        int       0-based monotonic counter
    phase           str       semantic phase name
    state           str       starting | running | completed | cancelled
                              | deadline_exceeded | failed
    message_code    str       machine-readable code (e.g. "snapshot.loading")
    completed_units int|null  optional progress numerator
    total_units     int|null  optional progress denominator
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, Any


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class DeadlineExceeded(Exception):
    """Raised when the request deadline has elapsed."""


class Cancelled(Exception):
    """Raised when cooperative cancellation is triggered (SIGINT/SIGTERM)."""


# ---------------------------------------------------------------------------
# Progress event
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """A single JSONL progress event emitted to stderr."""

    schema_version: int
    request_id: str
    timestamp: str
    sequence: int
    phase: str
    state: str
    message_code: str
    completed_units: int | None = None
    total_units: int | None = None

    _VALID_STATES = frozenset({
        'starting', 'running', 'completed',
        'cancelled', 'deadline_exceeded', 'failed',
    })

    def __post_init__(self) -> None:
        if self.state not in self._VALID_STATES:
            raise ValueError(f'invalid progress state: {self.state!r}')
        if self.schema_version != 1:
            raise ValueError(f'unsupported progress schema version: {self.schema_version}')

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            'schema_version': self.schema_version,
            'request_id': self.request_id,
            'timestamp': self.timestamp,
            'sequence': self.sequence,
            'phase': self.phase,
            'state': self.state,
            'message_code': self.message_code,
        }
        if self.completed_units is not None:
            d['completed_units'] = self.completed_units
        if self.total_units is not None:
            d['total_units'] = self.total_units
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------

class RequestContext:
    """Track deadline, cancellation, and progress for one request.

    The context installs signal handlers for SIGINT and SIGTERM on creation
    (main thread only) and restores the previous handlers on ``close()``.
    Progress events are written as JSONL lines to *progress_stream* (defaults
    to ``sys.stderr``).

    The context is safe to create even from non-main threads — signal
    handling is silently skipped in that case.
    """

    def __init__(
        self,
        request_id: str | None = None,
        deadline_seconds: float | None = None,
        progress_stream: IO[str] | None = None,
    ) -> None:
        self._request_id = request_id or uuid.uuid4().hex
        self._progress_stream = progress_stream or sys.stderr
        self._sequence = 0
        self._lock = threading.Lock()

        # Deadline tracking
        self._start_time = time.monotonic()
        self._deadline: float | None = None
        if deadline_seconds is not None:
            if deadline_seconds <= 0:
                raise ValueError('deadline_seconds must be positive')
            self._deadline = self._start_time + deadline_seconds

        # Cancellation tracking
        self._cancelled = False
        self._prev_sigint: signal.Handlers | None = None
        self._prev_sigterm: signal.Handlers | None = None
        self._signals_installed = False
        self._install_signal_handlers()

    # -- Properties ---------------------------------------------------------

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_deadline_exceeded(self) -> bool:
        if self._deadline is None:
            return False
        return time.monotonic() >= self._deadline

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def remaining_seconds(self) -> float | None:
        """Seconds until deadline, or None if no deadline is set."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    # -- Cooperative checks -------------------------------------------------

    def check_deadline(self) -> None:
        """Raise ``DeadlineExceeded`` if the deadline has elapsed."""
        if self.is_deadline_exceeded:
            raise DeadlineExceeded(
                f'request {self._request_id} exceeded deadline after '
                f'{self.elapsed_seconds:.1f}s'
            )

    def check_cancelled(self) -> None:
        """Raise ``Cancelled`` if SIGINT or SIGTERM was received."""
        if self._cancelled:
            raise Cancelled(f'request {self._request_id} was cancelled')

    def check(self) -> None:
        """Check both cancellation and deadline in one call."""
        self.check_cancelled()
        self.check_deadline()

    # -- Progress emission --------------------------------------------------

    def emit_progress(
        self,
        phase: str,
        state: str,
        message_code: str,
        *,
        completed_units: int | None = None,
        total_units: int | None = None,
    ) -> ProgressEvent:
        """Emit a JSONL progress event to the progress stream.

        Returns the emitted event for test inspection.
        """
        with self._lock:
            seq = self._sequence
            self._sequence += 1

        event = ProgressEvent(
            schema_version=1,
            request_id=self._request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence=seq,
            phase=phase,
            state=state,
            message_code=message_code,
            completed_units=completed_units,
            total_units=total_units,
        )
        line = event.to_json() + '\n'
        try:
            self._progress_stream.write(line)
            self._progress_stream.flush()
        except (OSError, ValueError):
            # Stream closed or broken — never let progress emission kill the
            # semantic pipeline.
            pass
        return event

    # -- Signal handling ----------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers on main thread only."""
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            self._prev_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_signal)
            # SIGTERM may not be available on all platforms (Windows)
            if hasattr(signal, 'SIGTERM'):
                self._prev_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, self._handle_signal)
            self._signals_installed = True
        except (OSError, ValueError):
            # Cannot set signal handler (not main thread or restricted env)
            pass

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Set the cancelled flag on SIGINT/SIGTERM."""
        self._cancelled = True

    def _restore_signal_handlers(self) -> None:
        """Restore previous signal handlers."""
        if not self._signals_installed:
            return
        try:
            if self._prev_sigint is not None:
                signal.signal(signal.SIGINT, self._prev_sigint)
            if hasattr(signal, 'SIGTERM') and self._prev_sigterm is not None:
                signal.signal(signal.SIGTERM, self._prev_sigterm)
        except (OSError, ValueError):
            pass
        self._signals_installed = False

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Restore signal handlers and mark the context inactive."""
        self._restore_signal_handlers()

    def __enter__(self) -> RequestContext:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        self.close()
        return False


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def cleanup_temp_files(output_dir: Any) -> None:
    """Best-effort removal of partial artifacts in the output directory.

    Called on cancellation or deadline so that incomplete files do not
    masquerade as valid context artifacts.
    """
    from pathlib import Path
    target = Path(str(output_dir)).expanduser().resolve()
    if not target.is_dir():
        return
    _OUTPUT_NAMES = frozenset({'context.json', 'context.md', 'graph.json', 'graph.mmd'})
    for name in _OUTPUT_NAMES:
        candidate = target / name
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass
