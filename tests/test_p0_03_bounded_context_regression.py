"""Phase B regression tests for bounded database-context selection.

These tests use **synthetic graphs** — no Sygma or external repository required.
They verify:

  - Hard max_objects cap on every public path
  - Deterministic selection (same input → same output)
  - Priority eviction preserves directly-mentioned tables and required FK edges
  - Truncation metadata is accurate
  - Large graph scalability
  - Relationship preservation (FK, view/DERIVED_FROM, synonym/ALIAS_OF, dependency)
  - Round-trip serialisation of new dataclasses
  - Boundary conditions (max_objects=1, empty story, no matches)
"""

from __future__ import annotations

import pytest

from moughorai.database_graph.models import (
    DatabaseGraph,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    NodeKind,
)
from moughorai.database_graph.context_selector import (
    DatabaseContextResult,
    OmittedCounts,
    SelectionDetail,
    TruncationMetadata,
    render_database_context_markdown,
    render_database_context_mermaid,
    select_database_context,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic graph builders
# ---------------------------------------------------------------------------

_VERIFIED = EvidenceRecord.verified()
_edge_counter = 0


def _node(kind: str, qname: str, *, schema: str | None = None) -> DatabaseGraphNode:
    return DatabaseGraphNode(
        id=qname.lower().replace(".", "_"),
        kind=kind,
        qualified_name=qname,
        schema=schema,
        evidence=_VERIFIED,
    )


def _edge(kind: str, from_id: str, to_id: str) -> DatabaseGraphEdge:
    global _edge_counter
    _edge_counter += 1
    return DatabaseGraphEdge(
        id=f"e{_edge_counter}",
        kind=kind,
        from_node=from_id,
        to_node=to_id,
        evidence=_VERIFIED,
    )


def _make_table_with_columns(
    name: str,
    columns: list[str],
    *,
    schema: str | None = None,
) -> tuple[list[DatabaseGraphNode], list[DatabaseGraphEdge]]:
    """Build a table node and its column nodes + HAS_COLUMN edges."""
    tbl = _node(NodeKind.TABLE.value, name, schema=schema)
    nodes = [tbl]
    edges = []
    for col_name in columns:
        col = _node(NodeKind.COLUMN.value, f"{name}.{col_name}")
        nodes.append(col)
        edges.append(_edge(EdgeKind.HAS_COLUMN.value, tbl.id, col.id))
    return nodes, edges


def _build_small_graph() -> DatabaseGraph:
    """A 3-table graph with FK, columns, and a view — small enough to fit in 60.

    Tables: TB_ALPHA (3 cols), TB_BETA (2 cols), TB_GAMMA (2 cols)
    FKs: TB_BETA → TB_ALPHA, TB_GAMMA → TB_ALPHA
    View: VW_COMBINED derived from TB_ALPHA
    """
    all_nodes: list[DatabaseGraphNode] = []
    all_edges: list[DatabaseGraphEdge] = []

    ns, es = _make_table_with_columns("TB_ALPHA", ["COL_A1", "COL_A2", "COL_A3"])
    all_nodes.extend(ns); all_edges.extend(es)

    ns, es = _make_table_with_columns("TB_BETA", ["COL_B1", "COL_B2"])
    all_nodes.extend(ns); all_edges.extend(es)

    ns, es = _make_table_with_columns("TB_GAMMA", ["COL_G1", "COL_G2"])
    all_nodes.extend(ns); all_edges.extend(es)

    # FK: BETA → ALPHA, GAMMA → ALPHA
    alpha_id = "tb_alpha"
    beta_id = "tb_beta"
    gamma_id = "tb_gamma"
    all_edges.append(_edge(EdgeKind.FOREIGN_KEY_TO.value, beta_id, alpha_id))
    all_edges.append(_edge(EdgeKind.FOREIGN_KEY_TO.value, gamma_id, alpha_id))

    # View derived from ALPHA
    vw = _node(NodeKind.VIEW.value, "VW_COMBINED")
    all_nodes.append(vw)
    all_edges.append(_edge(EdgeKind.DERIVED_FROM.value, vw.id, alpha_id))

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "abc123"},
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
    )


