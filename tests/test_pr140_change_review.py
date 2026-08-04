from __future__ import annotations

from copy import deepcopy
import json

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.change_review import (
    CHANGE_REVIEW_PRODUCER,
    ChangeReviewRequest,
    ChangeReviewResponse,
    ChangeReviewService,
    ChangeReviewState,
    ChangedFileStatus,
    SnapshotAlignmentState,
    render_change_review,
)
from moughorai.git_diff import DiffFile, DiffHunk, GitDiff
from moughorai.impact_analysis import ImpactChangeKind
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.reachability import (
    CoverageStatus,
    ProjectEvidence,
    ReachabilityAnalysisService,
    ReachabilityEvidenceBundle,
    ReachabilitySeed,
    RootCategory,
)
from moughorai.risk_analysis import (
    RiskAnalysisService,
    RiskMetricInput,
    RiskMetricKind,
)
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


def _node(
    identifier: str,
    kind: KnowledgeKind,
    name: str,
    *,
    project: str = "core",
    path: str | None = None,
) -> KnowledgeNode:
    metadata = (("path", path),) if path is not None else ()
    return KnowledgeNode(
        identifier,
        kind,
        name,
        metadata=metadata,
        qualified_name=name,
        project_id=project,
        language="java",
    )


def _snapshot(*, reverse: bool = False) -> AtlasSemanticSnapshot:
    nodes = (
        _node("project:core", KnowledgeKind.PROJECT, "core", path="."),
        _node("type:api", KnowledgeKind.TYPE, "demo.Api"),
        _node("type:consumer", KnowledgeKind.TYPE, "demo.Consumer"),
        _node("type:other", KnowledgeKind.TYPE, "demo.Other"),
    )
    edges = (
        KnowledgeEdge(
            "type:consumer",
            "type:api",
            KnowledgeRelation.IMPORTS,
            ("imports",),
        ),
    )
    graph = KnowledgeGraph(
        tuple(reversed(nodes)) if reverse else nodes,
        tuple(reversed(edges)) if reverse else edges,
    )
    symbols = [
        {"id": "type:api", "name": "Api", "source": "src/Api.java"},
        {
            "id": "type:consumer",
            "name": "Consumer",
            "source": "src/Consumer.java",
        },
        {"id": "type:other", "name": "Other", "source": "src/Other.java"},
    ]
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": symbols,
        }),
        workspace_fingerprint="pr140-workspace",
        analyzer_version="test-pr140/1",
    )


def _diff(*, reverse: bool = False) -> GitDiff:
    files = (
        DiffFile(
            "src/Api.java",
            "src/Api.java",
            (DiffHunk(4, 1, 4, 2, (4, 5), (4,)),),
        ),
        DiffFile(
            "src/Other.java",
            "src/Other.java",
            (DiffHunk(2, 1, 2, 1, (2,), (2,)),),
        ),
    )
    return GitDiff(
        tuple(reversed(files)) if reverse else files,
        base="HEAD~1",
        head="HEAD",
        repository_head="a" * 40,
        base_commit="b" * 40,
        head_commit="a" * 40,
    )


def _review(
    *,
    snapshot: AtlasSemanticSnapshot | None = None,
    diff: GitDiff | None = None,
    request: ChangeReviewRequest | None = None,
    fingerprint: str | None = "pr140-workspace",
) -> ChangeReviewResponse:
    selected_snapshot = snapshot or _snapshot()
    return ChangeReviewService.from_snapshot(selected_snapshot).review(
        diff or _diff(),
        request or ChangeReviewRequest(),
        current_workspace_fingerprint=fingerprint,
    )


def test_change_review_composes_exact_paths_and_pr136_impact() -> None:
    response = _review()

    assert response.producer_version == CHANGE_REVIEW_PRODUCER
    assert response.alignment is SnapshotAlignmentState.CURRENT
    assert [item.path for item in response.changed_files] == [
        "src/Api.java",
        "src/Other.java",
    ]
    assert response.changed_files[0].status is ChangedFileStatus.MODIFIED
    assert response.changed_files[0].subjects[0].canonical_id == "type:api"
    assert response.impact is not None
    assert "type:consumer" in {
        item.subject.canonical_id for item in response.impact.findings
    }
    assert response.section("impact").state is ChangeReviewState.PARTIAL
    assert response.section("subject_mapping").state is ChangeReviewState.PARTIAL
    assert all(
        record.snapshot_id == response.lineage
        for record in response.evidence_index.records
    )
    assert not contains_absolute_path(response.to_dict())


