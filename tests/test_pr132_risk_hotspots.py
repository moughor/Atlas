from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from benchmarks.benchmark_pr132_risk_hotspots import nearest_rank
from benchmarks.benchmark_pr132_snapshot_replay import replay

from moughorai.ai_explain.repository_projection import RepositoryExplanationProjector
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_git_context import (
    GitContextService,
    GitFileChange,
    GitHistoryWindow,
)
from moughorai.atlas_cli import app
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.risk_analysis import (
    RiskAnalysisReport,
    RiskAnalysisService,
    RiskAvailability,
    RiskConfiguration,
    RiskMetricInput,
    RiskMetricKind,
    RiskScope,
    RiskTrend,
)
from moughorai.repository_summary import RepositorySummaryService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.semantic_snapshot.models import SEMANTIC_SNAPSHOT_FORMAT, canonical_json
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def node(
    node_id: str,
    *,
    kind: KnowledgeKind = KnowledgeKind.TYPE,
    project: str = "demo",
    language: str = "java",
) -> KnowledgeNode:
    return KnowledgeNode(
        node_id,
        kind,
        node_id,
        qualified_name=f"example.{node_id}",
        project_id=project,
        language=language,
    )


def metadata(*node_ids: str, scopes: dict[str, str] | None = None):
    scopes = scopes or {}
    paths = {
        "production": "src/main/java/example/Item.java",
        "test": "src/test/java/example/ItemTest.java",
        "generated": "target/generated-sources/example/Item.java",
    }
    return tuple(
        {
            "id": node_id,
            "project_id": "demo",
            "source": paths.get(scopes.get(node_id, "production")),
            "metadata": {},
        }
        for node_id in node_ids
    )


def metric(
    subject_id: str,
    kind: RiskMetricKind,
    value: float,
    unit: str,
    *,
    producer: str = "test-producer.v1",
    window: str = "current-snapshot",
    coverage: float = 1.0,
    source_refs: tuple[str, ...] | None = None,
) -> RiskMetricInput:
    evidence = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        subject_id,
        producer,
        "test-snapshot",
        source_refs=(
            source_refs
            if source_refs is not None
            else (f"semantic-fact:{subject_id}:{kind.value}",)
        ),
        detail={"metric": kind.value, "unit": unit},
        reliability=0.9,
        specificity=0.95,
    )
    return RiskMetricInput(
        subject_id,
        kind,
        value,
        unit,
        producer,
        (evidence,),
        window,
        coverage,
    )


def capability(report: RiskAnalysisReport, kind: RiskMetricKind):
    return next(item for item in report.capabilities if item.metric is kind)


def factor(report: RiskAnalysisReport, subject_id: str, kind: RiskMetricKind):
    finding = report.finding(subject_id)
    assert finding is not None
    return next(item for item in finding.factors if item.metric.metric is kind)


def test_graph_degree_summary_is_filtered_distinct_and_exactly_digestible() -> None:
    graph = KnowledgeGraph(
        (node("a"), node("b"), node("owner", kind=KnowledgeKind.MODULE)),
        (
            KnowledgeEdge("a", "b", KnowledgeRelation.CALLS, ("first",)),
            KnowledgeEdge("a", "b", KnowledgeRelation.CALLS, ("second",)),
            KnowledgeEdge("owner", "a", KnowledgeRelation.OWNS, ("containment",)),
        ),
    )

    summaries = graph.degree_summaries(
        relations=(KnowledgeRelation.CALLS,),
        subject_kinds=(KnowledgeKind.TYPE,),
        neighbor_kinds=(KnowledgeKind.TYPE,),
    )
    by_id = {item.node_id: item for item in summaries}

    assert by_id["a"].outgoing == 1
    assert by_id["b"].incoming == 1
    assert by_id["a"].incoming == 0
    serialized = json.dumps(
        graph.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert graph.stable_digest() == hashlib.sha256(serialized).hexdigest()


def test_fixed_formula_renormalizes_missing_metrics_and_separates_confidence() -> None:
    graph = KnowledgeGraph((node("service"),), ())
    report = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 10, "cyclomatic_complexity"),
            metric("service", RiskMetricKind.LOW_TEST_DENSITY, 0.75, "risk_ratio"),
        ),
    )
    finding = report.finding("service")

    assert finding is not None
    assert finding.score == pytest.approx((0.25 * 0.5 + 0.10 * 0.75) / 0.35)
    assert finding.confidence.score == pytest.approx(0.2992)
    assert finding.confidence.tier.value == "insufficient"
    assert factor(report, "service", RiskMetricKind.COMPLEXITY).effective_weight == pytest.approx(0.25 / 0.35)
    assert RiskMetricKind.FAN_IN in finding.missing_signals
    assert "not a bug" in finding.explanation


def test_no_metric_evidence_is_unavailable_not_zero_risk() -> None:
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
    )

    assert report.hotspots == ()
    assert all(item.status is RiskAvailability.UNAVAILABLE for item in report.capabilities)
    assert capability(report, RiskMetricKind.COMPLEXITY).observation_count == 0


