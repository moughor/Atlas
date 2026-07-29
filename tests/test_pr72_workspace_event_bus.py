from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.workspace import (
    FileEvent,
    FileEventKind,
    IncrementalWorkspacePlanner,
    WorkspaceAnalysisOrchestrator,
    WorkspaceEvent,
    WorkspaceEventBus,
    WorkspaceEventKind,
    WorkspaceService,
    WorkspaceStateStore,
    WorkspaceWatcher,
)


def workspace(tmp_path: Path) -> WorkspaceService:
    (tmp_path / "core").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "core" / "a.py").write_text("a=1\n")
    (tmp_path / "app" / "b.py").write_text("b=1\n")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n    include: ['**/*.py']\n"
        "  - name: app\n    path: app\n    dependencies: [core]\n    include: ['**/*.py']\n"
    )
    return WorkspaceService(tmp_path)


def test_negative_history_limit_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        WorkspaceEventBus(history_limit=-1)


def test_event_to_dict() -> None:
    event = WorkspaceEvent(WorkspaceEventKind.ERROR, {"message": "bad"}, project="app", source="test", timestamp="t", event_id="e")
    assert event.to_dict() == {"event_id": "e", "kind": "error", "project": "app", "source": "test", "timestamp": "t", "payload": {"message": "bad"}}


def test_subscribe_requires_callable() -> None:
    with pytest.raises(TypeError, match="callable"):
        WorkspaceEventBus().subscribe(None)  # type: ignore[arg-type]


def test_publish_requires_event() -> None:
    with pytest.raises(TypeError, match="WorkspaceEvent"):
        WorkspaceEventBus().publish("bad")  # type: ignore[arg-type]


def test_basic_delivery() -> None:
    seen = []
    bus = WorkspaceEventBus()
    sid = bus.subscribe(seen.append)
    report = bus.emit(WorkspaceEventKind.ERROR, payload={"x": 1})
    assert report.delivered == (sid,)
    assert seen[0].payload == {"x": 1}


def test_kind_filter() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(seen.append, kinds=WorkspaceEventKind.STATE_SAVED)
    bus.emit(WorkspaceEventKind.ERROR)
    bus.emit(WorkspaceEventKind.STATE_SAVED)
    assert [event.kind for event in seen] == [WorkspaceEventKind.STATE_SAVED]


def test_multiple_kind_filter() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(seen.append, kinds=[WorkspaceEventKind.ERROR, WorkspaceEventKind.STATE_SAVED])
    bus.emit(WorkspaceEventKind.ERROR)
    bus.emit(WorkspaceEventKind.STATE_RESTORED)
    assert len(seen) == 1


def test_project_filter() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(seen.append, project="core")
    bus.emit(WorkspaceEventKind.PROJECT_STARTED, project="app")
    bus.emit(WorkspaceEventKind.PROJECT_STARTED, project="core")
    assert [event.project for event in seen] == ["core"]


def test_predicate_filter() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(seen.append, predicate=lambda event: event.payload.get("ok") is True)
    bus.emit(WorkspaceEventKind.ERROR, payload={"ok": False})
    bus.emit(WorkspaceEventKind.ERROR, payload={"ok": True})
    assert len(seen) == 1


def test_priority_order() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: seen.append("low"), priority=0)
    bus.subscribe(lambda event: seen.append("high"), priority=10)
    bus.emit(WorkspaceEventKind.ERROR)
    assert seen == ["high", "low"]


def test_registration_order_breaks_priority_ties() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: seen.append(1))
    bus.subscribe(lambda event: seen.append(2))
    bus.emit(WorkspaceEventKind.ERROR)
    assert seen == [1, 2]


def test_once_subscription_removed_after_success() -> None:
    seen = []
    bus = WorkspaceEventBus()
    bus.subscribe(seen.append, once=True)
    bus.emit(WorkspaceEventKind.ERROR)
    bus.emit(WorkspaceEventKind.ERROR)
    assert len(seen) == 1
    assert bus.subscription_count == 0


def test_unsubscribe() -> None:
    bus = WorkspaceEventBus()
    sid = bus.subscribe(lambda event: None)
    assert bus.unsubscribe(sid)
    assert not bus.unsubscribe(sid)


def test_duplicate_subscription_id_rejected() -> None:
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: None, subscription_id="x")
    with pytest.raises(ValueError, match="duplicate"):
        bus.subscribe(lambda event: None, subscription_id="x")


def test_clear_returns_count() -> None:
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: None)
    bus.subscribe(lambda event: None)
    assert bus.clear() == 2
    assert bus.subscription_count == 0


