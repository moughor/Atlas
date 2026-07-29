"""Immutable retrieval and LLM-context models."""
from __future__ import annotations

from dataclasses import dataclass

from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeNode


@dataclass(frozen=True)
class RetrievalHit:
    node: KnowledgeNode
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    hits: tuple[RetrievalHit, ...] = ()
    related_nodes: tuple[KnowledgeNode, ...] = ()
    evidence_edges: tuple[KnowledgeEdge, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True)
class LlmContext:
    query: str
    text: str
    node_keys: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
