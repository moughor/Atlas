"""Phase C public-path E2E tests for natural-language context selection.

These tests verify that the context selector works through the documented
public API with:

  - natural-language story input (no explicit table names)
  - max_hops=3, max_objects=60
  - serialized context output (to_dict / from_dict round-trip)
  - synthetic graphs with JPA entities, FK relationships, views, and columns

The tests model the five failure categories identified in the diagnostic matrix:

  1. Entity-bridged table retrieval from domain phrases
  2. FK-chain relationship expansion
  3. View/MV dependency traversal
  4. Budget eviction with table-first priority
  5. Deterministic serialization round-trip

No pack case IDs, story strings, or Sygma table names appear in this file.
"""

from __future__ import annotations

import json

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
    select_database_context,
    render_database_context_markdown,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERIFIED = EvidenceRecord.verified()
_eid = 0


def _n(kind: str, qname: str, **props) -> DatabaseGraphNode:
    prop_tuples = tuple(sorted(props.items()))
    return DatabaseGraphNode(
        id=qname.lower().replace(".", "_"),
        kind=kind,
        qualified_name=qname,
        properties=prop_tuples,
        evidence=_VERIFIED,
    )


def _e(kind: str, from_id: str, to_id: str, **props) -> DatabaseGraphEdge:
    global _eid
    _eid += 1
    prop_tuples = tuple(sorted(props.items()))
    return DatabaseGraphEdge(
        id=f"e2e_{_eid}",
        kind=kind,
        from_node=from_id,
        to_node=to_id,
        properties=prop_tuples,
        evidence=_VERIFIED,
    )


def _col(table: str, col: str) -> DatabaseGraphNode:
    return _n(NodeKind.COLUMN.value, f"{table}.{col}")


