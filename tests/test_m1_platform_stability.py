from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from benchmarks.benchmark_pr134_explain_anything import benchmark_synthetic
from benchmarks import canonical_baseline, repository_benchmark
from benchmarks.stability_manifest import (
    MANIFEST_FORMAT,
    BenchmarkManifest,
    BenchmarkMode,
    ComparisonStatus,
    ResultsSource,
    SnapshotArtifacts,
    canonical_text_digest,
    collect_snapshot_artifacts,
    compare_manifests,
    contains_machine_path,
    portable_snapshot_payload,
    portable_value,
)
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import Workspace


_COMMIT = "1" * 40
_MANIFEST_V1_FIXTURE_SHA256 = (
    "22998137d9a39aff038fd1e320c6dd4059409f5b285f453dc00ef52fc6bcc278"
)


def _artifacts(seed: str = "a") -> SnapshotArtifacts:
    projects = ("root", "module")
    workspace_order_hash = canonical_order_hash(projects)
    return SnapshotArtifacts(
        snapshot_size_bytes=1_024,
        snapshot_sha256=seed * 64,
        snapshot_id="b" * 64,
        semantic_payload_sha256="c" * 64,
        repository_report_sha256="d" * 64,
        analysis_report_sha256="0" * 64,
        explain_sha256="e" * 64,
        project_count=2,
        workspace_project_order_sha256=workspace_order_hash,
        analysis_order_sha256=canonical_order_hash(projects),
        portable_semantic_sha256="2" * 64,
        risk_sha256="3" * 64,
        knowledge_graph_sha256="4" * 64,
        deterministic_ordering_sha256=deterministic_order_hash(
            projects,
            workspace_order_hash,
        ),
        analysis_order=projects,
        workspace_projects=projects,
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
        repository_url="https://example.com/fixture.git",
        repository_branch="main",
        repository_tag=None,
        repository_tracked_size_bytes=4_096,
        repository_tracked_file_count=10,
        repository_submodules=(),
        repository_lfs_required=False,
        repository_history_complete=True,
        runtime_dependencies=(("httpx", "1.0.0"),),
    )


def test_manifest_is_canonical_versioned_and_exactly_round_trippable() -> None:
    manifest = _manifest()
    restored = BenchmarkManifest.from_json(manifest.to_json())
    payload = json.loads(manifest.to_json())

    assert restored.to_dict() == manifest.to_dict()
    assert restored.to_json() == manifest.to_json()
    assert manifest.baseline_eligible is True
    assert payload["format"] == "atlas-benchmark-manifest"
    assert payload["schema_version"] == 2
    assert payload["execution"]["median_duration_ms"] == 1_000
    assert payload["execution"]["repeat_count"] == 3
    assert payload["artifacts"]["analysis_report_sha256"] == "0" * 64
    assert payload["artifacts"]["risk_sha256"] == "3" * 64
    assert manifest.to_json().endswith("\n")


def test_schema_v1_manifest_fixture_remains_exactly_round_trippable() -> None:
    fixture = Path(__file__).parent / "fixtures" / "benchmark_manifest_v1_fresh.json"
    raw = fixture.read_bytes()

    assert sha256(raw).hexdigest() == _MANIFEST_V1_FIXTURE_SHA256
    manifest = BenchmarkManifest.from_json(raw.decode("utf-8"))
    assert manifest.schema_version == 1
    assert manifest.to_json().encode("utf-8") == raw


def test_schema_v1_positional_constructor_remains_backward_compatible() -> None:
    fixture = Path(__file__).parent / "fixtures" / "benchmark_manifest_v1_fresh.json"
    expected = BenchmarkManifest.from_json(fixture.read_text(encoding="utf-8"))

    constructed = BenchmarkManifest(
        expected.benchmark_id,
        expected.mode,
        expected.repository_name,
        expected.repository_commit,
        expected.repository_revision_verified,
        expected.checkout_identity,
        expected.atlas_commit,
        expected.atlas_version,
        expected.python_version,
        expected.python_implementation,
        expected.os_name,
        expected.os_release,
        expected.architecture,
        expected.observed_at_utc,
        expected.workers,
        expected.cache_mode,
        expected.measurement_scope,
        expected.analysis_duration_ms,
        expected.replay_duration_ms,
        expected.project_count,
        expected.success_count,
        expected.failure_count,
        expected.results_source,
        expected.analysis_success_verified,
        expected.source_manifest_sha256,
        expected.artifacts,
        expected.limitations,
        1,
        MANIFEST_FORMAT,
    )

    assert constructed.to_json() == expected.to_json()
    assert compare_manifests(expected, constructed).status is ComparisonStatus.MATCH


