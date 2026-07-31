from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.call_graph import (
    CallEdge,
    CallGraph,
    CallSiteKind,
    DispatchKind,
    MethodId,
    MethodSymbol,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.reachability import (
    CoverageStatus,
    DeadCodeReport,
    ProjectEvidence,
    ReachabilityAnalysisService,
    ReachabilityConfiguration,
    ReachabilityEvidenceBundle,
    ReachabilityProtection,
    ReachabilitySeed,
    ReachabilityState,
    RootCategory,
    SourceClassification,
)
from moughorai.semantic_evidence import ConfidenceTier
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def node(
    identity: str,
    name: str,
    kind: KnowledgeKind = KnowledgeKind.METHOD,
    *,
    project: str = "demo",
    language: str = "java",
) -> KnowledgeNode:
    return KnowledgeNode(
        identity,
        kind,
        name,
        qualified_name=name,
        project_id=project,
        language=language,
    )


def edge(
    source: str,
    target: str,
    relation: KnowledgeRelation = KnowledgeRelation.CALLS,
) -> KnowledgeEdge:
    return KnowledgeEdge(source, target, relation, (f"fixture:{relation.value}",))


def complete(project: str = "demo", **changes: object) -> ProjectEvidence:
    values = {
        "project": project,
        "languages": ("java",),
        "roots": CoverageStatus.COMPLETE,
        "calls": CoverageStatus.COMPLETE,
        "cfg": CoverageStatus.UNAVAILABLE,
        "frameworks": CoverageStatus.COMPLETE,
        "reflection": CoverageStatus.COMPLETE,
        "service_loader": CoverageStatus.COMPLETE,
        "generated": CoverageStatus.COMPLETE,
        "external_api": CoverageStatus.COMPLETE,
        "closed_world": True,
    }
    values.update(changes)
    return ProjectEvidence(**values)


def analyze(
    graph: KnowledgeGraph,
    *,
    roots: tuple[ReachabilitySeed, ...] = (),
    protections: tuple[ReachabilityProtection, ...] = (),
    projects: tuple[ProjectEvidence, ...] = (),
    metadata: tuple[dict[str, object], ...] = (),
    summary: dict[str, object] | None = None,
    call_graphs: dict[str, CallGraph] | None = None,
    failed_projects: tuple[str, ...] = (),
) -> DeadCodeReport:
    return ReachabilityAnalysisService().analyze(
        graph,
        symbol_metadata=metadata,
        repository_summary=summary,
        call_graphs=call_graphs,
        evidence=ReachabilityEvidenceBundle(roots, protections, projects),
        failed_projects=failed_projects,
        snapshot_lineage="test-snapshot",
    )


def finding(report: DeadCodeReport, subject_id: str):
    return next(item for item in report.findings if item.subject_id == subject_id)


def test_direct_and_transitive_reachability_are_deterministic() -> None:
    graph = KnowledgeGraph(
        (node("root", "demo.Main#main()"), node("one", "demo.One#go()"), node("two", "demo.Two#go()")),
        (edge("root", "one"), edge("one", "two")),
    )
    report = analyze(
        graph,
        roots=(ReachabilitySeed("root", RootCategory.APPLICATION, "demo"),),
        projects=(complete(),),
    )

    assert finding(report, "one").state is ReachabilityState.REACHABLE
    assert finding(report, "two").state is ReachabilityState.REACHABLE
    path = next(item for item in report.paths if item.target_subject_id == "two")
    assert path.relationship_sequence == ("calls", "calls")
    assert not path.truncated


def test_ownership_only_propagates_from_reached_member_to_owner() -> None:
    graph = KnowledgeGraph(
        (
            node("owner", "demo.Owner", KnowledgeKind.TYPE),
            node("root", "demo.Owner#root()"),
            node("unused", "demo.Owner#unused()"),
        ),
        (
            edge("root", "owner", KnowledgeRelation.MEMBER_OF),
            edge("unused", "owner", KnowledgeRelation.MEMBER_OF),
        ),
    )
    report = analyze(
        graph,
        roots=(ReachabilitySeed("root", RootCategory.APPLICATION, "demo"),),
        projects=(complete(),),
        metadata=(
            {"id": "root", "metadata": {"visibility": "private"}},
            {"id": "unused", "metadata": {"visibility": "private"}},
        ),
    )

    assert finding(report, "owner").state is ReachabilityState.REACHABLE
    assert finding(report, "unused").state is ReachabilityState.LIKELY_DEAD


def test_production_and_test_only_reachability_remain_separate() -> None:
    graph = KnowledgeGraph(
        (
            node("prod", "demo.Prod#main()"),
            node("test", "demo.Test#run()"),
            node("shared", "demo.Shared#go()"),
            node("helper", "demo.Helper#go()"),
        ),
        (edge("prod", "shared"), edge("test", "shared"), edge("test", "helper")),
    )
    report = analyze(
        graph,
        roots=(
            ReachabilitySeed("prod", RootCategory.APPLICATION, "demo"),
            ReachabilitySeed("test", RootCategory.TEST, "demo"),
        ),
        projects=(complete(),),
    )

    assert finding(report, "shared").state is ReachabilityState.REACHABLE
    helper = finding(report, "helper")
    assert helper.state is ReachabilityState.REACHABLE_TEST_ONLY
    assert helper.test_reachable and not helper.production_reachable
    assert helper not in report.dead_code_candidates


def test_missing_call_evidence_never_becomes_dead_code() -> None:
    graph = KnowledgeGraph((node("orphan", "demo.Orphan#go()"),), ())
    report = analyze(graph)

    orphan = finding(report, "orphan")
    assert orphan.state is ReachabilityState.UNKNOWN
    assert orphan.confidence_tier is ConfidenceTier.INSUFFICIENT
    assert not report.dead_code_candidates
    assert report.coverage.projects[0].calls is CoverageStatus.UNAVAILABLE


def test_private_closed_scope_can_be_likely_dead_but_public_symbol_is_protected() -> None:
    graph = KnowledgeGraph(
        (node("private", "demo.Api#hidden()"), node("public", "demo.Api#open()")),
        (),
    )
    metadata = (
        {"id": "private", "metadata": {"visibility": "private"}},
        {"id": "public", "metadata": {"visibility": "public"}},
    )
    report = analyze(graph, projects=(complete(),), metadata=metadata)

    assert finding(report, "private").state is ReachabilityState.LIKELY_DEAD
    assert finding(report, "private").confidence_tier is ConfidenceTier.HIGH
    assert finding(report, "public").state is ReachabilityState.UNUSED


def test_structural_external_api_evidence_preserves_uncalled_symbol() -> None:
    graph = KnowledgeGraph((node("api", "demo.Api#extend()"),), ())
    report = analyze(
        graph,
        protections=(ReachabilityProtection(
            "api",
            ReachabilityState.EXTERNALLY_REACHABLE,
            "published-module-descriptor",
            "demo",
            "java",
            "exported-package",
        ),),
        projects=(complete(),),
    )

    api = finding(report, "api")
    assert api.state is ReachabilityState.EXTERNALLY_REACHABLE
    assert api.evidence_ids


def test_framework_managed_requires_structured_framework_and_annotation_evidence() -> None:
    graph = KnowledgeGraph(
        (
            node("managed", "demo.Real", KnowledgeKind.TYPE),
            node("name-only", "demo.FakeController", KnowledgeKind.TYPE),
        ),
        (),
    )
    metadata = (
        {"id": "managed", "metadata": {"annotations": "RestController"}},
        {"id": "name-only", "metadata": {}},
    )
    summary = {
        "projects": [{
            "name": "demo",
            "frameworks": ["Spring"],
            "framework_evidence": [{
                "framework": "Spring",
                "scope": "project-local",
                "reference": "org.springframework:spring-web",
            }],
        }],
    }
    report = analyze(graph, metadata=metadata, summary=summary)

    assert finding(report, "managed").state is ReachabilityState.FRAMEWORK_MANAGED
    assert finding(report, "name-only").state is ReachabilityState.UNKNOWN


def test_resolved_and_unresolved_reflection_are_conservative() -> None:
    graph = KnowledgeGraph(
        (node("resolved", "demo.Reflected", KnowledgeKind.TYPE), node("other", "demo.Other", KnowledgeKind.TYPE)),
        (),
    )
    report = analyze(
        graph,
        protections=(ReachabilityProtection(
            "resolved",
            ReachabilityState.REFLECTION_DISCOVERED,
            "resolved-reflection-analyzer",
            "demo",
            "java",
            "class-literal",
        ),),
        projects=(complete(reflection=CoverageStatus.PARTIAL),),
    )

    assert finding(report, "resolved").state is ReachabilityState.REFLECTION_DISCOVERED
    assert finding(report, "other").state is ReachabilityState.UNKNOWN
    assert "reflection" in " ".join(finding(report, "other").limitations).casefold()


def test_service_loader_registration_is_not_dead_without_internal_calls() -> None:
    graph = KnowledgeGraph((node("provider", "demo.Provider", KnowledgeKind.TYPE),), ())
    report = analyze(
        graph,
        protections=(ReachabilityProtection(
            "provider",
            ReachabilityState.SERVICE_LOADER_DISCOVERED,
            "java-service-loader-metadata",
            "demo",
            "java",
            "module-provides",
            source_refs=("service:demo.Contract", "provider"),
        ),),
        projects=(complete(),),
    )

    assert finding(report, "provider").state is ReachabilityState.SERVICE_LOADER_DISCOVERED


def test_generated_and_annotation_managed_symbols_are_excluded_from_candidates() -> None:
    graph = KnowledgeGraph(
        (node("generated", "demo.GeneratedType", KnowledgeKind.TYPE), node("managed", "demo.Managed", KnowledgeKind.TYPE)),
        (),
    )
    metadata = ({"id": "generated", "metadata": {"annotations": "Generated"}},)
    report = analyze(
        graph,
        metadata=metadata,
        protections=(ReachabilityProtection(
            "managed",
            ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED,
            "annotation-processing-contract",
            "demo",
            "java",
            "generated-binding",
            SourceClassification.PRODUCTION,
        ),),
        projects=(complete(),),
    )

    assert finding(report, "generated").state is ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED
    assert finding(report, "managed").state is ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED
    assert not report.dead_code_candidates


def test_specialized_call_graph_is_authoritative_optional_evidence() -> None:
    graph = KnowledgeGraph(
        (node("caller", "demo.Caller#run()"), node("callee", "demo.Target#go()")),
        (),
    )
    caller = MethodId("demo.Caller", "run")
    callee = MethodId("demo.Target", "go")
    calls = CallGraph(
        (MethodSymbol(caller), MethodSymbol(callee)),
        (CallEdge(caller, callee, DispatchKind.STATIC, CallSiteKind.INVOCATION),),
    )
    report = analyze(
        graph,
        roots=(ReachabilitySeed("caller", RootCategory.APPLICATION, "demo"),),
        projects=(complete(calls=CoverageStatus.PARTIAL),),
        call_graphs={"demo": calls},
    )

    assert finding(report, "callee").state is ReachabilityState.REACHABLE
    assert any(
        record.producer == "moughorai.call_graph.v1"
        for record in report.evidence_index.records
    )


def test_constructor_call_reaches_constructor_and_owning_type() -> None:
    graph = KnowledgeGraph(
        (
            node("caller", "demo.Caller#run()"),
            node("constructor", "demo.Target#<init>()"),
            node("target-type", "demo.Target", KnowledgeKind.TYPE),
        ),
        (edge("constructor", "target-type", KnowledgeRelation.MEMBER_OF),),
    )
    caller = MethodId("demo.Caller", "run")
    constructor = MethodId("demo.Target", "<init>")
    calls = CallGraph(
        (MethodSymbol(caller), MethodSymbol(constructor)),
        (CallEdge(caller, constructor, DispatchKind.SPECIAL, CallSiteKind.CONSTRUCTOR),),
    )
    report = analyze(
        graph,
        roots=(ReachabilitySeed("caller", RootCategory.APPLICATION, "demo"),),
        projects=(complete(calls=CoverageStatus.PARTIAL),),
        call_graphs={"demo": calls},
    )

    assert finding(report, "constructor").state is ReachabilityState.REACHABLE
    assert finding(report, "target-type").state is ReachabilityState.REACHABLE
    constructor_path = next(
        item for item in report.paths if item.target_subject_id == "constructor"
    )
    assert constructor_path.relationship_sequence == ("constructor",)


def test_authoritative_cfg_unreachable_result_is_bounded_and_traceable() -> None:
    graph = KnowledgeGraph((node("block", "demo.Flow#block:7"),), ())
    report = analyze(
        graph,
        protections=(ReachabilityProtection(
            "block",
            ReachabilityState.UNREACHABLE,
            "java-semantics-reachability.v1",
            "demo",
            "java",
            "cfg-unreachable-block",
            source_refs=("cfg:demo.Flow#run():block:7",),
        ),),
        projects=(complete(cfg=CoverageStatus.COMPLETE),),
    )

    block = finding(report, "block")
    assert block.state is ReachabilityState.UNREACHABLE
    assert block.confidence_tier is ConfidenceTier.HIGH
    assert block in report.dead_code_candidates


def test_unsupported_language_scope_remains_explicitly_unknown() -> None:
    graph = KnowledgeGraph((node("ts", "demo.run", project="web", language="typescript"),), ())
    report = analyze(
        graph,
        projects=(ProjectEvidence(
            "web",
            ("typescript",),
            calls=CoverageStatus.UNAVAILABLE,
            limitations=("TypeScript call producer is unavailable.",),
        ),),
    )

    assert finding(report, "ts").state is ReachabilityState.UNKNOWN
    assert report.coverage.projects[0].languages == ("typescript",)
    assert "TypeScript" in " ".join(report.coverage.limitations)


def test_cache_identity_changes_with_reachability_inputs() -> None:
    graph = KnowledgeGraph((node("candidate", "demo.Candidate#go()"),), ())
    service = ReachabilityAnalysisService()
    unknown = service.analyze(graph, snapshot_lineage="cache")
    protected = service.analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            protections=(ReachabilityProtection(
                "candidate",
                ReachabilityState.SERVICE_LOADER_DISCOVERED,
                "service-registration",
            ),),
        ),
        snapshot_lineage="cache",
    )

    assert unknown.input_fingerprint != protected.input_fingerprint
    assert finding(unknown, "candidate").state is ReachabilityState.UNKNOWN
    assert finding(protected, "candidate").state is ReachabilityState.SERVICE_LOADER_DISCOVERED


