"""Load structured knowledge documents from the local workspace."""

from pathlib import Path
from typing import ClassVar

from moughorai.loaders.document_loader import DocumentLoader
from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)


class KnowledgeLoaderError(RuntimeError):
    """Raised when a knowledge document cannot be loaded."""


class KnowledgeLoader(
    DocumentLoader[
        KnowledgeDocument,
        KnowledgeContext,
    ]
):
    """Load Markdown knowledge documents from local directories."""

    SUBJECT: ClassVar[str] = "Knowledge"

    LOADER_ERROR: ClassVar[type[RuntimeError]] = (
        KnowledgeLoaderError
    )

    def _create_document(
        self,
        *,
        name: str,
        path: Path,
        category: str,
        content: str,
    ) -> KnowledgeDocument:
        return KnowledgeDocument(
            name=name,
            path=path,
            category=category,
            content=content,
        )

    def _create_context(
        self,
        documents: tuple[KnowledgeDocument, ...],
    ) -> KnowledgeContext:
        return KnowledgeContext(
            documents=documents,
        )