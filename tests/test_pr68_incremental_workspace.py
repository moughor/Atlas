from __future__ import annotations

from pathlib import Path
import os

import pytest

from moughorai.workspace import (
    FileEvent,
    FileEventKind,
    FileState,
    IncrementalWorkspacePlanner,
    WatchSnapshot,
    WorkspaceService,
    WorkspaceWatcher,
)


def write_workspace(root: Path) -> WorkspaceService:
    (root / "core").mkdir()
    (root / "app").mkdir()
    (root / "core" / "a.py").write_text("a = 1\n")
    (root / "app" / "b.py").write_text("b = 1\n")
    (root / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n"
        "    path: core\n"
        "    include: ['**/*.py']\n"
        "  - name: app\n"
        "    path: app\n"
        "    dependencies: [core]\n"
        "    include: ['**/*.py']\n"
    )
    return WorkspaceService(root)


def test_event_requires_previous_path_for_rename(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="require previous_path"):
        FileEvent(FileEventKind.RENAMED, tmp_path / "new.py")


def test_non_rename_rejects_previous_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only valid"):
        FileEvent(FileEventKind.CREATED, tmp_path / "new.py", previous_path=tmp_path / "old.py")


def test_event_paths_are_resolved(tmp_path: Path) -> None:
    event = FileEvent(FileEventKind.CREATED, tmp_path / "x.py")
    assert event.path.is_absolute()


def test_event_to_dict_uses_relative_paths(tmp_path: Path) -> None:
    event = FileEvent(FileEventKind.RENAMED, tmp_path / "new.py", "core", tmp_path / "old.py", 7)
    assert event.to_dict(root=tmp_path) == {
        "kind": "renamed", "path": "new.py", "previous_path": "old.py", "project": "core", "timestamp_ns": 7
    }


