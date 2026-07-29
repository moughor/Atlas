"""Generic document retrieval services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar

from moughorai.search.scorer import DocumentScorer

TDocument = TypeVar("TDocument")
TContext = TypeVar("TContext")


@dataclass(frozen=True)
class ScoredDocument(Generic[TDocument]):
    """A document together with its relevance score."""

    document: TDocument
    score: int


class DocumentRetriever(
    Generic[
        TDocument,
        TContext,
    ]
):
    """Retrieve the most relevant documents."""

    def __init__(
        self,
        *,
        loader: Callable[[], TContext],
        documents: Callable[
            [TContext],
            list[TDocument],
        ],
        build_context: Callable[
            [list[TDocument]],
            TContext,
        ],
        get_path: Callable[
            [TDocument],
            Path,
        ],
        get_content: Callable[
            [TDocument],
            str,
        ],
        scorer: DocumentScorer | None = None,
    ) -> None:
        self._loader = loader
        self._documents = documents
        self._build_context = build_context
        self._get_path = get_path
        self._get_content = get_content
        self._scorer = scorer or DocumentScorer()

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> TContext:
        """Return the most relevant documents."""

        context = self._loader()

        scored: list[
            ScoredDocument[TDocument]
        ] = []

        for document in self._documents(context):
            score = self._scorer.score(
                query,
                path=self._get_path(document),
                content=self._get_content(document),
            )

            if score > 0:
                scored.append(
                    ScoredDocument(
                        document=document,
                        score=score,
                    )
                )

        scored.sort(
            key=lambda item: item.score,
            reverse=True,
        )

        selected_documents = [
            item.document
            for item in scored[:limit]
        ]

        return self._build_context(
            selected_documents,
        )