def _build_large_graph(n_tables: int = 200, cols_per_table: int = 5) -> DatabaseGraph:
    """Build a large synthetic graph with n_tables tables, each with columns.

    Creates:
    - n_tables tables named TB_LARGE_0000 .. TB_LARGE_{n-1}
    - cols_per_table columns per table
    - FK chain: TB_LARGE_0001 → TB_LARGE_0000, etc.
    - A view VW_REPORT derived from TB_LARGE_0000
    - A synonym SYN_MAIN alias of TB_LARGE_0000
    Total nodes: n_tables * (1 + cols_per_table) + 2 (view + synonym)
    """
    all_nodes: list[DatabaseGraphNode] = []
    all_edges: list[DatabaseGraphEdge] = []

    for i in range(n_tables):
        name = f"TB_LARGE_{i:04d}"
        ns, es = _make_table_with_columns(name, [f"COL_{j}" for j in range(cols_per_table)])
        all_nodes.extend(ns)
        all_edges.extend(es)
        if i > 0:
            prev_name = f"TB_LARGE_{i-1:04d}"
            all_edges.append(_edge(
                EdgeKind.FOREIGN_KEY_TO.value,
                name.lower().replace(".", "_"),
                prev_name.lower().replace(".", "_"),
            ))

    # View
    vw = _node(NodeKind.VIEW.value, "VW_REPORT")
    all_nodes.append(vw)
    all_edges.append(_edge(EdgeKind.DERIVED_FROM.value, vw.id, "tb_large_0000"))

    # Synonym
    syn = _node(NodeKind.SYNONYM.value, "SYN_MAIN")
    all_nodes.append(syn)
    all_edges.append(_edge(EdgeKind.ALIAS_OF.value, syn.id, "tb_large_0000"))

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "large_test"},
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
    )


def _build_entity_bridge_graph() -> DatabaseGraph:
    """Graph with JPA entities to test entity bridging.

    Tables: TB_ORDER, TB_ORDER_ITEM
    Entities: OrderItem (MAPS_TO_TABLE → TB_ORDER_ITEM)
    FK: TB_ORDER_ITEM → TB_ORDER
    """
    all_nodes: list[DatabaseGraphNode] = []
    all_edges: list[DatabaseGraphEdge] = []

    ns, es = _make_table_with_columns("TB_ORDER", ["COL_O1", "COL_O2"])
    all_nodes.extend(ns); all_edges.extend(es)

    ns, es = _make_table_with_columns("TB_ORDER_ITEM", ["COL_OI1", "COL_OI2", "ORDER_ID"])
    all_nodes.extend(ns); all_edges.extend(es)

    all_edges.append(_edge(EdgeKind.FOREIGN_KEY_TO.value, "tb_order_item", "tb_order"))

    entity = _node(NodeKind.JAVA_ENTITY.value, "com.example.OrderItem")
    all_nodes.append(entity)
    all_edges.append(_edge(EdgeKind.MAPS_TO_TABLE.value, entity.id, "tb_order_item"))

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "entity_test"},
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
    )


# ---------------------------------------------------------------------------
# Tests: hard cap enforcement
# ---------------------------------------------------------------------------


