"""Rule selection services."""

from __future__ import annotations

from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)
from moughorai.rules.repository import RuleRepository
from moughorai.search import DocumentScorer
from moughorai.search.retriever import DocumentRetriever


class RuleSelector(
    DocumentRetriever[
        RuleDocument,
        RuleContext,
    ]
):
    """Select the most relevant rules for one request."""

    def __init__(
        self,
        repository: RuleRepository,
        scorer: DocumentScorer | None = None,
    ) -> None:
        super().__init__(
            loader=repository.load,
            documents=lambda context: list(context.documents),
            build_context=lambda documents: RuleContext(
                documents=tuple(documents),
            ),
            get_path=lambda document: document.path,
            get_content=lambda document: document.content,
            scorer=scorer,
        )