def test_percentile_cohorts_ties_boundary_and_reordered_inputs_are_deterministic() -> None:
    nodes = tuple(node(f"type-{index:02d}") for index in range(20))
    inputs = tuple(
        metric(
            item.id,
            RiskMetricKind.COMPLEXITY,
            19 if index >= 18 else index,
            "cyclomatic_complexity",
        )
        for index, item in enumerate(nodes)
    )
    service = RiskAnalysisService(RiskConfiguration(top_k=25))
    first = service.analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata(*(item.id for item in nodes)),
        metric_inputs=inputs,
    )
    shuffled_nodes = list(nodes)
    shuffled_inputs = list(inputs)
    random.Random(132).shuffle(shuffled_nodes)
    random.Random(231).shuffle(shuffled_inputs)
    second = RiskAnalysisService(RiskConfiguration(top_k=25)).analyze(
        KnowledgeGraph(tuple(shuffled_nodes), ()),
        symbol_metadata=tuple(reversed(metadata(*(item.id for item in nodes)))),
        metric_inputs=tuple(shuffled_inputs),
    )

    assert first.to_dict() == second.to_dict()
    tied = [first.finding("type-18"), first.finding("type-19")]
    assert all(item is not None for item in tied)
    assert tied[0].factors[0].metric.normalized_value == tied[1].factors[0].metric.normalized_value
    assert tied[0].rank < tied[1].rank
    assert tied[0].factors[0].metric.normalization == "deterministic-midrank-percentile:n=20"

    small_nodes = nodes[:19]
    small = RiskAnalysisService(RiskConfiguration(top_k=25)).analyze(
        KnowledgeGraph(small_nodes, ()),
        symbol_metadata=metadata(*(item.id for item in small_nodes)),
        metric_inputs=tuple(
            metric(item.id, RiskMetricKind.COMPLEXITY, 6, "cyclomatic_complexity")
            for item in small_nodes
        ),
    )
    assert small.hotspots[0].factors[0].metric.normalized_value == 0.5
    assert "absolute-bands" in small.hotspots[0].factors[0].metric.normalization


def test_large_constant_zero_cohort_uses_zero_absolute_band_not_percentiles() -> None:
    nodes = tuple(node(f"unchanged-{index:02d}") for index in range(20))
    report = RiskAnalysisService(RiskConfiguration(top_k=20)).analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata(*(item.id for item in nodes)),
        metric_inputs=tuple(
            metric(item.id, RiskMetricKind.CHANGE_FREQUENCY, 0, "commits")
            for item in nodes
        ),
    )

    values = {
        item.factors[0].metric.normalized_value for item in report.hotspots
    }
    normalizations = {
        item.factors[0].metric.normalization for item in report.hotspots
    }
    assert values == {0.0}
    assert normalizations == {
        "absolute-bands-no-variance:atlas-pr132-normalization/1"
    }
    assert all(
        "Low-coverage cohort" not in limitation
        for limitation in report.hotspots[0].limitations
    )


def test_default_ranking_excludes_test_generated_and_unknown_scopes_explicitly() -> None:
    ids = ("prod", "test", "generated", "unknown")
    graph = KnowledgeGraph(tuple(node(item) for item in ids), ())
    raw_metadata = list(metadata(
        "prod", "test", "generated", scopes={
            "prod": "production", "test": "test", "generated": "generated",
        },
    ))
    raw_metadata.append({"id": "unknown", "project_id": "demo", "source": None, "metadata": {}})
    report = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=tuple(raw_metadata),
        metric_inputs=tuple(
            metric(item, RiskMetricKind.COMPLEXITY, 20, "cyclomatic_complexity")
            for item in ids
        ),
    )

    assert [item.subject_id for item in report.hotspots] == ["prod"]
    assert dict(report.scope_counts) == {
        "generated": 1, "production": 1, "test": 1, "unknown": 1,
    }
    assert dict(report.excluded_scope_counts) == {
        "generated": 1, "test": 1, "unknown": 1,
    }


def test_project_test_counts_do_not_become_resolved_test_density() -> None:
    graph = KnowledgeGraph((node("project:demo", kind=KnowledgeKind.PROJECT),), ())
    summary = {
        "projects": [{
            "name": "project:demo",
            "path": ".",
            "files": 100,
            "size": 10_000,
            "production_files": 60,
            "test_files": 40,
            "generated_files": 0,
            "languages": {"Java": 100},
        }],
    }
    report = RiskAnalysisService().analyze(graph, repository_summary=summary)

    assert capability(report, RiskMetricKind.LOW_TEST_DENSITY).status is RiskAvailability.UNAVAILABLE
    assert factor(report, "project:demo", RiskMetricKind.SIZE).metric.unit == "bytes"
    assert "not lines of code" in " ".join(factor(
        report, "project:demo", RiskMetricKind.SIZE
    ).metric.limitations)


