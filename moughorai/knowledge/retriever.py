"""Knowledge retrieval services."""

from __future__ import annotations

from moughorai.knowledge.repository import KnowledgeRepository
from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)
from moughorai.search import DocumentScorer
from moughorai.search.retriever import DocumentRetriever


class KnowledgeRetriever(
    DocumentRetriever[
        KnowledgeDocument,
        KnowledgeContext,
    ]
):
    """Retrieve the most relevant knowledge documents."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        scorer: DocumentScorer | None = None,
    ) -> None:
        super().__init__(
            loader=repository.load,
            documents=lambda context: list(context.documents),
            build_context=lambda documents: KnowledgeContext(
                documents=tuple(documents),
            ),
            get_path=lambda document: document.path,
            get_content=lambda document: document.content,
            scorer=scorer,
        )