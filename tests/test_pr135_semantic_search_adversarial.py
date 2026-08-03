from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic_search import (
    SearchCapability,
    SearchCapabilityState,
    SemanticSearchRequest,
    SemanticSearchService,
)
from moughorai.semantic_search import service as semantic_search_service
from moughorai.semantic_search.index import SemanticSearchIndex
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


PROJECT = "project:alpha-core"
MODULE = "module:alpha-core:web-api"
PACKAGE = "package:com.acme"
CONTROLLER = "symbol:alpha-core:controller"
SERVICE = "symbol:alpha-core:service"
METHOD = "symbol:alpha-core:controller#handle"
DEPENDENCY = "dependency:maven:org.springframework:spring-web:6.1"


def _base_nodes() -> tuple[KnowledgeNode, ...]:
    return (
        KnowledgeNode(
            PROJECT,
            KnowledgeKind.PROJECT,
            "alpha-core",
            qualified_name="alpha-core",
            project_id="alpha-core",
        ),
        KnowledgeNode(
            MODULE,
            KnowledgeKind.MODULE,
            "web-api",
            qualified_name="alpha-core:web-api",
            project_id="alpha-core",
        ),
        KnowledgeNode(
            PACKAGE,
            KnowledgeKind.PACKAGE,
            "com.acme",
            qualified_name="com.acme",
            project_id="alpha-core",
            language="java",
        ),
        KnowledgeNode(
            CONTROLLER,
            KnowledgeKind.TYPE,
            "Controller",
            qualified_name="com.acme.Controller",
            project_id="alpha-core",
            language="java",
        ),
        KnowledgeNode(
            SERVICE,
            KnowledgeKind.TYPE,
            "WorkerService",
            qualified_name="com.acme.WorkerService",
            project_id="alpha-core",
            language="java",
        ),
        KnowledgeNode(
            METHOD,
            KnowledgeKind.METHOD,
            "handle",
            qualified_name="com.acme.Controller#handle",
            project_id="alpha-core",
            language="java",
        ),
        KnowledgeNode(
            DEPENDENCY,
            KnowledgeKind.DEPENDENCY,
            "spring-web",
            qualified_name="org.springframework:spring-web:6.1",
        ),
    )


def _base_edges() -> tuple[KnowledgeEdge, ...]:
    return (
        KnowledgeEdge(PROJECT, MODULE, KnowledgeRelation.OWNS, ("repository_summary.projects",)),
        KnowledgeEdge(MODULE, PACKAGE, KnowledgeRelation.OWNS, ("semantic_graph.project_id",)),
        KnowledgeEdge(PACKAGE, CONTROLLER, KnowledgeRelation.OWNS, ("global_symbol.owner_id",)),
        KnowledgeEdge(PACKAGE, SERVICE, KnowledgeRelation.OWNS, ("global_symbol.owner_id",)),
        KnowledgeEdge(CONTROLLER, METHOD, KnowledgeRelation.OWNS, ("global_symbol.owner_id",)),
        KnowledgeEdge(
            PROJECT,
            DEPENDENCY,
            KnowledgeRelation.DEPENDS_ON,
            ("declared_dependency:maven:org.springframework:spring-web:6.1:compile",),
        ),
    )


def _symbol(
    identifier: str,
    name: str,
    qualified_name: str,
    *,
    annotations: str = "",
    project: str = "alpha-core",
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "kind": "method" if "#" in qualified_name else "type",
        "name": name,
        "qualified_name": qualified_name,
        "project_id": project,
        "source": f"{project}/src/main/java/{name}.java",
        "metadata": {
            "annotations": annotations,
            "language": "java",
            "visibility": "public",
            **dict(metadata or {}),
        },
    }


def _base_symbols() -> tuple[dict[str, object], ...]:
    return (
        _symbol(
            CONTROLLER,
            "Controller",
            "com.acme.Controller",
            annotations=(
                "org.springframework.web.bind.annotation.RestController,"
                "jakarta.ws.rs.GET"
            ),
        ),
        _symbol(
            SERVICE,
            "WorkerService",
            "com.acme.WorkerService",
            annotations="org.springframework.stereotype.Service",
        ),
        _symbol(METHOD, "handle", "com.acme.Controller#handle"),
    )


