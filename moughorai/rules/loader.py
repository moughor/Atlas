"""Load structured rule documents from the local workspace."""

from pathlib import Path
from typing import ClassVar

from moughorai.loaders.document_loader import DocumentLoader
from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)


class RuleLoaderError(RuntimeError):
    """Raised when a rule document cannot be loaded."""


class RuleLoader(
    DocumentLoader[
        RuleDocument,
        RuleContext,
    ]
):
    """Load Markdown rule documents from local directories."""

    SUBJECT: ClassVar[str] = "Rule"

    LOADER_ERROR: ClassVar[type[RuntimeError]] = (
        RuleLoaderError
    )

    def _create_document(
        self,
        *,
        name: str,
        path: Path,
        category: str,
        content: str,
    ) -> RuleDocument:
        """Create one typed rule document."""

        return RuleDocument(
            name=name,
            path=path,
            category=category,
            content=content,
        )

    def _create_context(
        self,
        documents: tuple[RuleDocument, ...],
    ) -> RuleContext:
        """Create a typed rule context."""

        return RuleContext(
            documents=documents,
        )