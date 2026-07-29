"""Memory relevance scoring compatibility layer."""

from __future__ import annotations

from moughorai.search import DocumentScorer


class MemoryScorer(DocumentScorer):
    """Score memory documents against a natural-language query."""