def _snapshot(
    *,
    nodes: Iterable[KnowledgeNode] | None = None,
    edges: Iterable[KnowledgeEdge] | None = None,
    symbols: Iterable[Mapping[str, object]] | None = None,
) -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(
        tuple(_base_nodes() if nodes is None else nodes),
        tuple(_base_edges() if edges is None else edges),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": list(_base_symbols() if symbols is None else symbols),
        }),
        workspace_fingerprint="pr135-adversarial-fixture",
        analyzer_version="test-analyzer/1",
    )


def _search(
    text: str,
    *,
    snapshot: AtlasSemanticSnapshot | None = None,
    **request: object,
):
    service = SemanticSearchService.from_snapshot(snapshot or _snapshot())
    return service.search_semantic(SemanticSearchRequest(text, **request))


def test_explicit_kind_is_a_filter_on_exact_identity_not_a_kind_query() -> None:
    matching = _search("com.acme.Controller", kinds=(KnowledgeKind.TYPE,))
    conflicting = _search("com.acme.Controller", kinds=(KnowledgeKind.METHOD,))

    assert [hit.canonical_subject_id for hit in matching.hits] == [CONTROLLER]
    assert conflicting.hits == ()


def test_concept_and_explicit_kind_are_conjunctive() -> None:
    response = _search("rest endpoint", kinds=(KnowledgeKind.TYPE,))

    assert [hit.canonical_subject_id for hit in response.hits] == [CONTROLLER]
    assert response.hits[0].matched_concepts == ("rest_endpoint",)


def test_unavailable_relation_returns_no_results() -> None:
    response = _search("calls Controller")

    calls = next(item for item in response.capabilities if item.name == "relation.calls")
    assert calls.state is SearchCapabilityState.UNAVAILABLE
    assert response.hits == ()


def test_untraceable_relation_edge_is_not_returned_as_evidence() -> None:
    edges = (*_base_edges(), KnowledgeEdge(SERVICE, CONTROLLER, KnowledgeRelation.CALLS))
    response = _search("calls Controller", snapshot=_snapshot(edges=edges))

    assert response.hits == ()
    assert any("without safe traceable evidence" in item for item in response.limitations)


def test_custom_fully_qualified_annotation_is_not_name_classified() -> None:
    symbols = (
        _symbol(
            CONTROLLER,
            "Controller",
            "com.acme.Controller",
            annotations="com.example.framework.RestController",
        ),
        *_base_symbols()[1:],
    )
    response = _search("controller", snapshot=_snapshot(symbols=symbols))

    hit = next(
        (item for item in response.hits if item.canonical_subject_id == CONTROLLER),
        None,
    )
    assert hit is None or "controller" not in hit.matched_concepts
    if hit is not None:
        assert "structured_symbols" not in hit.capability_sources


def test_simple_known_annotation_remains_weak_and_explicitly_limited() -> None:
    symbols = (
        _symbol(
            CONTROLLER,
            "Controller",
            "com.acme.Controller",
            annotations="RestController",
        ),
        *_base_symbols()[1:],
    )
    response = _search("controller", snapshot=_snapshot(symbols=symbols))
    hit = next(item for item in response.hits if item.canonical_subject_id == CONTROLLER)

    assert hit.confidence.score < 0.8
    assert any("weak evidence" in item for item in hit.limitations)


def test_hyphenated_scope_and_dependency_subject_are_preserved() -> None:
    scoped = _search("controllers in project alpha-core")
    dependency = _search("depends on spring-web")

    assert dict(scoped.interpretation.filters)["project"] == "alpha-core"
    assert scoped.hits[0].project == "alpha-core"
    assert dependency.interpretation.subject_terms == ("spring-web",)
    assert [hit.canonical_subject_id for hit in dependency.hits] == [PROJECT]