def _git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _commit(root: Path, message: str, email: str, timestamp: str) -> None:
    import os

    environment = dict(os.environ)
    environment.update({
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_NAME": "Atlas Fixture",
        "GIT_COMMITTER_NAME": "Atlas Fixture",
    })
    _git(root, "add", ".")
    _git(root, "commit", "--no-gpg-sign", "-m", message, env=environment)


def test_bounded_git_history_populates_change_and_anonymous_ownership(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    root_file = tmp_path / "root.txt"
    module = tmp_path / "module"
    module.mkdir()
    module_file = module / "Main.java"
    root_file.write_text("one\n", encoding="utf-8")
    _commit(tmp_path, "root", "one@example.test", "2025-01-01T00:00:00+00:00")
    module_file.write_text("one\n", encoding="utf-8")
    _commit(tmp_path, "module one", "one@example.test", "2025-01-02T00:00:00+00:00")
    module_file.write_text("one\ntwo\n", encoding="utf-8")
    _commit(tmp_path, "module two", "two@example.test", "2025-01-03T00:00:00+00:00")

    history = GitContextService(tmp_path).collect_history(commit_limit=10)
    graph = KnowledgeGraph((
        node("root", kind=KnowledgeKind.PROJECT, project="root"),
        node("module", kind=KnowledgeKind.PROJECT, project="module"),
    ), ())
    summary = {"projects": [
        {"name": "root", "path": ".", "size": 10, "production_files": 1, "languages": {"Text": 1}},
        {"name": "module", "path": "module", "size": 20, "production_files": 1, "languages": {"Java": 1}},
    ]}
    report = RiskAnalysisService(
        RiskConfiguration(git_commit_limit=10)
    ).analyze(
        graph,
        repository_summary=summary,
        git_history=history,
    )

    assert history.commits_scanned == 3
    assert history.limit_reached is False
    assert factor(report, "module", RiskMetricKind.CHANGE_FREQUENCY).metric.raw_value == 2
    assert factor(report, "module", RiskMetricKind.OWNERSHIP_CONCENTRATION).metric.raw_value == 0.5
    serialized = json.dumps(report.to_dict(), sort_keys=True)
    assert "one@example.test" not in serialized
    assert "two@example.test" not in serialized
    assert "pseudonymous hashes" in serialized.lower()

    truncated = GitContextService(tmp_path).collect_history(commit_limit=2)
    assert truncated.commits_scanned == 2
    assert truncated.limit_reached is True


def test_report_round_trip_cache_and_trend_are_exact() -> None:
    graph = KnowledgeGraph((node("service"),), ())
    service = RiskAnalysisService()
    first = service.analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 5, "cyclomatic_complexity"),
        ),
    )
    cached = service.analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 5, "cyclomatic_complexity"),
        ),
    )
    restored = RiskAnalysisReport.from_dict(first.to_dict())
    second = service.analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 20, "cyclomatic_complexity"),
        ),
        previous_report=first,
    )

    assert cached is first
    assert restored.to_dict() == first.to_dict()
    assert second.finding("service").trend is RiskTrend.INCREASING


def test_unsupported_metric_unit_is_rejected_before_normalization() -> None:
    with pytest.raises(ValueError, match="unsupported unit for complexity"):
        RiskAnalysisService().analyze(
            KnowledgeGraph((node("service"),), ()),
            symbol_metadata=metadata("service"),
            metric_inputs=(
                metric("service", RiskMetricKind.COMPLEXITY, 7, "unknown-unit"),
            ),
        )


def test_normal_pipeline_publishes_additive_source_free_risk_context(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "Main.java").write_text(
        "package demo; public class Main { public void run() {} }",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])

    assert result.exit_code == 0, result.output
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    payload = snapshot.semantic_context["risk_analysis"]
    project_summary = snapshot.semantic_context["repository_summary"]["projects"][0]
    assert project_summary["inventoried_file_size_error_count"] == 0
    assert payload["schema_version"] == 1
    assert payload["producer_version"] == "atlas-pr132/1"
    assert RiskAnalysisReport.from_dict(payload).to_dict() == payload
    serialized = json.dumps(payload, sort_keys=True)
    assert "public class Main" not in serialized
    assert "public void run" not in serialized


def test_old_snapshot_and_ai_projection_degrade_without_risk_analysis() -> None:
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1, "workspace": {"root": "C:/legacy"},
        }),
        workspace_fingerprint="legacy",
        analyzer_version="test",
        history_reference=1,
    )
    projected = RepositoryExplanationProjector().project(snapshot).to_dict()

    assert projected["risk_analysis"]["status"] == "unavailable"
    assert projected["risk_analysis"]["hotspots"] == []


