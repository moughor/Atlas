from __future__ import annotations

from collections.abc import Mapping

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.measurement import MeasurementConfig, MeasurementSession
from moughorai.reachability import ReachabilityAnalysisService
from moughorai.risk_analysis import RiskAnalysisService
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_search import (
    QueryInterpretation,
    ScoreComponent,
    SearchCapabilityState,
    SemanticSearchQuery,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchService,
    StructuredSearchHit,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


API = "symbol:alpha:api-controller"
ADVERSARIAL = "symbol:alpha:rest-endpoint-cache-injected"
CACHE = "symbol:alpha:cache-service"
BASE = "symbol:alpha:base-port"
CHILD = "symbol:alpha:http-adapter"
DUPLICATE_ALPHA = "symbol:alpha:duplicate"
DUPLICATE_BETA = "symbol:beta:duplicate"
PROJECT_ALPHA = "project:alpha"
PROJECT_BETA = "project:beta"
MODULE_ALPHA = "module:alpha"
SPRING_WEB = "dependency:maven:org.springframework:spring-web:6.0"
CAFFEINE = "dependency:maven:com.github.ben-manes.caffeine:caffeine:3.1"


def _nodes() -> tuple[KnowledgeNode, ...]:
    return (
        KnowledgeNode(PROJECT_ALPHA, KnowledgeKind.PROJECT, "alpha", qualified_name="alpha", project_id="alpha"),
        KnowledgeNode(PROJECT_BETA, KnowledgeKind.PROJECT, "beta", qualified_name="beta", project_id="beta"),
        KnowledgeNode(MODULE_ALPHA, KnowledgeKind.MODULE, "alpha", qualified_name="alpha", project_id="alpha"),
        KnowledgeNode(
            API,
            KnowledgeKind.TYPE,
            "ApiController",
            qualified_name="com.acme.ApiController",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            ADVERSARIAL,
            KnowledgeKind.TYPE,
            "RestEndpointCacheInjected",
            qualified_name="com.acme.RestEndpointCacheInjected",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            CACHE,
            KnowledgeKind.TYPE,
            "CacheService",
            qualified_name="com.acme.CacheService",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            BASE,
            KnowledgeKind.TYPE,
            "BasePort",
            qualified_name="com.acme.BasePort",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            CHILD,
            KnowledgeKind.TYPE,
            "HttpAdapter",
            qualified_name="com.acme.HttpAdapter",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            DUPLICATE_ALPHA,
            KnowledgeKind.TYPE,
            "Duplicate",
            qualified_name="com.shared.Duplicate",
            project_id="alpha",
            language="java",
        ),
        KnowledgeNode(
            DUPLICATE_BETA,
            KnowledgeKind.TYPE,
            "Duplicate",
            qualified_name="com.shared.Duplicate",
            project_id="beta",
            language="java",
        ),
        KnowledgeNode(
            SPRING_WEB,
            KnowledgeKind.DEPENDENCY,
            "spring-web",
            qualified_name="org.springframework:spring-web:6.0",
            language="unknown",
        ),
        KnowledgeNode(
            CAFFEINE,
            KnowledgeKind.DEPENDENCY,
            "caffeine",
            qualified_name="com.github.ben-manes.caffeine:caffeine:3.1",
            language="unknown",
        ),
    )


def _edges() -> tuple[KnowledgeEdge, ...]:
    owned = (API, ADVERSARIAL, CACHE, BASE, CHILD, DUPLICATE_ALPHA)
    return (
        KnowledgeEdge(PROJECT_ALPHA, MODULE_ALPHA, KnowledgeRelation.OWNS, ("repository_summary.projects",)),
        *(KnowledgeEdge(PROJECT_ALPHA, target, KnowledgeRelation.OWNS, ("semantic_graph.project_id",)) for target in owned),
        *(KnowledgeEdge(MODULE_ALPHA, target, KnowledgeRelation.OWNS, ("global_symbol.owner_id",)) for target in owned),
        KnowledgeEdge(PROJECT_BETA, DUPLICATE_BETA, KnowledgeRelation.OWNS, ("semantic_graph.project_id",)),
        KnowledgeEdge(CHILD, BASE, KnowledgeRelation.INHERITS, ("implements",)),
        KnowledgeEdge(PROJECT_ALPHA, SPRING_WEB, KnowledgeRelation.DEPENDS_ON, ("declared_dependency:maven:org.springframework:spring-web:6.1:compile",)),
        KnowledgeEdge(PROJECT_ALPHA, CAFFEINE, KnowledgeRelation.DEPENDS_ON, ("declared_dependency:maven:com.github.ben-manes.caffeine:caffeine:3.1:compile",)),
    )


def _symbols() -> list[dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {
        API: {
            "annotations": "jakarta.ws.rs.GET,org.springframework.web.bind.annotation.RestController",
            "language": "java",
            "visibility": "public",
        },
        ADVERSARIAL: {"language": "java", "visibility": "public"},
        CACHE: {
            "annotations": "org.springframework.cache.annotation.Cacheable,jakarta.inject.Inject",
            "language": "java",
            "visibility": "public",
        },
        BASE: {"language": "java", "visibility": "public"},
        CHILD: {"language": "java", "inherits": "com.acme.BasePort", "visibility": "public"},
        DUPLICATE_ALPHA: {"language": "java", "visibility": "public"},
        DUPLICATE_BETA: {"language": "java", "visibility": "public"},
    }
    names = {
        API: ("ApiController", "com.acme.ApiController", "alpha"),
        ADVERSARIAL: ("RestEndpointCacheInjected", "com.acme.RestEndpointCacheInjected", "alpha"),
        CACHE: ("CacheService", "com.acme.CacheService", "alpha"),
        BASE: ("BasePort", "com.acme.BasePort", "alpha"),
        CHILD: ("HttpAdapter", "com.acme.HttpAdapter", "alpha"),
        DUPLICATE_ALPHA: ("Duplicate", "com.shared.Duplicate", "alpha"),
        DUPLICATE_BETA: ("Duplicate", "com.shared.Duplicate", "beta"),
    }
    return [
        {
            "id": symbol_id,
            "kind": "type",
            "name": name,
            "qualified_name": qualified,
            "project_id": project,
            "source": f"{project}/src/main/java/{name}.java",
            "metadata": metadata[symbol_id],
        }
        for symbol_id, (name, qualified, project) in names.items()
    ]


def _snapshot(
    *,
    reverse_graph_inputs: bool = False,
    graph_schema: int = 1,
    context_overrides: Mapping[str, object] | None = None,
) -> AtlasSemanticSnapshot:
    nodes = tuple(reversed(_nodes())) if reverse_graph_inputs else _nodes()
    edges = tuple(reversed(_edges())) if reverse_graph_inputs else _edges()
    graph = KnowledgeGraph(nodes, edges)
    graph_payload = graph.to_dict()
    graph_payload["schema_version"] = graph_schema
    stale_reachability = ReachabilityAnalysisService().analyze(
        graph,
        snapshot_lineage="fixture-lineage",
    ).to_dict()
    stale_reachability["graph_digest"] = "0" * 64
    context_data: dict[str, object] = {
        "schema_version": 1,
        "semantic_graph": graph_payload,
        "symbols": _symbols(),
        # This deliberately resembles a stale PR131 provider. Search must expose
        # the incompatibility instead of trusting or silently indexing it.
        "reachability": stale_reachability,
        "repository_report": {"summary": "OnlyReportToken security endpoint"},
        "repository_summary": {"summary": "OnlySummaryToken authentication"},
        "explain": {"answer": "OnlyExplainToken cache"},
        "source_code": "class OnlySourceToken {}",
    }
    context_data.update(context_overrides or {})
    context = WorkspaceSemanticContext(context_data)
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="workspace-fixture",
        analyzer_version="test-analyzer/1",
    )


def _service(**kwargs: object) -> SemanticSearchService:
    return SemanticSearchService.from_snapshot(_snapshot(**kwargs))


def _capability(response: SemanticSearchResponse, name: str):
    return next(item for item in response.capabilities if item.name == name)


def test_exact_identity_uses_pr134_canonical_resolver() -> None:
    response = _service().search_semantic(SemanticSearchRequest(API))

    assert [hit.canonical_subject_id for hit in response.hits] == [API]
    exact = next(item for item in response.hits[0].score_components if item.name == "exact_identity")
    assert exact.available is True
    assert exact.value == 1.0


@pytest.mark.parametrize(
    ("query", "expected_id", "concept"),
    (
        ("rest endpoint", API, "rest_endpoint"),
        ("caching", CACHE, "caching"),
        ("dependency injection", CACHE, "dependency_injection"),
    ),
)
def test_structured_annotation_evidence_beats_adversarial_names(
    query: str,
    expected_id: str,
    concept: str,
) -> None:
    response = _service().search_semantic(SemanticSearchRequest(query))
    positions = {hit.canonical_subject_id: index for index, hit in enumerate(response.hits)}

    assert expected_id in positions
    assert concept in response.hits[positions[expected_id]].matched_concepts
    if ADVERSARIAL in positions:
        adversarial = response.hits[positions[ADVERSARIAL]]
        assert positions[expected_id] < positions[ADVERSARIAL]
        assert concept not in adversarial.matched_concepts
        assert any("weak lexical match" in item for item in adversarial.limitations)


def test_kind_project_language_package_and_module_filters_compose() -> None:
    response = _service().search_semantic(SemanticSearchRequest(
        "rest endpoint",
        kinds=(KnowledgeKind.TYPE,),
        project="alpha",
        module="alpha",
        package="com.acme",
        language="JAVA",
    ))

    assert response.hits
    assert all(hit.kind is KnowledgeKind.TYPE for hit in response.hits)
    assert all(hit.project == "alpha" for hit in response.hits)
    assert all(hit.module == "alpha" for hit in response.hits)
    assert all(hit.package == "com.acme" for hit in response.hits)
    assert all(hit.language == "java" for hit in response.hits)
    assert SPRING_WEB not in {hit.canonical_subject_id for hit in response.hits}


def test_compound_natural_language_scope_is_deterministic() -> None:
    response = _service().search_semantic(
        SemanticSearchRequest("controllers in project alpha")
    )

    assert response.interpretation.filters == (("project", "alpha"),)
    assert response.hits[0].canonical_subject_id == API
    assert response.hits[0].matched_concepts == ("controller",)


def test_technology_subjects_are_results_with_explicit_presence_limitation() -> None:
    response = _service().search_semantic(SemanticSearchRequest("rest endpoint"))
    spring = next(hit for hit in response.hits if hit.canonical_subject_id == SPRING_WEB)

    assert spring.kind is KnowledgeKind.DEPENDENCY
    assert "rest_endpoint" in spring.matched_concepts
    assert any("presence does not establish use" in item for item in spring.limitations)
    assert "dependency_intelligence" in spring.capability_sources


def test_relational_inheritance_and_dependency_queries_use_canonical_edges() -> None:
    service = _service()
    inherited = service.search_semantic(SemanticSearchRequest("implements BasePort"))
    dependencies = service.search_semantic(SemanticSearchRequest("depends on spring-web"))

    child = next(hit for hit in inherited.hits if hit.canonical_subject_id == CHILD)
    alpha = next(hit for hit in dependencies.hits if hit.canonical_subject_id == PROJECT_ALPHA)
    assert child.relationships == ("canonical implements relationship matched",)
    assert alpha.relationships == ("canonical depends_on relationship matched",)
    assert child.evidence_ids
    assert alpha.evidence_ids


def test_missing_call_edges_are_reported_unavailable_not_inferred_absent() -> None:
    response = _service().search_semantic(SemanticSearchRequest("calls BasePort"))

    capability = _capability(response, "relation.calls")
    assert capability.state is SearchCapabilityState.UNAVAILABLE
    assert any("No authoritative canonical calls evidence" in item for item in capability.limitations)
    assert all(not hit.relationships for hit in response.hits)
    assert any(
        "No authoritative canonical calls evidence" in item
        for item in response.limitations
    )


def test_reordered_graph_inputs_and_repeated_search_are_byte_deterministic() -> None:
    forward = _snapshot()
    reverse = _snapshot(reverse_graph_inputs=True)
    assert forward.snapshot_id == reverse.snapshot_id

    request = SemanticSearchRequest("rest endpoint", limit=10)
    warm_service = SemanticSearchService.from_snapshot(forward)
    first = warm_service.search_semantic(request)
    warm = warm_service.search_semantic(request)
    second = SemanticSearchService.from_snapshot(reverse).search_semantic(request)
    assert first.to_json() == warm.to_json()
    assert first.to_json() == second.to_json()


def test_every_public_search_dto_has_an_exact_serialization_round_trip() -> None:
    request = SemanticSearchRequest(
        "implements BasePort",
        kinds=(KnowledgeKind.TYPE,),
        project="alpha",
        language="java",
        relation=KnowledgeRelation.INHERITS,
        minimum_confidence=0.0,
        limit=7,
    )
    response = _service().search_semantic(request)

    assert SemanticSearchRequest.from_dict(request.to_dict()).to_dict() == request.to_dict()
    interpretation = response.interpretation
    assert QueryInterpretation.from_dict(interpretation.to_dict()).to_dict() == interpretation.to_dict()
    for hit in response.hits:
        for component in hit.score_components:
            assert ScoreComponent.from_dict(component.to_dict()).to_dict() == component.to_dict()
        assert StructuredSearchHit.from_dict(hit.to_dict()).to_dict() == hit.to_dict()
    restored = SemanticSearchResponse.from_dict(response.to_dict())
    assert restored.to_dict() == response.to_dict()
    assert restored.to_json() == response.to_json()


def test_older_snapshot_without_pr129_graph_degrades_explicitly() -> None:
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "symbols": _symbols(),
            "repository_report": {"summary": "OnlyReportToken"},
        }),
        workspace_fingerprint="old-workspace",
        analyzer_version="old-analyzer/1",
    )
    response = SemanticSearchService.from_snapshot(snapshot).search_semantic(
        SemanticSearchRequest("ApiController")
    )

    assert response.hits == ()
    assert _capability(response, "canonical_graph").state is SearchCapabilityState.UNAVAILABLE
    assert _capability(response, "structured_symbols").state is SearchCapabilityState.PARTIAL
    assert any("older snapshot" in item for item in response.limitations)