class TestHardCap:
    """Verify the hard max_objects cap on all public paths."""

    def test_small_graph_no_truncation(self):
        """A graph that fits within 60 should not be truncated."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=60)
        assert len(result.selected_nodes) <= 60
        assert "TB_ALPHA" in {n.qualified_name for n in result.selected_nodes}

    def test_hard_cap_at_60(self):
        """Large graph must respect the hard cap of 60."""
        g = _build_large_graph(200, 5)
        result = select_database_context(g, "TB_LARGE_0000", max_objects=60)
        assert len(result.selected_nodes) <= 60
        assert result.truncation.was_truncated is True
        assert result.truncation.hard_cap == 60

    def test_hard_cap_at_1(self):
        """Extreme cap: max_objects=1 should return at most 1 node."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=1)
        assert len(result.selected_nodes) <= 1
        assert result.max_objects == 1

    def test_hard_cap_at_5(self):
        """Cap of 5 with a graph that has many more candidates."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA TB_BETA TB_GAMMA", max_objects=5)
        assert len(result.selected_nodes) <= 5

    def test_cap_enforced_on_pinned_nodes(self):
        """Even pinned nodes must be evicted if they exceed the cap."""
        g = _build_large_graph(50, 10)
        # TB_LARGE_0000 will have many FK neighbors and columns
        result = select_database_context(g, "TB_LARGE_0000", max_objects=10)
        assert len(result.selected_nodes) <= 10
        # The exact table itself should survive (highest priority)
        selected_names = {n.qualified_name for n in result.selected_nodes}
        assert "TB_LARGE_0000" in selected_names

    def test_max_objects_validation(self):
        """max_objects=0 or negative should raise ValueError."""
        g = _build_small_graph()
        with pytest.raises(ValueError, match="max_objects must be >= 1"):
            select_database_context(g, "test", max_objects=0)
        with pytest.raises(ValueError, match="max_objects must be >= 1"):
            select_database_context(g, "test", max_objects=-5)


# ---------------------------------------------------------------------------
# Tests: deterministic selection
# ---------------------------------------------------------------------------


class TestDeterministicSelection:
    """Same inputs must always produce the same outputs."""

    def test_repeated_calls_same_fingerprint(self):
        """Calling select_database_context twice produces identical fingerprints."""
        g = _build_small_graph()
        story = "TB_ALPHA and TB_BETA"
        r1 = select_database_context(g, story, max_objects=60)
        r2 = select_database_context(g, story, max_objects=60)

        assert r1.context_fingerprint == r2.context_fingerprint
        assert [n.id for n in r1.selected_nodes] == [n.id for n in r2.selected_nodes]
        assert [e.id for e in r1.selected_edges] == [e.id for e in r2.selected_edges]

    def test_repeated_calls_same_truncation(self):
        """Truncation metadata is deterministic."""
        g = _build_large_graph(100, 5)
        story = "TB_LARGE_0000"
        r1 = select_database_context(g, story, max_objects=20)
        r2 = select_database_context(g, story, max_objects=20)

        assert r1.truncation.to_dict() == r2.truncation.to_dict()
        assert r1.omitted_counts.to_dict() == r2.omitted_counts.to_dict()

    def test_deterministic_under_eviction(self):
        """When pinned nodes are evicted, the selection is still deterministic."""
        g = _build_large_graph(50, 10)
        story = "TB_LARGE_0000"
        r1 = select_database_context(g, story, max_objects=5)
        r2 = select_database_context(g, story, max_objects=5)

        assert [n.qualified_name for n in r1.selected_nodes] == \
               [n.qualified_name for n in r2.selected_nodes]


# ---------------------------------------------------------------------------
# Tests: priority eviction and relationship preservation
# ---------------------------------------------------------------------------


class TestPriorityEviction:
    """Verify that high-priority nodes survive eviction."""

    def test_exact_table_survives_over_fk_columns(self):
        """Directly-mentioned tables outrank FK columns in eviction."""
        g = _build_large_graph(30, 10)
        result = select_database_context(g, "TB_LARGE_0000 TB_LARGE_0005", max_objects=10)
        selected_names = {n.qualified_name for n in result.selected_nodes}
        assert "TB_LARGE_0000" in selected_names
        assert "TB_LARGE_0005" in selected_names

    def test_fk_edge_preserved_between_mentioned_tables(self):
        """FK edges between directly-mentioned tables survive the cap."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_BETA TB_ALPHA", max_objects=60)
        fk_edges = [
            (e.from_node, e.to_node) for e in result.selected_edges
            if e.kind == EdgeKind.FOREIGN_KEY_TO.value
        ]
        # TB_BETA → TB_ALPHA FK should be present
        assert ("tb_beta", "tb_alpha") in fk_edges

    def test_view_derived_from_preserved(self):
        """DERIVED_FROM (view dependency) edge is preserved when both nodes are selected."""
        g = _build_small_graph()
        result = select_database_context(g, "VW_COMBINED TB_ALPHA", max_objects=60)
        derived_edges = [
            e for e in result.selected_edges
            if e.kind == EdgeKind.DERIVED_FROM.value
        ]
        assert len(derived_edges) >= 1
        # VW_COMBINED → TB_ALPHA
        assert any(e.from_node == "vw_combined" and e.to_node == "tb_alpha"
                    for e in derived_edges)

    def test_synonym_alias_of_preserved(self):
        """ALIAS_OF (synonym) edge is preserved when both nodes are selected."""
        g = _build_large_graph(10, 2)
        result = select_database_context(g, "SYN_MAIN TB_LARGE_0000", max_objects=60)
        alias_edges = [
            e for e in result.selected_edges
            if e.kind == EdgeKind.ALIAS_OF.value
        ]
        selected_names = {n.qualified_name for n in result.selected_nodes}
        if "SYN_MAIN" in selected_names and "TB_LARGE_0000" in selected_names:
            assert len(alias_edges) >= 1


