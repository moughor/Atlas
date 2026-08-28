'''Tests for the bounded warm local runtime (Phase E).'''

from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.agent_context.warm_runtime import (
    WarmRuntimeSession,
    _process_rss_bytes,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.measurement import MeasurementSession
from moughorai.repository_runtime import (
    RepositoryIntelligenceRuntime,
    RepositoryRuntimeSession,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_snapshot(
    *,
    workspace_fingerprint: str = 'test-fp',
    analyzer_version: str = 'warm-test/1',
) -> AtlasSemanticSnapshot:
    '''Create a minimal valid snapshot for warm runtime testing.'''
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
    analyzer_version: str = 'warm-test/1',
) -> AtlasSemanticSnapshot:
    '''Create a snapshot with distinct content to produce different IDs.'''
    context = WorkspaceSemanticContext({key: value})
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint=workspace_fingerprint,
        analyzer_version=analyzer_version,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestWarmRuntimeConstruction:

    def test_default_construction(self) -> None:
        warm = WarmRuntimeSession()
        assert not warm.is_loaded
        assert warm.identity is None
        assert warm.statistics == {'reuse_count': 0, 'cold_load_count': 0}
        warm.close()

    def test_custom_memory_limit(self) -> None:
        warm = WarmRuntimeSession(max_memory_bytes=1024)
        warm.close()

    def test_invalid_memory_limit_zero(self) -> None:
        with pytest.raises(ValueError, match='positive'):
            WarmRuntimeSession(max_memory_bytes=0)

    def test_invalid_memory_limit_negative(self) -> None:
        with pytest.raises(ValueError, match='positive'):
            WarmRuntimeSession(max_memory_bytes=-1)


# ---------------------------------------------------------------------------
# Cold load
# ---------------------------------------------------------------------------

class TestColdLoad:

    def test_first_load_creates_session(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            session = warm.get_or_create(tmp_path, snapshot)
            assert isinstance(session, RepositoryRuntimeSession)
            assert warm.is_loaded
            assert warm.statistics['cold_load_count'] == 1
            assert warm.statistics['reuse_count'] == 0

    def test_identity_set_after_load(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snapshot)
            identity = warm.identity
            assert identity is not None
            root_posix = tmp_path.expanduser().resolve().as_posix()
            assert identity == (
                root_posix,
                snapshot.snapshot_id,
                snapshot.analyzer_version,
            )


# ---------------------------------------------------------------------------
# Warm reuse
# ---------------------------------------------------------------------------

class TestWarmReuse:

    def test_same_identity_reuses_session(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            first = warm.get_or_create(tmp_path, snapshot)
            second = warm.get_or_create(tmp_path, snapshot)
            assert first is second
            assert warm.statistics['cold_load_count'] == 1
            assert warm.statistics['reuse_count'] == 1

    def test_multiple_reuses_increment_counter(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snapshot)
            for _ in range(5):
                warm.get_or_create(tmp_path, snapshot)
            assert warm.statistics['reuse_count'] == 5
            assert warm.statistics['cold_load_count'] == 1


# ---------------------------------------------------------------------------
# Identity change releases previous runtime
# ---------------------------------------------------------------------------

class TestIdentityChange:

    def test_different_snapshot_replaces_session(self, tmp_path: Path) -> None:
        snap_a = _minimal_snapshot(workspace_fingerprint='fp-a')
        snap_b = _minimal_snapshot(workspace_fingerprint='fp-b')
        assert snap_a.snapshot_id != snap_b.snapshot_id

        with WarmRuntimeSession() as warm:
            first = warm.get_or_create(tmp_path, snap_a)
            second = warm.get_or_create(tmp_path, snap_b)
            assert first is not second
            assert warm.statistics['cold_load_count'] == 2
            assert warm.statistics['reuse_count'] == 0
            # Identity should reflect the new snapshot.
            assert warm.identity[1] == snap_b.snapshot_id

    def test_different_workspace_replaces_session(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        root_a = tmp_path / 'repo-a'
        root_b = tmp_path / 'repo-b'
        root_a.mkdir()
        root_b.mkdir()

        with WarmRuntimeSession() as warm:
            warm.get_or_create(root_a, snapshot)
            warm.get_or_create(root_b, snapshot)
            assert warm.statistics['cold_load_count'] == 2
            assert warm.identity[0] == root_b.resolve().as_posix()

    def test_different_analyzer_version_replaces_session(self, tmp_path: Path) -> None:
        snap_a = _minimal_snapshot(analyzer_version='v1')
        snap_b = _minimal_snapshot(analyzer_version='v2')

        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snap_a)
            warm.get_or_create(tmp_path, snap_b)
            assert warm.statistics['cold_load_count'] == 2


# ---------------------------------------------------------------------------
# runtime_for convenience
# ---------------------------------------------------------------------------

class TestRuntimeForConvenience:

    def test_runtime_for_returns_intelligence_runtime(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            runtime = warm.runtime_for(tmp_path, snapshot)
            assert isinstance(runtime, RepositoryIntelligenceRuntime)
            assert runtime.identity.snapshot_id == snapshot.snapshot_id


# ---------------------------------------------------------------------------
# Close / lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:

    def test_close_releases_session(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        warm = WarmRuntimeSession()
        warm.get_or_create(tmp_path, snapshot)
        assert warm.is_loaded
        warm.close()
        assert not warm.is_loaded
        assert warm.identity is None

    def test_use_after_close_raises(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        warm = WarmRuntimeSession()
        warm.close()
        with pytest.raises(RuntimeError, match='closed'):
            warm.get_or_create(tmp_path, snapshot)

    def test_context_manager_closes(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snapshot)
        assert not warm.is_loaded

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        warm = WarmRuntimeSession()
        warm.get_or_create(tmp_path, snapshot)
        warm.close()
        warm.close()  # Should not raise.


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_idle(self) -> None:
        with WarmRuntimeSession() as warm:
            h = warm.health()
            assert h['status'] == 'idle'
            assert h['loaded'] is False
            assert h['identity'] is None
            assert h['reuse_count'] == 0
            assert h['cold_load_count'] == 0
            assert isinstance(h['uptime_seconds'], float)
            assert h['session_age_seconds'] is None
            assert h['runtime_statistics'] is None
            assert isinstance(h['max_memory_bytes'], int)

    def test_health_loaded(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snapshot)
            h = warm.health()
            assert h['status'] == 'ready'
            assert h['loaded'] is True
            assert h['identity'] is not None
            assert h['identity']['snapshot_id'] == snapshot.snapshot_id
            assert h['identity']['analyzer_version'] == snapshot.analyzer_version
            assert h['cold_load_count'] == 1
            assert isinstance(h['session_age_seconds'], float)
            assert h['session_age_seconds'] >= 0.0
            assert h['runtime_statistics'] is not None
            assert isinstance(h['runtime_statistics']['runtime_build_count'], int)


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------

class TestTypeValidation:

    def test_rejects_non_path_workspace(self) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            with pytest.raises(TypeError, match='Path'):
                warm.get_or_create('/tmp/not-a-path', snapshot)  # type: ignore[arg-type]

    def test_rejects_non_snapshot(self, tmp_path: Path) -> None:
        with WarmRuntimeSession() as warm:
            with pytest.raises(TypeError, match='AtlasSemanticSnapshot'):
                warm.get_or_create(tmp_path, {'fake': 'snapshot'})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cold and warm paths produce identical output
# ---------------------------------------------------------------------------

class TestDeterministicOutput:

    def test_cold_and_warm_produce_identical_runtime(self, tmp_path: Path) -> None:
        '''The critical invariant: both paths must yield the same results.'''
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            # Cold path
            session_cold = warm.get_or_create(tmp_path, snapshot)
            runtime_cold = session_cold.runtime_for(snapshot)
            cold_identity = runtime_cold.identity

            # Warm path (same session object returned)
            session_warm = warm.get_or_create(tmp_path, snapshot)
            runtime_warm = session_warm.runtime_for(snapshot)
            warm_identity = runtime_warm.identity

            assert cold_identity == warm_identity
            assert runtime_cold is runtime_warm


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

class TestRepr:

    def test_repr_idle(self) -> None:
        warm = WarmRuntimeSession()
        r = repr(warm)
        assert 'idle' in r
        warm.close()

    def test_repr_loaded(self, tmp_path: Path) -> None:
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession() as warm:
            warm.get_or_create(tmp_path, snapshot)
            r = repr(warm)
            assert 'loaded' in r
            assert snapshot.snapshot_id[:12] in r

    def test_repr_closed(self) -> None:
        warm = WarmRuntimeSession()
        warm.close()
        r = repr(warm)
        assert 'closed' in r


# ---------------------------------------------------------------------------
# Measurement session propagation
# ---------------------------------------------------------------------------

class TestMeasurementPropagation:

    def test_measurement_session_propagated_to_runtime(self, tmp_path: Path) -> None:
        measurement = MeasurementSession()
        snapshot = _minimal_snapshot()
        with WarmRuntimeSession(measurement=measurement) as warm:
            session = warm.get_or_create(tmp_path, snapshot)
            assert session.measurement is measurement


# ---------------------------------------------------------------------------
# Memory utility
# ---------------------------------------------------------------------------

class TestProcessRss:

    def test_rss_returns_int_or_none(self) -> None:
        result = _process_rss_bytes()
        # On Linux CI this should be an int; elsewhere may be None.
        assert result is None or isinstance(result, int)
        if result is not None:
            assert result > 0
