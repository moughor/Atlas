from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.measurement import (
    MeasurementConfig,
    MeasurementPhase,
    MeasurementSession,
)
from moughorai.history import HistoryDatabase


runner = CliRunner()


@pytest.fixture(autouse=True)
def deterministic_analyzer() -> None:
    previous = atlas_cli._analyzer_factory
    atlas_cli._analyzer_factory = lambda _service: (
        lambda project, _dependencies: {"project": project.name}
    )
    yield
    atlas_cli._analyzer_factory = previous


def workspace(root: Path) -> Path:
    project = root / "core"
    project.mkdir(parents=True)
    (project / "main.txt").write_text("fixture\n", encoding="utf-8")
    (root / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n"
        "    path: core\n",
        encoding="utf-8",
    )
    return root


def test_analyze_help_exposes_opt_in_measurement_options() -> None:
    result = runner.invoke(app, ["analyze", "--help"])

    assert result.exit_code == 0
    assert "--profile" in result.stdout
    assert "--profile-output" in result.stdout
    assert "--profile-memory" in result.stdout
    assert "Collect Python" in result.stdout


def test_profile_preserves_stdout_and_writes_default_sidecar(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    expected = "core: succeeded\nprojects: 1\nsucceeded: yes\n"

    result = runner.invoke(
        app,
        ["analyze", str(root), "--no-recover", "--profile"],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == expected
    target = root / ".atlas" / "measurements" / "latest.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["producer"] == "atlas-performance-measurement/1.0"
    assert payload["samples"]
    assert "profile: samples=" in result.stderr
    assert "output=default" in result.stderr
    assert str(root.resolve()).replace("\\", "/") not in result.stderr.replace("\\", "/")
    assert len(HistoryDatabase(root).list()) == 1
    assert HistoryDatabase(root).list_adaptive_eligible() == ()


def test_profile_output_implies_collection_and_is_source_free(tmp_path: Path) -> None:
    root = workspace(tmp_path / "workspace")
    target = tmp_path / "artifacts" / "atlas-profile.json"

    result = runner.invoke(
        app,
        [
            "analyze",
            str(root),
            "--no-recover",
            "--profile-output",
            str(target),
        ],
    )

    assert result.exit_code == 0, result.stderr
    text = target.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert list(payload) == sorted(payload)
    assert {
        "aggregates",
        "filesystem",
        "phase_ids",
        "producer",
        "sampling",
        "samples",
        "schema_version",
    } <= set(payload)
    assert str(root.resolve()).replace("\\", "/") not in text.replace("\\", "/")
    assert "fixture" not in text
    assert not tuple(target.parent.glob(f"{target.name}.*.tmp"))
    assert "output=custom" in result.stderr
    assert str(target.resolve()).replace("\\", "/") not in result.stderr.replace("\\", "/")


def test_profile_memory_is_explicit_and_does_not_change_stdout(tmp_path: Path) -> None:
    root = workspace(tmp_path / "workspace")
    target = tmp_path / "memory.json"

    result = runner.invoke(
        app,
        [
            "analyze",
            str(root),
            "--no-recover",
            "--profile-memory",
            "--profile-output",
            str(target),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == "core: succeeded\nprojects: 1\nsucceeded: yes\n"
    payload = json.loads(target.read_text(encoding="utf-8"))
    rss = [
        sample["metrics"]["rss_bytes"]
        for sample in payload["samples"]
        if "rss_bytes" in sample["metrics"]
    ]
    assert rss
    assert {item["status"] for item in rss} <= {
        "measured",
        "unavailable",
        "unsupported",
    }
    assert "profile-memory:" in result.stderr


def test_profile_python_memory_is_opt_in_and_releases_owned_tracer(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path / "workspace")
    target = tmp_path / "python-memory.json"
    was_tracing = atlas_cli.tracemalloc.is_tracing()

    result = runner.invoke(
        app,
        [
            "analyze",
            str(root),
            "--no-recover",
            "--profile-python-memory",
            "--profile-output",
            str(target),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert atlas_cli.tracemalloc.is_tracing() is was_tracing
    payload = json.loads(target.read_text(encoding="utf-8"))
    python_peaks = [
        sample["metrics"]["python_peak_allocated_bytes"]
        for sample in payload["samples"]
        if "python_peak_allocated_bytes" in sample["metrics"]
    ]
    assert python_peaks
    assert {item["status"] for item in python_peaks} == {"measured"}
    assert "profile-python-memory: maximum_sampled_peak_bytes=" in result.stderr


def test_python_memory_collection_does_not_stop_a_preexisting_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = []
    monkeypatch.setattr(atlas_cli.tracemalloc, "is_tracing", lambda: True)
    monkeypatch.setattr(atlas_cli.tracemalloc, "start", lambda: pytest.fail("unexpected start"))
    monkeypatch.setattr(atlas_cli.tracemalloc, "stop", lambda: stopped.append(True))

    with atlas_cli._python_memory_collection(True):
        pass

    assert stopped == []


def test_overlapping_python_memory_contexts_share_tracer_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracing = False
    calls: list[str] = []

    def is_tracing() -> bool:
        return tracing

    def start() -> None:
        nonlocal tracing
        tracing = True
        calls.append("start")

    def stop() -> None:
        nonlocal tracing
        tracing = False
        calls.append("stop")

    monkeypatch.setattr(atlas_cli.tracemalloc, "is_tracing", is_tracing)
    monkeypatch.setattr(atlas_cli.tracemalloc, "start", start)
    monkeypatch.setattr(atlas_cli.tracemalloc, "stop", stop)

    first = atlas_cli._python_memory_collection(True)
    second = atlas_cli._python_memory_collection(True)
    with first:
        with second:
            assert tracing is True
        assert tracing is True
    assert calls == ["start", "stop"]


@dataclass(frozen=True)
class _FrozenApplicationError(Exception):
    message: str


def test_python_memory_context_preserves_frozen_application_exceptions() -> None:
    with pytest.raises(_FrozenApplicationError, match="application failure"):
        with atlas_cli._python_memory_collection(False):
            raise _FrozenApplicationError("application failure")


def test_ai_explain_profile_records_projection_without_changing_stdout(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    snapshot = Path(__file__).parent / "fixtures" / "semantic_snapshot_v1_minimal.ass"
    baseline = runner.invoke(
        app,
        ["ai", "explain", str(root), "--snapshot", str(snapshot)],
    )
    assert baseline.exit_code == 0, baseline.stderr

    result = runner.invoke(
        app,
        [
            "ai",
            "explain",
            str(root),
            "--snapshot",
            str(snapshot),
            "--profile",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == baseline.stdout
    payload = json.loads(
        (root / ".atlas" / "measurements" / "latest-explain.json").read_text(
            encoding="utf-8"
        )
    )
    assert MeasurementPhase.EXPLAIN_PROJECTION.value in {
        item["phase_id"] for item in payload["samples"]
    }
    serialized = json.dumps(payload)
    assert str(root.resolve()).replace("\\", "/") not in serialized.replace("\\", "/")
    assert "fixture" not in serialized


def test_atomic_sidecar_failure_preserves_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "measurement.json"
    session = MeasurementSession(MeasurementConfig(enabled=True))
    with session.scope(MeasurementPhase.PUBLICATION):
        pass
    original = session.report().to_json()
    target.write_text(original, encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(atlas_cli.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        atlas_cli._write_measurement_report(target, session.report())

    assert target.read_text(encoding="utf-8") == original
    assert not tuple(tmp_path.glob("measurement.json.*.tmp"))


def test_profile_output_cannot_enter_semantic_workspace_inputs(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path / "workspace")
    source_target = root / "profile.json"

    result = runner.invoke(
        app,
        [
            "analyze",
            str(root),
            "--no-recover",
            "--profile-output",
            str(source_target),
        ],
    )

    assert result.exit_code == 2
    assert "must be under .atlas/measurements" in result.stderr
    assert not source_target.exists()


def test_sidecar_writer_refuses_to_replace_unrelated_json(tmp_path: Path) -> None:
    target = tmp_path / "important.json"
    target.write_text('{"application":"data"}\n', encoding="utf-8")
    session = MeasurementSession(MeasurementConfig(enabled=True))

    with pytest.raises(ValueError, match="refusing to replace"):
        atlas_cli._write_measurement_report(target, session.report())

    assert target.read_text(encoding="utf-8") == '{"application":"data"}\n'


def test_sidecar_publication_failure_does_not_change_successful_analysis(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path / "workspace")
    target = tmp_path / "output.json"
    target.mkdir()

    result = runner.invoke(
        app,
        [
            "analyze",
            str(root),
            "--no-recover",
            "--profile-output",
            str(target),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == "core: succeeded\nprojects: 1\nsucceeded: yes\n"
    assert "profile: unavailable (sidecar-publication-failed)" in result.stderr


def test_sidecar_failure_does_not_mask_explain_failure(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "output.json"
    target.mkdir()

    result = runner.invoke(
        app,
        [
            "ai",
            "explain",
            str(root),
            "--snapshot",
            str(root / "missing.ass"),
            "--profile-output",
            str(target),
        ],
    )

    assert result.exit_code == 2
    assert "snapshot" in result.stderr.casefold()
    assert "profile: unavailable (sidecar-publication-failed)" in result.stderr
