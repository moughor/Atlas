"""Deterministic retrieval over the enterprise Java knowledge graph."""
from __future__ import annotations

import re
from collections import OrderedDict

from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_retrieval.models import RetrievalHit, RetrievalResult

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/#-]*")


class JavaKnowledgeRetriever:
    """Rank graph nodes and expand their local evidence neighbourhood."""

    def retrieve(
        self,
        graph: JavaKnowledgeGraph,
        query: str,
        *,
        limit: int = 8,
        include_related: bool = True,
    ) -> RetrievalResult:
        tokens = tuple(dict.fromkeys(token.casefold() for token in _TOKEN_RE.findall(query)))
        hits: list[RetrievalHit] = []

        for node in graph.nodes:
            score, reasons = self._score(node, query.casefold(), tokens)
            if score > 0:
                hits.append(RetrievalHit(node, score, tuple(reasons)))

        hits.sort(key=lambda hit: (-hit.score, hit.node.key.casefold()))
        selected = tuple(hits[: max(0, limit)])
        selected_keys = {hit.node.key for hit in selected}

        related: OrderedDict[str, KnowledgeNode] = OrderedDict()
        evidence = []
        if include_related:
            for hit in selected:
                for edge in (*graph.outgoing(hit.node.key), *graph.incoming(hit.node.key)):
                    evidence.append(edge)
                    other_key = edge.target if edge.source == hit.node.key else edge.source
                    if other_key not in selected_keys:
                        other = graph.node(other_key)
                        if other is not None:
                            related.setdefault(other.key, other)

        # Preserve deterministic edge order while removing duplicates.
        unique_edges = tuple(dict.fromkeys(evidence))
        unresolved = tuple(
            item for item in graph.unresolved
            if any(item.startswith(f"{key}:") or item.startswith(f"{key}#") for key in selected_keys)
        )
        return RetrievalResult(query, selected, tuple(related.values()), unique_edges, unresolved)

    def _score(self, node: KnowledgeNode, normalized_query: str, tokens: tuple[str, ...]) -> tuple[float, list[str]]:
        key = node.key.casefold()
        display = node.display_name.casefold()
        qualified = (node.qualified_name or "").casefold()
        facets = tuple(facet.casefold() for facet in node.facets)
        metadata = tuple(f"{name}:{value}".casefold() for name, value in node.metadata)
        score = 0.0
        reasons: list[str] = []

        if normalized_query and normalized_query in {key, display, qualified}:
            score += 100.0
            reasons.append("exact-name")
        elif normalized_query and (normalized_query in key or normalized_query in display or normalized_query in qualified):
            score += 45.0
            reasons.append("name-contains-query")

        for token in tokens:
            if token == display or token == qualified or token == key:
                score += 35.0
                reasons.append(f"exact-token:{token}")
            elif token in display or token in qualified or token in key:
                score += 12.0
                reasons.append(f"name-token:{token}")
            if any(token in facet for facet in facets):
                score += 8.0
                reasons.append(f"facet:{token}")
            if any(token in item for item in metadata):
                score += 5.0
                reasons.append(f"metadata:{token}")

        if node.kind is KnowledgeNodeKind.TYPE:
            score += 0.1
        return score, list(dict.fromkeys(reasons))