@pytest.mark.parametrize(
    "query",
    ("OnlyReportToken", "OnlySummaryToken", "OnlyExplainToken", "OnlySourceToken"),
)
def test_report_explain_summary_and_source_prose_are_not_indexed(query: str) -> None:
    response = _service().search_semantic(SemanticSearchRequest(query))

    assert response.hits == ()


@pytest.mark.parametrize("query", (r"C:\\private\\workspace", "/home/private/workspace"))
def test_absolute_paths_are_rejected_at_the_request_boundary(query: str) -> None:
    with pytest.raises(ValueError, match="absolute paths"):
        SemanticSearchRequest(query)


def test_stale_reachability_provider_is_explicitly_incompatible() -> None:
    response = _service().search_semantic(SemanticSearchRequest("dead code"))

    capability = _capability(response, "reachability")
    assert capability.state is SearchCapabilityState.INCOMPATIBLE
    assert any("schema-, producer-, or graph-incompatible" in item for item in capability.limitations)
    assert response.hits == ()


def _pattern_report(
    participant_id: str,
    *,
    unsafe_detail: bool = False,
) -> dict[str, object]:
    record = EvidenceRecord.create(
        EvidenceKind.ANALYSIS_RESULT,
        participant_id,
        "atlas-pr130/1",
        "fixture-lineage",
        source_refs=("design-pattern.fixture",),
        detail={
            "fact": (
                "host=build-agent-17 user=private-user RuntimeError: private-token"
                if unsafe_detail else "builder-structure"
            ),
        },
        limitations=("private-user@build-agent-17 exception details",)
        if unsafe_detail else (),
        reliability=0.9,
        specificity=0.9,
    )
    return {
        "schema_version": 1,
        "producer_version": "atlas-pr130/1",
        "input_fingerprint": "pattern-fixture",
        "findings": [{
            "pattern": "builder",
            "participants": [{
                "role": "builder",
                "symbol_id": participant_id,
                "qualified_name": "com.acme.ApiController",
            }],
            "confidence": 0.81,
            "confidence_tier": "high",
            "evidence_ids": [record.evidence_id],
            "explanation": "structured builder evidence",
            "limitations": ["private-user@build-agent-17 exception details"]
            if unsafe_detail else [],
            "scope": "alpha",
            "language": "java",
            "detector_version": "atlas-pr130/1",
        }],
        "capabilities": [{
            "pattern": "builder",
            "availability": "available",
            "required_evidence": ["structured builder evidence"],
            "available_evidence": ["structured builder evidence"],
            "limitations": ["private-user@build-agent-17 exception details"]
            if unsafe_detail else [],
        }],
        "evidence_index": EvidenceIndex((record,)).to_dict(),
    }