def test_negative_debounce_is_rejected(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    with pytest.raises(ValueError, match="non-negative"):
        WorkspaceWatcher(service.workspace, debounce_ms=-1)


def test_snapshot_contains_included_files(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace)
    files = watcher.snapshot().as_dict()
    assert {p.name for p in files} == {"a.py", "b.py"}


def test_snapshot_ignores_non_matching_files(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    (tmp_path / "core" / "note.txt").write_text("ignored")
    assert {p.suffix for p in WorkspaceWatcher(service.workspace).snapshot().as_dict()} == {".py"}


def test_first_poll_only_initializes(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace)
    assert watcher.poll(flush=True) == ()


def test_start_returns_snapshot(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace)
    assert len(watcher.start().files) == 2


def test_created_file_event(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=0)
    watcher.start()
    target = tmp_path / "core" / "new.py"
    target.write_text("new")
    events = watcher.poll(flush=True, now_ns=10)
    assert [(e.kind, e.path.name, e.project) for e in events] == [(FileEventKind.CREATED, "new.py", "core")]


def test_modified_file_event(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=0)
    watcher.start()
    target = tmp_path / "core" / "a.py"
    target.write_text("a = 2\n")
    events = watcher.poll(flush=True, now_ns=10)
    assert events[0].kind is FileEventKind.MODIFIED


def test_deleted_file_event(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=0)
    watcher.start()
    (tmp_path / "app" / "b.py").unlink()
    events = watcher.poll(flush=True, now_ns=10)
    assert [(e.kind, e.project) for e in events] == [(FileEventKind.DELETED, "app")]


def test_rename_is_inferred_from_identical_state(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace, debounce_ms=0)
    before = watcher.snapshot()
    old = tmp_path / "core" / "a.py"
    new = tmp_path / "core" / "renamed.py"
    old.rename(new)
    after = watcher.snapshot()
    events = watcher.diff(before, after, timestamp_ns=3)
    assert len(events) == 1
    assert events[0].kind is FileEventKind.RENAMED
    assert events[0].previous_path == old.resolve()


def test_cross_project_rename_uses_destination_project(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace)
    before = watcher.snapshot()
    old = tmp_path / "core" / "a.py"
    new = tmp_path / "app" / "a.py"
    old.rename(new)
    event = watcher.diff(before, watcher.snapshot())[0]
    assert event.project == "app"


def test_diff_order_is_deterministic(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace)
    before = watcher.snapshot()
    (tmp_path / "app" / "z.py").write_text("z")
    (tmp_path / "core" / "c.py").write_text("c")
    events = watcher.diff(before, watcher.snapshot())
    assert [(e.project, e.path.name) for e in events] == [("app", "z.py"), ("core", "c.py")]


def test_debounce_holds_recent_events(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=100)
    watcher.start()
    (tmp_path / "core" / "new.py").write_text("new")
    assert watcher.poll(now_ns=1_000_000) == ()
    assert watcher.flush(now_ns=50_000_000) == ()


def test_debounce_releases_mature_events(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=100)
    watcher.start()
    (tmp_path / "core" / "new.py").write_text("new")
    watcher.poll(now_ns=1)
    assert len(watcher.flush(now_ns=100_000_001)) == 1


def test_force_flush_ignores_debounce(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=1000)
    watcher.start()
    (tmp_path / "core" / "new.py").write_text("new")
    assert len(watcher.poll(now_ns=1, flush=True)) == 1


def test_create_then_modify_coalesces_to_create(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=100)
    watcher.start()
    target = tmp_path / "core" / "new.py"
    target.write_text("1")
    watcher.poll(now_ns=1)
    target.write_text("2")
    watcher.poll(now_ns=2)
    event = watcher.flush(now_ns=200_000_000)[0]
    assert event.kind is FileEventKind.CREATED


def test_create_then_delete_cancels_event(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=100)
    watcher.start()
    target = tmp_path / "core" / "new.py"
    target.write_text("1")
    watcher.poll(now_ns=1)
    target.unlink()
    watcher.poll(now_ns=2)
    assert watcher.flush(now_ns=200_000_000) == ()


def test_modify_then_delete_coalesces_to_delete(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=100)
    watcher.start()
    target = tmp_path / "core" / "a.py"
    target.write_text("2")
    watcher.poll(now_ns=1)
    target.unlink()
    watcher.poll(now_ns=2)
    assert watcher.flush(now_ns=200_000_000)[0].kind is FileEventKind.DELETED


def test_project_resolution_prefers_nested_project(tmp_path: Path) -> None:
    (tmp_path / "outer" / "inner").mkdir(parents=True)
    (tmp_path / "outer" / "inner" / "a.py").write_text("x")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: outer\n    path: outer\n    include: ['**/*.py']\n"
        "  - name: inner\n    path: outer/inner\n    include: ['**/*.py']\n"
    )
    watcher = WorkspaceWatcher(WorkspaceService(tmp_path).workspace)
    watcher.start()
    target = tmp_path / "outer" / "inner" / "b.py"
    target.write_text("b")
    assert watcher.poll(flush=True)[0].project == "inner"


def test_watch_snapshot_round_trip() -> None:
    path = Path("/tmp/a")
    state = FileState(1, 2, 3)
    assert WatchSnapshot(((path, state),)).as_dict() == {path: state}


def test_planner_initially_marks_all_projects_valid(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    assert planner.valid_projects == ("app", "core")


def test_planner_invalidates_changed_and_dependents(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "a.py", "core")
    plan = planner.plan((event,))
    assert plan.directly_changed == ("core",)
    assert plan.invalidated == ("core", "app")
    assert tuple(project.name for project in plan.analysis_order) == ("core", "app")


def test_app_change_does_not_invalidate_dependency(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    planner = IncrementalWorkspacePlanner(service)
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "app" / "b.py", "app")
    plan = planner.plan((event,))
    assert plan.invalidated == ("app",)


def test_unknown_project_events_are_ignored(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "outside.py")
    assert planner.plan((event,)).analysis_order == ()


def test_duplicate_events_produce_unique_projects(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    path = tmp_path / "core" / "a.py"
    events = (FileEvent(FileEventKind.MODIFIED, path, "core"), FileEvent(FileEventKind.MODIFIED, path, "core"))
    assert planner.plan(events).directly_changed == ("core",)


def test_invalidate_returns_only_previously_valid_projects(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    assert planner.invalidate({"core", "missing"}) == ("core",)
    assert planner.invalidate({"core"}) == ()


def test_mark_valid_checks_project_name(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    with pytest.raises(KeyError, match="unknown project"):
        planner.mark_valid("missing")


def test_mark_plan_valid_restores_projects(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "a.py", "core")
    plan = planner.plan((event,))
    assert planner.valid_projects == ()
    planner.mark_plan_valid(plan)
    assert planner.valid_projects == ("app", "core")


def test_plan_serialization_is_deterministic(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    event = FileEvent(FileEventKind.MODIFIED, tmp_path / "core" / "a.py", "core", timestamp_ns=5)
    data = planner.plan((event,)).to_dict()
    assert data["directly_changed"] == ["core"]
    assert data["analysis_order"] == ["core", "app"]


def test_file_state_detects_same_size_content_change(tmp_path: Path) -> None:
    service = write_workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace)
    before = watcher.snapshot()
    target = tmp_path / "core" / "a.py"
    original_ns = target.stat().st_mtime_ns
    target.write_text("a = 9\n")
    os.utime(target, ns=(original_ns, original_ns))
    after = watcher.snapshot()
    assert watcher.diff(before, after)[0].kind is FileEventKind.MODIFIED


def test_event_timestamp_comes_from_poll(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(write_workspace(tmp_path).workspace, debounce_ms=0)
    watcher.start()
    (tmp_path / "core" / "new.py").write_text("x")
    assert watcher.poll(now_ns=123, flush=True)[0].timestamp_ns == 123


def test_empty_plan_keeps_valid_projects(tmp_path: Path) -> None:
    planner = IncrementalWorkspacePlanner(write_workspace(tmp_path))
    assert planner.plan(()).invalidated == ()
    assert planner.valid_projects == ("app", "core")
