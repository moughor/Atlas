from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_ask import AskResult, CitationValidation
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.llm import ScriptedLlmProvider
from moughorai.semantic_snapshot import (
    ACTIVE_SNAPSHOT_FORMAT,
    ACTIVE_SNAPSHOT_SCHEMA_VERSION,
    AtlasSemanticSnapshot,
    SemanticSnapshotError,
    SemanticSnapshotStore,
    SnapshotResolutionMethod,
    SnapshotResolver,
)
from moughorai.workspace import Workspace


runner = CliRunner()
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def _snapshot(root: Path, directory: Path, marker: str) -> tuple[Path, AtlasSemanticSnapshot]:
    root.mkdir(parents=True, exist_ok=True)
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "marker": marker,
            "semantic_graph": {"nodes": [], "edges": []},
        }),
        workspace_fingerprint=f"workspace:{marker}",
        analyzer_version="test-pr160/1",
        history_reference=marker,
    )
    store = SemanticSnapshotStore(
        Workspace(root, ()),
        directory=directory,
        clock=lambda: NOW,
    )
    store.save(snapshot)
    return store.latest_path, snapshot


def _register_payload(
    root: Path,
    entries: list[tuple[Path, str]],
) -> dict[str, object]:
    return {
        "format": ACTIVE_SNAPSHOT_FORMAT,
        "schema_version": ACTIVE_SNAPSHOT_SCHEMA_VERSION,
        "workspace_root": root.resolve().as_posix(),
        "snapshots": [
            {"path": path.resolve().as_posix(), "snapshot_id": snapshot_id}
            for path, snapshot_id in entries
        ],
    }


def test_resolution_precedence_and_workspace_default(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    default_path, default = _snapshot(
        root, root / ".atlas" / "ass", "default",
    )
    active_path, active = _snapshot(
        root, tmp_path / "saved" / "ass", "active",
    )
    explicit_path, explicit = _snapshot(
        root, tmp_path / "explicit" / "ass", "explicit",
    )
    resolver = SnapshotResolver(root)

    initial = resolver.resolve()
    assert initial.snapshot == default
    assert initial.snapshot_path == default_path.resolve()
    assert initial.method is SnapshotResolutionMethod.WORKSPACE_DEFAULT

    activated = resolver.activate(active_path)
    assert activated.snapshot == active
    configured = resolver.resolve()
    assert configured.snapshot == active
    assert configured.method is SnapshotResolutionMethod.CONFIGURED_ACTIVE

    selected = resolver.resolve(explicit_path)
    assert selected.snapshot == explicit
    assert selected.method is SnapshotResolutionMethod.EXPLICIT
    assert selected.explicit is True


def test_explicit_missing_or_invalid_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    active_path, _active = _snapshot(
        root, tmp_path / "saved" / "ass", "active",
    )
    resolver = SnapshotResolver(root)
    resolver.activate(active_path)

    with pytest.raises(SemanticSnapshotError, match="does not exist") as missing:
        resolver.resolve(tmp_path / "missing.ass")
    assert "--snapshot supplied: true" in str(missing.value)
    assert "does not fall back" in str(missing.value)

    directory = tmp_path / "snapshot-directory"
    directory.mkdir()
    with pytest.raises(SemanticSnapshotError, match="expected a file"):
        resolver.resolve(directory)

    invalid = tmp_path / "invalid.ass"
    invalid.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SemanticSnapshotError, match="could not be verified"):
        resolver.resolve(invalid)


def test_invalid_or_changed_active_registration_does_not_fallback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    default_path, default = _snapshot(
        root, root / ".atlas" / "ass", "default",
    )
    active_path, _active = _snapshot(
        root, tmp_path / "saved" / "ass", "active",
    )
    resolver = SnapshotResolver(root)
    resolver.activate(active_path)
    active_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(SemanticSnapshotError, match="does not fall back"):
        resolver.resolve()

    active_path.write_bytes(default_path.read_bytes())
    with pytest.raises(SemanticSnapshotError, match="identity mismatch"):
        resolver.resolve()
    assert SemanticSnapshotStore(Workspace(root, ())).load() == default


def test_ambiguous_registration_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    first_path, first = _snapshot(root, tmp_path / "first", "first")
    second_path, second = _snapshot(root, tmp_path / "second", "second")
    resolver = SnapshotResolver(root)
    resolver.registration_path.parent.mkdir(parents=True)
    resolver.registration_path.write_text(
        json.dumps(_register_payload(root, [
            (first_path, first.snapshot_id),
            (second_path, second.snapshot_id),
        ])),
        encoding="utf-8",
    )

    with pytest.raises(SemanticSnapshotError, match="ambiguous.*found 2"):
        resolver.resolve()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", True, "format or schema"),
        ("schema_version", "1", "format or schema"),
        ("workspace_root", "relative-workspace", "must be absolute"),
    ),
)
def test_registration_metadata_is_strict(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    root = tmp_path / "workspace"
    path, snapshot = _snapshot(root, tmp_path / "saved", "saved")
    resolver = SnapshotResolver(root)
    payload = _register_payload(root, [(path, snapshot.snapshot_id)])
    payload[field] = value
    resolver.registration_path.parent.mkdir(parents=True)
    resolver.registration_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SemanticSnapshotError, match=message):
        resolver.resolve()