def test_callback_failure_is_collected() -> None:
    def broken(event):
        raise RuntimeError("boom")
    bus = WorkspaceEventBus()
    sid = bus.subscribe(broken)
    report = bus.emit(WorkspaceEventKind.ERROR)
    assert not report.succeeded
    assert report.failures[0].subscription_id == sid
    assert "RuntimeError: boom" in report.failures[0].error


def test_raise_errors_is_fail_fast() -> None:
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        bus.emit(WorkspaceEventKind.ERROR, raise_errors=True)


def test_predicate_failure_is_collected() -> None:
    bus = WorkspaceEventBus()
    bus.subscribe(lambda event: None, predicate=lambda event: 1 / 0)
    report = bus.emit(WorkspaceEventKind.ERROR)
    assert "ZeroDivisionError" in report.failures[0].error


def test_history_is_bounded() -> None:
    bus = WorkspaceEventBus(history_limit=2)
    for value in range(3):
        bus.emit(WorkspaceEventKind.ERROR, payload={"value": value})
    assert [event.payload["value"] for event in bus.history] == [1, 2]


def test_zero_history_limit() -> None:
    bus = WorkspaceEventBus(history_limit=0)
    bus.emit(WorkspaceEventKind.ERROR)
    assert bus.history == ()


def test_clear_history_returns_count() -> None:
    bus = WorkspaceEventBus()
    bus.emit(WorkspaceEventKind.ERROR)
    assert bus.clear_history() == 1
    assert bus.history == ()


def test_publish_many() -> None:
    bus = WorkspaceEventBus()
    reports = bus.publish_many([WorkspaceEvent(WorkspaceEventKind.ERROR), WorkspaceEvent(WorkspaceEventKind.STATE_SAVED)])
    assert len(reports) == 2
    assert len(bus.history) == 2


def test_report_to_dict() -> None:
    bus = WorkspaceEventBus()
    report = bus.emit(WorkspaceEventKind.ERROR)
    assert report.to_dict()["event"]["kind"] == "error"
    assert report.to_dict()["failures"] == []


def test_service_exposes_event_bus(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    assert isinstance(service.events, WorkspaceEventBus)


def test_service_accepts_shared_bus(tmp_path: Path) -> None:
    bus = WorkspaceEventBus()
    assert workspace_with_bus(tmp_path, bus).events is bus


def workspace_with_bus(tmp_path: Path, bus: WorkspaceEventBus) -> WorkspaceService:
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "x.py").write_text("x=1")
    (tmp_path / "atlas.yaml").write_text("projects:\n  - name: p\n    path: p\n")
    return WorkspaceService(tmp_path, event_bus=bus)


def test_configuration_emits_event(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    service.resolved_configuration("core")
    assert service.events.history[-1].kind is WorkspaceEventKind.CONFIGURATION_RESOLVED


def test_planner_emits_plan_and_invalidation(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "a.py", "core")
    planner.plan((event,))
    assert [item.kind for item in service.events.history][-2:] == [WorkspaceEventKind.CACHE_INVALIDATED, WorkspaceEventKind.PLAN_CREATED]


def test_watcher_emits_files_changed(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace, event_bus=service.events, debounce_ms=0)
    watcher.start()
    (tmp_path / "core" / "a.py").write_text("a=2\n")
    assert watcher.poll(flush=True)
    assert service.events.history[-1].kind is WorkspaceEventKind.FILES_CHANGED


def test_orchestrator_emits_analysis_lifecycle(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    WorkspaceAnalysisOrchestrator(service).execute(lambda project, deps: project.name)
    kinds = [event.kind for event in service.events.history]
    assert kinds[0] is WorkspaceEventKind.ANALYSIS_STARTED
    assert WorkspaceEventKind.PROJECT_STARTED in kinds
    assert WorkspaceEventKind.PROJECT_COMPLETED in kinds
    assert kinds[-1] is WorkspaceEventKind.ANALYSIS_COMPLETED


def test_orchestrator_emits_failure_and_block(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    def analyzer(project, deps):
        if project.name == "core":
            raise RuntimeError("bad")
        return project.name
    WorkspaceAnalysisOrchestrator(service).execute(analyzer)
    kinds = [event.kind for event in service.events.history]
    assert WorkspaceEventKind.PROJECT_FAILED in kinds
    assert WorkspaceEventKind.PROJECT_BLOCKED in kinds


def test_persistence_emits_save_and_restore(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    orchestrator = WorkspaceAnalysisOrchestrator(service)
    orchestrator.execute(lambda project, deps: project.name)
    store = WorkspaceStateStore(service)
    store.save(store.capture({"core": "core"}, ("core",)))
    store.restore(store.load())
    kinds = [event.kind for event in service.events.history]
    assert WorkspaceEventKind.STATE_SAVED in kinds
    assert WorkspaceEventKind.STATE_RESTORED in kinds
