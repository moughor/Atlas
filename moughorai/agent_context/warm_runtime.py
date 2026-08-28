'''Bounded warm local runtime that caches a loaded RepositoryRuntimeSession.

Provides in-process reuse of an already-validated repository runtime across
multiple requests without reloading snapshots. This is the minimal foundation
for a warm local service; the full stdio worker protocol can be layered on top.

Key properties:
- Strict local-only (no network, no sockets, no IPC)
- One runtime at a time (bounded memory)
- Cache keyed by (workspace_root, snapshot_id, analyzer_version) — never
  branch name, mtime, or other volatile state
- Deterministic release of previous runtime when identity changes
- Cold and warm paths produce byte-identical semantic output
'''

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from moughorai.measurement import MeasurementSession
from moughorai.repository_runtime import (
    RepositoryIntelligenceRuntime,
    RepositoryRuntimeIdentity,
    RepositoryRuntimeSession,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

_logger = logging.getLogger(__name__)

# Default memory budget: 5 GiB.  The warm runtime refuses to create a new
# session when the process resident set already exceeds this limit.
_DEFAULT_MAX_MEMORY_BYTES: int = 5 * 1024 ** 3

# Identity tuple: (workspace_root_posix, snapshot_id, analyzer_version).
WarmIdentity = tuple[str, str, str]


def _process_rss_bytes() -> int | None:
    '''Return the process resident set size in bytes, or None if unavailable.'''
    try:
        # Linux /proc/self/statm: pages; page size via os.sysconf.
        with open('/proc/self/statm', encoding='ascii') as fh:
            parts = fh.read().split()
        if len(parts) >= 2:
            pages = int(parts[1])
            page_size = os.sysconf('SC_PAGE_SIZE')
            return pages * page_size
    except (OSError, ValueError, AttributeError):
        pass
    try:
        import resource  # noqa: PLC0415 — optional, Unix only
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is in KiB on Linux, bytes on macOS.
        if hasattr(usage, 'ru_maxrss'):
            import sys
            if sys.platform == 'darwin':
                return usage.ru_maxrss
            return usage.ru_maxrss * 1024
    except (ImportError, AttributeError, ValueError):
        pass
    return None


@dataclass(frozen=True, slots=True)
class WarmRuntimeHealth:
    '''Snapshot of warm runtime health state.'''

    loaded: bool
    identity: WarmIdentity | None
    uptime_seconds: float
    session_age_seconds: float | None
    reuse_count: int
    cold_load_count: int
    process_rss_bytes: int | None
    max_memory_bytes: int
    memory_pressure: bool


class WarmRuntimeSession:
    '''Bounded warm runtime that caches a loaded RepositoryRuntimeSession.

    Keyed by exact (workspace_root, snapshot_id, analyzer_version).
    When identity changes, the previous runtime is released.
    Bounded to one runtime at a time.
    '''

    def __init__(
        self,
        *,
        max_memory_bytes: int = _DEFAULT_MAX_MEMORY_BYTES,
        measurement: MeasurementSession | None = None,
    ) -> None:
        if max_memory_bytes <= 0:
            raise ValueError('max_memory_bytes must be positive')
        self._max_memory = max_memory_bytes
        self._measurement = measurement or MeasurementSession()
        self._lock = RLock()
        self._session: RepositoryRuntimeSession | None = None
        self._identity: WarmIdentity | None = None
        self._workspace_root: Path | None = None
        self._closed = False
        self._reuse_count = 0
        self._cold_load_count = 0
        self._session_created_at: float | None = None
        self._created_at = time.monotonic()

    @staticmethod
    def _make_identity(
        workspace_root: Path,
        snapshot: AtlasSemanticSnapshot,
    ) -> WarmIdentity:
        '''Build an identity key from immutable snapshot lineage.'''
        root_posix = workspace_root.expanduser().resolve().as_posix()
        return (root_posix, snapshot.snapshot_id, snapshot.analyzer_version)

    def _check_memory_pressure(self) -> bool:
        '''Return True if the process exceeds the memory budget.'''
        rss = _process_rss_bytes()
        if rss is None:
            return False
        return rss > self._max_memory

    def get_or_create(
        self,
        workspace_root: Path,
        snapshot: AtlasSemanticSnapshot,
    ) -> RepositoryRuntimeSession:
        '''Get a cached session or create a new one.

        If the identity matches, returns the cached session (warm path).
        If it doesn't match, closes the old session and creates a new one
        (cold path).

        Both paths produce byte-identical semantic output for the same
        snapshot — the warm path just avoids re-materializing services.

        Raises RuntimeError if closed or under memory pressure.
        '''
        if not isinstance(workspace_root, Path):
            raise TypeError('workspace_root must be a Path')
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError('snapshot must be an AtlasSemanticSnapshot')

        identity = self._make_identity(workspace_root, snapshot)

        with self._lock:
            if self._closed:
                raise RuntimeError('warm runtime session is closed')

            # Warm hit: identity matches the cached session.
            if (
                self._session is not None
                and self._identity == identity
            ):
                # Validate lineage still matches (defensive, same as
                # RepositoryRuntimeSession.runtime_for).
                self._session.runtime_for(snapshot)
                self._reuse_count += 1
                _logger.debug(
                    'warm runtime reuse #%d for %s',
                    self._reuse_count,
                    identity[1][:12],
                )
                return self._session

            # Cold path: identity changed or first load.
            if self._check_memory_pressure():
                raise RuntimeError(
                    f'warm runtime refuses new session: process RSS exceeds '
                    f'{self._max_memory} bytes budget'
                )

            # Release the previous runtime.
            self._release_locked()

            _logger.info(
                'warm runtime cold load for snapshot %s (workspace=%s)',
                identity[1][:12],
                identity[0],
            )

            session = RepositoryRuntimeSession(
                workspace_root=workspace_root,
                measurement=self._measurement,
            )
            # Eagerly validate the snapshot can be loaded.
            session.runtime_for(snapshot)

            self._session = session
            self._identity = identity
            self._workspace_root = workspace_root
            self._cold_load_count += 1
            self._session_created_at = time.monotonic()
            return session

    def runtime_for(
        self,
        workspace_root: Path,
        snapshot: AtlasSemanticSnapshot,
    ) -> RepositoryIntelligenceRuntime:
        '''Convenience: get the cached session and return its runtime directly.'''
        session = self.get_or_create(workspace_root, snapshot)
        return session.runtime_for(snapshot)

    def close(self) -> None:
        '''Release the cached runtime and mark this session closed.'''
        with self._lock:
            self._release_locked()
            self._closed = True

    def _release_locked(self) -> None:
        '''Release the current session without changing closed state.

        Caller must hold self._lock.
        '''
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                _logger.exception('error closing cached runtime session')
            self._session = None
            self._identity = None
            self._workspace_root = None
            self._session_created_at = None

    def health(self) -> dict[str, Any]:
        '''Return health/readiness status as a JSON-serialisable dict.'''
        with self._lock:
            now = time.monotonic()
            rss = _process_rss_bytes()
            loaded = self._session is not None
            session_age = (
                now - self._session_created_at
                if self._session_created_at is not None
                else None
            )
            stats = (
                self._session.statistics
                if self._session is not None
                else None
            )
            return {
                'status': 'ready' if loaded else 'idle',
                'loaded': loaded,
                'identity': {
                    'workspace_root': self._identity[0],
                    'snapshot_id': self._identity[1],
                    'analyzer_version': self._identity[2],
                } if self._identity is not None else None,
                'uptime_seconds': round(now - self._created_at, 3),
                'session_age_seconds': (
                    round(session_age, 3) if session_age is not None else None
                ),
                'reuse_count': self._reuse_count,
                'cold_load_count': self._cold_load_count,
                'process_rss_bytes': rss,
                'max_memory_bytes': self._max_memory,
                'memory_pressure': rss is not None and rss > self._max_memory,
                'runtime_statistics': {
                    'runtime_build_count': stats.runtime_build_count,
                    'reuse_count': stats.reuse_count,
                    'component_build_counts': dict(stats.component_build_counts),
                } if stats is not None else None,
            }

    @property
    def is_loaded(self) -> bool:
        '''Whether a runtime is currently cached.'''
        with self._lock:
            return self._session is not None

    @property
    def identity(self) -> WarmIdentity | None:
        '''The identity of the currently cached runtime, or None.'''
        with self._lock:
            return self._identity

    @property
    def statistics(self) -> dict[str, int]:
        '''Return reuse/cold-load counters.'''
        with self._lock:
            return {
                'reuse_count': self._reuse_count,
                'cold_load_count': self._cold_load_count,
            }

    def __enter__(self) -> WarmRuntimeSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        with self._lock:
            state = 'closed' if self._closed else ('loaded' if self._session else 'idle')
            sid = self._identity[1][:12] if self._identity else 'none'
            return f'<WarmRuntimeSession state={state} snapshot={sid}>'