def test_punctuation_is_ignored_and_or_is_reported_as_ambiguous() -> None:
    plain = _search("controller")
    punctuated = _search("controller?!,;")
    alternatives = _search("controller or service")

    assert [hit.canonical_subject_id for hit in punctuated.hits] == [
        hit.canonical_subject_id for hit in plain.hits
    ]
    assert alternatives.interpretation.ambiguous is True
    assert alternatives.interpretation.alternatives == ("controller", "service")
    assert {hit.canonical_subject_id for hit in alternatives.hits} == {
        CONTROLLER,
        SERVICE,
    }


def test_duplicate_symbol_metadata_order_does_not_change_results() -> None:
    duplicate = _base_symbols()[0]
    symbols = (*_base_symbols(), duplicate)
    request = SemanticSearchRequest("controller")
    forward = SemanticSearchService.from_snapshot(
        _snapshot(symbols=symbols)
    ).search_semantic(request)
    reverse = SemanticSearchService.from_snapshot(
        _snapshot(symbols=reversed(symbols))
    ).search_semantic(request)

    def semantic_projection(response):
        return (
            response.interpretation.to_dict(),
            tuple(
                (
                    hit.canonical_subject_id,
                    hit.matched_concepts,
                    hit.capability_sources,
                    hit.confidence.score,
                    hit.limitations,
                )
                for hit in response.hits
            ),
            tuple(item.to_dict() for item in response.capabilities),
            response.limitations,
        )

    assert semantic_projection(forward) == semantic_projection(reverse)


def test_module_membership_propagates_through_nested_ownership() -> None:
    response = _search("controller", module="web-api")

    assert [hit.canonical_subject_id for hit in response.hits] == [CONTROLLER]
    assert response.hits[0].module == "web-api"


def test_nearest_nested_module_membership_reaches_methods() -> None:
    parent = KnowledgeNode(
        "module:alpha-core:parent",
        KnowledgeKind.MODULE,
        "parent",
        qualified_name="alpha-core:parent",
        project_id="alpha-core",
    )
    snapshot = _snapshot(
        nodes=(*_base_nodes(), parent),
        edges=(
            *_base_edges(),
            KnowledgeEdge(PROJECT, parent.id, KnowledgeRelation.OWNS, ("repository_summary.projects",)),
            KnowledgeEdge(parent.id, MODULE, KnowledgeRelation.OWNS, ("repository_summary.module_hierarchy",)),
        ),
    )

    nearest = _search("handle", snapshot=snapshot, module="web-api")
    ancestor = _search("handle", snapshot=snapshot, module="parent")

    assert [hit.canonical_subject_id for hit in nearest.hits] == [METHOD]
    assert ancestor.hits == ()


def test_inheritance_subtype_requires_traceable_subtype_evidence() -> None:
    generic = KnowledgeEdge(
        SERVICE,
        CONTROLLER,
        KnowledgeRelation.INHERITS,
        ("global_symbol.metadata:inherits:com.acme.Controller",),
    )
    response = _search(
        "implements Controller",
        snapshot=_snapshot(edges=(*_base_edges(), generic)),
    )

    assert response.hits == ()
    assert any("does not establish 'implements'" in item for item in response.limitations)


def test_used_by_requires_explicit_relation_disambiguation() -> None:
    response = _search("used by Controller")

    assert response.hits == ()
    assert response.interpretation.ambiguous is True
    assert any("'used by' is ambiguous" in item for item in response.limitations)


def test_every_hit_evidence_id_resolves_in_response_index() -> None:
    response = _search("depends on spring-web")

    assert response.hits
    assert all(
        response.evidence_index.get(evidence_id) is not None
        for hit in response.hits
        for evidence_id in hit.evidence_ids
    )


