"""Memory repository."""

from __future__ import annotations

from moughorai.memory.memory_loader import MemoryLoader
from moughorai.models.memory import MemoryContext


class MemoryRepository:
    """Caches project memory for retrieval."""

    def __init__(
        self,
        loader: MemoryLoader,
    ) -> None:
        self._loader = loader
        self._memory: MemoryContext | None = None

    def load(self) -> MemoryContext:
        """Return cached memory, loading it when necessary."""

        if self._memory is None:
            self._memory = self._loader.load()

        return self._memory

    def reload(self) -> MemoryContext:
        """Reload memory from the underlying loader."""

        self._memory = self._loader.load()
        return self._memory