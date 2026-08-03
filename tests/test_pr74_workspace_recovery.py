from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from time import sleep

import pytest

from moughorai.ai_context.persistence import (
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.semantic import SemanticDocument
from moughorai.workspace import (
    ANALYSIS_RESULT_PRODUCER_FINGERPRINT,
    ConfigurationLayer,
    RecoveryProjectStatus,
    WorkspaceAnalysisOrchestrator,
    WorkspaceCache,
    WorkspaceConfigurationResolver,
    WorkspaceEventKind,
    WorkspaceRecoveryError,
    WorkspaceRecoveryJournal,
    WorkspaceRecoveryManager,
    WorkspaceService,
    WorkspaceStateStore,
)


def make_service(tmp_path: Path) -> WorkspaceService:
    for name in ("core", "api", "docs"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.py").write_text(name, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n"
        "  - name: api\n    path: api\n    dependencies: [core]\n"
        "  - name: docs\n    path: docs\n",
        encoding="utf-8",
    )
    return WorkspaceService(tmp_path)


def interrupt_after_core(manager: WorkspaceRecoveryManager, orchestrator: WorkspaceAnalysisOrchestrator) -> None:
    def analyze(project, dependencies):
        if project.name == "api":
            raise KeyboardInterrupt("crash")
        return {"project": project.name, "deps": sorted(dependencies)}

    with pytest.raises(KeyboardInterrupt, match="crash"):
        manager.execute(orchestrator, analyze)


def test_default_journal_path(tmp_path: Path) -> None:
    manager = WorkspaceRecoveryManager(make_service(tmp_path))
    assert manager.path == tmp_path / ".atlas" / "workspace-recovery.json"


def test_recovery_manager_rejects_empty_producer_fingerprint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="producer_fingerprint"):
        WorkspaceRecoveryManager(make_service(tmp_path), producer_fingerprint="")


