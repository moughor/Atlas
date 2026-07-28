"""High-level retrieval facade for LLM consumers."""
from __future__ import annotations

from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_retrieval.context_builder import JavaLlmContextBuilder
from moughorai.java_retrieval.models import LlmContext, RetrievalResult
from moughorai.java_retrieval.retriever import JavaKnowledgeRetriever


class JavaRetrievalService:
    def __init__(
        self,
        retriever: JavaKnowledgeRetriever | None = None,
        context_builder: JavaLlmContextBuilder | None = None,
    ) -> None:
        self._retriever = retriever or JavaKnowledgeRetriever()
        self._context_builder = context_builder or JavaLlmContextBuilder()

    def retrieve(self, graph: JavaKnowledgeGraph, query: str, *, limit: int = 8) -> RetrievalResult:
        return self._retriever.retrieve(graph, query, limit=limit)

    def context(self, graph: JavaKnowledgeGraph, query: str, *, limit: int = 8, max_characters: int = 12000) -> LlmContext:
        result = self.retrieve(graph, query, limit=limit)
        return self._context_builder.build(result, max_characters=max_characters)
