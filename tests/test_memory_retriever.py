"""Tests for the memory retriever."""

from pathlib import Path
from unittest.mock import Mock

from moughorai.memory import MemoryRetriever
from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)


def make_document(name: str) -> MemoryDocument:
    """Create a memory document for retrieval tests."""

    return MemoryDocument(
        name=name,
        category="test",
        path=Path(f"{name}.md"),
        content=f"# {name}",
    )


def test_returns_empty_context_when_repository_is_empty() -> None:
    repository = Mock()
    repository.load.return_value = MemoryContext()

    retriever = MemoryRetriever(repository)

    result = retriever.retrieve("intel")

    assert result.documents == ()


def test_returns_only_matching_documents() -> None:
    intel = make_document("intel")
    python = make_document("python")

    repository = Mock()
    repository.load.return_value = MemoryContext(
        documents=(intel, python),
    )

    scorer = Mock()
    scorer.score.side_effect = [10, 0]

    retriever = MemoryRetriever(repository, scorer)

    result = retriever.retrieve("intel")

    assert result.documents == (intel,)


def test_returns_documents_sorted_by_score() -> None:
    first = make_document("a")
    second = make_document("b")
    third = make_document("c")

    repository = Mock()
    repository.load.return_value = MemoryContext(
        documents=(first, second, third),
    )

    scorer = Mock()
    scorer.score.side_effect = [5, 20, 10]

    retriever = MemoryRetriever(repository, scorer)

    result = retriever.retrieve("anything")

    assert result.documents == (
        second,
        third,
        first,
    )


def test_limit_is_respected() -> None:
    documents = (
        make_document("one"),
        make_document("two"),
        make_document("three"),
    )

    repository = Mock()
    repository.load.return_value = MemoryContext(
        documents=documents,
    )

    scorer = Mock()
    scorer.score.side_effect = [3, 2, 1]

    retriever = MemoryRetriever(repository, scorer)

    result = retriever.retrieve(
        "query",
        limit=2,
    )

    assert len(result.documents) == 2
    assert result.documents == documents[:2]


def test_repository_is_loaded_once() -> None:
    repository = Mock()
    repository.load.return_value = MemoryContext()

    retriever = MemoryRetriever(repository)

    retriever.retrieve("intel")

    repository.load.assert_called_once_with()


def test_scorer_receives_document_path_and_content() -> None:
    document = make_document("intel")

    repository = Mock()
    repository.load.return_value = MemoryContext(
        documents=(document,),
    )

    scorer = Mock()
    scorer.score.return_value = 10

    retriever = MemoryRetriever(repository, scorer)

    retriever.retrieve("intel memory")

    scorer.score.assert_called_once_with(
        "intel memory",
        path=document.path,
        content=document.content,
    )


def test_documents_with_equal_scores_keep_repository_order() -> None:
    first = make_document("first")
    second = make_document("second")
    third = make_document("third")

    repository = Mock()
    repository.load.return_value = MemoryContext(
        documents=(first, second, third),
    )

    scorer = Mock()
    scorer.score.side_effect = [10, 10, 10]

    retriever = MemoryRetriever(repository, scorer)

    result = retriever.retrieve("query")

    assert result.documents == (
        first,
        second,
        third,
    )