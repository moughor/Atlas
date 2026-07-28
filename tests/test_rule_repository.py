"""Tests for the rule repository."""

from pathlib import Path
from unittest.mock import Mock

from moughorai.models.rule import RuleContext
from moughorai.rules.repository import RuleRepository


RULE_DIRECTORY = Path("brain")
RULE_CATEGORY = "general"


def test_load_uses_cache() -> None:
    """The repository should cache loaded rules."""

    context = RuleContext()

    loader = Mock()
    loader.load.return_value = context

    repository = RuleRepository(
        loader,
        RULE_DIRECTORY,
        category=RULE_CATEGORY,
    )

    first_result = repository.load()
    second_result = repository.load()

    assert first_result is context
    assert second_result is context

    loader.load.assert_called_once_with(
        RULE_DIRECTORY,
        category=RULE_CATEGORY,
    )


def test_reload_forces_reload() -> None:
    """Reload should bypass the cache."""

    first = RuleContext()
    second = RuleContext()

    loader = Mock()
    loader.load.side_effect = [
        first,
        second,
    ]

    repository = RuleRepository(
        loader,
        RULE_DIRECTORY,
        category=RULE_CATEGORY,
    )

    first_result = repository.load()
    second_result = repository.reload()

    assert first_result is first
    assert second_result is second

    assert loader.load.call_count == 2
    loader.load.assert_called_with(
        RULE_DIRECTORY,
        category=RULE_CATEGORY,
    )


def test_reload_updates_cache() -> None:
    """Reload should replace the cached context."""

    first = RuleContext()
    second = RuleContext()

    loader = Mock()
    loader.load.side_effect = [
        first,
        second,
    ]

    repository = RuleRepository(
        loader,
        RULE_DIRECTORY,
        category=RULE_CATEGORY,
    )

    repository.load()
    reloaded = repository.reload()
    cached = repository.load()

    assert reloaded is second
    assert cached is second
    assert loader.load.call_count == 2