def test_candidate_truncation_is_explicit_and_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(SemanticSearchIndex, "MAXIMUM_CANDIDATES", 2)
    extra_nodes = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:controller-{index}",
            KnowledgeKind.TYPE,
            f"Controller{index}",
            qualified_name=f"com.acme.Controller{index}",
            project_id="alpha-core",
            language="java",
        )
        for index in range(3)
    )
    extra_symbols = tuple(
        _symbol(
            node.id,
            node.name,
            node.qualified_name or node.name,
            annotations="org.springframework.web.bind.annotation.RestController",
        )
        for node in extra_nodes
    )
    snapshot = _snapshot(
        nodes=(*_base_nodes(), *extra_nodes),
        edges=(*_base_edges(), *(
            KnowledgeEdge(PACKAGE, node.id, KnowledgeRelation.OWNS, ("global_symbol.owner_id",))
            for node in extra_nodes
        )),
        symbols=(*_base_symbols(), *extra_symbols),
    )
    response = _search("controller", snapshot=snapshot)

    assert response.total_candidate_count == 2
    assert any("candidate retrieval reached" in item for item in response.limitations)


def test_unsupported_capability_state_round_trips_exactly() -> None:
    capability = SearchCapability(
        "future-specialized-provider",
        SearchCapabilityState.UNSUPPORTED,
        limitations=("Provider schema is not supported by this consumer.",),
    )

    assert SearchCapability.from_dict(capability.to_dict()).to_dict() == capability.to_dict()


def test_test_and_generated_scope_is_labeled_and_location_is_not_retained() -> None:
    symbols = (
        _symbol(
            CONTROLLER,
            "Controller",
            "com.acme.Controller",
            annotations="org.springframework.web.bind.annotation.RestController",
            metadata={"source_classification": "test", "generated": "true"},
        ),
        *_base_symbols()[1:],
    )
    service = SemanticSearchService.from_snapshot(_snapshot(symbols=symbols))
    response = service.search_semantic(SemanticSearchRequest("controller"))
    hit = next(item for item in response.hits if item.canonical_subject_id == CONTROLLER)

    assert hit.source_classifications == ("generated", "test")
    assert service._index is not None
    assert service._index.entry(CONTROLLER).subject.path is None
    records = tuple(
        response.evidence_index.get(evidence_id)
        for evidence_id in hit.evidence_ids
    )
    assert any(
        record is not None
        and dict(record.detail).get("source_classifications") == "generated,test"
        for record in records
    )


def test_forward_incompatible_graph_enum_degrades_without_crashing() -> None:
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": {
                "schema_version": 1,
                "nodes": [{
                    "id": "future:node",
                    "kind": "future_kind",
                    "qualified_name": "future.Node",
                    "project_id": None,
                    "language": "future",
                }],
                "edges": [],
            },
            "symbols": [],
        }),
        workspace_fingerprint="forward-incompatible",
        analyzer_version="future-analyzer/1",
    )

    response = SemanticSearchService.from_snapshot(snapshot).search_semantic(
        SemanticSearchRequest("future.Node")
    )

    graph = next(
        item for item in response.capabilities if item.name == "canonical_graph"
    )
    assert graph.state is SearchCapabilityState.UNAVAILABLE
    assert response.hits == ()


def test_scope_filters_are_applied_before_the_candidate_bound(monkeypatch) -> None:
    monkeypatch.setattr(SemanticSearchIndex, "MAXIMUM_CANDIDATES", 2)
    alpha_nodes = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:type-{index}",
            KnowledgeKind.TYPE,
            f"Type{index}",
            qualified_name=f"a.Type{index}",
            project_id="alpha-core",
            language="java",
        )
        for index in range(3)
    )
    zeta_project = KnowledgeNode(
        "project:zeta",
        KnowledgeKind.PROJECT,
        "zeta",
        qualified_name="zeta",
        project_id="zeta",
    )
    zeta_type = KnowledgeNode(
        "symbol:zeta:target",
        KnowledgeKind.TYPE,
        "Target",
        qualified_name="z.Target",
        project_id="zeta",
        language="java",
    )
    response = _search(
        "classes in project zeta",
        snapshot=_snapshot(nodes=(*_base_nodes(), *alpha_nodes, zeta_project, zeta_type)),
    )

    assert [item.canonical_subject_id for item in response.hits] == [zeta_type.id]