def test_interruption_leaves_durable_statuses(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    interrupt_after_core(manager, WorkspaceAnalysisOrchestrator(service))
    report = manager.inspect()
    assert report.completed == ("core",)
    assert report.running == ("api",)
    assert report.pending == ("docs",)
    assert manager.path.exists()


def test_resume_analyzes_only_unfinished_projects(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    interrupt_after_core(manager, WorkspaceAnalysisOrchestrator(service))
    calls: list[str] = []
    report, recovery = WorkspaceRecoveryManager(service).resume(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: calls.append(project.name) or project.name,
    )
    assert calls == ["api", "docs"]
    assert report is not None and report.succeeded
    assert recovery.resumed == ("api", "docs")


def test_completed_dependency_value_is_available_after_resume(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    interrupt_after_core(manager, WorkspaceAnalysisOrchestrator(service))
    seen = {}

    def analyze(project, dependencies):
        seen[project.name] = dict(dependencies)
        return project.name

    WorkspaceRecoveryManager(service).resume(WorkspaceAnalysisOrchestrator(service), analyze)
    assert seen["api"]["core"]["project"] == "core"


def test_interrupted_semantic_result_is_restored_from_full_checkpoint(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(
        service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )

    def interrupt(project, dependencies):
        if project.name == "api":
            raise KeyboardInterrupt("crash")
        return SemanticDocument(
            language="java",
            source=f"class {project.name.title()} {{}}",
            syntax_tree=(),
            metadata={"project": project.name},
        )

    with pytest.raises(KeyboardInterrupt, match="crash"):
        manager.execute(WorkspaceAnalysisOrchestrator(service), interrupt)

    seen: dict[str, object] = {}

    def resume(project, dependencies):
        if project.name == "api":
            seen["core"] = dependencies["core"]
        return SemanticDocument(
            language="java",
            source="",
            syntax_tree=(),
            metadata={"project": project.name},
        )

    WorkspaceRecoveryManager(
        service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    ).resume(WorkspaceAnalysisOrchestrator(service), resume)

    restored = seen["core"]
    assert isinstance(restored, SemanticDocument)
    assert restored.language == "java"
    assert restored.metadata == {"project": "core"}
    assert restored.source == ""


def test_failed_projects_are_identified_and_retried(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)

    def fail_api(project, dependencies):
        if project.name == "api":
            raise RuntimeError("bad")
        return project.name

    manager.execute(WorkspaceAnalysisOrchestrator(service), fail_api)
    assert manager.inspect().failed == ("api",)
    calls = []
    WorkspaceRecoveryManager(service).resume(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: calls.append(project.name) or project.name,
    )
    assert calls == ["api"]


def test_completed_run_has_deterministic_report_order(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name, max_workers=3)
    report = manager.inspect()
    assert report.completed == ("core", "api", "docs")
    assert report.running == report.failed == report.pending == ()
    assert list(report.to_dict()) == [
        "journal_found", "resumed", "completed", "running", "failed", "pending",
        "invalidated", "invalidation_reason",
    ]


def test_concurrent_execution_updates_journal_safely(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    active = 0
    peak = 0
    lock = Lock()

    def analyze(project, dependencies):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.02)
        with lock:
            active -= 1
        return project.name

    manager = WorkspaceRecoveryManager(service)
    result = manager.execute(WorkspaceAnalysisOrchestrator(service), analyze, max_workers=2)
    assert result.succeeded and peak == 2
    assert manager.inspect().completed == result.analysis_order


def test_workspace_change_invalidates_journal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    (tmp_path / "core" / "main.py").write_text("changed", encoding="utf-8")
    report = manager.inspect()
    assert report.invalidated
    assert report.invalidation_reason == "workspace fingerprint changed"
    assert not manager.path.exists()


def test_configuration_change_invalidates_journal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    resolver = WorkspaceConfigurationResolver()
    first = resolver.resolve(ConfigurationLayer("workspace", {"recovery": {"enabled": True, "mode": "a"}}))
    second = resolver.resolve(ConfigurationLayer("workspace", {"recovery": {"enabled": True, "mode": "b"}}))
    manager = WorkspaceRecoveryManager(service, configuration=first)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    report = WorkspaceRecoveryManager(service, configuration=second).inspect()
    assert report.invalidated and report.invalidation_reason == "recovery configuration changed"


def test_analysis_producer_change_invalidates_journal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    WorkspaceRecoveryManager(
        service,
        producer_fingerprint="test/old",
    ).execute(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
    )

    report = WorkspaceRecoveryManager(
        service,
        producer_fingerprint="test/new",
    ).inspect()

    assert report.invalidated
    assert report.invalidation_reason == "analysis producer changed"


def test_pre_m21_semantic_checkpoint_producer_is_invalidated(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    previous = ANALYSIS_RESULT_PRODUCER_FINGERPRINT.replace(
        "workspace-analysis-result-v5",
        "workspace-analysis-result-v4",
    )
    WorkspaceRecoveryManager(
        service,
        producer_fingerprint=previous,
    ).execute(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
    )

    report = WorkspaceRecoveryManager(service).inspect()

    assert ANALYSIS_RESULT_PRODUCER_FINGERPRINT.endswith(
        "workspace-analysis-result-v5"
    )
    assert report.invalidated
    assert report.invalidation_reason == "analysis producer changed"


def test_unversioned_legacy_journal_is_read_then_invalidated(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
    )
    envelope = json.loads(manager.path.read_text(encoding="utf-8"))
    envelope["journal"].pop("producer_fingerprint")
    canonical = json.dumps(
        envelope["journal"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    envelope["checksum"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manager.path.write_text(json.dumps(envelope), encoding="utf-8")

    report = WorkspaceRecoveryManager(service).inspect()

    assert report.invalidated
    assert report.invalidation_reason == "analysis producer changed"


def test_stale_journal_is_invalidated(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manager = WorkspaceRecoveryManager(service, max_age_seconds=10, clock=lambda: now)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    later = WorkspaceRecoveryManager(service, max_age_seconds=10, clock=lambda: now + timedelta(seconds=11))
    report = later.inspect()
    assert report.invalidated
    assert report.invalidation_reason is not None and "stale" in report.invalidation_reason


def test_checksum_corruption_is_invalidated(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    data = json.loads(manager.path.read_text(encoding="utf-8"))
    data["journal"]["projects"]["core"]["status"] = "failed"
    manager.path.write_text(json.dumps(data), encoding="utf-8")
    report = manager.inspect()
    assert report.invalidated and report.invalidation_reason == "recovery journal checksum mismatch"


def test_invalid_project_set_is_rejected() -> None:
    with pytest.raises(WorkspaceRecoveryError, match="project set"):
        WorkspaceRecoveryJournal.from_dict(
            {
                "schema_version": 1,
                "workspace_fingerprint": "w",
                "configuration_fingerprint": "c",
                "requested": ["core"],
                "analysis_order": ["core"],
                "projects": {},
                "started_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )


def test_pr70_state_is_saved_during_recoverable_run(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    state = manager.state_store.load()
    assert state is not None and state.valid_projects == ("api", "core", "docs")


@pytest.mark.parametrize("max_workers", [1, 3])
def test_recovery_snapshots_workspace_once_and_saves_state_after_each_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_workers: int,
) -> None:
    service = make_service(tmp_path)
    cache = WorkspaceCache()
    snapshot_calls = 0
    fingerprint_calls = 0
    original_snapshot = cache.snapshot
    original_fingerprint = cache.fingerprint

    def counted_snapshot(workspace):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(workspace)

    def counted_fingerprint(project):
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        return original_fingerprint(project)

    monkeypatch.setattr(cache, "snapshot", counted_snapshot)
    monkeypatch.setattr(cache, "fingerprint", counted_fingerprint)
    state_store = WorkspaceStateStore(service, cache=cache)
    manager = WorkspaceRecoveryManager(service, state_store=state_store)

    report = manager.execute(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
        max_workers=max_workers,
    )

    assert report.succeeded
    assert snapshot_calls == 1
    assert fingerprint_calls == len(report.runs) * 2
    assert sum(
        event.kind is WorkspaceEventKind.STATE_SAVED
        for event in service.events.history
    ) == len(report.runs)
    state = state_store.load()
    assert state is not None
    assert state.valid_projects == ("api", "core", "docs")


def test_resume_reuses_its_single_verified_workspace_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(tmp_path)
    interrupt_after_core(
        WorkspaceRecoveryManager(service),
        WorkspaceAnalysisOrchestrator(service),
    )
    cache = WorkspaceCache()
    snapshot_calls = 0
    original_snapshot = cache.snapshot

    def counted_snapshot(workspace):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(workspace)

    monkeypatch.setattr(cache, "snapshot", counted_snapshot)
    manager = WorkspaceRecoveryManager(
        service,
        state_store=WorkspaceStateStore(service, cache=cache),
    )

    report, recovery = manager.resume(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
    )

    assert report is not None and report.succeeded
    assert recovery.resumed == ("api", "docs")
    assert snapshot_calls == 1


def test_completion_fingerprint_tracks_source_mutation_without_stale_reuse(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    state_store = WorkspaceStateStore(service)
    manager = WorkspaceRecoveryManager(service, state_store=state_store)

    def mutate_core(project, dependencies):
        if project.name == "core":
            (project.path / "main.py").write_text("changed", encoding="utf-8")
        return project.name

    report = manager.execute(
        WorkspaceAnalysisOrchestrator(service),
        mutate_core,
    )
    assert report.succeeded
    state = state_store.load()
    assert state is not None

    recovery = manager.inspect()
    restored, restore_report = state_store.restore(state)

    assert not recovery.invalidated
    assert "core" in restored
    assert restore_report.invalidated == ()

    (tmp_path / "core" / "main.py").write_text("core", encoding="utf-8")
    recovery = manager.inspect()
    restored, restore_report = state_store.restore(state)

    assert recovery.invalidated
    assert recovery.invalidation_reason == "workspace fingerprint changed"
    assert "core" not in restored
    assert restore_report.invalidated == ("core",)


def test_recovery_configuration_controls_path_and_enabled(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    path = tmp_path / "custom-recovery.json"
    configuration = WorkspaceConfigurationResolver().resolve(
        ConfigurationLayer("workspace", {"recovery": {"enabled": False, "path": str(path)}})
    )
    manager = WorkspaceRecoveryManager(service, configuration=configuration)
    result = manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    assert result.succeeded and manager.path == path and not path.exists()


def test_recovery_emits_pr72_events(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    kinds = [event.kind for event in service.events.history]
    assert WorkspaceEventKind.RECOVERY_STARTED in kinds
    assert WorkspaceEventKind.RECOVERY_JOURNAL_SAVED in kinds
    assert WorkspaceEventKind.RECOVERY_COMPLETED in kinds


def test_invalidation_emits_event(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    (tmp_path / "docs" / "main.py").write_text("changed", encoding="utf-8")
    manager.inspect()
    assert service.events.history[-1].kind is WorkspaceEventKind.RECOVERY_INVALIDATED


def test_missing_journal_reports_no_recovery(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    report, recovery = WorkspaceRecoveryManager(service).resume(
        WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name
    )
    assert report is None
    assert not recovery.journal_found and not recovery.invalidated


def test_custom_encoder_decoder_round_trip(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    encode = lambda value: {"wrapped": value}
    decode = lambda value: value["wrapped"]
    manager = WorkspaceRecoveryManager(service, encoder=encode, decoder=decode)

    def interrupt(project, dependencies):
        if project.name == "api":
            raise KeyboardInterrupt()
        return project.name

    with pytest.raises(KeyboardInterrupt):
        manager.execute(WorkspaceAnalysisOrchestrator(service), interrupt)
    seen = {}
    WorkspaceRecoveryManager(service, encoder=encode, decoder=decode).resume(
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: seen.update({project.name: dict(dependencies)}) or project.name,
    )
    assert seen["api"] == {"core": "core"}


def test_delete_is_idempotent(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    manager = WorkspaceRecoveryManager(service)
    manager.execute(WorkspaceAnalysisOrchestrator(service), lambda project, dependencies: project.name)
    assert manager.delete() is True
    assert manager.delete() is False
