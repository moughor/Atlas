from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from benchmarks.benchmark_pr134_explain_anything import benchmark_synthetic
from benchmarks import repository_benchmark
from benchmarks.stability_manifest import (
    BenchmarkManifest,
    BenchmarkMode,
    ComparisonStatus,
    ResultsSource,
    SnapshotArtifacts,
    canonical_text_digest,
    collect_snapshot_artifacts,
    compare_manifests,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import Workspace


_COMMIT = "1" * 40


def _artifacts(seed: str = "a") -> SnapshotArtifacts:
    return SnapshotArtifacts(
        snapshot_size_bytes=1_024,
        snapshot_sha256=seed * 64,
        snapshot_id="b" * 64,
        semantic_payload_sha256="c" * 64,
        repository_report_sha256="d" * 64,
        analysis_report_sha256="0" * 64,
        explain_sha256="e" * 64,
        project_count=2,
        workspace_project_order_sha256="f" * 64,
        analysis_order_sha256="1" * 64,
    )


def _manifest(
    *,
    artifacts: SnapshotArtifacts | None = None,
    durations: tuple[int, ...] = (1_000, 1_100, 900),
) -> BenchmarkManifest:
    return BenchmarkManifest(
        benchmark_id="fixture",
        mode=BenchmarkMode.FRESH_ANALYSIS,
        repository_name="Fixture Repository",
        repository_commit="2" * 40,
        repository_revision_verified=True,
        checkout_identity="fixture-root-v1",
        atlas_commit=_COMMIT,
        atlas_version="2.0.0",
        python_version="3.12.10",
        python_implementation="CPython",
        os_name="Windows",
        os_release="11",
        architecture="AMD64",
        observed_at_utc="2026-08-01T12:00:00Z",
        workers=1,
        cache_mode="force-no-recover",
        measurement_scope="atlas-analyze-subprocess",
        analysis_duration_ms=durations,
        replay_duration_ms=(),
        project_count=2,
        success_count=2,
        failure_count=0,
        results_source=ResultsSource.ANALYSIS_REPORT,
        analysis_success_verified=True,
        source_manifest_sha256=None,
        artifacts=artifacts or _artifacts(),
    )


def test_manifest_is_canonical_versioned_and_exactly_round_trippable() -> None:
    manifest = _manifest()
    restored = BenchmarkManifest.from_json(manifest.to_json())
    payload = json.loads(manifest.to_json())

    assert restored.to_dict() == manifest.to_dict()
    assert restored.to_json() == manifest.to_json()
    assert manifest.baseline_eligible is True
    assert payload["format"] == "atlas-benchmark-manifest"
    assert payload["schema_version"] == 1
    assert payload["execution"]["median_duration_ms"] == 1_000
    assert payload["execution"]["repeat_count"] == 3
    assert payload["artifacts"]["analysis_report_sha256"] == "0" * 64
    assert manifest.to_json().endswith("\n")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository_commit", "short", "full lowercase Git object ID"),
        ("observed_at_utc", "2026-08-01T12:00:00+01:00", "must use UTC"),
        ("workers", True, "non-negative integer"),
    ],
)
def test_manifest_rejects_ambiguous_identity_and_numeric_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values = {name: getattr(_manifest(), name) for name in _manifest().__dataclass_fields__}
    values[field] = value

    with pytest.raises(ValueError, match=message):
        BenchmarkManifest(**values)


def test_comparison_separates_correctness_drift_from_performance_warnings() -> None:
    baseline = _manifest()
    raw_only = _manifest(artifacts=replace(_artifacts(), snapshot_sha256="9" * 64))
    slower = _manifest(durations=(2_000, 2_100, 2_200))
    warning_boundary = _manifest(durations=(1_500, 1_500, 1_500))
    changed = _manifest(
        artifacts=replace(_artifacts(), repository_report_sha256="8" * 64)
    )

    raw_result = compare_manifests(baseline, raw_only)
    slow_result = compare_manifests(baseline, slower)
    boundary_result = compare_manifests(baseline, warning_boundary)
    changed_result = compare_manifests(baseline, changed)

    assert raw_result.status is ComparisonStatus.WARNING
    assert "operational history metadata" in raw_result.warnings[0]
    assert slow_result.status is ComparisonStatus.PERFORMANCE_CANDIDATE
    assert "independent batch" in slow_result.warnings[0]
    assert boundary_result.status is ComparisonStatus.WARNING
    assert "warning threshold" in boundary_result.warnings[0]
    assert changed_result.status is ComparisonStatus.REGRESSION
    assert "repository report hash changed" in changed_result.issues[0]