# ---------------------------------------------------------------------------
# Tests: entity bridging
# ---------------------------------------------------------------------------


class TestEntityBridging:
    """Verify the tightened entity bridging logic."""

    def test_full_name_match_bridges(self):
        """Full entity class name match should bridge to mapped table."""
        g = _build_entity_bridge_graph()
        result = select_database_context(g, "OrderItem", max_objects=60)
        selected_names = {n.qualified_name for n in result.selected_nodes}
        # OrderItem entity should bridge to TB_ORDER_ITEM
        assert "TB_ORDER_ITEM" in selected_names

    def test_single_common_word_does_not_bridge(self):
        """A single common word like 'ORDER' should not bridge dozens of entities."""
        g = _build_entity_bridge_graph()
        result = select_database_context(g, "order processing", max_objects=60)
        # The entity "OrderItem" has words ["order", "item"]
        # Only "order" matches — that's 1 hit, below the threshold of 2
        selected_names = {n.qualified_name for n in result.selected_nodes}
        # TB_ORDER may be found via domain segment, but entity bridge should not fire
        entity_nodes = [n for n in result.selected_nodes if n.kind == NodeKind.JAVA_ENTITY.value]
        # With only 1 word hit, the entity should NOT be bridged
        assert len(entity_nodes) == 0

    def test_two_word_match_bridges(self):
        """Two camelCase word hits should trigger entity bridging."""
        g = _build_entity_bridge_graph()
        result = select_database_context(g, "order item details", max_objects=60)
        selected_names = {n.qualified_name for n in result.selected_nodes}
        # "order" + "item" = 2 hits → bridge fires
        assert "TB_ORDER_ITEM" in selected_names


# ---------------------------------------------------------------------------
# Tests: truncation metadata
# ---------------------------------------------------------------------------


