"""Build compact, source-aware LLM context from deterministic retrieval results."""
from __future__ import annotations

from moughorai.java_knowledge.models import KnowledgeNode
from moughorai.java_retrieval.models import LlmContext, RetrievalResult


class JavaLlmContextBuilder:
    def build(self, result: RetrievalResult, *, max_characters: int = 12000) -> LlmContext:
        lines: list[str] = [f"QUERY: {result.query}", "", "PRIMARY SYMBOLS:"]
        keys: list[str] = []

        for index, hit in enumerate(result.hits, start=1):
            node = hit.node
            keys.append(node.key)
            lines.extend(self._node_lines(f"S{index}", node, f"score={hit.score:.1f}; reasons={','.join(hit.reasons)}"))

        if result.related_nodes:
            lines.extend(("", "RELATED SYMBOLS:"))
            for index, node in enumerate(result.related_nodes, start=1):
                keys.append(node.key)
                lines.extend(self._node_lines(f"R{index}", node))

        if result.evidence_edges:
            lines.extend(("", "RELATIONSHIPS:"))
            for index, edge in enumerate(result.evidence_edges, start=1):
                role = f"; role={edge.role}" if edge.role else ""
                lines.append(f"[E{index}] {edge.source} --{edge.kind.value}--> {edge.target}{role}")

        if result.unresolved:
            lines.extend(("", "UNRESOLVED REFERENCES:"))
            lines.extend(f"- {item}" for item in result.unresolved)

        text = "\n".join(lines)
        if len(text) > max_characters:
            marker = "\n...[context truncated deterministically]"
            text = text[: max(0, max_characters - len(marker))].rstrip() + marker

        return LlmContext(result.query, text, tuple(dict.fromkeys(keys)), result.unresolved)

    def _node_lines(self, evidence_id: str, node: KnowledgeNode, extra: str = "") -> list[str]:
        parts = [f"[{evidence_id}] {node.kind.value}: {node.key}"]
        if node.facets:
            parts.append(f"facets={','.join(node.facets)}")
        if node.source is not None:
            parts.append(f"source={node.source}")
        if node.metadata:
            parts.append("metadata=" + ",".join(f"{key}={value}" for key, value in node.metadata))
        if extra:
            parts.append(extra)
        return ["; ".join(parts)]