def test_package_scope_resolves_identity_beyond_resolver_ambiguity_bound() -> None:
    duplicates = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:foo-{index:02d}",
            KnowledgeKind.TYPE,
            "Foo",
            qualified_name=f"p{index:02d}.Foo",
            project_id="alpha-core",
            language="java",
        )
        for index in range(12)
    )
    target = KnowledgeNode(
        "symbol:alpha-core:foo-z",
        KnowledgeKind.TYPE,
        "Foo",
        qualified_name="z.Foo",
        project_id="alpha-core",
        language="java",
    )

    response = _search(
        "class Foo in package z",
        snapshot=_snapshot(nodes=(*_base_nodes(), *duplicates, target)),
    )

    assert [item.canonical_subject_id for item in response.hits] == [target.id]
    assert response.interpretation.ambiguous is False


def test_relation_scope_is_applied_before_the_edge_bound(monkeypatch) -> None:
    monkeypatch.setattr(semantic_search_service, "MAXIMUM_RELATION_EDGES", 2)
    projects = tuple(
        KnowledgeNode(
            f"project:a-{index}",
            KnowledgeKind.PROJECT,
            f"a-{index}",
            qualified_name=f"a-{index}",
            project_id=f"a-{index}",
        )
        for index in range(3)
    )
    zeta = KnowledgeNode(
        "project:zeta",
        KnowledgeKind.PROJECT,
        "zeta",
        qualified_name="zeta",
        project_id="zeta",
    )
    edges = (
        *_base_edges(),
        *(
            KnowledgeEdge(
                project.id,
                DEPENDENCY,
                KnowledgeRelation.DEPENDS_ON,
                ("declared_dependency:maven:org.springframework:spring-web:6.1:compile",),
            )
            for project in (*projects, zeta)
        ),
    )
    response = _search(
        "depends on spring-web in project zeta",
        snapshot=_snapshot(nodes=(*_base_nodes(), *projects, zeta), edges=edges),
    )

    assert [item.canonical_subject_id for item in response.hits] == [zeta.id]


def test_using_filters_dependency_kinds_before_candidate_bound(monkeypatch) -> None:
    monkeypatch.setattr(SemanticSearchIndex, "MAXIMUM_CANDIDATES", 2)
    noise = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:common-{index}",
            KnowledgeKind.TYPE,
            f"Common{index}",
            qualified_name=f"a.Common{index}",
            project_id="alpha-core",
            language="java",
        )
        for index in range(3)
    )
    common_dependency = KnowledgeNode(
        "dependency:maven:g:common:1",
        KnowledgeKind.DEPENDENCY,
        "common",
        qualified_name="g:common:1",
    )
    response = _search(
        "controllers using common",
        snapshot=_snapshot(
            nodes=(*_base_nodes(), *noise, common_dependency),
            edges=(
                *_base_edges(),
                KnowledgeEdge(
                    PROJECT,
                    common_dependency.id,
                    KnowledgeRelation.DEPENDS_ON,
                    ("declared_dependency:maven:g:common:1:compile",),
                ),
            ),
        ),
    )

    assert [item.canonical_subject_id for item in response.hits] == [CONTROLLER]


def test_relational_target_expands_beyond_resolver_ambiguity_bound() -> None:
    targets = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:foo-{index:02d}",
            KnowledgeKind.METHOD,
            "Foo",
            qualified_name=f"p{index:02d}.Type#Foo",
            project_id="alpha-core",
            language="java",
        )
        for index in range(13)
    )
    caller = KnowledgeNode(
        "symbol:alpha-core:caller",
        KnowledgeKind.METHOD,
        "caller",
        qualified_name="p.Caller#caller",
        project_id="alpha-core",
        language="java",
    )
    response = _search(
        "calls Foo",
        snapshot=_snapshot(
            nodes=(*_base_nodes(), *targets, caller),
            edges=(
                *_base_edges(),
                KnowledgeEdge(
                    caller.id,
                    targets[-1].id,
                    KnowledgeRelation.CALLS,
                    ("calls",),
                ),
            ),
        ),
    )

    assert [item.canonical_subject_id for item in response.hits] == [caller.id]
    assert response.interpretation.ambiguous is True
    assert targets[-1].id in response.interpretation.alternatives