def test_ai_projection_is_bounded_and_calls_values_risk_indicators() -> None:
    base = RiskAnalysisService(RiskConfiguration(top_k=25)).analyze(
        KnowledgeGraph(tuple(node(f"type-{index:02d}") for index in range(20)), ()),
        symbol_metadata=metadata(*(f"type-{index:02d}" for index in range(20))),
        metric_inputs=tuple(
            metric(f"type-{index:02d}", RiskMetricKind.COMPLEXITY, index, "cyclomatic_complexity")
            for index in range(20)
        ),
    )
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {"root": "C:/demo"},
            "risk_analysis": base.to_dict(),
        }),
        workspace_fingerprint="demo",
        analyzer_version="test",
        history_reference=1,
    )
    projected = RepositoryExplanationProjector().project(snapshot).to_dict()["risk_analysis"]
    serialized = json.dumps(projected, sort_keys=True)

    assert projected["included_hotspot_count"] == 10
    assert projected["omitted_hotspot_count"] == 10
    assert "risk indicators" in projected["interpretation"]
    assert projected["hotspots"][0]["cohort"]
    assert projected["hotspots"][0]["factors"][0]["producer"] == "test-producer.v1"
    assert projected["hotspots"][0]["factors"][0]["window"] == "current-snapshot"
    assert projected["hotspots"][0]["factors"][0]["normalization"]
    assert projected["evidence_records"]
    assert "bug finding" not in serialized.lower()


def test_ten_thousand_subject_chain_graph_keeps_publication_compact() -> None:
    count = 10_000
    nodes = tuple(node(f"n-{index:05d}") for index in range(count))
    edges = tuple(
        KnowledgeEdge(
            f"n-{index:05d}",
            f"n-{index + 1:05d}",
            KnowledgeRelation.INHERITS,
            ("synthetic-structured-edge",),
        )
        for index in range(count - 1)
    )
    graph = KnowledgeGraph(nodes, edges)

    report = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=metadata(*(item.id for item in nodes)),
    )
    payload = json.dumps(report.to_dict(), separators=(",", ":"), sort_keys=True)

    assert len(report.hotspots) == 25
    assert report.analyzed_subject_count == count
    assert len(report.evidence_index) < 100
    assert len(payload.encode("utf-8")) < 1_000_000


def test_canonical_positive_degrees_are_scored_without_inventing_zero_edges() -> None:
    graph = KnowledgeGraph(
        (node("base"), node("child"), node("isolated")),
        (
            KnowledgeEdge(
                "child",
                "base",
                KnowledgeRelation.INHERITS,
                ("java-inheritance:child:base",),
            ),
        ),
    )

    report = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=metadata("base", "child", "isolated"),
    )

    assert factor(report, "base", RiskMetricKind.FAN_IN).metric.raw_value == 1
    assert factor(report, "child", RiskMetricKind.FAN_OUT).metric.raw_value == 1
    assert report.finding("isolated") is None
    assert capability(report, RiskMetricKind.FAN_IN).status is RiskAvailability.PARTIAL
    serialized = json.dumps(report.to_dict(), sort_keys=True)
    assert "positive_relation_degrees" in serialized
    assert "absent relationships remain unknown" in serialized


def test_project_dependency_degree_does_not_create_external_fan_in() -> None:
    graph = KnowledgeGraph(
        (
            node("project:demo", kind=KnowledgeKind.PROJECT, project="demo"),
            node("dependency:g:a:1", kind=KnowledgeKind.DEPENDENCY, project="demo"),
        ),
        (
            KnowledgeEdge(
                "project:demo",
                "dependency:g:a:1",
                KnowledgeRelation.DEPENDS_ON,
                ("maven-dependency:demo:g:a:1:compile",),
            ),
        ),
    )
    summary = {"projects": [{
        "name": "project:demo",
        "path": ".",
        "inventoried_file_bytes": 100,
        "classified_non_test_source_files": 1,
        "language_file_counts": {"Java": 1},
    }]}

    report = RiskAnalysisService().analyze(graph, repository_summary=summary)

    assert factor(report, "project:demo", RiskMetricKind.FAN_OUT).metric.raw_value == 1
    assert not any(
        item.metric.metric is RiskMetricKind.FAN_IN
        for item in report.finding("project:demo").factors
    )


def test_zero_coverage_input_is_unavailable_and_never_ranked() -> None:
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric(
                "service",
                RiskMetricKind.COMPLEXITY,
                20,
                "cyclomatic_complexity",
                coverage=0.0,
            ),
        ),
    )

    assert report.hotspots == ()
    result = capability(report, RiskMetricKind.COMPLEXITY)
    assert result.status is RiskAvailability.UNAVAILABLE
    assert result.observation_count == 1
    assert result.scored_subject_count == 0


