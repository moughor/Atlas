from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from benchmarks import benchmark_m21_recovery as benchmark
from moughorai.workspace import (
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
)


_SOURCE_MARKER = "m21-private-source-marker"


def _workspace(root: Path) -> Path:
    source = root / "module"
    source.mkdir(parents=True)
    (source / "app.py").write_text(
        f"value: int = 1  # {_SOURCE_MARKER}\n",
        encoding="utf-8",
    )
    (root / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: app\n"
        "    path: module\n"
        "    include: ['**/*.py']\n",
        encoding="utf-8",
    )
    return root


def _assert_source_free(value: object, root: Path) -> None:
    encoded = json.dumps(value, sort_keys=True)
    normalized = encoded.replace("\\", "/")
    assert str(root.resolve()).replace("\\", "/") not in normalized
    assert root.name not in encoded
    assert _SOURCE_MARKER not in encoded


def test_profiled_samples_are_source_free_and_semantically_deterministic(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path / "private-repository-name")

    first = benchmark.run_sample(
        root,
        tmp_path / "results" / "first",
        recovery=False,
        profile=True,
        profile_memory=False,
    )
    second = benchmark.run_sample(
        root,
        tmp_path / "results" / "second",
        recovery=False,
        profile=True,
        profile_memory=False,
    )

    assert first["succeeded"] is True
    assert benchmark._require_deterministic_samples([first, second]) == (
        benchmark._require_deterministic_samples([second, first])
    )
    _assert_source_free(first, root)
    measurement = json.loads(
        (tmp_path / "results" / "first" / "measurement.json").read_text(
            encoding="utf-8"
        )
    )
    _assert_source_free(measurement, root)
    assert all(
        sample["phase_id"] != "workspace.discovery"
        for sample in measurement["samples"]
    )
    assert all(
        consumer["consumer"] != "workspace-discovery"
        for consumer in measurement["filesystem"]["consumers"]
    )


def test_recovery_sample_uses_the_production_resume_boundary(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path / "private-recovery-repository")
    off = benchmark.run_sample(
        root,
        tmp_path / "results" / "off",
        recovery=False,
        profile=True,
        profile_memory=False,
    )
    on = benchmark.run_sample(
        root,
        tmp_path / "results" / "on",
        recovery=True,
        profile=True,
        profile_memory=False,
    )

    assert on["succeeded"] is True
    assert (
        on["analysis_order_sha256"],
        on["report_sha256"],
        on["results_sha256"],
    ) == (
        off["analysis_order_sha256"],
        off["report_sha256"],
        off["results_sha256"],
    )
    assert set(on["artifacts"]) == {"journal", "measurement", "state"}
    measurement = json.loads(
        (tmp_path / "results" / "on" / "measurement.json").read_text(
            encoding="utf-8"
        )
    )
    recovery_samples = [
        sample for sample in measurement["samples"]
        if sample["phase_id"] == "recovery"
    ]
    assert recovery_samples
    assert any(
        sample["metrics"]["bytes_processed"]["status"] == "unavailable"
        for sample in recovery_samples
    )
    _assert_source_free(on, root)


def test_report_digest_excludes_operational_duration() -> None:
    first = WorkspaceRunReport(
        (
            ProjectRun(
                "app",
                ProjectRunStatus.SUCCEEDED,
                value={"value": 1},
                duration_ms=1.0,
            ),
        ),
        ("app",),
        ("app",),
    )
    second = WorkspaceRunReport(
        (
            ProjectRun(
                "app",
                ProjectRunStatus.SUCCEEDED,
                value={"value": 1},
                duration_ms=999.0,
            ),
        ),
        ("app",),
        ("app",),
    )

    assert benchmark._digest(benchmark._deterministic_report(first)) == (
        benchmark._digest(benchmark._deterministic_report(second))
    )


def test_determinism_gate_ignores_raw_operational_artifacts() -> None:
    sample = {
        "mode": "recovery-on",
        "cache_state": "filesystem-warm-or-uncontrolled",
        "measurement_scope": "workspace-recovery-execution",
        "profile_enabled": True,
        "process_memory_enabled": False,
        "project_count": 1,
        "succeeded": True,
        "status_counts": {"succeeded": 1},
        "analysis_order_sha256": "a" * 64,
        "report_sha256": "b" * 64,
        "results_sha256": "c" * 64,
        "wall_time_ns": 1,
        "process_cpu_time_ns": 2,
        "artifacts": {"journal": {"bytes": 10, "sha256": "d" * 64}},
    }
    repeated = json.loads(json.dumps(sample))
    repeated["wall_time_ns"] = 999
    repeated["artifacts"]["journal"] = {"bytes": 11, "sha256": "e" * 64}

    assert benchmark._require_deterministic_samples([sample, repeated])
    repeated["results_sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="deterministic evidence changed"):
        benchmark._require_deterministic_samples([sample, repeated])


def test_portable_label_and_output_boundaries(tmp_path: Path) -> None:
    root = _workspace(tmp_path / "repository")
    assert benchmark._label("apache-maven") == "apache-maven"
    for invalid in ("Apache-Maven", "../maven", "maven/path", " maven"):
        with pytest.raises(ValueError, match="portable identifier"):
            benchmark._label(invalid)
    with pytest.raises(ValueError, match="outside"):
        benchmark._validate_output_location(root.resolve(), root.resolve() / "out")
    benchmark._validate_output_location(
        root.resolve(),
        (tmp_path / "results").resolve(),
    )
    with pytest.raises(ValueError, match="requires profile"):
        benchmark.run_sample(
            root,
            tmp_path / "invalid",
            recovery=False,
            profile=False,
            profile_memory=True,
        )


def test_cli_bundle_uses_logical_identity_without_repository_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path / "private-cli-repository")
    output = tmp_path / "bundles"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_m21_recovery",
            str(root),
            str(output),
            "--label",
            "fixture",
            "--recovery",
            "off",
        ],
    )

    assert benchmark.main() == 0
    bundle = json.loads(capsys.readouterr().out)
    assert bundle["benchmark_id"] == "fixture"
    assert "repository_identity" not in bundle
    assert len(bundle["deterministic_evidence_sha256"]) == 64
    _assert_source_free(bundle, root)
    raw = (output / "fixture-off.json").read_bytes()
    assert raw == benchmark._canonical(bundle) + b"\n"
    assert len(hashlib.sha256(raw).hexdigest()) == 64