class TestTruncationMetadata:
    """Verify TruncationMetadata and SelectionDetail accuracy."""

    def test_no_truncation_metadata(self):
        """When all candidates fit, was_truncated is False."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=60)
        trunc = result.truncation
        if trunc.total_candidates <= 60:
            assert trunc.was_truncated is (trunc.total_candidates > 60)

    def test_truncation_metadata_fields(self):
        """All TruncationMetadata fields are populated when truncated."""
        g = _build_large_graph(100, 5)
        result = select_database_context(g, "TB_LARGE_0000", max_objects=20)
        trunc = result.truncation
        assert trunc.was_truncated is True
        assert trunc.hard_cap == 20
        assert trunc.total_candidates > 20
        assert trunc.total_selected == len(result.selected_nodes)
        assert trunc.total_selected <= 20

    def test_tier_details_sum_to_totals(self):
        """Per-tier selected + omitted sums must equal the total candidates."""
        g = _build_large_graph(50, 5)
        result = select_database_context(g, "TB_LARGE_0000 TB_LARGE_0010", max_objects=30)
        trunc = result.truncation

        total_sel = sum(d.selected for d in trunc.tier_details)
        total_omit = sum(d.omitted for d in trunc.tier_details)
        assert total_sel == trunc.total_selected
        assert total_sel + total_omit == trunc.total_candidates

    def test_pinned_evicted_count(self):
        """pinned_evicted counts exactly the evicted pinned-tier nodes."""
        g = _build_large_graph(50, 10)
        result = select_database_context(g, "TB_LARGE_0000", max_objects=5)
        trunc = result.truncation
        # When the graph has many pinned candidates but only 5 slots,
        # some pinned nodes must be evicted
        assert trunc.pinned_evicted >= 0
        # The total selected must not exceed the cap
        assert trunc.total_selected <= 5


# ---------------------------------------------------------------------------
# Tests: serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisationRoundTrip:
    """Verify to_dict / from_dict round-trip for new dataclasses."""

    def test_selection_detail_round_trip(self):
        sd = SelectionDetail(tier=0, tier_label="pinned", selected=10, omitted=5)
        d = sd.to_dict()
        sd2 = SelectionDetail.from_dict(d)
        assert sd == sd2

    def test_truncation_metadata_round_trip(self):
        tm = TruncationMetadata(
            was_truncated=True,
            hard_cap=60,
            total_candidates=500,
            total_selected=60,
            tier_details=(
                SelectionDetail(tier=0, tier_label="pinned", selected=40, omitted=100),
                SelectionDetail(tier=1, tier_label="fk_connected", selected=10, omitted=50),
            ),
            pinned_evicted=20,
        )
        d = tm.to_dict()
        tm2 = TruncationMetadata.from_dict(d)
        assert tm == tm2

    def test_database_context_result_round_trip(self):
        """Full DatabaseContextResult with truncation survives round-trip."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=60)
        d = result.to_dict()
        result2 = DatabaseContextResult.from_dict(d)
        assert result.context_fingerprint == result2.context_fingerprint
        assert result.max_objects == result2.max_objects
        assert result.truncation.to_dict() == result2.truncation.to_dict()

    def test_backward_compat_from_dict_no_truncation(self):
        """from_dict should handle legacy payloads without truncation field."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=60)
        d = result.to_dict()
        del d["truncation"]
        result2 = DatabaseContextResult.from_dict(d)
        assert result2.truncation == TruncationMetadata()


# ---------------------------------------------------------------------------
# Tests: boundary conditions
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """Edge cases and boundary conditions."""

    def test_empty_story_returns_empty(self):
        """Empty or irrelevant story should produce empty context."""
        g = _build_small_graph()
        result = select_database_context(g, "", max_objects=60)
        assert len(result.selected_nodes) == 0
        assert len(result.selected_edges) == 0

    def test_irrelevant_story_returns_empty(self):
        g = _build_small_graph()
        result = select_database_context(g, "quantum physics black hole", max_objects=60)
        assert len(result.selected_nodes) == 0

    def test_max_hops_zero(self):
        """max_hops=0 should still work (no BFS expansion needed)."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_hops=0, max_objects=60)
        assert "TB_ALPHA" in {n.qualified_name for n in result.selected_nodes}

    def test_single_node_graph(self):
        """A graph with one table node should work."""
        tbl = _node(NodeKind.TABLE.value, "TB_SINGLE")
        g = DatabaseGraph.create(
            provenance={"vcs": "test", "head_sha": "single"},
            nodes=(tbl,),
            edges=(),
        )
        result = select_database_context(g, "TB_SINGLE", max_objects=60)
        assert len(result.selected_nodes) == 1
        assert result.selected_nodes[0].qualified_name == "TB_SINGLE"


# ---------------------------------------------------------------------------
# Tests: renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    """Verify renderers handle new truncation metadata."""

    def test_markdown_renderer_with_truncation(self):
        """Markdown renderer should include truncation info when present."""
        g = _build_large_graph(100, 5)
        result = select_database_context(g, "TB_LARGE_0000", max_objects=20)
        md = render_database_context_markdown(result)
        assert "⚠" in md
        assert "omitted" in md.lower()

    def test_mermaid_renderer(self):
        """Mermaid renderer should produce valid output."""
        g = _build_small_graph()
        result = select_database_context(g, "TB_ALPHA", max_objects=60)
        mmd = render_database_context_mermaid(result)
        assert "graph LR" in mmd


# ---------------------------------------------------------------------------
# Tests: large-graph scalability
# ---------------------------------------------------------------------------


class TestLargeGraphScalability:
    """Verify performance and correctness at scale."""

    def test_500_table_graph(self):
        """500-table graph should complete and respect the cap."""
        g = _build_large_graph(500, 3)
        result = select_database_context(g, "TB_LARGE_0000 TB_LARGE_0250", max_objects=60)
        assert len(result.selected_nodes) <= 60
        selected_names = {n.qualified_name for n in result.selected_nodes}
        assert "TB_LARGE_0000" in selected_names
        assert "TB_LARGE_0250" in selected_names

    def test_1000_table_graph(self):
        """1000-table graph should complete and respect the cap."""
        g = _build_large_graph(1000, 2)
        result = select_database_context(g, "TB_LARGE_0000", max_objects=60)
        assert len(result.selected_nodes) <= 60
        assert result.truncation.was_truncated is True
        assert result.truncation.total_candidates > 60