def test_external_evidence_is_canonical_and_raw_source_is_not_republished() -> None:
    raw_source = 'class Secret { String password = "hunter2"; }'
    safe_input = metric(
        "service",
        RiskMetricKind.COMPLEXITY,
        10,
        "cyclomatic_complexity",
        source_refs=(raw_source,),
    )
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(safe_input,),
    )

    assert raw_source not in json.dumps(report.to_dict(), sort_keys=True)
    original = safe_input.evidence_records[0]
    forged = EvidenceRecord(
        'password="hunter2"',
        original.kind,
        original.subject_id,
        original.producer,
        original.snapshot_id,
        original.source_refs,
        original.scope,
        original.language,
        original.detail,
        original.limitations,
        original.reliability,
        original.specificity,
    )
    with pytest.raises(ValueError, match="canonical deterministic evidence ID"):
        RiskMetricInput(
            "service",
            RiskMetricKind.COMPLEXITY,
            10,
            "cyclomatic_complexity",
            original.producer,
            (forged,),
        )

    raw_limitation = 'class Secret { String token = "TOP-SECRET"; }'
    limited_evidence = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "service",
        "limited-producer.v1",
        "test-snapshot",
        source_refs=("semantic-result:limited",),
        limitations=(raw_limitation,),
        reliability=0.9,
        specificity=0.9,
    )
    limited_report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(RiskMetricInput(
            "service",
            RiskMetricKind.COMPLEXITY,
            10,
            "cyclomatic_complexity",
            "limited-producer.v1",
            (limited_evidence,),
            limitations=(raw_limitation,),
        ),),
    )
    limited_payload = json.dumps(limited_report.to_dict(), sort_keys=True)
    assert raw_limitation not in limited_payload
    assert "reported one or more limitations" in limited_payload
    assert '"upstream_limitation_count": "2"' in limited_payload

    unsafe_producer = "class Secret {}"
    unsafe_evidence = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        "service",
        unsafe_producer,
        "test-snapshot",
    )
    with pytest.raises(ValueError, match="bounded semantic identifier"):
        RiskMetricInput(
            "service",
            RiskMetricKind.COMPLEXITY,
            10,
            "cyclomatic_complexity",
            unsafe_producer,
            (unsafe_evidence,),
        )


def test_incomplete_inventory_size_is_unavailable_not_zero_risk(tmp_path: Path) -> None:
    graph = KnowledgeGraph((
        node("demo", kind=KnowledgeKind.PROJECT, project="demo"),
    ), ())
    base = {
        "name": "demo",
        "path": ".",
        "inventoried_file_bytes": 0,
        "inventoried_file_count": 1,
        "classified_non_test_source_files": 1,
        "language_file_counts": {"Java": 1},
    }
    incomplete = RiskAnalysisService().analyze(
        graph,
        repository_summary={
            "projects": [{**base, "inventoried_file_size_error_count": 1}],
        },
    )
    legacy_snapshot = RiskAnalysisService().analyze(
        graph,
        repository_summary={"projects": [base]},
    )
    complete = RiskAnalysisService().analyze(
        graph,
        repository_summary={
            "projects": [{**base, "inventoried_file_size_error_count": 0}],
        },
    )

    assert incomplete.finding("demo") is None
    assert legacy_snapshot.finding("demo") is None
    assert capability(incomplete, RiskMetricKind.SIZE).status is RiskAvailability.UNAVAILABLE
    assert capability(legacy_snapshot, RiskMetricKind.SIZE).status is RiskAvailability.UNAVAILABLE
    assert factor(complete, "demo", RiskMetricKind.SIZE).metric.raw_value == 0
    assert RepositorySummaryService._size(tmp_path / "missing.java") == (0, 1)


def test_normalization_separates_producers_and_windows() -> None:
    nodes = tuple(node(f"subject-{index:02d}") for index in range(40))
    inputs = tuple(
        metric(
            item.id,
            RiskMetricKind.COMPLEXITY,
            index % 20,
            "cyclomatic_complexity",
            producer="producer-a.v1" if index < 20 else "producer-b.v1",
            window="snapshot-a" if index < 20 else "snapshot-b",
        )
        for index, item in enumerate(nodes)
    )
    report = RiskAnalysisService(RiskConfiguration(top_k=40)).analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata(*(item.id for item in nodes)),
        metric_inputs=inputs,
    )

    first = factor(report, "subject-19", RiskMetricKind.COMPLEXITY).metric
    second = factor(report, "subject-39", RiskMetricKind.COMPLEXITY).metric
    assert first.normalized_value == second.normalized_value == 1.0
    assert first.cohort != second.cohort
    assert "producer=producer-a.v1" in first.cohort
    assert "window=snapshot-b" in second.cohort


def test_scope_fallback_distinguishes_source_roots_from_package_names() -> None:
    ids = ("package-example", "example-project", "fixture", "vendored")
    raw_metadata = (
        {
            "id": "package-example",
            "project_id": "demo",
            "source": "src/main/java/example/Production.java",
            "metadata": {},
        },
        {
            "id": "example-project",
            "project_id": "demo",
            "source": "examples/demo/src/main/java/Demo.java",
            "metadata": {},
        },
        {
            "id": "fixture",
            "project_id": "demo",
            "source": "src/testFixtures/java/Fixture.java",
            "metadata": {},
        },
        {
            "id": "vendored",
            "project_id": "demo",
            "source": "vendor/Library.java",
            "metadata": {"source_classification": "vendored"},
        },
    )
    report = RiskAnalysisService().analyze(
        KnowledgeGraph(tuple(node(item) for item in ids), ()),
        symbol_metadata=raw_metadata,
        metric_inputs=tuple(
            metric(item, RiskMetricKind.COMPLEXITY, 20, "cyclomatic_complexity")
            for item in ids
        ),
    )

    assert [item.subject_id for item in report.hotspots] == ["package-example"]
    assert dict(report.scope_counts) == {
        "production": 1,
        "test": 2,
        "unknown": 1,
    }