def _make_enterprise_graph() -> DatabaseGraph:
    """Synthetic graph modelling an enterprise domain with entities, views, FKs.

    Domain: order management with customers, products, reviews, and reports.

    Tables:
      TB_ORD_ORDER(ID, CUSTOMER_ID, STATUS)
      TB_ORD_ORDER_ITEM(ID, ORDER_ID, PRODUCT_ID, QUANTITY)
      TB_APP_CUSTOMER(ID, NAME, EMAIL)
      TB_APP_PRODUCT(ID, SKU, CATEGORY)
      TB_ORD_ORDER_REVIEW(ID, ORDER_ID, RATING, COMMENT)
      VW_ORDER_SUMMARY (view, derived from TB_ORD_ORDER + TB_APP_CUSTOMER)

    Entities:
      com.example.order.Order → TB_ORD_ORDER
      com.example.order.OrderItem → TB_ORD_ORDER_ITEM
      com.example.order.OrderReview → TB_ORD_ORDER_REVIEW
      com.example.customer.Customer → TB_APP_CUSTOMER

    FKs:
      TB_ORD_ORDER_ITEM.ORDER_ID → TB_ORD_ORDER.ID
      TB_ORD_ORDER.CUSTOMER_ID → TB_APP_CUSTOMER.ID
      TB_ORD_ORDER_ITEM.PRODUCT_ID → TB_APP_PRODUCT.ID
      TB_ORD_ORDER_REVIEW.ORDER_ID → TB_ORD_ORDER.ID

    Plus 100 distractor tables to test budget eviction.
    """
    nodes = []
    edges = []

    # Core tables
    for tbl, cols in [
        ("TB_ORD_ORDER", ["ID", "CUSTOMER_ID", "STATUS"]),
        ("TB_ORD_ORDER_ITEM", ["ID", "ORDER_ID", "PRODUCT_ID", "QUANTITY"]),
        ("TB_APP_CUSTOMER", ["ID", "NAME", "EMAIL"]),
        ("TB_APP_PRODUCT", ["ID", "SKU", "CATEGORY"]),
        ("TB_ORD_ORDER_REVIEW", ["ID", "ORDER_ID", "RATING", "COMMENT"]),
    ]:
        nodes.append(_n(NodeKind.TABLE.value, tbl))
        for c in cols:
            nodes.append(_col(tbl, c))
            edges.append(_e(EdgeKind.HAS_COLUMN.value, tbl.lower().replace(".", "_"), f"{tbl}.{c}".lower().replace(".", "_")))

    # View
    nodes.append(_n(NodeKind.VIEW.value, "VW_ORDER_SUMMARY"))
    edges.append(_e(EdgeKind.DERIVED_FROM.value, "vw_order_summary", "tb_ord_order"))
    edges.append(_e(EdgeKind.DERIVED_FROM.value, "vw_order_summary", "tb_app_customer"))

    # Entities
    for ent, tbl in [
        ("com.example.order.Order", "TB_ORD_ORDER"),
        ("com.example.order.OrderItem", "TB_ORD_ORDER_ITEM"),
        ("com.example.order.OrderReview", "TB_ORD_ORDER_REVIEW"),
        ("com.example.customer.Customer", "TB_APP_CUSTOMER"),
    ]:
        nodes.append(_n(NodeKind.JAVA_ENTITY.value, ent))
        edges.append(_e(EdgeKind.MAPS_TO_TABLE.value, ent.lower().replace(".", "_"), tbl.lower().replace(".", "_")))

    # FKs with source_table/target_table properties
    fk_pairs = [
        ("TB_ORD_ORDER_ITEM", "ORDER_ID", "TB_ORD_ORDER", "ID"),
        ("TB_ORD_ORDER", "CUSTOMER_ID", "TB_APP_CUSTOMER", "ID"),
        ("TB_ORD_ORDER_ITEM", "PRODUCT_ID", "TB_APP_PRODUCT", "ID"),
        ("TB_ORD_ORDER_REVIEW", "ORDER_ID", "TB_ORD_ORDER", "ID"),
    ]
    for src_t, src_c, tgt_t, tgt_c in fk_pairs:
        edges.append(_e(
            EdgeKind.FOREIGN_KEY_TO.value,
            src_t.lower().replace(".", "_"),
            tgt_t.lower().replace(".", "_"),
            source_table=src_t, target_table=tgt_t,
            source_column=src_c, target_column=tgt_c,
        ))

    # 100 distractor tables
    for i in range(100):
        name = f"TB_DIST_{i:03d}"
        nodes.append(_n(NodeKind.TABLE.value, name))
        for c in ["ID", "DATA"]:
            nodes.append(_col(name, c))
            edges.append(_e(EdgeKind.HAS_COLUMN.value, name.lower(), f"{name}.{c}".lower().replace(".", "_")))

    return DatabaseGraph.create(
        provenance={"vcs": "test", "head_sha": "e2e_synthetic"},
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


# ---------------------------------------------------------------------------
# Tests: Natural-language entity bridging
# ---------------------------------------------------------------------------


class TestNaturalLanguageEntityBridging:
    """Entity class names resolve to tables from domain phrases."""

    def test_order_item_from_domain_phrase(self):
        """'order item quantity' should find TB_ORD_ORDER_ITEM via OrderItem entity."""
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "check the order item quantity for this shipment", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_ORD_ORDER_ITEM" in sel

    def test_customer_from_domain_phrase(self):
        """'customer email address' should find TB_APP_CUSTOMER via Customer entity."""
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "retrieve the customer email address for verification", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_APP_CUSTOMER" in sel

    def test_order_review_from_paraphrased_story(self):
        """Paraphrased story about reviews should find TB_ORD_ORDER_REVIEW."""
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "a review rating is incorrect for one order, investigate the review comments", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_ORD_ORDER_REVIEW" in sel


# ---------------------------------------------------------------------------
# Tests: FK chain expansion
# ---------------------------------------------------------------------------


class TestFkChainExpansion:
    """FK neighbors of matched tables should be included."""

    def test_order_brings_customer_via_fk(self):
        """Matching Order should include Customer via FK(CUSTOMER_ID→ID)."""
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "an order has wrong status, check the order details", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_ORD_ORDER" in sel
        # Customer should be reachable via FK
        assert "TB_APP_CUSTOMER" in sel


# ---------------------------------------------------------------------------
# Tests: Budget eviction with distractor tables
# ---------------------------------------------------------------------------


class TestBudgetEviction:
    """Required tables survive eviction in a graph with many distractors."""

    def test_cap_at_60_with_distractors(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "order item quantity is wrong", max_hops=3, max_objects=60)
        assert len(ctx.selected_nodes) <= 60
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_ORD_ORDER_ITEM" in sel

    def test_deterministic_repeated_selection(self):
        g = _make_enterprise_graph()
        s = "check order item quantity"
        r1 = select_database_context(g, s, max_hops=3, max_objects=60)
        r2 = select_database_context(g, s, max_hops=3, max_objects=60)
        assert r1.context_fingerprint == r2.context_fingerprint


# ---------------------------------------------------------------------------
# Tests: Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    """Public context output survives to_dict / from_dict."""

    def test_full_round_trip(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "order item details", max_hops=3, max_objects=60)
        d = ctx.to_dict()
        ctx2 = DatabaseContextResult.from_dict(d)
        assert ctx.context_fingerprint == ctx2.context_fingerprint
        assert ctx.max_objects == ctx2.max_objects
        assert len(ctx.selected_nodes) == len(ctx2.selected_nodes)

    def test_json_serializable(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "customer email", max_hops=3, max_objects=60)
        d = ctx.to_dict()
        j = json.dumps(d, ensure_ascii=False, sort_keys=True)
        d2 = json.loads(j)
        assert d2["context_fingerprint"] == d["context_fingerprint"]


# ---------------------------------------------------------------------------
# Tests: Plural/singular variation
# ---------------------------------------------------------------------------


class TestPluralSingularVariation:
    """Stories with plural/singular variations match entity names."""

    def test_reviews_matches_review(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "the reviews for orders are missing ratings", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_ORD_ORDER_REVIEW" in sel

    def test_customers_matches_customer(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "list all customers with their names", max_hops=3, max_objects=60)
        sel = {n.qualified_name for n in ctx.selected_nodes if n.kind in ("table", "view", "materialized_view")}
        assert "TB_APP_CUSTOMER" in sel


# ---------------------------------------------------------------------------
# Tests: Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRendering:
    """Public markdown renderer handles natural-language results."""

    def test_render_produces_markdown(self):
        g = _make_enterprise_graph()
        ctx = select_database_context(g, "order item quantity", max_hops=3, max_objects=60)
        md = render_database_context_markdown(ctx)
        assert "# Database Context" in md
        assert "nodes selected" in md
