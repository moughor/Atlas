"""Knowledge repository."""

from __future__ import annotations

from moughorai.knowledge.knowledge_loader import KnowledgeLoader
from moughorai.models.knowledge import KnowledgeContext


class KnowledgeRepository:
    """Caches knowledge loaded from disk."""

    def __init__(
        self,
        loader: KnowledgeLoader,
    ) -> None:
        self._loader = loader
        self._knowledge: KnowledgeContext | None = None

    def load(self) -> KnowledgeContext:
        """Return cached knowledge."""

        if self._knowledge is None:
            self._knowledge = self._loader.load()

        return self._knowledge

    def reload(self) -> KnowledgeContext:
        """Reload knowledge from disk."""

        self._knowledge = self._loader.load()
        return self._knowledge