def test_configuration_rejects_duplicate_metric_weights() -> None:
    duplicated = tuple(RiskConfiguration().weights)
    duplicated = (*duplicated[:-1], duplicated[0])

    with pytest.raises(ValueError, match="exactly once"):
        RiskConfiguration(weights=duplicated)


def test_report_deserialization_rejects_missing_evidence_records() -> None:
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 10, "cyclomatic_complexity"),
        ),
    )
    payload = report.to_dict()
    payload["evidence_index"]["records"] = []

    with pytest.raises(ValueError, match="references missing evidence"):
        RiskAnalysisReport.from_dict(payload)


def test_failed_projects_are_reported_as_partial_without_stopping_other_results() -> None:
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 10, "cyclomatic_complexity"),
        ),
        failed_projects=("broken-module",),
    )

    assert report.finding("service") is not None
    assert any("broken-module" in item for item in report.limitations)


def test_git_history_from_subdirectory_is_workspace_relative(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    _commit(tmp_path, "outside", "one@example.test", "2025-02-01T00:00:00+00:00")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "Main.java"
    source.write_text("class Main {}\n", encoding="utf-8")
    _commit(tmp_path, "workspace", "two@example.test", "2025-02-02T00:00:00+00:00")

    history = GitContextService(workspace).collect_history(commit_limit=10)

    assert history.workspace_prefix == "workspace"
    assert history.commits_scanned == 1
    assert [item.path for item in history.changes] == ["Main.java"]


def test_repository_summary_order_does_not_change_report_identity() -> None:
    graph = KnowledgeGraph((
        node("one", kind=KnowledgeKind.PROJECT, project="one"),
        node("two", kind=KnowledgeKind.PROJECT, project="two"),
    ), ())
    projects = [
        {
            "name": "one", "path": "one", "inventoried_file_bytes": 10,
            "classified_non_test_source_files": 1,
            "language_file_counts": {"Java": 1},
        },
        {
            "name": "two", "path": "two", "inventoried_file_bytes": 20,
            "classified_non_test_source_files": 1,
            "language_file_counts": {"Java": 1},
        },
    ]

    first = RiskAnalysisService().analyze(graph, repository_summary={"projects": projects})
    second = RiskAnalysisService().analyze(
        graph, repository_summary={"projects": list(reversed(projects))}
    )

    assert first.to_dict() == second.to_dict()


def test_conflicting_duplicate_symbol_metadata_is_rejected_in_any_order() -> None:
    graph = KnowledgeGraph((node("service"),), ())
    production = {
        "id": "service",
        "project_id": "demo",
        "source": "src/main/java/Service.java",
        "metadata": {},
    }
    test = {
        "id": "service",
        "project_id": "demo",
        "source": "src/test/java/ServiceTest.java",
        "metadata": {},
    }
    observation = (
        metric("service", RiskMetricKind.COMPLEXITY, 10, "cyclomatic_complexity"),
    )

    for records in ((production, test), (test, production)):
        with pytest.raises(
            ValueError,
            match="conflicting duplicate symbol metadata for canonical ID: service",
        ):
            RiskAnalysisService().analyze(
                graph,
                symbol_metadata=records,
                metric_inputs=observation,
            )


def test_snapshot_replay_accepts_real_ass_envelope_and_nearest_rank_p95(
    tmp_path: Path,
) -> None:
    graph = KnowledgeGraph((
        node("demo", kind=KnowledgeKind.PROJECT, project="demo"),
    ), ())
    snapshot = tmp_path / "latest.ass"
    atlas_snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "semantic_graph": graph.to_dict(),
            "repository_summary": {"projects": [{
                "name": "demo",
                "path": ".",
                "inventoried_file_bytes": 100,
                "classified_non_test_source_files": 1,
                "language_file_counts": {"Java": 1},
            }]},
            "symbols": [],
        }),
        workspace_fingerprint="fixture-workspace",
        analyzer_version="fixture-analyzer",
    )
    raw_snapshot = atlas_snapshot.to_dict()
    snapshot.write_text(json.dumps({
        "checksum": hashlib.sha256(
            canonical_json(raw_snapshot).encode("utf-8")
        ).hexdigest(),
        "format": SEMANTIC_SNAPSHOT_FORMAT,
        "snapshot": raw_snapshot,
    }), encoding="utf-8")

    result = replay(snapshot, repeats=2)

    assert result["graph_nodes"] == 1
    assert result["repeats"] == 2
    assert result["input_validation"] == "envelope-checksum-and-snapshot-id"
    assert result["exact_feature_snapshot_bytes"] > 0
    assert result["enriched_with_risk_bytes"] > result["baseline_without_risk_bytes"]
    assert nearest_rank([1.0, 2.0, 3.0], 0.95) == 3.0
    assert nearest_rank([5.0, 1.0, 3.0, 4.0, 2.0], 0.95) == 5.0

    envelope = json.loads(snapshot.read_text(encoding="utf-8"))
    envelope["checksum"] = "0" * 64
    snapshot.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        replay(snapshot, repeats=1)