def test_resolver_never_searches_arbitrary_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    _snapshot(root, tmp_path / "arbitrary" / "nested", "ignored")

    def forbidden_search(*_args, **_kwargs):
        raise AssertionError("recursive filesystem search was attempted")

    monkeypatch.setattr(Path, "rglob", forbidden_search)
    with pytest.raises(SemanticSnapshotError, match="canonical expected path"):
        SnapshotResolver(root).resolve()


def test_registration_is_workspace_local_source_safe_and_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    root = parent / "workspace with spaces"
    source = root / "src" / "Main.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Main {}\n", encoding="utf-8")
    saved_path, saved = _snapshot(root, tmp_path / "saved path" / "ass", "saved")
    monkeypatch.chdir(parent)
    resolver = SnapshotResolver(Path("workspace with spaces"))
    activation = runner.invoke(app, [
        "snapshot", "activate", str(saved_path),
        "--root", str(root),
        "--json",
    ])
    assert activation.exit_code == 0, activation.stderr
    activation_payload = json.loads(activation.stdout)
    resolution = resolver.resolve()

    assert resolver.workspace_root == root.resolve()
    assert resolution.snapshot_path == saved_path.resolve()
    assert resolution.to_dict()["snapshot_path"] == saved_path.resolve().as_posix()
    assert resolution.to_dict()["workspace_root"] == root.resolve().as_posix()
    assert source.read_text(encoding="utf-8") == "class Main {}\n"
    assert resolver.registration_path == root / ".atlas" / "active-snapshot.json"
    payload = json.loads(resolver.registration_path.read_text(encoding="utf-8"))
    assert payload == _register_payload(root, [(saved_path, saved.snapshot_id)])
    assert activation_payload == {
        **resolution.to_dict(),
        "registration_path": resolver.registration_path.as_posix(),
    }

    status = runner.invoke(app, [
        "snapshot", "status", "--root", str(root), "--json",
    ])
    assert status.exit_code == 0, status.stderr
    assert json.loads(status.stdout) == resolution.to_dict()


def test_code_impact_and_explain_share_active_resolution(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    saved_path, snapshot = _snapshot(root, tmp_path / "saved" / "ass", "shared")
    SnapshotResolver(root).activate(saved_path)

    code = runner.invoke(app, [
        "code-impact", "method:not-represented", str(root), "--json",
    ])
    explain = runner.invoke(app, [
        "ai", "explain", str(root), "--json",
    ])
    assert code.exit_code == explain.exit_code == 0
    expected = (
        f"snapshot: {saved_path.resolve()}\n"
        "snapshot-resolution: configured-active\n"
        f"snapshot-id: {snapshot.snapshot_id}\n"
    )
    assert code.stderr == explain.stderr == expected


def test_ai_ask_uses_active_resolution_without_provider_guessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    saved_path, snapshot = _snapshot(root, tmp_path / "saved" / "ass", "ask")
    SnapshotResolver(root).activate(saved_path)
    captured: list[AtlasSemanticSnapshot] = []

    class CapturingAskEngine:
        def __init__(self, _client, *, memory) -> None:
            assert memory is not None

        def ask(self, loaded, request):
            captured.append(loaded)
            return AskResult(
                "Deterministic answer",
                loaded.snapshot_id,
                request.conversation_id,
                citations=CitationValidation(),
                provider="scripted",
                model="test",
            )

    monkeypatch.setattr(atlas_cli, "AskEngine", CapturingAskEngine)
    monkeypatch.setattr(
        atlas_cli,
        "_ai_provider_factory",
        lambda: ScriptedLlmProvider(()),
    )
    result = runner.invoke(app, [
        "ai", "ask", "What snapshot is active?", str(root), "--json",
    ])

    assert result.exit_code == 0, result.stderr
    assert captured == [snapshot]
    assert "snapshot-resolution: configured-active" in result.stderr
    assert str(saved_path.resolve()) in result.stderr


def test_missing_failure_is_actionable_and_reports_considered_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "relative-root"
    result = runner.invoke(app, [
        "code-impact", "method:missing", str(root), "--json",
    ])

    assert result.exit_code == 2
    assert str(root.resolve()) in result.stderr
    assert str((root / ".atlas" / "ass" / "latest.ass").resolve()) in result.stderr
    assert "--snapshot supplied: false" in result.stderr
    assert "run analyze" in result.stderr
    assert "provide --snapshot" in result.stderr