def test_schema_v2_comparison_uses_portable_semantics_across_checkout_roots() -> None:
    baseline = _manifest()
    current = _manifest(
        artifacts=replace(
            _artifacts(),
            semantic_payload_sha256="9" * 64,
        )
    )

    comparison = compare_manifests(baseline, current)

    assert comparison.status is ComparisonStatus.WARNING
    assert comparison.issues == ()
    assert comparison.warnings == (
        "path-scoped semantic payload hash changed while portable semantics stayed stable",
    )


def test_portable_projection_normalizes_mapping_keys_and_file_uris(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    source = root / "src" / "Example.java"

    projected = portable_value(
        {
            str(source): {
                "uri": source.as_uri(),
                "encoded_uri": source.as_uri().replace("/", "%2F"),
            }
        },
        root,
    )

    assert len(projected) == 1
    key = next(iter(projected))
    assert "REPOSITORY_ROOT" in key
    assert str(root) not in json.dumps(projected)
    assert projected[key]["uri"].startswith("REPOSITORY_ROOT")
    assert "REPOSITORY_ROOT" in projected[key]["encoded_uri"]


def test_portable_projection_rejects_normalized_key_collisions(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()

    with pytest.raises(ValueError, match="key collision"):
        portable_value({str(root): 1, root.as_uri(): 2}, root)


@pytest.mark.parametrize(
    "value",
    (
        r"declared_dependency:maven:org.acme.treeshake:lib-a:\${project.version}:compile",
        r"dependency:maven:org.acme.treeshake%3Alib-e:%5C%24%7Bproject.version%7D:compile",
        r'''char[]quotedChars="()<>@,;:\\\"/[]?= \t\r\n".''',
    ),
)
def test_machine_path_detection_preserves_quarkus_semantic_syntax(value: str) -> None:
    assert not contains_machine_path(value)


@pytest.mark.parametrize(
    "value",
    (
        r"C:\Users\alice\repository\pom.xml",
        r"source=C%3A%5CUsers%5Calice%5Crepository%5Cpom.xml",
        r"\\server\share\repository\pom.xml",
        "//server/share/repository/pom.xml",
        "file:///C:/Users/alice/repository/pom.xml",
        "/home/alice/repository/pom.xml",
    ),
)
def test_machine_path_detection_still_rejects_real_machine_paths(value: str) -> None:
    assert contains_machine_path(value)


def test_portable_snapshot_accepts_quarkus_semantic_syntax(tmp_path: Path) -> None:
    dependency_id = (
        r"dependency:maven:org.acme.treeshake%3Alib-a:"
        r"%5C%24%7Bproject.version%7D:compile"
    )
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "semantic_graph": {
            "nodes": [{"id": dependency_id}],
            "edges": [{
                "target": dependency_id,
                "evidence": [
                    r"declared_dependency:maven:org.acme.treeshake:"
                    r"lib-a:\${project.version}:compile"
                ],
            }],
        },
        "symbols": [{
            "metadata": {
                "return_type": r'''char[]quotedChars="()<>@,;:\\\"/[]?= \t\r\n".'''
            }
        }],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="path-scoped",
        analyzer_version="2.0.0",
    )

    projected = portable_snapshot_payload(snapshot, tmp_path)

    assert projected["semantic_context"]["semantic_graph"]["nodes"][0][
        "id"
    ] == dependency_id


def test_portable_snapshot_reports_machine_path_location(tmp_path: Path) -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "symbols": [{"metadata": {"external_path": r"D:\cache\artifact.jar"}}],
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="path-scoped",
        analyzer_version="2.0.0",
    )

    with pytest.raises(
        ValueError,
        match=(
            r'\$\["semantic_context"\]\["symbols"\]\[0\]'
            r'\["metadata"\]\["external_path"\]'
        ),
    ):
        portable_snapshot_payload(snapshot, tmp_path)


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
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda *args: _COMMIT)
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_provenance",
        lambda *args, **kwargs: (
            "https://example.com/fixture.git", "main", None, 4_096, 10, (), False, True
        ),
    )
    monkeypatch.setattr(
        repository_benchmark,
        "_runtime_dependencies",
        lambda: (("httpx", "1.0.0"),),
    )
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