def test_serialization_round_trip_and_reordered_inputs_are_exact() -> None:
    nodes = (node("root", "demo.Root#run()"), node("target", "demo.Target#go()"))
    edges = (edge("root", "target"),)
    bundle = ReachabilityEvidenceBundle(
        (ReachabilitySeed("root", RootCategory.APPLICATION, "demo"),),
        (),
        (complete(),),
    )
    service = ReachabilityAnalysisService()
    first = service.analyze(
        KnowledgeGraph(nodes, edges), evidence=bundle, snapshot_lineage="stable",
    )
    second = service.analyze(
        KnowledgeGraph(reversed(nodes), reversed(edges)), evidence=bundle,
        snapshot_lineage="stable",
    )

    assert first.to_dict() == second.to_dict()
    assert DeadCodeReport.from_dict(first.to_dict()).to_dict() == first.to_dict()
    grouped = first.to_dict(grouped=True)
    assert DeadCodeReport.from_dict(grouped).to_dict(grouped=True) == grouped
    assert [record.evidence_id for record in first.evidence_index.records] == [
        record.evidence_id for record in second.evidence_index.records
    ]

    unsupported = first.to_dict()
    unsupported["schema_version"] = 999
    try:
        DeadCodeReport.from_dict(unsupported)
    except ValueError as exc:
        assert "unsupported reachability report schema" in str(exc)
    else:
        raise AssertionError("unknown reachability schema must be rejected")


