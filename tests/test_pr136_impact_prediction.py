from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.dependency_graph import (
    DependencyEdge,
    DependencyGraph,
    DependencyKind,
)
from moughorai.global_symbols import (
    GlobalSymbol,
    GlobalSymbolDatabase,
    GlobalSymbolKind,
)
from moughorai.impact_analysis.models import (
    EXTERNAL_CONSUMER_LIMITATION,
    BreakingChangeState,
    ImpactAnalysisReport,
    ImpactCapabilityState,
    ImpactCategory,
    ImpactChangeKind,
    ImpactPath,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
    ImpactedSymbol,
)
from moughorai.impact_analysis.prediction import ImpactPredictionService
from moughorai.impact_analysis.service import ImpactAnalysisService
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.measurement import MeasurementConfig, MeasurementSession
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
from moughorai.subject_resolution import (
    ResolutionStatus,
    SubjectQuery,
)


CORE_PROJECT = "project:core"
CORE_MODULE = "module:core"
CORE_PACKAGE = "package:com.acme"
ROOT_TYPE = "type:root"
ROOT_METHOD = "method:root-run"
IMPORTER = "type:importer"
TRANSITIVE_IMPORTER = "type:transitive-importer"
SUBTYPE = "type:subtype"
CALLER = "method:caller"
OVERRIDER = "method:overrider"
SIBLING = "type:sibling"
UNKNOWN_DEPENDENCY = "dependency:maven:org.example:library"
DEPENDENT_PROJECT = "project:dependent"
TEST_METHOD = "method:test-root"
CALL_EVIDENCE = ("moughorai.call_graph.v1:calls",)


def _node(
    identifier: str,
    kind: KnowledgeKind,
    name: str,
    qualified_name: str,
    *,
    project: str | None = "core",
    language: str = "java",
    **metadata: str,
) -> KnowledgeNode:
    return KnowledgeNode(
        identifier,
        kind,
        name,
        metadata=tuple(sorted(metadata.items())),
        qualified_name=qualified_name,
        project_id=project,
        language=language,
    )


def _nodes() -> tuple[KnowledgeNode, ...]:
    return (
        _node(CORE_PROJECT, KnowledgeKind.PROJECT, "core", "core"),
        _node(CORE_MODULE, KnowledgeKind.MODULE, "core", "core"),
        _node(
            CORE_PACKAGE,
            KnowledgeKind.PACKAGE,
            "com.acme",
            "com.acme",
        ),
        _node(
            ROOT_TYPE,
            KnowledgeKind.TYPE,
            "Root",
            "com.acme.Root",
            visibility="public",
            scope_id="core",
        ),
        _node(
            ROOT_METHOD,
            KnowledgeKind.METHOD,
            "run",
            "com.acme.Root#run()",
            visibility="public",
            scope_id="core",
        ),
        _node(
            IMPORTER,
            KnowledgeKind.TYPE,
            "Importer",
            "com.acme.Importer",
            visibility="private",
        ),
        _node(
            TRANSITIVE_IMPORTER,
            KnowledgeKind.TYPE,
            "TransitiveImporter",
            "com.acme.TransitiveImporter",
            visibility="private",
        ),
        _node(
            SUBTYPE,
            KnowledgeKind.TYPE,
            "Subtype",
            "com.acme.Subtype",
            visibility="public",
        ),
        _node(
            CALLER,
            KnowledgeKind.METHOD,
            "callRoot",
            "com.acme.Caller#callRoot()",
            visibility="private",
        ),
        _node(
            OVERRIDER,
            KnowledgeKind.METHOD,
            "run",
            "com.acme.Subtype#run()",
            visibility="public",
        ),
        _node(
            SIBLING,
            KnowledgeKind.TYPE,
            "UnrelatedSibling",
            "com.acme.UnrelatedSibling",
            visibility="public",
        ),
        _node(
            UNKNOWN_DEPENDENCY,
            KnowledgeKind.DEPENDENCY,
            "org.example:library",
            "org.example:library",
            project=None,
            language="unknown",
            ecosystem="maven",
            version="unversioned",
            scope="unspecified",
            optional="false",
        ),
        _node(
            DEPENDENT_PROJECT,
            KnowledgeKind.PROJECT,
            "dependent",
            "dependent",
            project="dependent",
        ),
    )