def test_compatible_pr128_pr130_pr131_and_pr132_facts_are_projected() -> None:
    graph = KnowledgeGraph(_nodes(), _edges())
    symbol_metadata = _symbols()
    symbol_metadata[0]["metadata"]["entry_point"] = "java-main"
    reachability = ReachabilityAnalysisService().analyze(
        graph,
        symbol_metadata=symbol_metadata,
        snapshot_lineage="provider-fixture",
    )
    risks = RiskAnalysisService().analyze(
        graph,
        symbol_metadata=symbol_metadata,
    )
    snapshot = _snapshot(context_overrides={
        "architecture": {
            "schema_version": 1,
            "findings": [{
                "architecture": "layered",
                "confidence": 0.72,
                "evidence": [{
                    "kind": "project-relationship",
                    "reference": "alpha",
                    "detail": "canonical project evidence",
                }],
            }],
        },
        "design_patterns": _pattern_report(API),
        "reachability": reachability.to_dict(),
        "risk_analysis": risks.to_dict(),
    })
    service = SemanticSearchService.from_snapshot(snapshot)

    architecture = service.search_semantic(
        SemanticSearchRequest("layered architecture")
    )
    pattern = service.search_semantic(SemanticSearchRequest("builder pattern"))
    entry = service.search_semantic(SemanticSearchRequest("entry point"))
    risk = service.search_semantic(SemanticSearchRequest("risk hotspot"))

    assert architecture.hits[0].canonical_subject_id == PROJECT_ALPHA
    assert pattern.hits[0].canonical_subject_id == API
    assert "design_patterns" in pattern.hits[0].capability_sources
    assert entry.hits[0].canonical_subject_id == API
    assert "reachability" in entry.hits[0].capability_sources
    assert risk.hits
    assert all("risk_analysis" in item.capability_sources for item in risk.hits)
    assert all(
        response.evidence_index.get(evidence_id) is not None
        for response in (architecture, pattern, entry, risk)
        for hit in response.hits
        for evidence_id in hit.evidence_ids
    )