def test_cache_is_immutable_and_safe_for_concurrent_readers() -> None:
    graph = KnowledgeGraph((node("service"),), ())
    inputs = (
        metric(
            "service",
            RiskMetricKind.COMPLEXITY,
            10,
            "cyclomatic_complexity",
        ),
    )
    service = RiskAnalysisService()
    report = service.analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=inputs,
    )
    extra = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        "service",
        "test-producer.v1",
        "test-snapshot",
    )

    with pytest.raises(TypeError, match="frozen evidence"):
        report.evidence_index.add(extra)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(
            lambda _: service.analyze(
                graph,
                symbol_metadata=metadata("service"),
                metric_inputs=inputs,
            ),
            range(32),
        ))

    assert all(item is report for item in results)
    assert service.analyze(
        graph,
        symbol_metadata=metadata("service"),
        metric_inputs=inputs,
    ).to_dict() == report.to_dict()


def test_ranking_uses_unrounded_scores_before_canonical_tie_breaking() -> None:
    weights = tuple(
        (
            kind,
            1.0 if kind is RiskMetricKind.COMPLEXITY
            else 0.0000001 if kind is RiskMetricKind.SIZE
            else 0.0,
        )
        for kind in RiskMetricKind
    )
    graph = KnowledgeGraph((node("a-lower"), node("z-higher")), ())
    inputs = (
        metric("a-lower", RiskMetricKind.COMPLEXITY, 6, "cyclomatic_complexity"),
        metric("z-higher", RiskMetricKind.COMPLEXITY, 6, "cyclomatic_complexity"),
        metric("a-lower", RiskMetricKind.SIZE, 0, "bytes"),
        metric("z-higher", RiskMetricKind.SIZE, 200_000_000, "bytes"),
    )

    report = RiskAnalysisService(
        RiskConfiguration(top_k=1, weights=weights)
    ).analyze(
        graph,
        symbol_metadata=metadata("a-lower", "z-higher"),
        metric_inputs=inputs,
    )

    assert report.hotspots[0].subject_id == "z-higher"
    assert report.hotspots[0].score == 0.5


def test_heatmaps_and_capability_producers_are_bounded() -> None:
    count = 60
    nodes = tuple(node(f"subject-{index:02d}") for index in range(count))
    inputs = tuple(
        metric(
            item.id,
            RiskMetricKind.COMPLEXITY,
            10,
            "cyclomatic_complexity",
            producer=f"producer-{index:02d}.v1",
        )
        for index, item in enumerate(nodes)
    )

    report = RiskAnalysisService().analyze(
        KnowledgeGraph(nodes, ()),
        symbol_metadata=metadata(*(item.id for item in nodes)),
        metric_inputs=inputs,
    )
    complexity = capability(report, RiskMetricKind.COMPLEXITY)
    heatmap = next(
        item for item in report.heatmaps
        if item.metric is RiskMetricKind.COMPLEXITY
    )

    assert len(complexity.producers) == 32
    assert complexity.omitted_producer_count == 28
    assert len(heatmap.cohorts) == 50
    assert heatmap.omitted_cohort_count == 10
    assert heatmap.omitted_subject_count == 10


def test_test_or_sample_project_sources_do_not_enter_production_ranking(
    tmp_path: Path,
) -> None:
    project = tmp_path / "examples" / "demo"
    source = project / "src" / "main" / "java" / "Demo.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Demo {}\n", encoding="utf-8")
    named_sample = tmp_path / "app" / "src" / "main" / "java" / "App.java"
    named_sample.parent.mkdir(parents=True)
    named_sample.write_text("class App {}\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: demo-sample\n"
        "    path: examples/demo\n"
        "  - name: samples-by-name-only\n"
        "    path: app\n",
        encoding="utf-8",
    )

    summary = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    projects = {item["name"]: item for item in summary["projects"]}

    assert projects["demo-sample"]["classified_non_test_source_files"] == 0
    assert projects["demo-sample"]["classified_test_source_files"] == 1
    assert projects["samples-by-name-only"]["classified_non_test_source_files"] == 1
    assert projects["samples-by-name-only"]["classified_test_source_files"] == 0


