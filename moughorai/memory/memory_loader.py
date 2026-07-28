"""Load structured memory documents from the local workspace."""

from pathlib import Path
from typing import ClassVar

from moughorai.loaders.document_loader import DocumentLoader
from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)


class MemoryLoaderError(RuntimeError):
    """Raised when a memory document cannot be loaded."""


class MemoryLoader(
    DocumentLoader[
        MemoryDocument,
        MemoryContext,
    ]
):
    """Load Markdown memory documents from local directories."""

    SUBJECT: ClassVar[str] = "Memory"

    LOADER_ERROR: ClassVar[type[RuntimeError]] = (
        MemoryLoaderError
    )

    def _create_document(
        self,
        *,
        name: str,
        path: Path,
        category: str,
        content: str,
    ) -> MemoryDocument:
        """Create one typed memory document."""
        return MemoryDocument(
            name=name,
            path=path,
            category=category,
            content=content,
        )

    def _create_context(
        self,
        documents: tuple[MemoryDocument, ...],
    ) -> MemoryContext:
        """Create one typed memory context."""
        return MemoryContext(
            documents=documents,
        )