def _edges() -> tuple[KnowledgeEdge, ...]:
    return (
        KnowledgeEdge(
            CORE_PROJECT,
            CORE_MODULE,
            KnowledgeRelation.OWNS,
            ("repository_summary.projects",),
        ),
        KnowledgeEdge(
            CORE_MODULE,
            CORE_PACKAGE,
            KnowledgeRelation.OWNS,
            ("global_symbol.owner_id",),
        ),
        KnowledgeEdge(
            CORE_PACKAGE,
            ROOT_TYPE,
            KnowledgeRelation.OWNS,
            ("global_symbol.owner_id",),
        ),
        KnowledgeEdge(
            CORE_PACKAGE,
            ROOT_METHOD,
            KnowledgeRelation.OWNS,
            ("global_symbol.owner_id",),
        ),
        KnowledgeEdge(
            CORE_PACKAGE,
            SIBLING,
            KnowledgeRelation.OWNS,
            ("global_symbol.owner_id",),
        ),
        KnowledgeEdge(
            IMPORTER,
            ROOT_TYPE,
            KnowledgeRelation.IMPORTS,
            ("imports",),
        ),
        KnowledgeEdge(
            TRANSITIVE_IMPORTER,
            IMPORTER,
            KnowledgeRelation.IMPORTS,
            ("imports",),
        ),
        KnowledgeEdge(
            SUBTYPE,
            ROOT_TYPE,
            KnowledgeRelation.INHERITS,
            ("extends",),
        ),
        KnowledgeEdge(
            CALLER,
            ROOT_METHOD,
            KnowledgeRelation.CALLS,
            CALL_EVIDENCE,
        ),
        KnowledgeEdge(
            OVERRIDER,
            ROOT_METHOD,
            KnowledgeRelation.OVERRIDES,
            ("global_symbol.metadata:overrides:com.acme.Root#run()",),
        ),
        KnowledgeEdge(
            UNKNOWN_DEPENDENCY,
            ROOT_TYPE,
            KnowledgeRelation.DEPENDS_ON,
            (
                "declared_dependency:maven:org.example:library:unversioned:unspecified",
            ),
        ),
        KnowledgeEdge(
            DEPENDENT_PROJECT,
            CORE_PROJECT,
            KnowledgeRelation.DEPENDS_ON,
            ("workspace.projects:dependent:dependencies:core",),
        ),
    )


def _graph(*, reverse: bool = False) -> KnowledgeGraph:
    nodes = tuple(reversed(_nodes())) if reverse else _nodes()
    edges = tuple(reversed(_edges())) if reverse else _edges()
    return KnowledgeGraph(nodes, edges)


def _snapshot(
    graph: KnowledgeGraph | None = None,
    **context_additions: object,
) -> AtlasSemanticSnapshot:
    context: dict[str, object] = {"schema_version": 1}
    if graph is not None:
        context["semantic_graph"] = graph.to_dict()
    context.update(context_additions)
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr136-fixture",
        analyzer_version="test-analyzer/1",
    )


def _predict(
    subject: str,
    *,
    graph: KnowledgeGraph | None = None,
    snapshot: AtlasSemanticSnapshot | None = None,
    change: ImpactChangeKind = ImpactChangeKind.SIGNATURE,
    depth: int = 4,
    include_tests: bool = False,
    module: str | None = None,
    measurement: MeasurementSession | None = None,
) -> ImpactPredictionResponse:
    selected_snapshot = snapshot or _snapshot(graph or _graph())
    service = ImpactPredictionService.from_snapshot(
        selected_snapshot,
        measurement=measurement,
    )
    return service.predict(ImpactPredictionRequest(
        SubjectQuery(subject),
        change_kind=change,
        module=module,
        max_depth=depth,
        limit=100,
        include_tests=include_tests,
    ))