def test_empty_diff_is_available_without_fabricated_semantic_findings() -> None:
    response = _review(diff=GitDiff(()))

    assert response.changed_files == ()
    assert response.diff.total_file_count == 0
    assert response.section("git_diff").state is ChangeReviewState.AVAILABLE
    assert response.section("impact").state is ChangeReviewState.INSUFFICIENT
    assert response.impact is None
    assert ChangeReviewResponse.from_dict(response.to_dict()).to_dict() == response.to_dict()


def test_older_snapshot_without_pr129_graph_reports_unavailable_identity() -> None:
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({"schema_version": 1}),
        workspace_fingerprint="old-workspace",
        analyzer_version="legacy-fixture/1",
    )
    response = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("src/Api.java", "src/Api.java"),)),
        fingerprint="old-workspace",
    )

    assert response.changed_files[0].subjects == ()
    assert response.section("subject_mapping").state is ChangeReviewState.UNAVAILABLE
    assert response.section("impact").state is ChangeReviewState.INSUFFICIENT
    assert "PR129 graph" in " ".join(response.limitations)


def test_change_review_serialization_and_rendering_are_exact_and_deterministic() -> None:
    first = _review()
    second = _review(snapshot=_snapshot(reverse=True), diff=_diff(reverse=True))

    assert first.to_json() == second.to_json()
    assert ChangeReviewResponse.from_dict(first.to_dict()).to_dict() == first.to_dict()
    assert render_change_review(first) == render_change_review(second)
    assert "Atlas Change Review" in render_change_review(first)
    assert first.diff.source_content_retained is False
    assert "public class" not in first.to_json()


def test_unknown_and_stale_snapshots_disable_semantic_conclusions() -> None:
    unknown = _review(fingerprint=None)
    stale = _review(fingerprint="different-workspace")

    assert unknown.alignment is SnapshotAlignmentState.UNKNOWN
    assert unknown.impact is None
    assert unknown.architecture_reviews == ()
    assert all(not item.subjects for item in unknown.changed_files)
    assert unknown.section("impact").state is ChangeReviewState.UNAVAILABLE

    assert stale.alignment is SnapshotAlignmentState.STALE
    assert stale.impact is None
    assert stale.section("subject_mapping").state is ChangeReviewState.STALE
    assert stale.section("architecture").state is ChangeReviewState.STALE


def test_explicit_currency_assumption_is_partial_and_reproducible() -> None:
    request = ChangeReviewRequest(assume_snapshot_current=True)
    response = _review(request=request, fingerprint=None)

    assert response.alignment is SnapshotAlignmentState.ASSUMED_CURRENT
    assert response.impact is not None
    assert response.section("snapshot_alignment").state is ChangeReviewState.PARTIAL
    assert "explicitly assumed" in " ".join(response.limitations)


def test_deleted_binary_and_renamed_files_preserve_uncertainty() -> None:
    diff = GitDiff((
        DiffFile("src/Api.java", None, (DiffHunk(1, 1, 0, 0, (), (1,)),)),
        DiffFile("assets/logo.bin", "assets/logo.bin", (), binary=True),
        DiffFile("src/Old.java", "src/Other.java", (), renamed=True),
    ))
    response = _review(diff=diff)
    by_path = {item.path: item for item in response.changed_files}

    assert by_path["src/Api.java"].status is ChangedFileStatus.DELETED
    assert by_path["src/Api.java"].subjects == ()
    assert "base snapshot" in " ".join(by_path["src/Api.java"].limitations)
    assert by_path["assets/logo.bin"].binary is True
    assert by_path["assets/logo.bin"].subjects == ()
    assert by_path["src/Other.java"].status is ChangedFileStatus.RENAMED
    assert "identity continuity" in " ".join(by_path["src/Other.java"].limitations)