def test_project_specific_git_limitations_do_not_leak_to_other_projects() -> None:
    graph = KnowledgeGraph((
        node("a", kind=KnowledgeKind.PROJECT, project="a"),
        node("b", kind=KnowledgeKind.PROJECT, project="b"),
    ), ())
    summary = {"projects": [
        {
            "name": "a", "path": "a", "inventoried_file_bytes": 1,
            "inventoried_file_size_error_count": 0,
            "classified_non_test_source_files": 1,
            "language_file_counts": {"Java": 1},
        },
        {
            "name": "b", "path": "b", "inventoried_file_bytes": 1,
            "inventoried_file_size_error_count": 0,
            "classified_non_test_source_files": 1,
            "language_file_counts": {"Java": 1},
        },
    ]}
    history = GitHistoryWindow(
        "a" * 40,
        10,
        2,
        (
            GitFileChange("1" * 40, "2025-01-01T00:00:00Z", "", "a/A.java", 1, 0),
            GitFileChange(
                "2" * 40,
                "2025-01-02T00:00:00Z",
                "git-contributor:known",
                "b/B.java",
                1,
                0,
            ),
        ),
    )

    report = RiskAnalysisService(
        RiskConfiguration(git_commit_limit=10)
    ).analyze(graph, repository_summary=summary, git_history=history)
    b_ownership = factor(
        report,
        "b",
        RiskMetricKind.OWNERSHIP_CONCENTRATION,
    )

    assert not any("unavailable for a" in item for item in b_ownership.metric.limitations)
    assert any("unavailable for a" in item for item in report.limitations)


def test_graph_metric_trend_survives_a_canonical_graph_change() -> None:
    nodes = (node("base"), node("child-1"), node("child-2"))
    first_graph = KnowledgeGraph(nodes, (
        KnowledgeEdge("child-1", "base", KnowledgeRelation.INHERITS, ("first",)),
    ))
    second_graph = KnowledgeGraph(nodes, (
        KnowledgeEdge("child-1", "base", KnowledgeRelation.INHERITS, ("first",)),
        KnowledgeEdge("child-2", "base", KnowledgeRelation.INHERITS, ("second",)),
    ))
    service = RiskAnalysisService()
    first = service.analyze(first_graph, symbol_metadata=metadata(*(item.id for item in nodes)))
    second = service.analyze(
        second_graph,
        symbol_metadata=metadata(*(item.id for item in nodes)),
        previous_report=first,
    )

    assert second.finding("base").trend is RiskTrend.INCREASING


def test_incremental_git_window_produces_a_comparable_trend(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    source = tmp_path / "Main.java"
    source.write_text("class Main {}\n", encoding="utf-8")
    _commit(tmp_path, "first", "one@example.test", "2025-01-01T00:00:00+00:00")
    graph = KnowledgeGraph((node("demo", kind=KnowledgeKind.PROJECT),), ())
    summary = {"projects": [{
        "name": "demo",
        "path": ".",
        "inventoried_file_bytes": 10,
        "inventoried_file_size_error_count": 0,
        "classified_non_test_source_files": 1,
        "language_file_counts": {"Java": 1},
    }]}
    service = RiskAnalysisService(RiskConfiguration(git_commit_limit=10))
    first = service.analyze(
        graph,
        repository_summary=summary,
        git_history=GitContextService(tmp_path).collect_history(commit_limit=10),
    )

    source.write_text("class Main { void run() {} }\n", encoding="utf-8")
    _commit(tmp_path, "second", "one@example.test", "2025-01-02T00:00:00+00:00")
    second = service.analyze(
        graph,
        repository_summary=summary,
        git_history=GitContextService(tmp_path).collect_history(commit_limit=10),
        previous_report=first,
    )

    assert factor(
        second,
        "demo",
        RiskMetricKind.CHANGE_FREQUENCY,
    ).metric.raw_value == 2
    assert second.finding("demo").trend is RiskTrend.INCREASING


def test_git_history_decodes_non_ascii_paths_deterministically(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    source = tmp_path / "ā.java"
    source.write_text("class UnicodePath {}\n", encoding="utf-8")
    _commit(tmp_path, "unicode path", "unicode@example.test", "2025-03-01T00:00:00+00:00")

    history = GitContextService(tmp_path).collect_history(commit_limit=10)

    assert [item.path for item in history.changes] == ["ā.java"]

    with pytest.raises(ValueError, match="workspace-relative"):
        GitFileChange("1", "2025-01-01T00:00:00Z", "", "../outside.java", 1, 0)


def test_deserialization_rejects_invalid_confidence_and_heatmap_counts() -> None:
    report = RiskAnalysisService().analyze(
        KnowledgeGraph((node("service"),), ()),
        symbol_metadata=metadata("service"),
        metric_inputs=(
            metric("service", RiskMetricKind.COMPLEXITY, 10, "cyclomatic_complexity"),
        ),
    )
    confidence_payload = report.to_dict()
    confidence_payload["hotspots"][0]["confidence"]["score"] = 2.0
    with pytest.raises(ValueError, match="confidence score"):
        RiskAnalysisReport.from_dict(confidence_payload)

    heatmap_payload = report.to_dict()
    complexity_heatmap = next(
        item for item in heatmap_payload["heatmaps"]
        if item["metric"] == "complexity"
    )
    complexity_heatmap["cohorts"][0]["bins"][0]["count"] = -1
    with pytest.raises(ValueError, match="bin count"):
        RiskAnalysisReport.from_dict(heatmap_payload)