def test_relation_result_scope_does_not_re_scope_the_named_target() -> None:
    checkout = KnowledgeNode(
        "project:checkout",
        KnowledgeKind.PROJECT,
        "checkout",
        qualified_name="checkout",
        project_id="checkout",
    )
    local_service = KnowledgeNode(
        "symbol:checkout:service",
        KnowledgeKind.TYPE,
        "Service",
        qualified_name="checkout.Service",
        project_id="checkout",
        language="java",
    )
    shared_service = KnowledgeNode(
        "symbol:shared:service",
        KnowledgeKind.TYPE,
        "Service",
        qualified_name="shared.Service",
        project_id="shared",
        language="java",
    )
    caller = KnowledgeNode(
        "symbol:checkout:caller",
        KnowledgeKind.METHOD,
        "checkout",
        qualified_name="checkout.Caller#checkout",
        project_id="checkout",
        language="java",
    )
    response = _search(
        "calls Service in project checkout",
        snapshot=_snapshot(
            nodes=(
                *_base_nodes(), checkout, local_service, shared_service, caller,
            ),
            edges=(
                *_base_edges(),
                KnowledgeEdge(
                    caller.id,
                    shared_service.id,
                    KnowledgeRelation.CALLS,
                    ("calls",),
                ),
            ),
        ),
    )

    assert [item.canonical_subject_id for item in response.hits] == [caller.id]
    assert response.interpretation.ambiguous is True


def test_search_response_normalizes_hits_to_an_immutable_unique_tuple() -> None:
    response = _search("controller")
    restored = replace(response, hits=list(response.hits))

    assert isinstance(restored.hits, tuple)
    with pytest.raises(ValueError, match="must be unique"):
        replace(response, hits=(response.hits[0], response.hits[0]))


@pytest.mark.parametrize(
    "mutation",
    (
        {"request": {"minimum_confidence": True}},
        {"request": {"limit": True}},
        {"component": {"available": "false"}},
        {"response": {"returned_count": True}},
    ),
)
def test_json_dto_boolean_coercions_are_rejected(mutation) -> None:
    response = _search("controller")
    payload = response.to_dict()
    if "request" in mutation:
        payload["request"].update(mutation["request"])
    elif "component" in mutation:
        payload["hits"][0]["score_components"][0].update(mutation["component"])
    else:
        payload.update(mutation["response"])

    with pytest.raises(TypeError):
        type(response).from_dict(payload)


@pytest.mark.parametrize(
    "secret",
    ("hunter2", "raw secret source text password equals hunter2"),
)
def test_untrusted_language_project_scope_and_edge_text_never_reach_response(
    secret: str,
) -> None:
    nodes = tuple(
        replace(node, project_id=secret, language=secret)
        if node.id == CONTROLLER else node
        for node in _base_nodes()
    )
    symbols = (
        _symbol(
            CONTROLLER,
            "Controller",
            "com.acme.Controller",
            annotations="org.springframework.web.bind.annotation.RestController",
            project=secret,
            metadata={"language": secret},
        ),
        *_base_symbols()[1:],
    )
    snapshot = _snapshot(
        nodes=nodes,
        edges=(
            *_base_edges(),
            KnowledgeEdge(
                SERVICE,
                CONTROLLER,
                KnowledgeRelation.CALLS,
                ("raw source fragment password hunter2",),
            ),
        ),
        symbols=symbols,
    )

    concept = _search("controller", snapshot=snapshot)
    relation = _search("calls Controller", snapshot=snapshot)

    assert "hunter2" not in concept.to_json()
    assert "hunter2" not in relation.to_json()
    hit = next(item for item in concept.hits if item.canonical_subject_id == CONTROLLER)
    assert hit.project is None
    assert hit.language == "unknown"
    assert relation.hits == ()


@pytest.mark.parametrize(
    "field,malformed",
    (
        ("kinds", "type"),
        ("hits", ["not-an-object"]),
        ("capabilities", ["not-an-object"]),
    ),
)
def test_json_dto_collection_shapes_are_rejected(field, malformed) -> None:
    response = _search("controller")
    payload = response.to_dict()
    if field == "kinds":
        payload["request"][field] = malformed
    else:
        payload[field] = malformed

    with pytest.raises(TypeError):
        type(response).from_dict(payload)


