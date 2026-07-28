"""Tests for the knowledge repository."""

from unittest.mock import Mock

from moughorai.knowledge import KnowledgeRepository
from moughorai.models.knowledge import KnowledgeContext


def test_load_reads_knowledge_from_loader() -> None:
    knowledge = KnowledgeContext()

    loader = Mock()
    loader.load.return_value = knowledge

    repository = KnowledgeRepository(loader)

    result = repository.load()

    assert result is knowledge
    loader.load.assert_called_once_with()


def test_load_returns_cached_knowledge() -> None:
    knowledge = KnowledgeContext()

    loader = Mock()
    loader.load.return_value = knowledge

    repository = KnowledgeRepository(loader)

    first = repository.load()
    second = repository.load()

    assert first is knowledge
    assert second is knowledge
    loader.load.assert_called_once_with()


def test_reload_reads_knowledge_again() -> None:
    initial = KnowledgeContext()
    updated = KnowledgeContext()

    loader = Mock()
    loader.load.side_effect = [
        initial,
        updated,
    ]

    repository = KnowledgeRepository(loader)

    first = repository.load()
    second = repository.reload()

    assert first is initial
    assert second is updated
    assert loader.load.call_count == 2


def test_load_returns_reloaded_knowledge() -> None:
    initial = KnowledgeContext()
    updated = KnowledgeContext()

    loader = Mock()
    loader.load.side_effect = [
        initial,
        updated,
    ]

    repository = KnowledgeRepository(loader)

    repository.load()
    repository.reload()

    result = repository.load()

    assert result is updated
    assert loader.load.call_count == 2


def test_reload_before_first_load() -> None:
    knowledge = KnowledgeContext()

    loader = Mock()
    loader.load.return_value = knowledge

    repository = KnowledgeRepository(loader)

    result = repository.reload()

    assert result is knowledge
    loader.load.assert_called_once_with()