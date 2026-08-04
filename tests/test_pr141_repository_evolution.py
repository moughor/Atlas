from __future__ import annotations

from copy import deepcopy

import pytest

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_git_context import GitHistoryWindow
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_evolution import (
    EvolutionCapabilityKind,
    EvolutionChangeKind,
    EvolutionState,
    RepositoryEvolutionRequest,
    RepositoryEvolutionResponse,
    RepositoryEvolutionService,
    render_repository_evolution,
)
from moughorai.risk_analysis import RiskAnalysisService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


def _node(
    identifier: str,
    qualified_name: str,
    *,
    metadata: tuple[tuple[str, str], ...] = (),
) -> KnowledgeNode:
    return KnowledgeNode(
        identifier,
        KnowledgeKind.TYPE,
        qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        project_id="api",
        language="java",
        metadata=metadata,
    )


def _graph(
    nodes: tuple[KnowledgeNode, ...],
    edges: tuple[KnowledgeEdge, ...] = (),
    *,
    reverse: bool = False,
) -> KnowledgeGraph:
    return KnowledgeGraph(
        tuple(reversed(nodes)) if reverse else nodes,
        tuple(reversed(edges)) if reverse else edges,
    )


def _snapshot(
    graph: KnowledgeGraph | None,
    *,
    fingerprint: str,
    root: str = "C:/portable/repository",
    analyzer: str = "atlas-test/1",
    additions: dict[str, object] | None = None,
) -> AtlasSemanticSnapshot:
    context: dict[str, object] = {
        "schema_version": 1,
        "workspace": {
            "root": root,
            "projects": [{"name": "api", "path": "api"}],
        },
    }
    if graph is not None:
        context["semantic_graph"] = graph.to_dict()
    if additions:
        context.update(additions)
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint=fingerprint,
        analyzer_version=analyzer,
    )


def _mixed_pair(*, reverse: bool = False):
    a_before = _node("type:a", "demo.A")
    a_after = _node("type:a", "demo.RenamedA")
    b = _node("type:b", "demo.B")
    c = _node("type:c", "demo.C")
    d = _node("type:d", "demo.D")
    base_edges = (
        KnowledgeEdge("type:a", "type:b", KnowledgeRelation.IMPORTS, ("imports",)),
        KnowledgeEdge("type:b", "type:d", KnowledgeRelation.DEPENDS_ON, ("uses",)),
    )
    head_edges = (
        KnowledgeEdge("type:a", "type:c", KnowledgeRelation.IMPORTS, ("imports",)),
        KnowledgeEdge(
            "type:c", "type:d", KnowledgeRelation.DEPENDS_ON, ("imports", "uses")
        ),
    )
    return (
        _snapshot(
            _graph((a_before, b, d), base_edges, reverse=reverse),
            fingerprint="base-fixture",
        ),
        _snapshot(
            _graph((a_after, c, d), head_edges, reverse=reverse),
            fingerprint="head-fixture",
        ),
    )


def _snapshot_with_pr132_head(head: str, *, fingerprint: str) -> AtlasSemanticSnapshot:
    project = KnowledgeNode(
        "project:api",
        KnowledgeKind.PROJECT,
        "api",
        qualified_name="api",
        project_id="api",
    )
    graph = _graph((project,))
    risk = RiskAnalysisService().analyze(
        graph,
        repository_summary={"projects": [{"name": "api", "path": "api"}]},
        git_history=GitHistoryWindow(head, 200, 1, ()),
    )
    return _snapshot(
        graph,
        fingerprint=fingerprint,
        additions={"risk_analysis": risk.to_dict()},
    )