def test_file_and_subject_bounds_are_reported_not_silently_dropped() -> None:
    response = _review(request=ChangeReviewRequest(
        maximum_files=1,
        maximum_subjects_per_file=1,
        maximum_subjects=1,
    ))

    assert response.diff.total_file_count == 2
    assert response.diff.selected_file_count == 1
    assert response.diff.omitted_file_count == 1
    assert response.section("git_diff").state is ChangeReviewState.PARTIAL
    assert "1 changed file" in " ".join(response.limitations)


def test_missing_calls_and_tests_never_become_a_no_tests_claim() -> None:
    response = _review()
    tests = response.section("tests")
    wording = " ".join(tests.limitations).casefold()

    assert tests.item_ids == ()
    assert tests.state in {
        ChangeReviewState.PARTIAL,
        ChangeReviewState.UNAVAILABLE,
        ChangeReviewState.INSUFFICIENT,
    }
    assert "must not be interpreted" in wording
    assert "no tests are required" in wording


def test_compatible_pr131_evidence_produces_a_targeted_test_recommendation() -> None:
    root = _node("method:root", KnowledgeKind.METHOD, "demo.Api#run()")
    test = _node("method:test", KnowledgeKind.METHOD, "demo.ApiTest#testRun()")
    graph = KnowledgeGraph(
        (root, test),
        (KnowledgeEdge(
            "method:test",
            "method:root",
            KnowledgeRelation.CALLS,
            ("fixture:calls",),
        ),),
    )
    reachability = ReachabilityAnalysisService().analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            roots=(ReachabilitySeed(
                "method:test",
                RootCategory.TEST,
                "core",
                source_refs=("test-root",),
            ),),
            projects=(ProjectEvidence(
                "core",
                ("java",),
                roots=CoverageStatus.COMPLETE,
                calls=CoverageStatus.COMPLETE,
            ),),
        ),
        snapshot_lineage="pr131-fixture",
    )
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [
                {"id": "method:root", "name": "run", "source": "src/Api.java"},
                {"id": "method:test", "name": "testRun", "source": "test/ApiTest.java"},
            ],
            "reachability": reachability.to_dict(),
        }),
        workspace_fingerprint="test-link-workspace",
        analyzer_version="test-pr140/1",
    )
    response = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("src/Api.java", "src/Api.java"),)),
        fingerprint="test-link-workspace",
    )

    assert response.section("tests").state is ChangeReviewState.PARTIAL
    assert response.section("tests").item_ids == ("method:test",)
    assert response.section("tests").evidence_ids


def test_compatible_pr132_risk_is_current_context_not_diff_attribution() -> None:
    base = _snapshot()
    graph = KnowledgeGraph.from_dict(base.semantic_context["semantic_graph"])
    evidence = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        "type:consumer",
        "test-risk-producer/1",
        "risk-fixture",
        source_refs=("semantic-fact:complexity",),
        detail={"metric": "complexity", "unit": "cyclomatic_complexity"},
        reliability=0.9,
        specificity=0.95,
    )
    report = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=({
            "id": "type:consumer",
            "project_id": "core",
            "source": "src/Consumer.java",
            "metadata": {},
        },),
        metric_inputs=(RiskMetricInput(
            "type:consumer",
            RiskMetricKind.COMPLEXITY,
            20.0,
            "cyclomatic_complexity",
            "test-risk-producer/1",
            (evidence,),
        ),),
    )
    context = dict(base.semantic_context)
    context["risk_analysis"] = report.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="risk-workspace",
        analyzer_version="test-pr140/1",
    )
    response = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("src/Api.java", "src/Api.java"),)),
        fingerprint="risk-workspace",
    )

    risk = response.section("risk")
    assert risk.state is ChangeReviewState.PARTIAL
    assert risk.item_ids == ("type:consumer",)
    wording = " ".join(risk.limitations).casefold()
    assert "existing pr132 current-snapshot context" in wording
    assert "not claimed to have introduced" in wording


def test_general_migration_and_clean_architecture_are_not_inferred() -> None:
    response = _review()

    assert response.section("architecture").item_ids == ()
    assert response.section("architecture").state is ChangeReviewState.INSUFFICIENT
    assert "no clean-architecture claim" in " ".join(
        response.section("architecture").limitations
    )
    assert response.section("migration").state is ChangeReviewState.UNSUPPORTED