def _finding(
    response: ImpactPredictionResponse,
    subject_id: str,
    category: ImpactCategory,
):
    return next(
        item
        for item in response.findings
        if item.canonical_subject_id == subject_id and item.category is category
    )


def _capability(response: ImpactPredictionResponse, name: str):
    return next(item for item in response.capabilities if item.name == name)


def _reachability_with_test_root(
    graph: KnowledgeGraph,
    *,
    calls: CoverageStatus = CoverageStatus.COMPLETE,
):
    return ReachabilityAnalysisService().analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            roots=(ReachabilitySeed(
                TEST_METHOD,
                RootCategory.TEST,
                "core",
                source_refs=("test-root",),
            ),),
            projects=(ProjectEvidence(
                "core",
                ("java",),
                roots=CoverageStatus.COMPLETE,
                calls=calls,
            ),),
        ),
        snapshot_lineage="pr131-fixture",
    )


@pytest.mark.parametrize(
    ("subject", "consumer", "category", "relation"),
    (
        (ROOT_TYPE, IMPORTER, ImpactCategory.IMPORTER, KnowledgeRelation.IMPORTS),
        (ROOT_TYPE, SUBTYPE, ImpactCategory.SUBTYPE, KnowledgeRelation.INHERITS),
        (
            ROOT_TYPE,
            UNKNOWN_DEPENDENCY,
            ImpactCategory.DEPENDENCY,
            KnowledgeRelation.DEPENDS_ON,
        ),
        (ROOT_METHOD, CALLER, ImpactCategory.CALLER, KnowledgeRelation.CALLS),
        (
            ROOT_METHOD,
            OVERRIDER,
            ImpactCategory.OVERRIDING_MEMBER,
            KnowledgeRelation.OVERRIDES,
        ),
    ),
)
def test_authoritative_relations_produce_traceable_direct_impacts(
    subject: str,
    consumer: str,
    category: ImpactCategory,
    relation: KnowledgeRelation,
) -> None:
    response = _predict(subject)
    finding = _finding(response, consumer, category)

    assert finding.direct is True
    assert finding.path.length == 1
    assert finding.path.relationships == (relation,)
    assert finding.path.steps[0].reverse is True
    assert finding.evidence_ids
    assert all(
        response.evidence_index.get(evidence_id) is not None
        for evidence_id in finding.evidence_ids
    )


def test_transitive_impact_preserves_ordered_shortest_evidence_path() -> None:
    response = _predict(ROOT_TYPE)
    finding = _finding(
        response,
        TRANSITIVE_IMPORTER,
        ImpactCategory.IMPORTER,
    )

    assert finding.direct is False
    assert finding.path.length == 2
    assert finding.path.relationships == (
        KnowledgeRelation.IMPORTS,
        KnowledgeRelation.IMPORTS,
    )
    assert tuple(step.target_subject_id for step in finding.path.steps) == (
        IMPORTER,
        TRANSITIVE_IMPORTER,
    )


def test_change_kind_and_reverse_direction_bound_propagation() -> None:
    implementation = _predict(ROOT_TYPE, change=ImpactChangeKind.IMPLEMENTATION)
    signature = _predict(ROOT_TYPE, change=ImpactChangeKind.SIGNATURE)
    reverse_only = _predict(IMPORTER, change=ImpactChangeKind.SIGNATURE)

    implementation_ids = {item.canonical_subject_id for item in implementation.findings}
    signature_ids = {item.canonical_subject_id for item in signature.findings}
    reverse_only_ids = {item.canonical_subject_id for item in reverse_only.findings}
    assert IMPORTER in implementation_ids
    assert SUBTYPE not in implementation_ids
    assert SUBTYPE in signature_ids
    assert ROOT_TYPE not in reverse_only_ids