def test_exact_node_add_remove_and_modified_are_reported() -> None:
    response = RepositoryEvolutionService().compare(*_mixed_pair())

    assert response.state is EvolutionState.PARTIAL
    assert response.total_node_change_count == 3
    assert response.omitted_node_change_count == 0
    assert response.unchanged_node_count == 1
    assert {
        (item.change, item.subject_id)
        for item in response.node_changes
    } == {
        (EvolutionChangeKind.MODIFIED, "type:a"),
        (EvolutionChangeKind.REMOVED, "type:b"),
        (EvolutionChangeKind.ADDED, "type:c"),
    }
    modified = next(
        item for item in response.node_changes
        if item.change is EvolutionChangeKind.MODIFIED
    )
    assert modified.changed_fields == ("name", "qualified_name")
    assert modified.before is not None and modified.before.qualified_name == "demo.A"
    assert modified.after is not None and modified.after.qualified_name == "demo.RenamedA"
    assert all(len(item.evidence_ids) == 2 for item in response.node_changes)


def test_relation_add_remove_and_evidence_only_modification_are_distinct() -> None:
    a, b, c = (_node(f"type:{name}", f"demo.{name.upper()}") for name in "abc")
    base = _snapshot(
        _graph(
            (a, b, c),
            (
                KnowledgeEdge("type:a", "type:b", KnowledgeRelation.IMPORTS, ("imports",)),
                KnowledgeEdge("type:b", "type:c", KnowledgeRelation.DEPENDS_ON, ("uses",)),
            ),
        ),
        fingerprint="relation-base",
    )
    head = _snapshot(
        _graph(
            (a, b, c),
            (
                KnowledgeEdge(
                    "type:a", "type:b", KnowledgeRelation.IMPORTS,
                    ("global_symbol.metadata:imports:demo.B", "imports"),
                ),
                KnowledgeEdge("type:c", "type:a", KnowledgeRelation.INHERITS, ("extends",)),
            ),
        ),
        fingerprint="relation-head",
    )

    response = RepositoryEvolutionService().compare(base, head)

    assert response.total_relation_change_count == 3
    assert response.unchanged_relation_count == 0
    assert {
        (item.change, item.source.canonical_id, item.target.canonical_id, item.relation)
        for item in response.relation_changes
    } == {
        (EvolutionChangeKind.MODIFIED, "type:a", "type:b", KnowledgeRelation.IMPORTS),
        (EvolutionChangeKind.REMOVED, "type:b", "type:c", KnowledgeRelation.DEPENDS_ON),
        (EvolutionChangeKind.ADDED, "type:c", "type:a", KnowledgeRelation.INHERITS),
    }
    changed = next(
        item for item in response.relation_changes
        if item.change is EvolutionChangeKind.MODIFIED
    )
    assert changed.before_evidence_count == 1
    assert changed.after_evidence_count == 2
    assert changed.before_evidence_digest != changed.after_evidence_digest


def test_zero_evidence_canonical_relation_remains_a_valid_observation() -> None:
    a = _node("type:a", "demo.A")
    b = _node("type:b", "demo.B")
    base = _snapshot(_graph((a, b)), fingerprint="empty-evidence-base")
    head = _snapshot(
        _graph(
            (a, b),
            (KnowledgeEdge("type:a", "type:b", KnowledgeRelation.IMPORTS, ()),),
        ),
        fingerprint="empty-evidence-head",
    )

    response = RepositoryEvolutionService().compare(base, head)

    assert len(response.relation_changes) == 1
    change = response.relation_changes[0]
    assert change.change is EvolutionChangeKind.ADDED
    assert change.after_evidence_count == 0
    assert change.after_evidence_digest is not None
    assert RepositoryEvolutionResponse.from_dict(response.to_dict()).to_dict() == response.to_dict()