def _cycle_snapshot() -> AtlasSemanticSnapshot:
    nodes = tuple(
        _node(
            f"project:{name}",
            KnowledgeKind.PROJECT,
            name,
            project=name,
            path=f"{name}/pom.xml",
        )
        for name in ("alpha", "beta", "gamma")
    )
    edges = tuple(
        KnowledgeEdge(
            f"project:{source}",
            f"project:{target}",
            KnowledgeRelation.DEPENDS_ON,
            (f"workspace.projects:{source}:dependencies:{target}",),
        )
        for source, target in (
            ("alpha", "beta"),
            ("beta", "gamma"),
            ("gamma", "alpha"),
        )
    )
    graph = KnowledgeGraph(nodes, edges)
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "semantic_graph": graph.to_dict(),
        "symbols": [],
        "workspace": {
            "root": ".",
            "projects": [
                {"name": name, "path": name, "dependencies": []}
                for name in ("alpha", "beta", "gamma")
            ],
        },
        "architecture": {
            "schema_version": 1,
            "findings": [],
            "dependency_directions": [],
            "dependency_cycles": [["alpha", "beta", "gamma"]],
            "bounded_contexts": [],
            "ports": [],
            "adapters": [],
            "infrastructure_layers": [],
            "dependency_analysis": {"executed": True, "evidence_edge_count": 3},
            "classification_conflicts": [],
        },
    })
    snapshot = AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="cycle-workspace",
        analyzer_version="test-pr140/1",
    )
    return snapshot


def test_verified_cycle_seam_is_presented_as_existing_context_only() -> None:
    snapshot = _cycle_snapshot()
    diff = GitDiff((DiffFile("alpha/pom.xml", "alpha/pom.xml"),))
    response = _review(
        snapshot=snapshot,
        diff=diff,
        fingerprint="cycle-workspace",
    )

    assert response.architecture_reviews
    assert response.section("architecture").state is ChangeReviewState.PARTIAL
    assert response.section("migration").state is ChangeReviewState.PARTIAL
    wording = " ".join(response.section("architecture").limitations).casefold()
    assert "existing" in wording
    assert "not claimed to have introduced" in wording


def test_architecture_advice_limit_is_global_across_changed_scopes() -> None:
    snapshot = _cycle_snapshot()
    paths = tuple(
        f"{name}/pom.xml" for name in ("alpha", "beta", "gamma")
    )
    request = ChangeReviewRequest(
        architecture_subject_limit=3,
        architecture_advice_limit=1,
    )

    first = _review(
        snapshot=snapshot,
        diff=GitDiff(tuple(DiffFile(path, path) for path in paths)),
        request=request,
        fingerprint="cycle-workspace",
    )
    second = _review(
        snapshot=snapshot,
        diff=GitDiff(tuple(DiffFile(path, path) for path in reversed(paths))),
        request=request,
        fingerprint="cycle-workspace",
    )

    advice = tuple(
        item
        for review in first.architecture_reviews
        for item in review.advice
    )
    assert first.to_json() == second.to_json()
    assert len(advice) == 1
    assert first.section("architecture").item_ids == (advice[0].advice_id,)
    assert "global result bound" in " ".join(
        first.section("architecture").limitations
    )


def test_request_and_response_models_reject_tampering() -> None:
    response = _review()
    payload = response.to_dict()

    unknown = deepcopy(payload)
    unknown["unexpected"] = True
    with pytest.raises(ValueError, match="unknown change review response"):
        ChangeReviewResponse.from_dict(unknown)

    stale_with_impact = deepcopy(payload)
    stale_with_impact["alignment"] = "stale"
    with pytest.raises(ValueError, match="fingerprint|stale|projection|alignment"):
        ChangeReviewResponse.from_dict(stale_with_impact)

    malformed_evidence = deepcopy(payload)
    malformed_evidence["changed_files"][0]["evidence_ids"] = ["evidence:bad"]  # type: ignore[index]
    with pytest.raises(ValueError, match="malformed evidence"):
        ChangeReviewResponse.from_dict(malformed_evidence)

    assert json.loads(response.to_json())["request"]["change_kind"] == ImpactChangeKind.UNKNOWN.value
