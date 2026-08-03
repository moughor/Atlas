"""Measure recovery checkpoint behavior without reusing CLI recovery artifacts.

This diagnostic runner deliberately isolates every sample's PR70 state and PR74
journal.  It measures the recovery/execution pipeline only; semantic snapshot and
history publication remain outside the timed scope and are covered by the canonical
repository benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter_ns, process_time_ns
from typing import Any

from moughorai.ai_context import (
    AnalyzerRegistry,
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.measurement import MeasurementConfig, MeasurementSession
from moughorai.workspace import (
    WorkspaceAnalysisOrchestrator,
    WorkspaceRecoveryManager,
    WorkspaceService,
    WorkspaceStateStore,
)


_BENCHMARK_LABEL = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_DETERMINISTIC_SAMPLE_FIELDS = (
    "mode",
    "cache_state",
    "measurement_scope",
    "profile_enabled",
    "process_memory_enabled",
    "project_count",
    "succeeded",
    "status_counts",
    "analysis_order_sha256",
    "report_sha256",
    "results_sha256",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _label(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("benchmark label must be a string")
    normalized = value.strip().casefold()
    if normalized != value or _BENCHMARK_LABEL.fullmatch(normalized) is None:
        raise ValueError(
            "benchmark label must be a lowercase portable identifier"
        )
    return normalized


def _validate_output_location(root: Path, output: Path) -> None:
    """Reject output that could become part of the measured repository."""

    if root == output or output.is_relative_to(root):
        raise ValueError("benchmark output must be outside the repository root")


def _deterministic_report(report: Any) -> dict[str, object]:
    """Return report evidence with operational durations removed."""

    runs = []
    for run in report.runs:
        value = run.to_dict()
        value.pop("duration_ms", None)
        runs.append(value)
    return {
        "succeeded": report.succeeded,
        "requested": list(report.requested),
        "analysis_order": list(report.analysis_order),
        "runs": runs,
    }


def _deterministic_sample(sample: dict[str, object]) -> dict[str, object]:
    evidence = {name: sample[name] for name in _DETERMINISTIC_SAMPLE_FIELDS}
    for optional in ("filesystem", "sampling"):
        if optional in sample:
            evidence[optional] = sample[optional]
    artifacts = sample.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("sample artifacts must be an object")
    # Raw state, journal, and measurement bytes contain operational timestamps or
    # observations.  Their presence is deterministic; their hashes and sizes are
    # deliberately not semantic gates.
    evidence["artifact_kinds"] = sorted(artifacts)
    return evidence


def _require_deterministic_samples(
    samples: list[dict[str, object]],
) -> str:
    if not samples:
        raise ValueError("benchmark must contain at least one sample")
    expected = _deterministic_sample(samples[0])
    expected_digest = _digest(expected)
    for index, sample in enumerate(samples[1:], start=2):
        observed = _deterministic_sample(sample)
        if observed != expected:
            raise RuntimeError(
                "benchmark deterministic evidence changed in sample "
                f"{index}: {expected_digest} != {_digest(observed)}"
            )
    return expected_digest


def run_sample(
    root: Path,
    sample_dir: Path,
    *,
    recovery: bool,
    profile: bool,
    profile_memory: bool,
) -> dict[str, object]:
    """Run one fresh, single-worker sample and return source-free evidence."""

    for name, value in (
        ("recovery", recovery),
        ("profile", profile),
        ("profile_memory", profile_memory),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be a boolean")
    if profile_memory and not profile:
        raise ValueError("profile_memory requires profile")
    root = root.expanduser().resolve()
    sample_dir = sample_dir.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"repository root does not exist: {root}")
    _validate_output_location(root, sample_dir)
    if sample_dir.exists():
        raise FileExistsError(f"sample output already exists: {sample_dir}")
    sample_dir.mkdir(parents=True)
    measurement = MeasurementSession(MeasurementConfig(
        enabled=profile,
        capture_process_memory=profile_memory,
        worker_metrics_supported=True,
    ))
    service = WorkspaceService(root, measurement=measurement)
    orchestrator = WorkspaceAnalysisOrchestrator(service)
    analyzer = AnalyzerRegistry(measurement=measurement)
    state_path = sample_dir / "workspace-state.json"
    journal_path = sample_dir / "workspace-recovery.json"
    state_store = WorkspaceStateStore(
        service,
        path=state_path,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )

    # Workspace discovery is intentionally outside this benchmark's timed and
    # measured scope.  Clear the run-local observations produced while creating
    # the service so the sidecar and external clocks describe the same boundary.
    measurement.clear()
    wall_start = perf_counter_ns()
    cpu_start = process_time_ns()
    if recovery:
        manager = WorkspaceRecoveryManager(
            service,
            path=journal_path,
            state_store=state_store,
            encoder=encode_analysis_result,
            decoder=decode_analysis_result,
        )
        report, _ = manager.resume(orchestrator, analyzer, max_workers=1)
        if report is None:
            report = manager.execute(
                orchestrator,
                analyzer,
                projects=list(service.workspace.names()),
                force=True,
                max_workers=1,
            )
    else:
        report = orchestrator.execute(
            analyzer,
            projects=service.workspace.names(),
            force=True,
            max_workers=1,
        )
    cpu_time_ns = process_time_ns() - cpu_start
    wall_time_ns = perf_counter_ns() - wall_start

    encoded_results = {
        name: encode_analysis_result(value)
        for name, value in sorted(orchestrator._results.items())
    }
    status_counts: dict[str, int] = {}
    for run in report.runs:
        status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
    result: dict[str, object] = {
        "mode": "recovery-on" if recovery else "recovery-off",
        "cache_state": "filesystem-warm-or-uncontrolled",
        "measurement_scope": "workspace-recovery-execution",
        "profile_enabled": profile,
        "process_memory_enabled": profile_memory,
        "project_count": len(report.runs),
        "succeeded": report.succeeded,
        "status_counts": dict(sorted(status_counts.items())),
        "analysis_order_sha256": _digest([run.project for run in report.runs]),
        "report_sha256": _digest(_deterministic_report(report)),
        "results_sha256": _digest(encoded_results),
        "wall_time_ns": wall_time_ns,
        "process_cpu_time_ns": cpu_time_ns,
        "artifacts": {},
    }
    artifacts = result["artifacts"]
    if not isinstance(artifacts, dict):
        raise RuntimeError("benchmark artifact collection was not initialized")
    for label, path in (("state", state_path), ("journal", journal_path)):
        if path.exists():
            artifacts[label] = _file_record(path)

    if profile:
        measurement_path = sample_dir / "measurement.json"
        measurement_report = measurement.report()
        measurement_path.write_text(
            measurement_report.to_json(),
            encoding="utf-8",
            newline="\n",
        )
        artifacts["measurement"] = _file_record(measurement_path)
        result["filesystem"] = measurement_report.filesystem.to_dict()
        result["sampling"] = measurement_report.sampling.to_dict()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--recovery", choices=("on", "off"), required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--profile-memory", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.profile_memory and not args.profile:
        parser.error("--profile-memory requires --profile")
    root = args.root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"repository root does not exist: {root}")
    try:
        label = _label(args.label)
        _validate_output_location(root, output)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    bundle_path = output / f"{label}-{args.recovery}.json"
    sample_dirs = tuple(
        output / f"{label}-{args.recovery}-{index:02d}"
        for index in range(1, args.runs + 1)
    )
    existing = [path for path in (*sample_dirs, bundle_path) if path.exists()]
    if existing:
        parser.error("benchmark output already exists")
    output.mkdir(parents=True, exist_ok=True)

    samples = []
    for sample_dir in sample_dirs:
        samples.append(run_sample(
            root,
            sample_dir,
            recovery=args.recovery == "on",
            profile=args.profile,
            profile_memory=args.profile_memory,
        ))
    deterministic_evidence = _require_deterministic_samples(samples)
    bundle = {
        "schema_version": 1,
        "runner": "atlas-m2.1-recovery",
        "benchmark_id": label,
        "deterministic_evidence_sha256": deterministic_evidence,
        "samples": samples,
    }
    bundle_path.write_bytes(_canonical(bundle) + b"\n")
    print(json.dumps(bundle, sort_keys=True, indent=2))
    return 0 if all(bool(sample["succeeded"]) for sample in samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
