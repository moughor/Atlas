"""Tests for rule selection services."""

from pathlib import Path
from unittest.mock import Mock

from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)
from moughorai.rules.repository import RuleRepository
from moughorai.rules.selector import RuleSelector
from moughorai.search import DocumentScorer


def create_document(
    name: str,
    path: str,
    content: str,
    *,
    category: str = "general",
) -> RuleDocument:
    """Create one rule document for testing."""

    return RuleDocument(
        name=name,
        path=Path(path),
        category=category,
        content=content,
    )


def create_repository(
    *documents: RuleDocument,
) -> Mock:
    """Create a mocked rule repository."""

    repository = Mock(spec=RuleRepository)
    repository.load.return_value = RuleContext(
        documents=documents,
    )

    return repository


def test_select_returns_matching_rule() -> None:
    """Matching rules should be returned."""

    python = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse type hints.",
        category="language",
    )
    testing = create_document(
        name="Testing",
        path="testing.md",
        content="# Testing\n\nUse pytest.",
        category="testing",
    )
    repository = create_repository(
        python,
        testing,
    )

    selector = RuleSelector(repository)

    result = selector.retrieve("pytest")

    assert result.documents == (testing,)


def test_select_excludes_non_matching_rules() -> None:
    """Rules with zero relevance should be excluded."""

    python = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse type hints.",
        category="language",
    )
    testing = create_document(
        name="Testing",
        path="testing.md",
        content="# Testing\n\nUse pytest.",
        category="testing",
    )
    repository = create_repository(
        python,
        testing,
    )

    selector = RuleSelector(repository)

    result = selector.retrieve("Docker")

    assert result.is_empty


def test_select_ranks_rules_by_score() -> None:
    """Rules should be ordered by descending relevance."""

    filename_match = create_document(
        name="Pytest",
        path="pytest.md",
        content="# Testing\n\nGeneral test guidance.",
        category="testing",
    )
    body_match = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse pytest for tests.",
        category="language",
    )
    repository = create_repository(
        body_match,
        filename_match,
    )

    selector = RuleSelector(repository)

    result = selector.retrieve("pytest")

    assert result.documents == (
        filename_match,
        body_match,
    )


def test_select_respects_limit() -> None:
    """Only the requested number of rules should be returned."""

    first = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nPython guidance.",
        category="language",
    )
    second = create_document(
        name="Python typing",
        path="typing.md",
        content="# Typing\n\nPython type hints.",
        category="language",
    )
    third = create_document(
        name="Python testing",
        path="testing.md",
        content="# Testing\n\nTest Python code.",
        category="testing",
    )
    repository = create_repository(
        first,
        second,
        third,
    )

    selector = RuleSelector(repository)

    result = selector.retrieve(
        "Python",
        limit=2,
    )

    assert result.documents == (
        first,
        second,
    )


def test_select_returns_empty_context_for_empty_query() -> None:
    """An empty query should not select any rule."""

    document = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse type hints.",
        category="language",
    )
    repository = create_repository(document)

    selector = RuleSelector(repository)

    result = selector.retrieve("")

    assert result == RuleContext()


def test_select_loads_repository_once() -> None:
    """A selection should load its context once."""

    document = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse type hints.",
        category="language",
    )
    repository = create_repository(document)

    selector = RuleSelector(repository)

    selector.retrieve("Python")

    repository.load.assert_called_once_with()


def test_select_accepts_custom_scorer() -> None:
    """A custom scorer should be used when provided."""

    document = create_document(
        name="Python",
        path="python.md",
        content="# Python\n\nUse type hints.",
        category="language",
    )
    repository = create_repository(document)

    scorer = Mock(spec=DocumentScorer)
    scorer.score.return_value = 10

    selector = RuleSelector(
        repository,
        scorer=scorer,
    )

    result = selector.retrieve("unrelated query")

    assert result.documents == (document,)
    scorer.score.assert_called_once_with(
        "unrelated query",
        path=document.path,
        content=document.content,
    )