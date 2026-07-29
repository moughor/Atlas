from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.workspace import (
    STATE_SCHEMA_VERSION,
    WorkspaceAnalysisOrchestrator,
    WorkspacePersistentState,
    WorkspaceService,
    WorkspaceStateError,
    WorkspaceStateStore,
)


def make_service(tmp_path: Path) -> WorkspaceService:
    for name in ("core", "api", "ui"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.py").write_text(name, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n    path: core\n"
        "  - name: api\n    path: api\n    dependencies: [core]\n"
        "  - name: ui\n    path: ui\n    dependencies: [api]\n",
        encoding="utf-8",
    )
    return WorkspaceService(tmp_path)


def populated(tmp_path: Path):
    service = make_service(tmp_path)
    orch = WorkspaceAnalysisOrchestrator(service)
    orch.execute(lambda project, deps: {"project": project.name, "deps": sorted(deps)})
    return service, orch


def test_default_state_path(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert WorkspaceStateStore(service).path == tmp_path / ".atlas" / "workspace-state.json"


def test_capture_includes_schema_and_valid_results(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    state = WorkspaceStateStore(service).capture(orch._results, orch.planner.valid_projects)
    assert state.schema_version == STATE_SCHEMA_VERSION
    assert dict(state.results)["core"]["project"] == "core"
    assert state.valid_projects == ("api", "core", "ui")


def test_capture_ignores_unknown_results(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    state = WorkspaceStateStore(service).capture({"missing": 1}, ("missing",))
    assert state.results == ()


def test_capture_requires_result_to_be_valid(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    state = WorkspaceStateStore(service).capture({"core": 1}, ())
    assert state.results == ()


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    path = store.save(store.capture(orch._results, orch.planner.valid_projects))
    assert path.exists() and path.parent.name == ".atlas"


def test_saved_json_is_deterministic_shape(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    store.save(store.capture(orch._results, orch.planner.valid_projects))
    data = json.loads(store.path.read_text())
    assert sorted(data) == ["checksum", "state"]
    assert data["state"]["schema_version"] == 1


def test_load_round_trip(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    original = store.capture(orch._results, orch.planner.valid_projects)
    store.save(original)
    assert store.load() == original


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert WorkspaceStateStore(make_service(tmp_path)).load() is None


def test_corrupt_json_raises(tmp_path: Path) -> None:
    store = WorkspaceStateStore(make_service(tmp_path))
    store.path.parent.mkdir()
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(WorkspaceStateError, match="cannot read"):
        store.load()


def test_checksum_mismatch_raises(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    store.save(store.capture(orch._results, orch.planner.valid_projects))
    data = json.loads(store.path.read_text())
    data["state"]["valid_projects"] = []
    store.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WorkspaceStateError, match="checksum"):
        store.load()


def test_unknown_schema_raises() -> None:
    with pytest.raises(WorkspaceStateError, match="unsupported"):
        WorkspacePersistentState.from_dict({"schema_version": 99, "workspace_fingerprint": "x", "project_fingerprints": {}, "valid_projects": [], "results": {}, "saved_at": "x"})


def test_missing_fields_raise() -> None:
    with pytest.raises(WorkspaceStateError, match="missing"):
        WorkspacePersistentState.from_dict({})


def test_restore_all_unchanged_results(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    state = store.capture(orch._results, orch.planner.valid_projects)
    results, report = store.restore(state)
    assert tuple(sorted(results)) == ("api", "core", "ui")
    assert report.restored == ("api", "core", "ui")
    assert report.invalidated == ()


def test_restore_none_reports_no_state(tmp_path: Path) -> None:
    results, report = WorkspaceStateStore(make_service(tmp_path)).restore(None)
    assert results == {} and not report.state_found and not report.restored_any


def test_changed_project_is_invalidated(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    state = store.capture(orch._results, orch.planner.valid_projects)
    (tmp_path / "api" / "main.py").write_text("changed", encoding="utf-8")
    results, report = store.restore(state)
    assert "api" not in results and report.invalidated == ("api",)
    assert "core" in results


def test_removed_project_result_is_ignored(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    state = store.capture(orch._results, orch.planner.valid_projects)
    object.__setattr__(state, "results", state.results + (("ghost", 1),))
    _, report = store.restore(state)
    assert report.ignored == ("ghost",)


def test_custom_encoder_decoder(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    store = WorkspaceStateStore(service, encoder=lambda value: {"v": value}, decoder=lambda value: value["v"])
    state = store.capture({"core": 7}, ("core",))
    results, _ = store.restore(state)
    assert results == {"core": 7}


def test_encoder_failure_is_wrapped(tmp_path: Path) -> None:
    store = WorkspaceStateStore(make_service(tmp_path), encoder=lambda value: 1 / 0)
    with pytest.raises(WorkspaceStateError, match="cannot encode"):
        store.capture({"core": 1}, ("core",))


def test_decoder_failure_is_wrapped(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    state = WorkspaceStateStore(service).capture({"core": 1}, ("core",))
    with pytest.raises(WorkspaceStateError, match="cannot decode"):
        WorkspaceStateStore(service, decoder=lambda value: 1 / 0).restore(state)


def test_delete_existing_state(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    store.save(store.capture(orch._results, orch.planner.valid_projects))
    assert store.delete() is True and not store.path.exists()


def test_delete_missing_state_is_false(tmp_path: Path) -> None:
    assert WorkspaceStateStore(make_service(tmp_path)).delete() is False


def test_orchestrator_save_and_restore(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    orch.save_state(store)
    restored = WorkspaceAnalysisOrchestrator(service)
    report = restored.restore_state(store)
    assert report.restored == ("api", "core", "ui")
    assert restored.result("ui")["project"] == "ui"


def test_restored_results_are_reused(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    orch.save_state(store)
    restored = WorkspaceAnalysisOrchestrator(service)
    restored.restore_state(store)
    calls = []
    report = restored.execute(lambda project, deps: calls.append(project.name))
    assert calls == []
    assert all(run.status.value == "reused" for run in report.runs)


def test_changed_result_is_not_reused(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    orch.save_state(store)
    (tmp_path / "core" / "main.py").write_text("changed", encoding="utf-8")
    restored = WorkspaceAnalysisOrchestrator(service)
    report = restored.restore_state(store)
    assert report.invalidated == ("core",)
    assert "core" not in restored.cached_projects


def test_restore_report_serialization(tmp_path: Path) -> None:
    _, report = WorkspaceStateStore(make_service(tmp_path)).restore(None)
    assert report.to_dict() == {"state_found": False, "restored": [], "invalidated": [], "ignored": []}


def test_state_serialization_uses_sorted_project_keys(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    state = WorkspaceStateStore(service).capture({"ui": 3, "core": 1, "api": 2}, ("ui", "api", "core"))
    assert tuple(name for name, _ in state.results) == ("api", "core", "ui")


def test_saved_at_is_timezone_aware(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    state = WorkspaceStateStore(service).capture({}, ())
    assert state.saved_at.endswith("+00:00")


def test_workspace_fingerprint_changes_with_content(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    store = WorkspaceStateStore(service)
    before = store.capture({}, ()).workspace_fingerprint
    (tmp_path / "ui" / "main.py").write_text("changed", encoding="utf-8")
    after = store.capture({}, ()).workspace_fingerprint
    assert before != after


def test_custom_state_path(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert WorkspaceStateStore(service, tmp_path / "state.json").path == tmp_path / "state.json"


def test_invalid_mapping_types_raise() -> None:
    with pytest.raises(WorkspaceStateError):
        WorkspacePersistentState.from_dict({"schema_version": 1, "workspace_fingerprint": "x", "project_fingerprints": [], "valid_projects": [], "results": {}, "saved_at": "x"})


def test_atomic_save_leaves_no_temp_files(tmp_path: Path) -> None:
    service, orch = populated(tmp_path)
    store = WorkspaceStateStore(service)
    store.save(store.capture(orch._results, orch.planner.valid_projects))
    assert list(store.path.parent.glob("*.tmp")) == []
