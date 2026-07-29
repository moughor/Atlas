"""Tests for knowledge retrieval services."""

from pathlib import Path
from unittest.mock import Mock

from moughorai.knowledge.repository import KnowledgeRepository
from moughorai.knowledge.retriever import KnowledgeRetriever
from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)
from moughorai.search import DocumentScorer


def create_document(
    name: str,
    path: str,
    content: str,
    *,
    category: str = "project",
) -> KnowledgeDocument:
    """Create one knowledge document for testing."""

    return KnowledgeDocument(
        name=name,
        path=Path(path),
        category=category,
        content=content,
    )


def create_repository(
    *documents: KnowledgeDocument,
) -> Mock:
    """Create a mocked knowledge repository."""

    repository = Mock(spec=KnowledgeRepository)
    repository.load.return_value = KnowledgeContext(
        documents=documents,
    )

    return repository


def test_retrieve_returns_matching_document() -> None:
    """Matching knowledge should be returned."""

    database = create_document(
        name="Database",
        path="database.md",
        content="# Database\n\nUse PostgreSQL.",
    )
    testing = create_document(
        name="Testing",
        path="testing.md",
        content="# Testing\n\nUse pytest.",
    )
    repository = create_repository(
        database,
        testing,
    )

    retriever = KnowledgeRetriever(repository)

    result = retriever.retrieve("PostgreSQL")

    assert result.documents == (database,)


def test_retrieve_excludes_non_matching_documents() -> None:
    """Documents with zero relevance should be excluded."""

    database = create_document(
        name="Database",
        path="database.md",
        content="# Database\n\nUse PostgreSQL.",
    )
    testing = create_document(
        name="Testing",
        path="testing.md",
        content="# Testing\n\nUse pytest.",
    )
    repository = create_repository(
        database,
        testing,
    )

    retriever = KnowledgeRetriever(repository)

    result = retriever.retrieve("Docker")

    assert result.is_empty


def test_retrieve_ranks_documents_by_score() -> None:
    """Documents should be ordered by descending relevance."""

    filename_match = create_document(
        name="Database notes",
        path="postgresql.md",
        content="# Storage\n\nGeneral database notes.",
    )
    body_match = create_document(
        name="Architecture",
        path="architecture.md",
        content="# Architecture\n\nThe project uses PostgreSQL.",
    )
    repository = create_repository(
        body_match,
        filename_match,
    )

    retriever = KnowledgeRetriever(repository)

    result = retriever.retrieve("PostgreSQL")

    assert result.documents == (
        filename_match,
        body_match,
    )


def test_retrieve_respects_limit() -> None:
    """Only the requested number of documents should be returned."""

    first = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nPython guidance.",
    )
    second = create_document(
        name="Python testing",
        path="testing.md",
        content="# Python Testing\n\nPython tests.",
    )
    third = create_document(
        name="Project",
        path="project.md",
        content="# Project\n\nBuilt with Python.",
    )
    repository = create_repository(
        first,
        second,
        third,
    )

    retriever = KnowledgeRetriever(repository)

    result = retriever.retrieve(
        "Python",
        limit=2,
    )

    assert len(result.documents) == 2
    assert result.documents == (
        first,
        second,
    )


def test_retrieve_returns_empty_context_for_empty_query() -> None:
    """An empty query should not match any document."""

    document = create_document(
        name="Database",
        path="database.md",
        content="# Database\n\nUse PostgreSQL.",
    )
    repository = create_repository(document)

    retriever = KnowledgeRetriever(repository)

    result = retriever.retrieve("")

    assert result == KnowledgeContext()


def test_retrieve_loads_repository_once() -> None:
    """A retrieval should load its context from the repository once."""

    document = create_document(
        name="Database",
        path="database.md",
        content="# Database\n\nUse PostgreSQL.",
    )
    repository = create_repository(document)

    retriever = KnowledgeRetriever(repository)

    retriever.retrieve("PostgreSQL")

    repository.load.assert_called_once_with()


def test_retrieve_accepts_custom_scorer() -> None:
    """A custom scorer should be used when provided."""

    document = create_document(
        name="Database",
        path="database.md",
        content="# Database\n\nUse PostgreSQL.",
    )
    repository = create_repository(document)

    scorer = Mock(spec=DocumentScorer)
    scorer.score.return_value = 10

    retriever = KnowledgeRetriever(
        repository,
        scorer=scorer,
    )

    result = retriever.retrieve("unrelated query")

    assert result.documents == (document,)
    scorer.score.assert_called_once_with(
        "unrelated query",
        path=document.path,
        content=document.content,
    )