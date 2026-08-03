from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.measurement import (
    MeasurementConfig,
    MeasurementPhase,
    MeasurementSession,
    MetricReason,
    MetricStatus,
)
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import (
    Project,
    Workspace,
    WorkspaceAnalysisOrchestrator,
    WorkspaceRecoveryManager,
    WorkspaceService,
    WorkspaceStateStore,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _service(tmp_path: Path, measurement: MeasurementSession) -> WorkspaceService:
    for name in ("core", "api"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.py").write_text(name, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n"
        "  - name: api\n    path: api\n    dependencies: [core]\n",
        encoding="utf-8",
    )
    return WorkspaceService(tmp_path, measurement=measurement)


def test_snapshot_measurement_is_source_free_and_semantically_inert(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "app"
    project_root.mkdir()
    (project_root / "main.java").write_text("class Main {}", encoding="utf-8")
    workspace = Workspace(tmp_path, (Project("app", project_root),))
    context = WorkspaceContextBuilder().build(workspace)

    baseline = SemanticSnapshotStore(workspace, clock=lambda: NOW).capture(context)
    session = MeasurementSession(MeasurementConfig(enabled=True))
    store = SemanticSnapshotStore(
        workspace,
        directory=tmp_path / "profiled-snapshots",
        clock=lambda: NOW,
        measurement=session,
    )
    profiled = store.capture(context)
    store.save(profiled)
    loaded = store.load()

    assert loaded == baseline == profiled
    phase_ids = {sample.phase_id for sample in session.report().samples}
    assert {
        MeasurementPhase.SNAPSHOT.value,
        MeasurementPhase.SERIALIZATION.value,
        MeasurementPhase.PUBLICATION.value,
        MeasurementPhase.PERSISTENCE.value,
    }.issubset(phase_ids)
    encoded = session.report().to_json()
    assert str(tmp_path) not in encoded
    assert "class Main" not in encoded

    phase_status = {
        item["phase_id"]: item
        for item in session.report().to_dict()["phase_status"]
    }
    assert phase_status[MeasurementPhase.SNAPSHOT.value]["status"] == "measured"
    assert phase_status[MeasurementPhase.KOTLIN_PARSING.value] == {
        "phase_id": MeasurementPhase.KOTLIN_PARSING.value,
        "status": "unavailable",
        "reason": "not-recorded",
    }
    assert phase_status[MeasurementPhase.EXPLAIN_PROJECTION.value]["status"] == "unavailable"


def test_persistence_and_recovery_use_the_same_run_local_session(
    tmp_path: Path,
) -> None:
    session = MeasurementSession(MeasurementConfig(enabled=True))
    service = _service(tmp_path, session)
    orchestrator = WorkspaceAnalysisOrchestrator(service)
    orchestrator.execute(lambda project, dependencies: project.name)

    state_store = WorkspaceStateStore(service)
    state = state_store.capture(orchestrator._results, orchestrator.planner.valid_projects)
    state_store.save(state)
    assert state_store.load() == state

    recovery = WorkspaceRecoveryManager(service, state_store=state_store)
    report = recovery.execute(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
        force=True,
    )
    assert report.succeeded
    phases = {sample.phase_id for sample in session.report().samples}
    assert MeasurementPhase.PERSISTENCE.value in phases
    assert MeasurementPhase.SERIALIZATION.value in phases
    assert MeasurementPhase.RECOVERY.value in phases


def test_concurrent_worker_metrics_are_factual_and_failures_are_recorded(
    tmp_path: Path,
) -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True, worker_metrics_supported=True)
    )
    service = _service(tmp_path, session)

    def analyze(project, dependencies):
        if project.name == "core":
            raise RuntimeError("expected")
        return project.name

    result = WorkspaceAnalysisOrchestrator(service).execute(analyze, max_workers=2)
    assert not result.succeeded
    samples = [
        sample
        for sample in session.report().samples
        if sample.phase_id == MeasurementPhase.PROJECT_ANALYSIS.value
    ]
    assert samples
    assert any(not sample.succeeded for sample in samples)
    for sample in samples:
        assert sample.metric("queue_wait_ns").status is MetricStatus.MEASURED
        assert sample.metric("queue_depth").status is MetricStatus.MEASURED
        assert sample.metric("process_cpu_time_ns").status is MetricStatus.UNAVAILABLE
        assert (
            sample.metric("process_cpu_time_ns").reason
            is MetricReason.CONCURRENT_ATTRIBUTION
        )
        assert sample.worker_id.startswith("atlas-workspace-")
    assert str(tmp_path) not in json.dumps(session.report().to_dict())
