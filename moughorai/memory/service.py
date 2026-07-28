"""Memory loading service."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from moughorai.config import AppConfig
from moughorai.memory.memory_loader import MemoryLoader
from moughorai.memory.repository import MemoryRepository
from moughorai.memory.retriever import MemoryRetriever
from moughorai.models.memory import MemoryContext


class _MemoryContextLoader(Protocol):
    """Loader interface required by MemoryRepository."""

    def load(self) -> MemoryContext:
        """Load a memory context."""


class _BoundMemoryLoader:
    """Bind a MemoryLoader to one project memory directory."""

    def __init__(
        self,
        loader: MemoryLoader,
        path: Path,
        *,
        category: str,
    ) -> None:
        self._loader = loader
        self._path = path
        self._category = category

    def load(self) -> MemoryContext:
        """Load memory from the bound directory."""

        return self._loader.load(
            self._path,
            category=self._category,
        )


class MemoryService:
    """Load project memory for one request."""

    def __init__(
        self,
        config: AppConfig,
        loader: MemoryLoader,
        retriever: MemoryRetriever | None = None,
    ) -> None:
        self.config = config
        self.loader = loader
        self.retriever = retriever

    def load(
        self,
        *,
        query: str = "",
        project: Path | None = None,
    ) -> MemoryContext:
        """Load relevant project memory with a full-memory fallback."""

        if project is None:
            return MemoryContext()

        project_memory_path = (
            self.config.paths.projects
            / project.name
            / "memory"
        )

        resolved_project_memory_path = self._resolve_workspace_path(
            project_memory_path,
        )

        if not resolved_project_memory_path.is_dir():
            return MemoryContext()

        if self.retriever is not None:
            retrieved_memory = self.retriever.retrieve(query)

            if retrieved_memory.documents:
                return retrieved_memory

            repository = getattr(
                self.retriever,
                "_repository",
                None,
            )

            if repository is not None:
                return repository.load()

            return retrieved_memory

        bound_loader: _MemoryContextLoader = _BoundMemoryLoader(
            self.loader,
            project_memory_path,
            category="memory",
        )

        repository = MemoryRepository(bound_loader)

        if not query.strip():
            return repository.load()

        retriever = MemoryRetriever(repository)
        retrieved_memory = retriever.retrieve(query)

        if retrieved_memory.documents:
            return retrieved_memory

        return repository.load()

    def _resolve_workspace_path(
        self,
        path: Path,
    ) -> Path:
        """Resolve a path relative to the configured workspace."""

        if path.is_absolute():
            return path.resolve()

        return (
            self.config.workspace_root
            / path
        ).resolve()