def test_ownership_aggregates_upward_without_propagating_to_siblings() -> None:
    response = _predict(ROOT_TYPE)

    assert _finding(
        response, CORE_PACKAGE, ImpactCategory.OWNING_PACKAGE
    ).path.relationships[-1] is KnowledgeRelation.OWNS
    assert _finding(
        response, CORE_MODULE, ImpactCategory.OWNING_MODULE
    ).path.relationships[-1] is KnowledgeRelation.OWNS
    assert _finding(
        response, CORE_PROJECT, ImpactCategory.OWNING_PROJECT
    ).path.relationships[-1] is KnowledgeRelation.OWNS
    assert SIBLING not in {
        item.canonical_subject_id for item in response.findings
    }


def test_project_dependency_is_reported_from_canonical_reverse_dependency() -> None:
    response = _predict(CORE_PROJECT, change=ImpactChangeKind.DEPENDENCY)
    finding = _finding(
        response,
        DEPENDENT_PROJECT,
        ImpactCategory.PROJECT_DEPENDENT,
    )

    assert finding.direct
    assert finding.path.relationships == (KnowledgeRelation.DEPENDS_ON,)


def test_zero_local_public_api_uses_exact_external_consumer_limitation() -> None:
    graph = KnowledgeGraph((
        _node(
            "type:isolated",
            KnowledgeKind.TYPE,
            "Isolated",
            "com.acme.Isolated",
            visibility="public",
        ),
    ))
    response = _predict(
        "type:isolated",
        graph=graph,
        change=ImpactChangeKind.SIGNATURE,
    )

    assert response.findings == ()
    assert response.breaking_change.state is BreakingChangeState.POTENTIALLY_BREAKING
    assert EXTERNAL_CONSUMER_LIMITATION in response.breaking_change.limitations
    assert response.breaking_change.external_consumers_possible is True


def test_unknown_dependency_version_and_scope_are_not_fabricated() -> None:
    finding = _finding(
        _predict(ROOT_TYPE),
        UNKNOWN_DEPENDENCY,
        ImpactCategory.DEPENDENCY,
    )
    attributes = dict(finding.attributes)

    assert attributes["ecosystem"] == "maven"
    assert attributes["optional"] == "false"
    assert "version" not in attributes
    assert "scope" not in attributes
    assert any("version is unknown" in item for item in finding.limitations)
    assert any("scope is unknown" in item for item in finding.limitations)


def test_exact_round_trip_and_reordered_graph_inputs_are_deterministic() -> None:
    first = _predict(ROOT_TYPE, graph=_graph())
    second = _predict(ROOT_TYPE, graph=_graph(reverse=True))

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert ImpactPredictionResponse.from_dict(first.to_dict()).to_dict() == first.to_dict()


def test_ambiguous_and_old_snapshots_degrade_without_traversal() -> None:
    duplicates = KnowledgeGraph((
        _node(
            "type:duplicate-a",
            KnowledgeKind.TYPE,
            "Duplicate",
            "com.acme.Duplicate",
            project="a",
        ),
        _node(
            "type:duplicate-b",
            KnowledgeKind.TYPE,
            "Duplicate",
            "com.acme.Duplicate",
            project="b",
        ),
    ))
    ambiguous = _predict("com.acme.Duplicate", graph=duplicates)
    unavailable = _predict("com.acme.Root", snapshot=_snapshot())

    assert ambiguous.resolution.status is ResolutionStatus.AMBIGUOUS
    assert ambiguous.findings == ()
    assert ambiguous.visited_node_count == 0
    assert unavailable.resolution.status is ResolutionStatus.UNAVAILABLE
    assert unavailable.findings == ()
    assert "dependencies" in unavailable.unavailable_analyses


def _risk_report(graph: KnowledgeGraph) -> dict[str, object]:
    evidence = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        IMPORTER,
        "test-risk-producer/1",
        "risk-fixture",
        source_refs=("semantic-fact:complexity",),
        detail={"metric": "complexity", "unit": "cyclomatic_complexity"},
        reliability=0.9,
        specificity=0.95,
    )
    metric = RiskMetricInput(
        IMPORTER,
        RiskMetricKind.COMPLEXITY,
        20.0,
        "cyclomatic_complexity",
        "test-risk-producer/1",
        (evidence,),
    )
    return RiskAnalysisService().analyze(
        graph,
        symbol_metadata=({
            "id": IMPORTER,
            "project_id": "core",
            "source": "src/main/java/com/acme/Importer.java",
            "metadata": {},
        },),
        metric_inputs=(metric,),
    ).to_dict()