def test_comparison_rejects_incompatible_environment() -> None:
    baseline = _manifest()
    values = {
        name: getattr(baseline, name)
        for name in baseline.__dataclass_fields__
    }
    values["os_name"] = "Linux"

    result = compare_manifests(baseline, BenchmarkManifest(**values))

    assert result.status is ComparisonStatus.INCOMPARABLE
    assert result.issues == ("operating system differs: 'Windows' != 'Linux'",)


def test_canonical_text_hash_normalizes_line_endings_and_final_newline() -> None:
    assert canonical_text_digest("one\r\ntwo") == canonical_text_digest("one\ntwo\n\n")


def test_tracked_v1_snapshot_fixture_loads_and_replays_deterministically() -> None:
    fixture = Path(__file__).parent / "fixtures" / "semantic_snapshot_v1_minimal.ass"
    first = collect_snapshot_artifacts(fixture)
    second = collect_snapshot_artifacts(fixture)
    store = SemanticSnapshotStore(
        Workspace(fixture.parent, ()),
        fixture.parent,
    )

    assert first == second
    assert first.snapshot_id == (
        "f12c4697456d84a7c7b134a35eacf80a43339ea878739c47b762c42f3a571f99"
    )
    assert first.snapshot_sha256 == (
        "9eddc54e355485feb46b80f5d5ef21cad0389019f7426ef4354e89a43d0fa19e"
    )
    assert first.semantic_payload_sha256 == (
        "6f4ca5e1ad210b7281503ba4179385997b62e29e82d7ea6b09a3c574d1304125"
    )
    assert first.explain_sha256 == (
        "ad0e3b3bd67c983927aeb5165c1ac794b86a8e2069004a05267a10725c4f85c5"
    )
    loaded = store.load(fixture)
    assert loaded is not None
    assert SemanticSnapshotStore._serialize(loaded) == fixture.read_text(
        encoding="utf-8"
    )
    assert first.project_count == 0
    assert first.repository_report_sha256 is None
    assert first.analysis_report_sha256 is None
    assert first.analysis_order_sha256 is None


def test_semantic_hash_ignores_run_reference_but_raw_snapshot_identity_does_not(
    tmp_path: Path,
) -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {"root": ".", "projects": []},
        "repository_summary": {"schema_version": 1, "project_count": 0},
    })
    first = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="same-workspace",
        analyzer_version="2.0.0",
        history_reference=1,
    )
    second = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="same-workspace",
        analyzer_version="2.0.0",
        history_reference=2,
    )
    first_path = tmp_path / "first.ass"
    second_path = tmp_path / "second.ass"
    first_path.write_text(
        SemanticSnapshotStore._serialize(first), encoding="utf-8", newline="\n"
    )
    second_path.write_text(
        SemanticSnapshotStore._serialize(second), encoding="utf-8", newline="\n"
    )

    first_artifacts = collect_snapshot_artifacts(first_path)
    second_artifacts = collect_snapshot_artifacts(second_path)

    assert first_artifacts.snapshot_sha256 != second_artifacts.snapshot_sha256
    assert first_artifacts.snapshot_id != second_artifacts.snapshot_id
    assert (
        first_artifacts.semantic_payload_sha256
        == second_artifacts.semantic_payload_sha256
    )
    assert first_artifacts.explain_sha256 == second_artifacts.explain_sha256


def test_pr134_synthetic_benchmark_has_a_bounded_deterministic_smoke_contract() -> None:
    first = benchmark_synthetic(
        100,
        repeats=3,
        lookup_count=10,
        fact_count=8,
        token_budget=3_000,
    )
    second = benchmark_synthetic(
        100,
        repeats=2,
        lookup_count=10,
        fact_count=8,
        token_budget=3_000,
    )

    assert first["determinism_verified"] is True
    assert first["canonical_graph_node_count"] == 100
    assert first["graph_digest"] == second["graph_digest"]
    assert first["resolution_hash"] == second["resolution_hash"]
    assert first["selected_context_hash"] == second["selected_context_hash"]


def test_repository_runner_builds_manifest_from_normal_analysis_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    report = {
        "type": "workspace-analysis",
        "succeeded": True,
        "requested": ["root", "module"],
        "analysis_order": ["root", "module"],
        "runs": [
            {"project": "root", "status": "succeeded"},
            {"project": "module", "status": "succeeded"},
        ],
    }
    artifacts = _artifacts()
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_identity",
        lambda *args, **kwargs: ("2" * 40, True, True, []),
    )
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda: _COMMIT)
    monkeypatch.setattr(repository_benchmark, "_verify_atlas_unchanged", lambda *args: None)
    monkeypatch.setattr(repository_benchmark, "_verify_repository_unchanged", lambda *args, **kwargs: None)
    monkeypatch.setattr(repository_benchmark, "_run_analysis", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        repository_benchmark,
        "collect_snapshot_artifacts",
        lambda *args, **kwargs: artifacts,
    )

    manifest = repository_benchmark.capture_analysis(
        root,
        repository_name="Fixture Repository",
        checkout_identity="fixture-root-v1",
        repeats=3,
        observed_at_utc="2026-08-01T12:00:00Z",
    )

    assert manifest.mode is BenchmarkMode.FRESH_ANALYSIS
    assert manifest.project_count == manifest.success_count == 2
    assert manifest.failure_count == 0
    assert manifest.baseline_eligible is True
    assert manifest.artifacts.analysis_order_sha256 == canonical_order_hash(
        ("root", "module")
    )
    assert manifest.artifacts.analysis_report_sha256 == canonical_order_hash(report)