def test_json_dto_rejects_malformed_component_and_untraceable_scores() -> None:
    response = _search("controller")

    malformed = response.to_dict()
    malformed["hits"][0]["score_components"].append("not-an-object")
    with pytest.raises(TypeError):
        type(response).from_dict(malformed)

    dangling = response.to_dict()
    dangling["hits"][0]["score_components"][0]["evidence_ids"] = [
        "evidence:" + "0" * 64
    ]
    with pytest.raises(ValueError, match="unresolvable|inconsistent"):
        type(response).from_dict(dangling)

    inconsistent = response.to_dict()
    score = inconsistent["hits"][0]["score"]
    inconsistent["hits"][0]["score"] = 0.0 if score else 1.0
    with pytest.raises(ValueError, match="score is inconsistent"):
        type(response).from_dict(inconsistent)


def test_json_dto_rejects_malformed_or_tampered_evidence_records() -> None:
    response = _search("controller")

    malformed = response.to_dict()
    malformed["evidence_index"]["records"].append("not-an-object")
    with pytest.raises(TypeError, match="evidence records"):
        type(response).from_dict(malformed)

    tampered = response.to_dict()
    tampered["evidence_index"]["records"][0]["detail"]["note"] = (
        "password hunter2"
    )
    with pytest.raises(ValueError, match="evidence ID is inconsistent"):
        type(response).from_dict(tampered)

    replaced = response.to_dict()
    record = replaced["evidence_index"]["records"][0]
    original_id = record["evidence_id"]
    replacement_id = "evidence:" + "0" * 64
    record["evidence_id"] = replacement_id
    for hit in replaced["hits"]:
        hit["evidence_ids"] = [
            replacement_id if item == original_id else item
            for item in hit["evidence_ids"]
        ]
        for component in hit["score_components"]:
            component["evidence_ids"] = [
                replacement_id if item == original_id else item
                for item in component["evidence_ids"]
            ]
    with pytest.raises(ValueError, match="evidence ID is inconsistent"):
        type(response).from_dict(replaced)


def test_json_dto_rejects_contributing_component_marked_unavailable() -> None:
    response = _search("controller")
    payload = response.to_dict()
    component = next(
        item for item in payload["hits"][0]["score_components"]
        if item["contribution"] > 0.0
    )
    component["available"] = False

    with pytest.raises(ValueError, match="unavailable score components"):
        type(response).from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (("missing_roles", "rawsource"), ("model_version", True)),
)
def test_json_dto_strictly_validates_nested_confidence(field, value) -> None:
    response = _search("worker")
    payload = response.to_dict()
    payload["hits"][0]["confidence"][field] = value

    with pytest.raises((TypeError, ValueError)):
        type(response).from_dict(payload)


def test_unknown_multi_token_query_resolves_identity_then_lexical_tokens() -> None:
    platform = KnowledgeNode(
        "repository:atlas-platform",
        KnowledgeKind.REPOSITORY,
        "Atlas Platform",
        qualified_name="Atlas Platform",
    )
    transport = KnowledgeNode(
        "symbol:alpha-core:transport-action",
        KnowledgeKind.TYPE,
        "TransportAction",
        qualified_name="org.elasticsearch.TransportAction",
        project_id="alpha-core",
        language="java",
    )
    snapshot = _snapshot(nodes=(*_base_nodes(), platform, transport))

    exact = _search("Atlas Platform", snapshot=snapshot)
    lexical = _search("transport action", snapshot=snapshot)

    assert [item.qualified_name for item in exact.hits] == ["Atlas Platform"]
    assert [item.canonical_subject_id for item in lexical.hits] == [transport.id]
    assert lexical.hits[0].score <= 0.39


def test_unscoped_identity_ambiguity_is_not_hidden_by_resolver_bound() -> None:
    duplicates = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:foo-{index:02d}",
            KnowledgeKind.TYPE,
            "Foo",
            qualified_name=f"p{index:02d}.Foo",
            project_id="alpha-core",
            language="java",
        )
        for index in range(13)
    )

    response = _search("Foo", snapshot=_snapshot(nodes=(*_base_nodes(), *duplicates)))

    assert response.interpretation.ambiguous is True
    assert response.total_candidate_count == 13
    assert len(response.hits) == 13
    assert len(response.interpretation.alternatives) == 13