def test_deterministic_analysis_report_excludes_per_project_timings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    first = {
        "type": "workspace-analysis",
        "succeeded": True,
        "analysis_order": ["root"],
        "runs": [
            {
                "project": "root",
                "status": "succeeded",
                "duration_ms": 1.25,
                "value": {"path": str(root / "pom.xml")},
            }
        ],
    }
    second = {
        **first,
        "runs": [{**first["runs"][0], "duration_ms": 999.75}],
    }

    first_projected = repository_benchmark._deterministic_analysis_report(
        first,
        root,
    )
    second_projected = repository_benchmark._deterministic_analysis_report(
        second,
        root,
    )

    assert first_projected == second_projected
    assert "duration_ms" not in first_projected["runs"][0]
    assert "REPOSITORY_ROOT" in first_projected["runs"][0]["value"]["path"]


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
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda *args: _COMMIT)
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_provenance",
        lambda *args, **kwargs: (
            "https://example.com/fixture.git", "main", None, 4_096, 10, (), False, True
        ),
    )
    monkeypatch.setattr(
        repository_benchmark,
        "_runtime_dependencies",
        lambda: (("httpx", "1.0.0"),),
    )
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
        analysis_order=(),
        deterministic_ordering_sha256=replay_order_hash(("root", "module")),
    )
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_identity",
        lambda *args, **kwargs: ("2" * 40, True, True, []),
    )
    monkeypatch.setattr(repository_benchmark, "_atlas_commit", lambda *args: _COMMIT)
    monkeypatch.setattr(
        repository_benchmark,
        "_repository_provenance",
        lambda *args, **kwargs: (
            "https://example.com/fixture.git", "main", None, 4_096, 10, (), False, True
        ),
    )
    monkeypatch.setattr(
        repository_benchmark,
        "_runtime_dependencies",
        lambda: (("httpx", "1.0.0"),),
    )
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
        analysis_order=(),
        deterministic_ordering_sha256=replay_order_hash(("root", "module")),
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
    baseline.write_bytes(_manifest().to_json().encode("utf-8"))
    current.write_bytes(
        _manifest(
            artifacts=replace(
                _artifacts(),
                repository_report_sha256="8" * 64,
            )
        ).to_json().encode("utf-8"),
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
    baseline.write_bytes(provisional.to_json().encode("utf-8"))
    current.write_bytes(provisional.to_json().encode("utf-8"))

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


def test_m1_1_repository_definitions_are_canonical_and_pinned() -> None:
    version, definitions = canonical_baseline.load_definitions()

    assert version == "m1.1"
    assert tuple(item.repository_id for item in definitions) == (
        "apache-maven",
        "quarkus",
    )
    assert all(item.commit and item.url.startswith("https://") for item in definitions)
    assert all(item.tracked_file_count > 0 for item in definitions)
    assert all(item.tracked_size_bytes > 0 for item in definitions)


def test_portable_snapshot_projection_removes_checkout_identity() -> None:
    def snapshot(root: str, fingerprint: str) -> AtlasSemanticSnapshot:
        return AtlasSemanticSnapshot.create(
            WorkspaceSemanticContext({
                "schema_version": 1,
                "workspace": {
                    "root": root,
                    "projects": [{"name": "root", "path": "."}],
                },
                "repository_summary": {
                    "schema_version": 1,
                    "project_count": 1,
                    "root": root,
                },
                "repository_report": {"schema_version": 1, "title": "Fixture"},
                "diagnostics": [{"location": f"{root}/src/Main.java"}],
                "risk_analysis": {"schema_version": 1, "hotspots": []},
                "semantic_graph": {"schema_version": 1, "nodes": [], "edges": []},
            }),
            workspace_fingerprint=fingerprint,
            analyzer_version="2.0.0",
        )

    first = canonical_baseline.portable_snapshot_payload(
        snapshot("C:/checkouts/fixture", "windows-root"),
        Path("C:/checkouts/fixture"),
    )
    second = canonical_baseline.portable_snapshot_payload(
        snapshot("D:/other/fixture", "other-root"),
        Path("D:/other/fixture"),
    )

    assert first == second
    assert "C:/checkouts" not in json.dumps(first)
    assert "D:/other" not in json.dumps(second)


def test_manifest_file_loader_rejects_noncanonical_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    canonical = _manifest().to_json().encode("utf-8")
    variants = (
        json.dumps(_manifest().to_dict()).encode("utf-8"),
        canonical.replace(b"\n", b"\r\n"),
        b"\xef\xbb\xbf" + canonical,
        canonical + b" ",
    )
    for value in variants:
        path.write_bytes(value)
        with pytest.raises(ValueError, match="canonical|UTF-8|manifest JSON"):
            BenchmarkManifest.from_file(path)

    path.write_bytes(canonical)
    assert BenchmarkManifest.from_file(path).to_dict() == _manifest().to_dict()


def test_manifest_rejects_machine_paths_and_compares_new_semantic_gates() -> None:
    with pytest.raises(ValueError, match="absolute machine paths"):
        replace(_manifest(), limitations=(r"captured at C:\Users\alice\repo",))

    changed = replace(
        _manifest(),
        artifacts=replace(_artifacts(), risk_sha256="9" * 64),
    )
    comparison = compare_manifests(_manifest(), changed)

    assert comparison.status is ComparisonStatus.REGRESSION
    assert comparison.issues == (
        f"risk hash changed: {'3' * 64!r} -> {'9' * 64!r}",
    )


def test_replay_comparison_requires_identical_input_snapshot() -> None:
    artifacts = replace(
        _artifacts(),
        analysis_report_sha256=None,
        analysis_order_sha256=None,
        analysis_order=(),
        deterministic_ordering_sha256=replay_order_hash(("root", "module")),
    )
    baseline = replace(
        _manifest(),
        mode=BenchmarkMode.SNAPSHOT_REPLAY,
        analysis_duration_ms=(),
        replay_duration_ms=(100, 110, 90),
        results_source=ResultsSource.LINKED_FRESH_MANIFEST,
        source_manifest_sha256="6" * 64,
        artifacts=artifacts,
    )
    current = replace(
        baseline,
        artifacts=replace(artifacts, snapshot_sha256="9" * 64),
    )

    comparison = compare_manifests(baseline, current)

    assert comparison.status is ComparisonStatus.INCOMPARABLE
    assert "replay snapshot hash differs" in comparison.issues[0]

    corrupted = baseline.to_dict()
    corrupted["artifacts"]["deterministic_ordering_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="replay deterministic ordering hash"):
        BenchmarkManifest.from_dict(corrupted)


def test_fresh_manifest_rejects_disjoint_project_inventories() -> None:
    artifacts = replace(
        _artifacts(),
        analysis_order=("other-root", "other-module"),
        analysis_order_sha256=canonical_order_hash(
            ("other-root", "other-module")
        ),
        deterministic_ordering_sha256=deterministic_order_hash(
            ("other-root", "other-module"),
            _artifacts().workspace_project_order_sha256,
        ),
    )

    with pytest.raises(ValueError, match="project inventories are inconsistent"):
        replace(_manifest(), artifacts=artifacts)


def test_golden_bundle_matches_verified_source_free_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": tmp_path.as_posix(),
            "projects": [
                {"name": "root", "path": "."},
                {"name": "module", "path": "module"},
            ],
        },
        "repository_summary": {"schema_version": 1, "project_count": 2},
        "repository_report": {"schema_version": 1, "title": "Fixture"},
        "risk_analysis": {
            "schema_version": 1,
            "producer_version": "fixture",
            "hotspots": [],
            "heatmaps": [],
            "capabilities": {},
            "limitations": [],
        },
        "semantic_graph": {"schema_version": 1, "nodes": [], "edges": []},
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="path-scoped",
        analyzer_version="2.0.0",
    )
    snapshot_path = tmp_path / "latest.ass"
    snapshot_path.write_text(
        SemanticSnapshotStore._serialize(snapshot),
        encoding="utf-8",
        newline="\n",
    )
    observed = collect_snapshot_artifacts(
        snapshot_path,
        repository_root=tmp_path,
    )
    artifacts = replace(
        observed,
        analysis_report_sha256="0" * 64,
        analysis_order_sha256=canonical_order_hash(("root", "module")),
        analysis_order=("root", "module"),
        deterministic_ordering_sha256=deterministic_order_hash(
            ("root", "module"),
            observed.workspace_project_order_sha256,
        ),
    )
    manifest = _manifest(artifacts=artifacts)
    target = tmp_path / "golden"

    paths = canonical_baseline.write_golden_bundle(
        target,
        repository_root=tmp_path,
        snapshot_path=snapshot_path,
        manifest=manifest,
    )

    assert tuple(path.name for path in paths) == (
        "ai-explain.md",
        "benchmark-metadata.json",
        "checksums.json",
        "deterministic-ordering.json",
        "knowledge-graph-summary.json",
        "repository-report.json",
        "risk-summary.json",
        "semantic-snapshot.json",
    )
    assert tmp_path.as_posix() not in (target / "semantic-snapshot.json").read_text(
        encoding="utf-8"
    )
    verified = canonical_baseline.verify_golden_bundle(
        target,
        snapshot_path=snapshot_path,
        require_external_snapshot=True,
    )
    assert verified.to_dict() == manifest.to_dict()
    assert canonical_baseline.main(
        ["verify-golden", str(target), "--snapshot", str(snapshot_path)]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {
        "benchmark_id": manifest.benchmark_id,
        "benchmark_version": manifest.benchmark_version,
        "external_snapshot_verified": True,
        "format": canonical_baseline.GOLDEN_BUNDLE_FORMAT,
        "schema_version": canonical_baseline.GOLDEN_BUNDLE_SCHEMA_VERSION,
    }
    with pytest.raises(ValueError, match="external raw ASS is required"):
        canonical_baseline.verify_golden_bundle(
            target,
            require_external_snapshot=True,
        )
    with pytest.raises(FileExistsError, match="already exists"):
        canonical_baseline.write_golden_bundle(
            target,
            repository_root=tmp_path,
            snapshot_path=snapshot_path,
            manifest=manifest,
        )

    manifest_output = tmp_path / "published-manifest.json"
    golden_output = tmp_path / "published-golden"
    canonical_baseline._publish_capture_outputs(
        manifest_output,
        golden_output,
        repository_root=tmp_path,
        snapshot_path=snapshot_path,
        manifest=manifest,
    )
    assert BenchmarkManifest.from_file(manifest_output).to_dict() == manifest.to_dict()
    assert canonical_baseline.verify_golden_bundle(
        golden_output,
        snapshot_path=snapshot_path,
        require_external_snapshot=True,
    ).to_dict() == manifest.to_dict()

    raced_target = tmp_path / "raced-golden"
    raced_target.mkdir()
    marker = raced_target / "foreign.txt"
    marker.write_text("foreign\n", encoding="utf-8", newline="\n")
    with pytest.raises(FileExistsError, match="appeared during publication"):
        canonical_baseline._publish_golden_directory(
            golden_output,
            raced_target,
        )
    assert marker.read_text(encoding="utf-8") == "foreign\n"
    assert golden_output.is_dir()


def test_golden_bundle_verifier_rejects_corruption_and_coordinated_tampering(
    tmp_path: Path,
) -> None:
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": tmp_path.as_posix(),
            "projects": [
                {"name": "root", "path": "."},
                {"name": "module", "path": "module"},
            ],
        },
        "repository_summary": {"schema_version": 1, "project_count": 2},
        "repository_report": {"schema_version": 1, "title": "Fixture"},
        "risk_analysis": {"schema_version": 1, "hotspots": []},
        "semantic_graph": {"schema_version": 1, "nodes": [], "edges": []},
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="path-scoped",
        analyzer_version="2.0.0",
    )
    snapshot_path = tmp_path / "latest.ass"
    snapshot_path.write_text(
        SemanticSnapshotStore._serialize(snapshot),
        encoding="utf-8",
        newline="\n",
    )
    observed = collect_snapshot_artifacts(snapshot_path, repository_root=tmp_path)
    manifest = _manifest(
        artifacts=replace(
            observed,
            analysis_report_sha256="0" * 64,
            analysis_order_sha256=canonical_order_hash(("root", "module")),
            analysis_order=("root", "module"),
            deterministic_ordering_sha256=deterministic_order_hash(
                ("root", "module"),
                observed.workspace_project_order_sha256,
            ),
        )
    )
    target = tmp_path / "golden"
    canonical_baseline.write_golden_bundle(
        target,
        repository_root=tmp_path,
        snapshot_path=snapshot_path,
        manifest=manifest,
    )

    extra = target / "unexpected.txt"
    extra.write_text("unexpected\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="file set is invalid"):
        canonical_baseline.verify_golden_bundle(target)
    extra.unlink()

    report_path = target / "repository-report.json"
    original_report = report_path.read_bytes()
    report_path.write_bytes(original_report + b" ")
    with pytest.raises(ValueError, match="not canonical"):
        canonical_baseline.verify_golden_bundle(target)
    report_path.write_bytes(original_report)

    explanation_path = target / "ai-explain.md"
    original_explanation = explanation_path.read_bytes()
    explanation_path.write_bytes(original_explanation + b"tampered\n")
    with pytest.raises(ValueError, match="checksum mismatch for ai-explain.md"):
        canonical_baseline.verify_golden_bundle(target)
    explanation_path.write_bytes(original_explanation)

    report = json.loads(original_report)
    report["title"] = "Coordinated tampering"
    report_path.write_bytes(_canonical_test_json(report))
    checksums_path = target / "checksums.json"
    checksums = json.loads(checksums_path.read_bytes())
    checksums["files"][report_path.name] = sha256(report_path.read_bytes()).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))
    with pytest.raises(ValueError, match="repository report"):
        canonical_baseline.verify_golden_bundle(target)

    report_path.write_bytes(original_report)
    checksums["files"][report_path.name] = sha256(original_report).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))
    metadata_path = target / "benchmark-metadata.json"
    original_metadata = metadata_path.read_bytes()
    metadata = json.loads(original_metadata)
    metadata["manifest"]["unknown_field"] = "not allowed"
    metadata_path.write_bytes(_canonical_test_json(metadata))
    checksums["files"][metadata_path.name] = sha256(metadata_path.read_bytes()).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))
    with pytest.raises(ValueError, match="unknown=.*unknown_field"):
        canonical_baseline.verify_golden_bundle(target)

    metadata_path.write_bytes(original_metadata)
    checksums["files"][metadata_path.name] = sha256(original_metadata).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))

    portable_path = target / "semantic-snapshot.json"
    original_portable = portable_path.read_bytes()
    portable = json.loads(original_portable)
    portable["format"] = "unsupported-portable-format"
    portable_path.write_bytes(_canonical_test_json(portable))
    checksums["files"][portable_path.name] = sha256(
        portable_path.read_bytes()
    ).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))
    with pytest.raises(ValueError, match="unsupported portable semantic snapshot format"):
        canonical_baseline.verify_golden_bundle(target)
    portable_path.write_bytes(original_portable)
    checksums["files"][portable_path.name] = sha256(original_portable).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))

    portable = json.loads(original_portable)
    portable["semantic_context"]["workspace"]["projects"][0]["name"] = "renamed"
    portable_path.write_bytes(_canonical_test_json(portable))
    checksums["files"][portable_path.name] = sha256(
        portable_path.read_bytes()
    ).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))
    with pytest.raises(
        ValueError,
        match="ordering does not match portable semantics",
    ):
        canonical_baseline.verify_golden_bundle(target)
    portable_path.write_bytes(original_portable)
    checksums["files"][portable_path.name] = sha256(original_portable).hexdigest()
    checksums_path.write_bytes(_canonical_test_json(checksums))

    other = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="different-snapshot",
        analyzer_version="2.0.0",
    )
    other_path = tmp_path / "other.ass"
    other_path.write_text(
        SemanticSnapshotStore._serialize(other),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="external raw ASS does not match"):
        canonical_baseline.verify_golden_bundle(
            target,
            snapshot_path=other_path,
        )