def test_bounds_preserve_exact_totals_omissions_and_partial_capabilities() -> None:
    base_nodes = tuple(_node(f"type:old-{index}", f"demo.Old{index}") for index in range(4))
    head_nodes = tuple(_node(f"type:new-{index}", f"demo.New{index}") for index in range(4))
    base_edges = tuple(
        KnowledgeEdge(
            base_nodes[index].id,
            base_nodes[index + 1].id,
            KnowledgeRelation.IMPORTS,
            ("imports",),
        )
        for index in range(3)
    )
    head_edges = tuple(
        KnowledgeEdge(
            head_nodes[index].id,
            head_nodes[index + 1].id,
            KnowledgeRelation.IMPORTS,
            ("imports",),
        )
        for index in range(3)
    )
    response = RepositoryEvolutionService().compare(
        _snapshot(_graph(base_nodes, base_edges), fingerprint="bounded-base"),
        _snapshot(_graph(head_nodes, head_edges), fingerprint="bounded-head"),
        RepositoryEvolutionRequest(2, 1),
    )

    assert (response.total_node_change_count, len(response.node_changes)) == (8, 2)
    assert response.omitted_node_change_count == 6
    assert (response.total_relation_change_count, len(response.relation_changes)) == (6, 1)
    assert response.omitted_relation_change_count == 5
    assert response.capability(EvolutionCapabilityKind.CANONICAL_NODES).state is EvolutionState.PARTIAL
    assert response.capability(EvolutionCapabilityKind.CANONICAL_RELATIONS).state is EvolutionState.PARTIAL
    assert any("omitted" in item for item in response.limitations)


def test_reordered_inputs_repeat_byte_identically_and_round_trip_exactly() -> None:
    forward = RepositoryEvolutionService().compare(*_mixed_pair(reverse=False))
    reordered = RepositoryEvolutionService().compare(*_mixed_pair(reverse=True))
    repeated = RepositoryEvolutionService().compare(*_mixed_pair(reverse=False))

    assert forward.to_json() == reordered.to_json() == repeated.to_json()
    assert RepositoryEvolutionResponse.from_dict(forward.to_dict()).to_dict() == forward.to_dict()


def test_same_snapshot_is_insufficient_without_fabricated_changes() -> None:
    snapshot, _ = _mixed_pair()
    response = RepositoryEvolutionService().compare(snapshot, snapshot)

    assert response.state is EvolutionState.INSUFFICIENT
    assert response.node_changes == ()
    assert response.relation_changes == ()
    assert "no evolution interval exists" in " ".join(response.limitations)


def test_missing_pr132_git_head_is_explicitly_unavailable() -> None:
    response = RepositoryEvolutionService().compare(*_mixed_pair())
    capability = response.capability(EvolutionCapabilityKind.COMMIT_ALIGNMENT)

    assert capability.state is EvolutionState.UNAVAILABLE
    assert capability.evidence_ids == ()
    assert "absent" in " ".join(capability.limitations)


def test_compatible_pr132_git_heads_are_partial_analysis_time_associations() -> None:
    response = RepositoryEvolutionService().compare(
        _snapshot_with_pr132_head("a" * 40, fingerprint="commit-base"),
        _snapshot_with_pr132_head("b" * 40, fingerprint="commit-head"),
    )
    capability = response.capability(EvolutionCapabilityKind.COMMIT_ALIGNMENT)

    assert capability.state is EvolutionState.PARTIAL
    assert response.base.git_head == "a" * 40
    assert response.head.git_head == "b" * 40
    assert len(capability.evidence_ids) == 2
    assert "clean worktree" in " ".join(capability.limitations)


