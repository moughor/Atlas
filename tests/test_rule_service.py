from unittest.mock import Mock

from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)
from moughorai.rules import RuleService


def create_rules() -> RuleContext:
    return RuleContext(
        documents=(
            RuleDocument(
                name="python.md",
                path="rules/python.md",
                category="language",
                content="Use Python type hints.",
            ),
        ),
    )


def test_load_returns_empty_without_selector() -> None:
    service = RuleService()

    result = service.load(
        query="Write Python code.",
    )

    assert result == RuleContext()


def test_load_returns_empty_for_empty_query() -> None:
    selector = Mock()

    service = RuleService(selector)

    result = service.load(
        query="   ",
    )

    assert result == RuleContext()

    selector.retrieve.assert_not_called()


def test_load_uses_configured_selector() -> None:
    expected = create_rules()

    selector = Mock()
    selector.retrieve.return_value = expected

    service = RuleService(selector)

    result = service.load(
        query="Use Python typing.",
    )

    assert result == expected

    selector.retrieve.assert_called_once_with(
        "Use Python typing.",
    )