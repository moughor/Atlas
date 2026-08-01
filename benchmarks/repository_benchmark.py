"""Run or replay a repository benchmark and emit an M1 stability manifest."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Mapping

from moughorai.version import __version__

from .stability_manifest import (
    BenchmarkManifest,
    BenchmarkMode,
    ComparisonStatus,
    ResultsSource,
    SnapshotArtifacts,
    canonical_digest,
    collect_snapshot_artifacts,
    compare_manifests,
    utc_observation_time,
)


_ATLAS_ROOT = Path(__file__).resolve().parents[1]


def capture_analysis(
    repository_root: Path,
    *,
    repository_name: str,
    expected_repository_commit: str | None = None,
    checkout_identity: str | None = None,
    repeats: int = 3,
    workers: int = 1,
    timeout_seconds: int = 7_200,
    observed_at_utc: str | None = None,
    allow_unpinned: bool = False,
) -> BenchmarkManifest:
    """Run the normal production analysis path and verify repeatable semantics."""

    root = repository_root.expanduser().resolve()
    _positive(repeats, "benchmark repeats")
    _positive(workers, "benchmark workers")
    _positive(timeout_seconds, "analysis timeout")
    repository_commit, verified, git_backed, limitations = _repository_identity(
        root,
        expected_repository_commit,
        allow_unpinned=allow_unpinned,
    )
    atlas_commit = _atlas_commit()
    if checkout_identity is None:
        limitations.append(
            "A controlled checkout identity was not declared; path-scoped semantic "
            "hashes are not eligible for a golden baseline."
        )
    durations: list[int] = []
    artifacts: list[SnapshotArtifacts] = []
    project_counts: list[int] = []
    success_counts: list[int] = []
    failure_counts: list[int] = []
    for _ in range(repeats):
        started = perf_counter()
        report = _run_analysis(
            root,
            workers=workers,
            timeout_seconds=timeout_seconds,
        )
        durations.append(max(1, round((perf_counter() - started) * 1_000)))
        project_count, success_count, failure_count, analysis_order = (
            _analysis_counts(report)
        )
        snapshot_path = root / ".atlas" / "ass" / "latest.ass"
        captured = collect_snapshot_artifacts(snapshot_path)
        captured = replace(
            captured,
            analysis_order_sha256=canonical_digest(analysis_order),
            analysis_report_sha256=canonical_digest(report),
        )
        if captured.project_count != project_count:
            raise RuntimeError(
                "analysis report and semantic snapshot project counts disagree"
            )
        artifacts.append(captured)
        project_counts.append(project_count)
        success_counts.append(success_count)
        failure_counts.append(failure_count)
    _require_one(project_counts, "project count")
    _require_one(success_counts, "success count")
    _require_one(failure_counts, "failure count")
    _verify_artifact_determinism(artifacts, exact_snapshot=False)
    _verify_repository_unchanged(
        root,
        repository_commit,
        git_backed=git_backed,
    )
    _verify_atlas_unchanged(atlas_commit)
    raw_hashes = {item.snapshot_sha256 for item in artifacts}
    if len(raw_hashes) > 1:
        limitations.append(
            "Raw snapshot hashes differ across fresh runs because run-specific "
            "history metadata participates in ASS identity; semantic gates matched."
        )
    return _manifest(
        benchmark_id=_benchmark_id(repository_name),
        mode=BenchmarkMode.FRESH_ANALYSIS,
        repository_name=repository_name,
        repository_commit=repository_commit,
        repository_revision_verified=verified,
        checkout_identity=checkout_identity,
        atlas_commit=atlas_commit,
        observed_at_utc=observed_at_utc,
        workers=workers,
        cache_mode="force-no-recover",
        measurement_scope="atlas-analyze-subprocess",
        analysis_duration_ms=tuple(durations),
        replay_duration_ms=(),
        project_count=project_counts[0],
        success_count=success_counts[0],
        failure_count=failure_counts[0],
        results_source=ResultsSource.ANALYSIS_REPORT,
        analysis_success_verified=True,
        source_manifest_sha256=None,
        artifacts=artifacts[-1],
        limitations=tuple(limitations),
    )


def capture_replay(
    snapshot_path: Path,
    *,
    repository_root: Path,
    repository_name: str,
    project_count: int,
    success_count: int,
    expected_repository_commit: str | None = None,
    checkout_identity: str | None = None,
    repeats: int = 3,
    observed_at_utc: str | None = None,
    allow_unpinned: bool = False,
    source_manifest: BenchmarkManifest | None = None,
) -> BenchmarkManifest:
    """Replay a checksum-verified ASS without claiming a fresh analysis."""

    _positive(repeats, "benchmark repeats")
    _non_negative(project_count, "project count")
    _non_negative(success_count, "success count")
    if success_count > project_count:
        raise ValueError("success count cannot exceed project count")
    root = repository_root.expanduser().resolve()
    repository_commit, verified, git_backed, limitations = _repository_identity(
        root,
        expected_repository_commit,
        allow_unpinned=allow_unpinned,
    )
    atlas_commit = _atlas_commit()
    if checkout_identity is None:
        limitations.append(
            "A controlled checkout identity was not declared; path-scoped semantic "
            "hashes are not eligible for a golden baseline."
        )
    durations: list[int] = []
    artifacts: list[SnapshotArtifacts] = []
    for _ in range(repeats):
        started = perf_counter()
        artifacts.append(collect_snapshot_artifacts(snapshot_path))
        durations.append(max(1, round((perf_counter() - started) * 1_000)))
    _verify_artifact_determinism(artifacts, exact_snapshot=True)
    _verify_repository_unchanged(
        root,
        repository_commit,
        git_backed=git_backed,
    )
    _verify_atlas_unchanged(atlas_commit)
    if artifacts[-1].project_count != project_count:
        raise ValueError("declared and snapshot project counts disagree")
    success_verified, source_hash = _replay_provenance(
        source_manifest,
        repository_name=repository_name,
        repository_commit=repository_commit,
        checkout_identity=checkout_identity,
        project_count=project_count,
        success_count=success_count,
        artifacts=artifacts[-1],
    )
    if success_verified:
        limitations.append(
            "Snapshot replay validates persisted output only; analysis duration was "
            "not reproduced. Project results are linked to the accepted fresh manifest."
        )
    else:
        limitations.append(
            "Snapshot replay validates persisted output only; analysis duration and "
            "per-project completion counts are declared historical observations, not "
            "reproduced evidence."
        )
    return _manifest(
        benchmark_id=_benchmark_id(repository_name),
        mode=BenchmarkMode.SNAPSHOT_REPLAY,
        repository_name=repository_name,
        repository_commit=repository_commit,
        repository_revision_verified=verified,
        checkout_identity=checkout_identity,
        atlas_commit=atlas_commit,
        observed_at_utc=observed_at_utc,
        workers=1,
        cache_mode="snapshot-replay",
        measurement_scope="ass-load-validate-hash-explain",
        analysis_duration_ms=(),
        replay_duration_ms=tuple(durations),
        project_count=project_count,
        success_count=success_count,
        failure_count=project_count - success_count,
        results_source=(
            ResultsSource.LINKED_FRESH_MANIFEST
            if success_verified
            else ResultsSource.DECLARED_HISTORICAL
        ),
        analysis_success_verified=success_verified,
        source_manifest_sha256=source_hash,
        artifacts=artifacts[-1],
        limitations=tuple(limitations),
    )


def _manifest(
    *,
    benchmark_id: str,
    mode: BenchmarkMode,
    repository_name: str,
    repository_commit: str | None,
    repository_revision_verified: bool,
    checkout_identity: str | None,
    atlas_commit: str,
    observed_at_utc: str | None,
    workers: int,
    cache_mode: str,
    measurement_scope: str,
    analysis_duration_ms: tuple[int, ...],
    replay_duration_ms: tuple[int, ...],
    project_count: int,
    success_count: int,
    failure_count: int,
    results_source: ResultsSource,
    analysis_success_verified: bool,
    source_manifest_sha256: str | None,
    artifacts: SnapshotArtifacts,
    limitations: tuple[str, ...],
) -> BenchmarkManifest:
    return BenchmarkManifest(
        benchmark_id=benchmark_id,
        mode=mode,
        repository_name=repository_name,
        repository_commit=repository_commit,
        repository_revision_verified=repository_revision_verified,
        checkout_identity=checkout_identity,
        atlas_commit=atlas_commit,
        atlas_version=__version__,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        os_name=platform.system(),
        os_release=platform.release(),
        architecture=platform.machine() or "unknown",
        observed_at_utc=observed_at_utc or utc_observation_time(),
        workers=workers,
        cache_mode=cache_mode,
        measurement_scope=measurement_scope,
        analysis_duration_ms=analysis_duration_ms,
        replay_duration_ms=replay_duration_ms,
        project_count=project_count,
        success_count=success_count,
        failure_count=failure_count,
        results_source=results_source,
        analysis_success_verified=analysis_success_verified,
        source_manifest_sha256=source_manifest_sha256,
        artifacts=artifacts,
        limitations=limitations,
    )


def _run_analysis(
    root: Path,
    *,
    workers: int,
    timeout_seconds: int,
) -> Mapping[str, object]:
    command = [
        sys.executable,
        "-B",
        "-m",
        "moughorai.atlas_cli",
        "analyze",
        str(root),
        "--force",
        "--no-recover",
        "--workers",
        str(workers),
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=_ATLAS_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Atlas analysis exited with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Atlas analysis did not emit valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("Atlas analysis report must be a JSON object")
    return payload


def _analysis_counts(
    report: Mapping[str, object],
) -> tuple[int, int, int, tuple[str, ...]]:
    if report.get("type") != "workspace-analysis":
        raise RuntimeError("Atlas analysis report has an unexpected type")
    if report.get("succeeded") is not True:
        raise RuntimeError("Atlas workspace analysis did not succeed")
    runs = report.get("runs")
    order = report.get("analysis_order")
    if not isinstance(runs, list) or not isinstance(order, list):
        raise RuntimeError("Atlas analysis report lacks runs or analysis order")
    statuses = []
    run_projects = []
    for run in runs:
        if not isinstance(run, Mapping):
            raise RuntimeError("Atlas analysis run entry must be an object")
        status = run.get("status")
        if status not in {"succeeded", "failed", "blocked", "reused", "cancelled"}:
            raise RuntimeError("Atlas analysis run status is invalid")
        project = run.get("project")
        if not isinstance(project, str) or not project.strip():
            raise RuntimeError("Atlas analysis run project must be a non-empty string")
        statuses.append(status)
        run_projects.append(project)
    analysis_order = tuple(
        item for item in order if isinstance(item, str) and item.strip()
    )
    if len(analysis_order) != len(order) or len(analysis_order) != len(runs):
        raise RuntimeError("Atlas analysis order is incomplete or inconsistent")
    if len(set(analysis_order)) != len(analysis_order):
        raise RuntimeError("Atlas analysis order contains duplicate project identities")
    if tuple(run_projects) != analysis_order:
        raise RuntimeError("Atlas run order and analysis order disagree")
    success = sum(status in {"succeeded", "reused"} for status in statuses)
    if not runs:
        raise RuntimeError("Atlas analysis report contains no projects")
    if success != len(runs):
        raise RuntimeError("Atlas analysis report contains a non-success project status")
    return len(runs), success, len(runs) - success, analysis_order


def _verify_artifact_determinism(
    values: list[SnapshotArtifacts],
    *,
    exact_snapshot: bool,
) -> None:
    if not values:
        raise ValueError("at least one benchmark artifact is required")
    for name in (
        "analysis_report_sha256",
        "semantic_payload_sha256",
        "repository_report_sha256",
        "explain_sha256",
        "project_count",
        "workspace_project_order_sha256",
        "analysis_order_sha256",
        *(
            ("snapshot_size_bytes", "snapshot_sha256", "snapshot_id")
            if exact_snapshot
            else ()
        ),
    ):
        _require_one([getattr(item, name) for item in values], name)


def _repository_identity(
    root: Path,
    expected: str | None,
    *,
    allow_unpinned: bool,
) -> tuple[str | None, bool, bool, list[str]]:
    if not root.is_dir():
        raise ValueError(f"benchmark repository does not exist: {root}")
    if expected is not None and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", expected) is None:
        raise ValueError("expected repository commit must be a full lowercase Git object ID")
    actual = _git_head(root)
    if actual is not None:
        if _git_top_level(root) != root:
            raise ValueError("benchmark repository root must be the Git top-level")
        if expected is not None and actual != expected:
            raise ValueError(
                f"benchmark repository commit mismatch: {actual} != {expected}"
            )
        dirty = _working_tree_status(root)
        if dirty:
            raise ValueError("benchmark repository has tracked or untracked modifications")
        if expected is not None:
            return actual, True, True, []
        if not allow_unpinned:
            raise ValueError(
                "benchmark repository commit was not explicitly pinned; pass "
                "--repository-commit or explicitly allow a provisional run"
            )
        return actual, False, True, [
            "Repository HEAD was recorded but not explicitly pinned by the benchmark "
            "invocation; this record is provisional and cannot become a golden baseline."
        ]
    if not allow_unpinned:
        raise ValueError(
            "benchmark repository has no verifiable Git commit; use a pinned clone "
            "or explicitly allow a provisional unpinned run"
        )
    return expected, False, False, [
        "Repository Git metadata is unavailable; this record is provisional and "
        "cannot become a golden baseline."
    ]


def _atlas_commit() -> str:
    commit = _git_head(_ATLAS_ROOT)
    if commit is None:
        raise ValueError("Atlas benchmark runner requires a Git checkout")
    if _git_top_level(_ATLAS_ROOT) != _ATLAS_ROOT:
        raise ValueError("Atlas benchmark runner root is not the Git top-level")
    dirty = _working_tree_status(_ATLAS_ROOT)
    if dirty:
        raise ValueError("Atlas worktree has tracked or untracked modifications")
    return commit


def _git_head(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    diagnostic = f"{completed.stdout}\n{completed.stderr}".casefold()
    if "not a git repository" in diagnostic:
        return None
    raise RuntimeError(
        "cannot resolve benchmark Git revision: "
        + (completed.stderr.strip() or completed.stdout.strip())
    )


def _git_required(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "benchmark Git command failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return completed.stdout.strip()


def _git_top_level(root: Path) -> Path:
    return Path(
        _git_required(root, "rev-parse", "--show-toplevel")
    ).resolve()


def _working_tree_status(root: Path) -> str:
    return _git_required(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude).atlas",
        ":(exclude).atlas/**",
    )


def _verify_repository_unchanged(
    root: Path,
    expected: str | None,
    *,
    git_backed: bool,
) -> None:
    actual = _git_head(root)
    if not git_backed:
        if actual is not None:
            raise RuntimeError("benchmark repository Git identity changed during capture")
        return
    if actual != expected:
        raise RuntimeError("benchmark repository commit changed during capture")
    if _working_tree_status(root):
        raise RuntimeError("benchmark repository changed during capture")


def _verify_atlas_unchanged(expected: str) -> None:
    actual = _git_head(_ATLAS_ROOT)
    if actual != expected:
        raise RuntimeError("Atlas commit changed during benchmark capture")
    if _working_tree_status(_ATLAS_ROOT):
        raise RuntimeError("Atlas worktree changed during benchmark capture")


def _replay_provenance(
    source: BenchmarkManifest | None,
    *,
    repository_name: str,
    repository_commit: str | None,
    checkout_identity: str | None,
    project_count: int,
    success_count: int,
    artifacts: SnapshotArtifacts,
) -> tuple[bool, str | None]:
    if source is None:
        return False, None
    if source.mode is not BenchmarkMode.FRESH_ANALYSIS or not source.baseline_eligible:
        raise ValueError("replay source must be an eligible fresh-analysis manifest")
    expected = (
        ("repository name", source.repository_name, repository_name),
        ("repository commit", source.repository_commit, repository_commit),
        ("checkout identity", source.checkout_identity, checkout_identity),
        ("project count", source.project_count, project_count),
        ("success count", source.success_count, success_count),
        (
            "snapshot hash",
            source.artifacts.snapshot_sha256,
            artifacts.snapshot_sha256,
        ),
    )
    mismatches = [
        f"{name}: {left!r} != {right!r}"
        for name, left, right in expected
        if left != right
    ]
    if mismatches:
        raise ValueError("replay source does not match artifact: " + "; ".join(mismatches))
    return True, canonical_digest(source.to_dict())


def _benchmark_id(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not result:
        raise ValueError("repository name must not be empty")
    return result


def _require_one(values: list[object], name: str) -> None:
    if len(set(values)) != 1:
        raise RuntimeError(f"benchmark {name} changed across repeated runs")


def _positive(value: object, name: str) -> None:
    _non_negative(value, name)
    if value == 0:
        raise ValueError(f"{name} must be positive")


def _non_negative(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _write(path: Path, value: str, *, overwrite: bool = False) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"benchmark output already exists: {target}; use --force-output to replace it"
        )
    descriptor, temporary = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary_path, target)
        else:
            try:
                os.link(temporary_path, target)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"benchmark output appeared during write: {target}"
                ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _emit(value: str, output: Path | None, *, overwrite: bool = False) -> None:
    if output is None:
        print(value, end="")
    else:
        _write(output, value, overwrite=overwrite)


def _common_capture_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository-name", required=True)
    parser.add_argument("--repository-commit")
    parser.add_argument("--checkout-identity")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--observed-at")
    parser.add_argument("--allow-unpinned", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force-output", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Run fresh Atlas analysis.")
    analyze.add_argument("repository_root", type=Path)
    analyze.add_argument("--workers", type=int, default=1)
    analyze.add_argument("--timeout-seconds", type=int, default=7_200)
    _common_capture_options(analyze)
    replay = commands.add_parser("replay", help="Replay an existing ASS artifact.")
    replay.add_argument("snapshot", type=Path)
    replay.add_argument("--repository-root", type=Path, required=True)
    replay.add_argument("--project-count", type=int, required=True)
    replay.add_argument("--success-count", type=int, required=True)
    replay.add_argument("--source-manifest", type=Path)
    _common_capture_options(replay)
    compare = commands.add_parser("compare", help="Compare two manifest records.")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("current", type=Path)
    compare.add_argument("--output", type=Path)
    compare.add_argument("--force-output", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.command == "analyze":
        result = capture_analysis(
            arguments.repository_root,
            repository_name=arguments.repository_name,
            expected_repository_commit=arguments.repository_commit,
            checkout_identity=arguments.checkout_identity,
            repeats=arguments.repeats,
            workers=arguments.workers,
            timeout_seconds=arguments.timeout_seconds,
            observed_at_utc=arguments.observed_at,
            allow_unpinned=arguments.allow_unpinned,
        )
        _emit(
            result.to_json(),
            arguments.output,
            overwrite=arguments.force_output,
        )
        return 0
    if arguments.command == "replay":
        result = capture_replay(
            arguments.snapshot,
            repository_root=arguments.repository_root,
            repository_name=arguments.repository_name,
            project_count=arguments.project_count,
            success_count=arguments.success_count,
            expected_repository_commit=arguments.repository_commit,
            checkout_identity=arguments.checkout_identity,
            repeats=arguments.repeats,
            observed_at_utc=arguments.observed_at,
            allow_unpinned=arguments.allow_unpinned,
            source_manifest=(
                None
                if arguments.source_manifest is None
                else BenchmarkManifest.from_json(
                    arguments.source_manifest.read_text(encoding="utf-8")
                )
            ),
        )
        _emit(
            result.to_json(),
            arguments.output,
            overwrite=arguments.force_output,
        )
        return 0
    baseline = BenchmarkManifest.from_json(arguments.baseline.read_text(encoding="utf-8"))
    current = BenchmarkManifest.from_json(arguments.current.read_text(encoding="utf-8"))
    comparison = compare_manifests(baseline, current)
    _emit(
        comparison.to_json(),
        arguments.output,
        overwrite=arguments.force_output,
    )
    if comparison.status is ComparisonStatus.REGRESSION:
        return 1
    if comparison.status is ComparisonStatus.INCOMPARABLE:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
