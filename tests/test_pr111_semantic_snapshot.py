from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.semantic import Diagnostic
from moughorai.semantic_snapshot import (
    AtlasSemanticSnapshot,
    SemanticSnapshotError,
    SemanticSnapshotStore,
)
from moughorai.workspace import Project, Workspace


NOW = datetime(2026, 7, 29, 20, 52, 57, tzinfo=timezone.utc)


def _workspace(tmp_path: Path) -> Workspace:
    project = tmp_path / "app"
    project.mkdir()
    (project / "main.java").write_text("class Main {}", encoding="utf-8")
    return Workspace(tmp_path, (Project("app", project),))


def _context(workspace: Workspace):
    return WorkspaceContextBuilder().build(
        workspace,
        diagnostics=(Diagnostic("A1", "verified"),),
    )


def test_capture_is_deterministic_and_provider_independent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    first = store.capture(_context(workspace), history_reference=7)
    second = store.capture(_context(workspace), history_reference=7)
    assert first == second
    text = json.dumps(first.to_dict(), sort_keys=True)
    assert all(provider not in text.lower() for provider in ("ollama", "openai", "claude", "gemini"))


def test_save_writes_immutable_history_and_latest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    snapshot = store.capture(_context(workspace))
    historical = store.save(snapshot)
    assert historical.name == "2026-07-29T20-52-57Z.ass"
    assert historical.read_bytes() == store.latest_path.read_bytes()
    assert store.list() == (historical,)
    assert store.load() == snapshot
    assert store.load(historical) == snapshot


def test_same_timestamp_cannot_overwrite_different_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    store.save(store.capture(_context(workspace)))
    changed = WorkspaceContextBuilder().build(workspace, diagnostics=(Diagnostic("B2", "changed"),))
    with pytest.raises(SemanticSnapshotError, match="immutable"):
        store.save(store.capture(changed))


def test_context_builder_consumes_loaded_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    original = _context(workspace)
    store.save(store.capture(original))
    restored = WorkspaceContextBuilder.from_snapshot(store.load())
    assert restored.to_json() == original.to_json()


def test_snapshot_detects_checksum_and_identifier_tampering(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    store.save(store.capture(_context(workspace)))
    envelope = json.loads(store.latest_path.read_text(encoding="utf-8"))
    envelope["snapshot"]["analyzer_version"] = "tampered"
    store.latest_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(SemanticSnapshotError, match="checksum"):
        store.load()

    raw = store.capture(_context(workspace)).to_dict()
    raw["snapshot_id"] = "0" * 64
    with pytest.raises(SemanticSnapshotError, match="identifier"):
        AtlasSemanticSnapshot.from_dict(raw)


def test_changed_source_changes_workspace_fingerprint(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    before = store.capture(_context(workspace)).workspace_fingerprint
    (tmp_path / "app" / "main.java").write_text("class Changed {}", encoding="utf-8")
    after = store.capture(_context(workspace)).workspace_fingerprint
    assert before != after


def test_missing_latest_and_naive_clock_are_handled(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert SemanticSnapshotStore(workspace).load() is None
    store = SemanticSnapshotStore(workspace, clock=lambda: datetime(2026, 7, 29))
    with pytest.raises(SemanticSnapshotError, match="timezone-aware"):
        store.save(store.capture(_context(workspace)))