def test_risk_compatibility_changes_context_not_impact_membership() -> None:
    graph = _graph()
    compatible_report = _risk_report(graph)
    incompatible_report = dict(compatible_report)
    incompatible_report["graph_digest"] = "0" * 64
    mismatched_lineage_report = dict(compatible_report)
    mismatched_lineage_report["lineage"] = "foreign-risk-lineage"
    compatible = _predict(
        ROOT_TYPE,
        snapshot=_snapshot(graph, risk_analysis=compatible_report),
    )
    incompatible = _predict(
        ROOT_TYPE,
        snapshot=_snapshot(graph, risk_analysis=incompatible_report),
    )
    mismatched_lineage = _predict(
        ROOT_TYPE,
        snapshot=_snapshot(graph, risk_analysis=mismatched_lineage_report),
    )

    membership = lambda response: tuple(
        (
            item.canonical_subject_id,
            item.category.value,
            tuple(relation.value for relation in item.path.relationships),
        )
        for item in response.findings
    )
    assert membership(compatible) == membership(incompatible)
    assert _capability(compatible, "risk").state is ImpactCapabilityState.AVAILABLE
    assert _capability(incompatible, "risk").state is ImpactCapabilityState.INCOMPATIBLE
    assert _capability(
        mismatched_lineage, "risk"
    ).state is ImpactCapabilityState.INCOMPATIBLE
    assert _finding(
        compatible, IMPORTER, ImpactCategory.IMPORTER
    ).risk_context is not None
    assert all(item.risk_context is None for item in incompatible.findings)
    assert all(item.risk_context is None for item in mismatched_lineage.findings)


def test_compatible_pr131_path_can_add_a_conservative_test_finding() -> None:
    graph = KnowledgeGraph(
        (
            _node(
                ROOT_METHOD,
                KnowledgeKind.METHOD,
                "run",
                "com.acme.Root#run()",
                visibility="public",
            ),
            _node(
                TEST_METHOD,
                KnowledgeKind.METHOD,
                "testRun",
                "com.acme.RootTest#testRun()",
            ),
        ),
        (
            KnowledgeEdge(
                TEST_METHOD,
                ROOT_METHOD,
                KnowledgeRelation.CALLS,
                ("fixture:calls",),
            ),
        ),
    )
    reachability = ReachabilityAnalysisService().analyze(
        graph,
        evidence=ReachabilityEvidenceBundle(
            roots=(ReachabilitySeed(
                TEST_METHOD,
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
    response = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=reachability.to_dict()),
        include_tests=True,
    )

    finding = _finding(response, TEST_METHOD, ImpactCategory.TEST)
    assert finding.strength.value == "probable_incomplete"
    assert finding.path.relationships[-1] is KnowledgeRelation.CALLS
    assert _capability(response, "tests").state is ImpactCapabilityState.PARTIAL

    unrelated = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        ROOT_METHOD,
        "moughorai.call_graph.v1",
        reachability.snapshot_lineage,
        source_refs=("unrelated:source", ROOT_METHOD),
        detail={"relation": "calls"},
        reliability=0.9,
        specificity=1.0,
    )
    tampered = reachability.to_dict()
    test_path = next(
        item
        for item in tampered["paths"]
        if item["root_subject_id"] == TEST_METHOD
        and item["target_subject_id"] == ROOT_METHOD
    )
    root_evidence_id = reachability.roots[0].evidence_ids[0]
    test_path["evidence_ids"] = [root_evidence_id, unrelated.evidence_id]
    tampered["evidence_index"]["records"].append(unrelated.to_dict())
    rejected = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=tampered),
        include_tests=True,
    )

    assert rejected.affected_test_ids == ()