def test_capture_cli_preflights_both_outputs_before_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_output = tmp_path / "manifest.json"
    manifest_output.write_text("already present\n", encoding="utf-8", newline="\n")
    invoked = False

    def unexpected_capture(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("capture must not start after failed output preflight")

    monkeypatch.setattr(canonical_baseline, "capture_definition", unexpected_capture)
    with pytest.raises(FileExistsError, match="manifest output already exists"):
        canonical_baseline.main(
            [
                "capture",
                "apache-maven",
                str(tmp_path),
                "--atlas-commit",
                _COMMIT,
                "--output",
                str(manifest_output),
                "--golden-output",
                str(tmp_path / "golden"),
            ]
        )
    assert invoked is False

    with pytest.raises(ValueError, match="must not overlap"):
        canonical_baseline._preflight_capture_outputs(
            tmp_path / "nested" / "manifest.json",
            tmp_path / "nested",
        )


def _canonical_test_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_order_hash(value: object) -> str:
    from benchmarks.stability_manifest import canonical_digest

    return canonical_digest(value)


def deterministic_order_hash(
    analysis_order: tuple[str, ...],
    workspace_project_order_sha256: str,
) -> str:
    return canonical_order_hash({
        "analysis_order": analysis_order,
        "workspace_project_order_sha256": workspace_project_order_sha256,
    })


def replay_order_hash(workspace_projects: tuple[str, ...]) -> str:
    return canonical_order_hash({
        "analysis_order": None,
        "workspace_projects": workspace_projects,
    })