def test_malformed_pr132_git_head_is_incompatible_not_accepted() -> None:
    response = RepositoryEvolutionService().compare(
        _snapshot_with_pr132_head("not-a-full-object-id", fingerprint="malformed-base"),
        _snapshot_with_pr132_head("b" * 40, fingerprint="valid-head"),
    )
    capability = response.capability(EvolutionCapabilityKind.COMMIT_ALIGNMENT)

    assert capability.state is EvolutionState.INCOMPATIBLE
    assert response.base.git_head is None
    assert response.head.git_head == "b" * 40
    assert "malformed" in " ".join(capability.limitations)


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        (
            _snapshot(None, fingerprint="missing-graph-base"),
            _snapshot(_graph((_node("type:a", "demo.A"),)), fingerprint="graph-head"),
            EvolutionState.UNAVAILABLE,
        ),
        (
            _snapshot(
                _graph((_node("type:a", "demo.A"),)),
                fingerprint="analyzer-base",
                analyzer="atlas-test/1",
            ),
            _snapshot(
                _graph((_node("type:a", "demo.A"),)),
                fingerprint="analyzer-head",
                analyzer="atlas-test/2",
            ),
            EvolutionState.INCOMPATIBLE,
        ),
        (
            _snapshot(
                _graph((_node("type:a", "demo.A"),)),
                fingerprint="workspace-base",
                root="C:/portable/one",
            ),
            _snapshot(
                _graph((_node("type:a", "demo.A"),)),
                fingerprint="workspace-head",
                root="C:/portable/two",
            ),
            EvolutionState.INCOMPATIBLE,
        ),
    ],
)
def test_missing_graph_and_incompatible_pairs_degrade_explicitly(
    base: AtlasSemanticSnapshot,
    head: AtlasSemanticSnapshot,
    expected: EvolutionState,
) -> None:
    response = RepositoryEvolutionService().compare(base, head)

    assert response.state is expected
    assert response.node_changes == ()
    assert response.relation_changes == ()
    assert response.capability(EvolutionCapabilityKind.CANONICAL_NODES).state is expected
    assert response.capability(EvolutionCapabilityKind.CANONICAL_RELATIONS).state is expected
    assert response.limitations


def test_public_subject_projection_is_source_free_and_excludes_graph_identity() -> None:
    before = _node(
        "internal:type:a",
        "demo.A",
        metadata=(("source", "src/main/java/demo/A.java"),),
    )
    after = _node(
        "internal:type:a",
        "demo.ChangedA",
        metadata=(("source", "src/main/java/demo/A.java"),),
    )
    response = RepositoryEvolutionService().compare(
        _snapshot(_graph((before,)), fingerprint="projection-base"),
        _snapshot(_graph((after,)), fingerprint="projection-head"),
    )
    serialized = response.to_dict()
    change = serialized["node_changes"][0]

    assert change["before"]["canonical_id"] == "internal:type:a"
    assert change["after"]["canonical_id"] == "internal:type:a"
    assert "_graph_id" not in change["before"]
    assert "C:\\" not in response.to_json()
    assert "source" not in change["before"]


def test_request_and_nested_contracts_reject_unknown_fields() -> None:
    payload = RepositoryEvolutionService().compare(*_mixed_pair()).to_dict()
    payload["future"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        RepositoryEvolutionResponse.from_dict(payload)

    payload = RepositoryEvolutionService().compare(*_mixed_pair()).to_dict()
    payload["request"]["future"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        RepositoryEvolutionResponse.from_dict(payload)

    payload = RepositoryEvolutionService().compare(*_mixed_pair()).to_dict()
    payload["node_changes"][0]["future"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        RepositoryEvolutionResponse.from_dict(payload)


def test_response_payload_is_independent_of_caller_mutation() -> None:
    response = RepositoryEvolutionService().compare(*_mixed_pair())
    payload = deepcopy(response.to_dict())
    payload["limitations"].append("caller-only")
    assert "caller-only" not in response.limitations


def test_human_renderer_reports_unique_change_observation_limitations() -> None:
    response = RepositoryEvolutionService().compare(*_mixed_pair())

    rendered = render_repository_evolution(response)
    expected = {
        limitation
        for change in (*response.node_changes, *response.relation_changes)
        for limitation in change.limitations
    }

    assert "Change Observation Limitations\n" in rendered
    assert expected
    section = rendered.split(
        "Change Observation Limitations\n", 1,
    )[1].split("\n\nLimitations\n", 1)[0]
    assert section.splitlines() == [f"- {item}" for item in sorted(expected)]


def test_human_renderer_marks_change_limitations_empty_for_unchanged_pair() -> None:
    snapshot, _ = _mixed_pair()

    rendered = render_repository_evolution(
        RepositoryEvolutionService().compare(snapshot, snapshot),
    )
    section = rendered.split(
        "Change Observation Limitations\n", 1,
    )[1].split("\n\nLimitations\n", 1)[0]

    assert section == "- none"