def test_scoped_resolution_does_not_select_from_truncated_ambiguity() -> None:
    nodes = tuple(
        _node(
            f"type:{index:02d}",
            KnowledgeKind.TYPE,
            "Thing",
            "demo.Thing",
            project=f"project-{index:02d}",
            scope_id=("wanted" if index in {0, 13} else f"other-{index:02d}"),
        )
        for index in range(14)
    )

    response = _predict(
        "demo.Thing",
        graph=KnowledgeGraph(nodes, ()),
        module="wanted",
    )

    assert response.resolution.status is ResolutionStatus.AMBIGUOUS
    assert response.resolution.subject is None
    assert response.resolution.omitted_candidate_count > 0
    assert response.findings == ()


def test_pr131_tampered_evidence_id_is_rejected() -> None:
    graph = KnowledgeGraph(
        (
            _node(
                ROOT_METHOD,
                KnowledgeKind.METHOD,
                "run",
                "com.acme.Root#run()",
            ),
            _node(
                TEST_METHOD,
                KnowledgeKind.METHOD,
                "testRun",
                "com.acme.RootTest#testRun()",
            ),
        ),
        (KnowledgeEdge(
            TEST_METHOD,
            ROOT_METHOD,
            KnowledgeRelation.CALLS,
            ("fixture:calls",),
        ),),
    )
    report = _reachability_with_test_root(graph)
    raw = report.to_dict()
    path = next(
        item
        for item in raw["paths"]
        if item["root_subject_id"] == TEST_METHOD
        and item["target_subject_id"] == ROOT_METHOD
    )
    call_id = next(
        evidence_id
        for evidence_id in path["evidence_ids"]
        if dict(report.evidence_index.get(evidence_id).detail).get("relation")
        == "calls"
    )
    tampered_id = f"evidence:{'1' * 64}"
    path["evidence_ids"] = [
        tampered_id if evidence_id == call_id else evidence_id
        for evidence_id in path["evidence_ids"]
    ]
    record = next(
        item
        for item in raw["evidence_index"]["records"]
        if item["evidence_id"] == call_id
    )
    record["evidence_id"] = tampered_id

    response = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=raw),
        include_tests=True,
    )

    assert response.affected_test_ids == ()
    assert (
        _capability(response, "tests").state
        is ImpactCapabilityState.INCOMPATIBLE
    )


def test_pr131_member_owner_path_accepts_member_of_edge_evidence() -> None:
    test_owner = "type:test-owner"
    graph = KnowledgeGraph(
        (
            _node(
                ROOT_METHOD,
                KnowledgeKind.METHOD,
                "run",
                "com.acme.Root#run()",
            ),
            _node(
                test_owner,
                KnowledgeKind.TYPE,
                "RootTest",
                "com.acme.RootTest",
            ),
            _node(
                TEST_METHOD,
                KnowledgeKind.METHOD,
                "testRun",
                "com.acme.RootTest#testRun()",
            ),
        ),
        (
            KnowledgeEdge(
                TEST_METHOD,
                test_owner,
                KnowledgeRelation.MEMBER_OF,
                ("global_symbol.owner_id",),
            ),
            KnowledgeEdge(
                test_owner,
                ROOT_METHOD,
                KnowledgeRelation.CALLS,
                ("fixture:calls",),
            ),
        ),
    )
    report = _reachability_with_test_root(graph)
    path = next(
        item
        for item in report.paths
        if item.root_subject_id == TEST_METHOD
        and item.target_subject_id == ROOT_METHOD
    )

    assert path.relationship_sequence == ("member_owner", "calls")
    assert any(
        dict(report.evidence_index.get(evidence_id).detail).get("relation")
        == "member_of"
        for evidence_id in path.evidence_ids
    )

    response = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=report.to_dict()),
        include_tests=True,
    )

    finding = _finding(response, TEST_METHOD, ImpactCategory.TEST)
    assert finding.path.relationships == (
        KnowledgeRelation.CALLS,
        KnowledgeRelation.MEMBER_OF,
    )