def test_repository_runner_rejects_disagreement_between_run_and_analysis_order() -> None:
    report = {
        "type": "workspace-analysis",
        "succeeded": True,
        "analysis_order": ["root", "module"],
        "runs": [
            {"project": "module", "status": "succeeded"},
            {"project": "root", "status": "succeeded"},
        ],
    }

    with pytest.raises(RuntimeError, match="run order and analysis order disagree"):
        repository_benchmark._analysis_counts(report)


def test_repository_runner_rejects_analysis_report_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    reports = iter((
        {
            "type": "workspace-analysis",
            "succeeded": True,
            "analysis_order": ["root", "module"],
            "runs": [
                {"project": "root", "status": "succeeded"},
                {"project": "module", "status": "succeeded"},
            ],
        },
        {
            "type": "workspace-analysis",
            "succeeded": True,
            "analysis_order": ["root", "module"],
            "runs": [
                {"project": "root", "status": "succeeded"},
                {"project": "module", "status": "reused"},
            ],
        },
    ))
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_identity",
        lambda *args, **kwargs: ("2" * 40, True, True, []),
    )
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda: _COMMIT)
    monkeypatch.setattr(repository_benchmark, "_verify_atlas_unchanged", lambda *args: None)
    monkeypatch.setattr(repository_benchmark, "_verify_repository_unchanged", lambda *args, **kwargs: None)
    monkeypatch.setattr(repository_benchmark, "_run_analysis", lambda *args, **kwargs: next(reports))
    monkeypatch.setattr(
        repository_benchmark,
        "collect_snapshot_artifacts",
        lambda *args, **kwargs: _artifacts(),
    )

    with pytest.raises(RuntimeError, match="analysis_report_sha256 changed"):
        repository_benchmark.capture_analysis(
            root,
            repository_name="Fixture Repository",
            checkout_identity="fixture-root-v1",
            repeats=2,
            observed_at_utc="2026-08-01T12:00:00Z",
        )


def test_manifest_loader_rejects_string_coercion() -> None:
    payload = _manifest().to_dict()
    payload["repository"]["name"] = 123

    with pytest.raises(ValueError, match="repository name must be a non-empty string"):
        BenchmarkManifest.from_dict(payload)

    payload = _manifest().to_dict()
    payload["future_field"] = "silent-data-loss"
    with pytest.raises(ValueError, match="unknown=.*future_field"):
        BenchmarkManifest.from_dict(payload)


