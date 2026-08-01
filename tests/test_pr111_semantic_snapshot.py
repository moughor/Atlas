from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

import pytest

from moughorai.ai_context import WorkspaceContextBuilder, WorkspaceSemanticContext
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


def test_same_timestamp_preserves_both_immutable_snapshots(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    store.save(store.capture(_context(workspace)))
    changed = WorkspaceContextBuilder().build(workspace, diagnostics=(Diagnostic("B2", "changed"),))
    second = store.save(store.capture(changed))
    assert second.name.startswith("2026-07-29T20-52-57Z-")
    assert len(store.list()) == 2
    assert store.load(second).semantic_context["diagnostics"][0]["code"] == "B2"


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


@pytest.mark.parametrize("schema", [True, 1.0, "1"])
def test_snapshot_schema_requires_an_exact_json_integer(
    tmp_path: Path,
    schema: object,
) -> None:
    workspace = _workspace(tmp_path)
    raw = SemanticSnapshotStore(workspace).capture(_context(workspace)).to_dict()
    raw["schema_version"] = schema

    with pytest.raises(SemanticSnapshotError, match="schema must be an integer"):
        AtlasSemanticSnapshot.from_dict(raw)


@pytest.mark.parametrize("history_reference", [True, 1.5])
def test_snapshot_creation_rejects_an_invalid_history_reference(
    tmp_path: Path,
    history_reference: object,
) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(SemanticSnapshotError, match="history_reference"):
        AtlasSemanticSnapshot.create(
            _context(workspace),
            workspace_fingerprint="workspace",
            analyzer_version="2.0.0",
            history_reference=history_reference,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("workspace_fingerprint", None, "workspace fingerprint"),
        ("workspace_fingerprint", "", "workspace fingerprint"),
        ("analyzer_version", 200, "analyzer version"),
        ("analyzer_version", " ", "analyzer version"),
        ("snapshot_id", None, "snapshot identifier"),
    ],
)
def test_snapshot_metadata_requires_exact_non_empty_strings(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    workspace = _workspace(tmp_path)
    raw = SemanticSnapshotStore(workspace).capture(_context(workspace)).to_dict()
    raw[field] = value

    with pytest.raises(SemanticSnapshotError, match=message):
        AtlasSemanticSnapshot.from_dict(raw)


def test_save_rejects_nested_context_mutation_before_writing(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    store = SemanticSnapshotStore(workspace, clock=lambda: NOW)
    snapshot = store.capture(_context(workspace))
    workspace_context = snapshot.semantic_context["workspace"]
    assert isinstance(workspace_context, dict)
    workspace_context["root"] = "mutated"

    with pytest.raises(SemanticSnapshotError, match="identifier mismatch"):
        store.save(snapshot)

    assert not store.latest_path.exists()


def test_snapshot_store_rejects_non_finite_semantic_values(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    context = _context(workspace).to_dict()
    context["metrics"] = [{"name": "invalid", "value": float("nan")}]

    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="workspace",
        analyzer_version="2.0.0",
    )

    with pytest.raises(SemanticSnapshotError, match="finite JSON data"):
        SemanticSnapshotStore(workspace).save(snapshot)

    assert not SemanticSnapshotStore(workspace).latest_path.exists()


def test_snapshot_loader_rejects_non_standard_json_constants(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    path = tmp_path / "invalid.ass"
    path.write_text(
        '{"format":"atlas-semantic-snapshot","checksum":"invalid",'
        '"snapshot":{"semantic_context":{"metrics":[NaN]}}}',
        encoding="utf-8",
    )

    with pytest.raises(SemanticSnapshotError, match="non-finite JSON number"):
        SemanticSnapshotStore(workspace).load(path)


def test_concurrent_store_instances_preserve_distinct_historical_snapshots(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    barrier = Barrier(2)

    def clock() -> datetime:
        barrier.wait(timeout=5)
        return NOW

    first_store = SemanticSnapshotStore(workspace, clock=clock)
    second_store = SemanticSnapshotStore(workspace, clock=clock)
    first = first_store.capture(_context(workspace), history_reference=1)
    second = second_store.capture(_context(workspace), history_reference=2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = tuple(executor.map(lambda item: item[0].save(item[1]), (
            (first_store, first),
            (second_store, second),
        )))

    assert len(set(paths)) == 2
    assert len(first_store.list()) == 2
    loaded_ids = {
        loaded.snapshot_id
        for path in first_store.list()
        if (loaded := first_store.load(path)) is not None
    }
    assert loaded_ids == {first.snapshot_id, second.snapshot_id}
    latest = first_store.load()
    assert latest is not None
    assert latest.snapshot_id in loaded_ids