def test_scope_filter_reuses_postings_without_materializing_the_scope() -> None:
    service = SemanticSearchService.from_snapshot(_snapshot())
    assert service._index is not None

    scope = service._index.scope_ids(project="alpha-core", language="java")

    assert scope is not None
    assert not isinstance(scope, frozenset)
    assert scope.matches(CONTROLLER)
    assert not scope.matches(DEPENDENCY)


def test_bounded_lexical_retrieval_prioritizes_multi_term_matches(
    monkeypatch,
) -> None:
    monkeypatch.setattr(SemanticSearchIndex, "MAXIMUM_CANDIDATES", 2)
    action_nodes = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:action-{index}",
            KnowledgeKind.TYPE,
            "Action",
            qualified_name=f"a{index}.Action",
            project_id="alpha-core",
            language="java",
        )
        for index in range(3)
    )
    transport_action = KnowledgeNode(
        "symbol:alpha-core:transport-action",
        KnowledgeKind.TYPE,
        "TransportAction",
        qualified_name="z.TransportAction",
        project_id="alpha-core",
        language="java",
    )

    response = _search(
        "transport action",
        snapshot=_snapshot(nodes=(*_base_nodes(), *action_nodes, transport_action)),
    )

    assert transport_action.id in {
        item.canonical_subject_id for item in response.hits
    }
    assert any("candidate retrieval reached" in item for item in response.limitations)


def test_global_candidate_bound_never_discards_exact_identity(monkeypatch) -> None:
    monkeypatch.setattr(SemanticSearchIndex, "MAXIMUM_CANDIDATES", 2)
    exact = KnowledgeNode(
        "symbol:alpha-core:cache-z",
        KnowledgeKind.TYPE,
        "Cache",
        qualified_name="z.Cache",
        project_id="alpha-core",
        language="java",
    )
    semantic_nodes = tuple(
        KnowledgeNode(
            f"symbol:alpha-core:cache-a{index}",
            KnowledgeKind.TYPE,
            f"CacheClient{index}",
            qualified_name=f"a.CacheClient{index}",
            project_id="alpha-core",
            language="java",
        )
        for index in range(2)
    )
    semantic_symbols = tuple(
        _symbol(
            node.id,
            node.name,
            node.qualified_name or node.name,
            annotations="org.springframework.cache.annotation.Cacheable",
        )
        for node in semantic_nodes
    )

    response = _search(
        "cache",
        snapshot=_snapshot(
            nodes=(*_base_nodes(), exact, *semantic_nodes),
            symbols=(*_base_symbols(), *semantic_symbols),
        ),
    )

    assert exact.id in {item.canonical_subject_id for item in response.hits}
    exact_hit = next(
        item for item in response.hits if item.canonical_subject_id == exact.id
    )
    assert next(
        component for component in exact_hit.score_components
        if component.name == "exact_identity"
    ).value == 1.0


def test_evidence_free_lexical_cap_preserves_match_ordering() -> None:
    partial = KnowledgeNode(
        "symbol:alpha-core:fast-transport",
        KnowledgeKind.TYPE,
        "FastTransport",
        qualified_name="a.FastTransport",
        project_id="alpha-core",
        language="java",
    )
    complete = KnowledgeNode(
        "symbol:alpha-core:transport-action-complete",
        KnowledgeKind.TYPE,
        "TransportAction",
        qualified_name="z.TransportAction",
        project_id="alpha-core",
        language="java",
    )

    response = _search(
        "transport action",
        snapshot=_snapshot(nodes=(*_base_nodes(), partial, complete)),
    )

    assert [item.canonical_subject_id for item in response.hits[:2]] == [
        complete.id,
        partial.id,
    ]
    assert response.hits[0].score == pytest.approx(0.39)
    assert response.hits[1].score == pytest.approx(0.195)
