"""Memory retrieval services."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.memory.repository import MemoryRepository
from moughorai.memory.scorer import MemoryScorer
from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)


@dataclass(frozen=True)
class ScoredMemory:
    """A memory document together with its relevance score."""

    document: MemoryDocument
    score: int


class MemoryRetriever:
    """Retrieves the most relevant memory documents."""

    def __init__(
        self,
        repository: MemoryRepository,
        scorer: MemoryScorer | None = None,
    ) -> None:
        self._repository = repository
        self._scorer = scorer or MemoryScorer()

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> MemoryContext:
        """Return the most relevant memory documents."""

        memory = self._repository.load()

        scored: list[ScoredMemory] = []

        for document in memory.documents:
            score = self._scorer.score(
                query,
                path=document.path,
                content=document.content,
            )

            if score > 0:
                scored.append(
                    ScoredMemory(
                        document=document,
                        score=score,
                    )
                )

        scored.sort(
            key=lambda item: item.score,
            reverse=True,
        )

        return MemoryContext(
            documents=[
                item.document
                for item in scored[:limit]
            ]
        )