def test_repository_revision_is_verified_only_when_explicitly_pinned(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(repository_benchmark, "_git_head", lambda root: "2" * 40)
    monkeypatch.setattr(repository_benchmark, "_git_top_level", lambda root: root)
    monkeypatch.setattr(repository_benchmark, "_working_tree_status", lambda root: "")

    with pytest.raises(ValueError, match="was not explicitly pinned"):
        repository_benchmark._repository_identity(
            tmp_path,
            None,
            allow_unpinned=False,
        )
    commit, verified, git_backed, limitations = repository_benchmark._repository_identity(
        tmp_path,
        None,
        allow_unpinned=True,
    )
    assert commit == "2" * 40
    assert verified is False
    assert git_backed is True
    assert "provisional" in limitations[0]

    assert repository_benchmark._repository_identity(
        tmp_path,
        "2" * 40,
        allow_unpinned=False,
    ) == ("2" * 40, True, True, [])

    monkeypatch.setattr(
        repository_benchmark,
        "_working_tree_status",
        lambda root: "?? src/Untracked.java",
    )
    with pytest.raises(ValueError, match="tracked or untracked modifications"):
        repository_benchmark._repository_identity(
            tmp_path,
            "2" * 40,
            allow_unpinned=False,
        )


def test_repository_capture_rejects_lost_git_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(repository_benchmark, "_git_head", lambda root: None)

    with pytest.raises(RuntimeError, match="commit changed during capture"):
        repository_benchmark._verify_repository_unchanged(
            tmp_path,
            "2" * 40,
            git_backed=True,
        )


def test_replay_results_remain_declared_without_a_linked_fresh_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    replay_artifacts = replace(
        _artifacts(),
        analysis_report_sha256=None,
        analysis_order_sha256=None,
    )
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_identity",
        lambda *args, **kwargs: ("2" * 40, True, True, []),
    )
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda: _COMMIT)
    monkeypatch.setattr(repository_benchmark, "_verify_atlas_unchanged", lambda *args: None)
    monkeypatch.setattr(repository_benchmark, "_verify_repository_unchanged", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        repository_benchmark,
        "collect_snapshot_artifacts",
        lambda *args, **kwargs: replay_artifacts,
    )

    declared = repository_benchmark.capture_replay(
        tmp_path / "latest.ass",
        repository_root=tmp_path,
        repository_name="Fixture Repository",
        project_count=2,
        success_count=2,
        checkout_identity="fixture-root-v1",
        repeats=3,
        observed_at_utc="2026-08-01T12:00:00Z",
    )
    linked = repository_benchmark.capture_replay(
        tmp_path / "latest.ass",
        repository_root=tmp_path,
        repository_name="Fixture Repository",
        project_count=2,
        success_count=2,
        checkout_identity="fixture-root-v1",
        repeats=3,
        observed_at_utc="2026-08-01T12:00:00Z",
        source_manifest=_manifest(),
    )

    assert declared.results_source is ResultsSource.DECLARED_HISTORICAL
    assert declared.analysis_success_verified is False
    assert declared.baseline_eligible is False
    assert linked.results_source is ResultsSource.LINKED_FRESH_MANIFEST
    assert linked.analysis_success_verified is True
    assert linked.source_manifest_sha256 is not None
    assert linked.baseline_eligible is True

    with pytest.raises(ValueError, match="checkout identity"):
        repository_benchmark.capture_replay(
            tmp_path / "latest.ass",
            repository_root=tmp_path,
            repository_name="Fixture Repository",
            project_count=2,
            success_count=2,
            checkout_identity="different-root-v1",
            repeats=3,
            observed_at_utc="2026-08-01T12:00:00Z",
            source_manifest=_manifest(),
        )


def test_replay_requires_the_exact_same_snapshot_across_repetitions() -> None:
    first = replace(
        _artifacts(),
        analysis_report_sha256=None,
        analysis_order_sha256=None,
    )
    second = replace(first, snapshot_sha256="9" * 64)

    with pytest.raises(RuntimeError, match="snapshot_sha256 changed"):
        repository_benchmark._verify_artifact_determinism(
            [first, second],
            exact_snapshot=True,
        )

    repository_benchmark._verify_artifact_determinism(
        [first, second],
        exact_snapshot=False,
    )


def test_benchmark_output_refuses_silent_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force-output"):
        repository_benchmark._write(output, "replacement")

    assert output.read_text(encoding="utf-8") == "existing"
    repository_benchmark._write(output, "replacement", overwrite=True)
    assert output.read_text(encoding="utf-8") == "replacement"


def test_compare_cli_returns_nonzero_for_correctness_regression(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    output = tmp_path / "comparison.json"
    baseline.write_text(_manifest().to_json(), encoding="utf-8")
    current.write_text(
        _manifest(
            artifacts=replace(
                _artifacts(),
                repository_report_sha256="8" * 64,
            )
        ).to_json(),
        encoding="utf-8",
    )

    result = repository_benchmark.main(
        ["compare", str(baseline), str(current), "--output", str(output)]
    )

    assert result == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "regression"


def test_ineligible_records_are_incomparable_and_cli_returns_two(
    tmp_path: Path,
) -> None:
    provisional = replace(_manifest(), checkout_identity=None)
    comparison = compare_manifests(provisional, provisional)
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    output = tmp_path / "comparison.json"
    baseline.write_text(provisional.to_json(), encoding="utf-8")
    current.write_text(provisional.to_json(), encoding="utf-8")

    result = repository_benchmark.main(
        ["compare", str(baseline), str(current), "--output", str(output)]
    )

    assert comparison.status is ComparisonStatus.INCOMPARABLE
    assert result == 2


def test_snapshot_artifact_collection_rejects_malformed_project_inventory(
    tmp_path: Path,
) -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {"root": ".", "projects": [{"path": "."}]},
        "repository_summary": {"schema_version": 1, "project_count": 1},
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace",
        analyzer_version="2.0.0",
    )
    path = tmp_path / "malformed.ass"
    path.write_text(
        SemanticSnapshotStore._serialize(snapshot),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ValueError, match="project name"):
        collect_snapshot_artifacts(path)


def canonical_order_hash(value: tuple[str, ...]) -> str:
    from benchmarks.stability_manifest import canonical_digest

    return canonical_digest(value)
