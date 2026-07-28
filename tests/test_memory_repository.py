"""Tests for the memory repository."""

from unittest.mock import Mock

from moughorai.memory import MemoryRepository
from moughorai.models.memory import MemoryContext


def test_load_reads_memory_from_loader() -> None:
    memory = MemoryContext()

    loader = Mock()
    loader.load.return_value = memory

    repository = MemoryRepository(loader)

    result = repository.load()

    assert result is memory
    loader.load.assert_called_once_with()


def test_load_returns_cached_memory() -> None:
    memory = MemoryContext()

    loader = Mock()
    loader.load.return_value = memory

    repository = MemoryRepository(loader)

    first_result = repository.load()
    second_result = repository.load()

    assert first_result is memory
    assert second_result is memory
    loader.load.assert_called_once_with()


def test_reload_reads_memory_again() -> None:
    initial_memory = MemoryContext()
    reloaded_memory = MemoryContext()

    loader = Mock()
    loader.load.side_effect = [
        initial_memory,
        reloaded_memory,
    ]

    repository = MemoryRepository(loader)

    first_result = repository.load()
    second_result = repository.reload()

    assert first_result is initial_memory
    assert second_result is reloaded_memory
    assert loader.load.call_count == 2


def test_load_returns_reloaded_memory_after_reload() -> None:
    initial_memory = MemoryContext()
    reloaded_memory = MemoryContext()

    loader = Mock()
    loader.load.side_effect = [
        initial_memory,
        reloaded_memory,
    ]

    repository = MemoryRepository(loader)

    repository.load()
    repository.reload()
    result = repository.load()

    assert result is reloaded_memory
    assert loader.load.call_count == 2


def test_reload_works_before_initial_load() -> None:
    memory = MemoryContext()

    loader = Mock()
    loader.load.return_value = memory

    repository = MemoryRepository(loader)

    result = repository.reload()

    assert result is memory
    loader.load.assert_called_once_with()