def test_unmapped_pr130_participants_downgrade_capability_and_are_not_indexed() -> None:
    response = SemanticSearchService.from_snapshot(_snapshot(context_overrides={
        "design_patterns": _pattern_report("symbol:stale:missing"),
    })).search_semantic(SemanticSearchRequest("builder pattern"))

    capability = _capability(response, "design_patterns")
    assert capability.state is SearchCapabilityState.UNAVAILABLE
    assert capability.coverage == 0.0
    assert any("Indexed 0 of 1" in item for item in capability.limitations)
    assert response.hits == ()


def test_upstream_provider_details_are_projected_to_a_bounded_safe_record() -> None:
    response = SemanticSearchService.from_snapshot(_snapshot(context_overrides={
        "design_patterns": _pattern_report(API, unsafe_detail=True),
    })).search_semantic(SemanticSearchRequest("builder pattern"))

    encoded = response.to_json()
    assert response.hits
    assert "private-user" not in encoded
    assert "build-agent-17" not in encoded
    assert "private-token" not in encoded
    assert all(
        dict(record.detail).keys() == {"upstream_evidence_id"}
        for record in response.evidence_index.records
    )


def test_duplicate_qualified_names_in_distinct_projects_are_not_collapsed() -> None:
    response = _service().search_semantic(SemanticSearchRequest("com.shared.Duplicate"))

    assert response.interpretation.ambiguous is True
    assert {hit.canonical_subject_id for hit in response.hits} == {
        DUPLICATE_ALPHA,
        DUPLICATE_BETA,
    }
    assert [hit.canonical_subject_id for hit in response.hits] == sorted(
        (DUPLICATE_ALPHA, DUPLICATE_BETA)
    )


def test_search_records_m2_phase_samples_without_affecting_results() -> None:
    session = MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_filesystem=False,
    ))
    service = SemanticSearchService.from_snapshot(_snapshot(), measurement=session)
    response = service.search_semantic(SemanticSearchRequest("rest endpoint"))
    phases = {sample.phase_id for sample in session.report().samples}

    assert response.hits
    assert {
        "semantic_search.index",
        "semantic_search.interpret",
        "semantic_search.retrieve",
        "semantic_search.score",
        "semantic_search.evidence",
        "semantic_search.sort",
    }.issubset(phases)


def test_snapshot_service_rejects_the_legacy_query_api_explicitly() -> None:
    with pytest.raises(TypeError, match="search_semantic"):
        _service().search(SemanticSearchQuery(text="ApiController"))