def test_more_than_twenty_thousand_pr131_paths_reports_truncation() -> None:
    graph = KnowledgeGraph(
        (
            _node(
                ROOT_METHOD,
                KnowledgeKind.METHOD,
                "run",
                "com.acme.Root#run()",
            ),
            _node(
                TEST_METHOD,
                KnowledgeKind.METHOD,
                "testRun",
                "com.acme.RootTest#testRun()",
            ),
        ),
        (KnowledgeEdge(
            TEST_METHOD,
            ROOT_METHOD,
            KnowledgeRelation.CALLS,
            ("fixture:calls",),
        ),),
    )
    raw = _reachability_with_test_root(graph).to_dict()
    path = next(
        item
        for item in raw["paths"]
        if item["root_subject_id"] == TEST_METHOD
        and item["target_subject_id"] == ROOT_METHOD
    )
    raw["paths"] = [dict(path) for _ in range(20_001)]

    response = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=raw),
        include_tests=True,
    )

    assert response.truncated is True
    assert any(
        "path" in limitation.casefold()
        and (
            "bounded" in limitation.casefold()
            or "limit" in limitation.casefold()
        )
        for limitation in response.limitations
    )


def test_pr131_without_usable_call_paths_reports_tests_unavailable() -> None:
    graph = KnowledgeGraph(
        (
            _node(
                ROOT_METHOD,
                KnowledgeKind.METHOD,
                "run",
                "com.acme.Root#run()",
            ),
            _node(
                TEST_METHOD,
                KnowledgeKind.METHOD,
                "testRun",
                "com.acme.RootTest#testRun()",
            ),
        ),
        (),
    )
    report = _reachability_with_test_root(
        graph,
        calls=CoverageStatus.UNAVAILABLE,
    )

    response = _predict(
        ROOT_METHOD,
        snapshot=_snapshot(graph, reachability=report.to_dict()),
        include_tests=True,
    )

    capability = _capability(response, "tests")
    assert response.affected_test_ids == ()
    assert capability.state is ImpactCapabilityState.UNAVAILABLE
    assert any(
        "call" in limitation.casefold()
        and "no usable" in limitation.casefold()
        for limitation in capability.limitations
    )


def test_measurement_is_semantically_inert_but_records_pr136_phases() -> None:
    graph = _graph()
    snapshot = _snapshot(graph)
    baseline = _predict(ROOT_TYPE, snapshot=snapshot)
    measurement = MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_process_memory=False,
        capture_python_memory=False,
        capture_filesystem=False,
    ))
    measured = _predict(
        ROOT_TYPE,
        snapshot=snapshot,
        measurement=measurement,
    )

    assert measured.to_dict() == baseline.to_dict()
    assert {
        "impact_prediction.resolver_index",
        "impact_prediction.index",
        "impact_prediction.query",
        "impact_prediction.resolve",
        "impact_prediction.neighbors",
        "impact_prediction.traverse",
        "impact_prediction.cycle_check",
        "impact_prediction.direct",
        "impact_prediction.sort",
        "impact_prediction.score",
        "impact_prediction.evidence",
        "impact_prediction.serialize",
    }.issubset({
        sample.phase_id for sample in measurement.report().samples
    })


def test_pr26_contracts_and_service_behavior_remain_compatible() -> None:
    root = GlobalSymbol.create(
        GlobalSymbolKind.METHOD,
        "root",
        "root",
        source=Path("root.java"),
    )
    consumer = GlobalSymbol.create(
        GlobalSymbolKind.METHOD,
        "consumer",
        "consumer",
        source=Path("consumer.java"),
    )
    report = ImpactAnalysisService(
        GlobalSymbolDatabase((root, consumer)),
        DependencyGraph((DependencyEdge(
            consumer.id,
            root.id,
            DependencyKind.CALLS,
        ),)),
    ).analyze((root.id,))

    assert tuple(ImpactPath.__dataclass_fields__) == ("symbols", "kinds")
    assert tuple(ImpactedSymbol.__dataclass_fields__) == (
        "symbol",
        "distance",
        "path",
    )
    assert tuple(ImpactAnalysisReport.__dataclass_fields__) == (
        "roots",
        "impacted",
        "files",
        "unresolved_ids",
    )
    assert [item.symbol for item in report.impacted] == [consumer]