def test_traversal_bound_reports_deterministic_partial_coverage() -> None:
    graph = KnowledgeGraph(
        tuple(node(str(index), f"demo.C{index}#go()") for index in range(5)),
        tuple(edge(str(index), str(index + 1)) for index in range(4)),
    )
    report = ReachabilityAnalysisService().analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            roots=(ReachabilitySeed("0", RootCategory.APPLICATION, "demo"),),
            projects=(complete(),),
        ),
        snapshot_lineage="bounded",
        configuration=ReachabilityConfiguration(max_traversal_nodes=3),
    )

    assert report.coverage.traversal_truncated
    assert report.coverage.status is CoverageStatus.PARTIAL
    assert finding(report, "2").state is ReachabilityState.REACHABLE
    assert finding(report, "3").state is ReachabilityState.UNUSED
    assert not report.dead_code_candidates


def test_partial_project_failure_does_not_create_an_empty_success() -> None:
    graph = KnowledgeGraph(
        (
            node("good", "good.Main#run()", project="good"),
            node("failed", "failed.Main#run()", project="failed"),
        ),
        (),
    )
    report = analyze(
        graph,
        roots=(ReachabilitySeed("good", RootCategory.APPLICATION, "good"),),
        projects=(complete("good"),),
        failed_projects=("failed",),
    )

    assert finding(report, "good").state is ReachabilityState.REACHABLE
    assert not any(item.subject_id == "failed" for item in report.findings)
    failed = next(item for item in report.coverage.projects if item.project == "failed")
    assert failed.status is CoverageStatus.UNAVAILABLE
    assert failed.analyzed_subjects == 0


def test_report_and_compact_publication_remain_source_free() -> None:
    graph = KnowledgeGraph((node("root", "demo.Main#main()"),), ())
    report = analyze(
        graph,
        roots=(ReachabilitySeed("root", RootCategory.APPLICATION, "demo"),),
        projects=(complete(),),
    )
    serialized = json.dumps(report.to_dict(), sort_keys=True)

    for source_fragment in ("public class", "return this", "if (", "new SomeType("):
        assert source_fragment not in serialized


def test_normal_pipeline_publishes_additive_reachability_context(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "Main.java").write_text(
        "package demo; public class Main { "
        "public static void main(String[] args) {} "
        "private void hidden() {} }",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])

    assert result.exit_code == 0, result.output
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    payload = snapshot.semantic_context["reachability"]
    assert payload["schema_version"] == 1
    assert payload["producer_version"] == "atlas-pr131/1"
    assert any(item["category"] == "application" for item in payload["roots"])
    restored = DeadCodeReport.from_dict(payload)
    assert any(item.state is ReachabilityState.REACHABLE for item in restored.findings)
    assert any(item.state is ReachabilityState.UNKNOWN for item in restored.findings)
    assert payload["serialization"] == "grouped-findings-v1"
    main_symbol = next(
        item for item in snapshot.semantic_context["symbols"]
        if item["qualified_name"].endswith("#main(String[])")
    )
    assert main_symbol["metadata"]["entry_point"] == "java-main"
    assert main_symbol["metadata"]["visibility"] == "public"
    assert "public class" not in json.dumps(payload, sort_keys=True)


def test_old_context_without_reachability_remains_valid() -> None:
    legacy = {"schema_version": 1, "semantic_graph": {"nodes": [], "edges": []}}
    assert "reachability" not in legacy
    assert KnowledgeGraph.from_dict(legacy["semantic_graph"]).to_dict() == {
        "schema_version": 1,
        "nodes": [],
        "edges": [],
    }
