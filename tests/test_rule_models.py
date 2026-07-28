"""Tests for typed rule models."""

from pathlib import Path

from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)


def create_rule(
    *,
    name: str = "Python",
    path: str = "python.md",
    category: str = "language",
    content: str = "# Python\n\nUse type hints.",
) -> RuleDocument:
    """Create one rule document for testing."""

    return RuleDocument(
        name=name,
        path=Path(path),
        category=category,
        content=content,
    )


def test_rule_document_exposes_computed_properties() -> None:
    """A rule document should expose useful metadata."""

    document = create_rule(
        path="rules/PYTHON.MD",
        content="# Python\n\nUse type hints.",
    )

    assert document.suffix == ".md"
    assert document.character_count == len(document.content)
    assert document.line_count == 3


def test_rule_document_renders_structured_content() -> None:
    """A rule document should render as a prompt section."""

    document = create_rule()

    rendered = document.render()

    assert "## Rule: Python" in rendered
    assert "Category: language" in rendered
    assert "Path: python.md" in rendered
    assert "Use type hints." in rendered


def test_empty_rule_context_is_empty() -> None:
    """A context without documents should be empty."""

    context = RuleContext()

    assert context.is_empty
    assert context.document_count == 0
    assert context.total_character_count == 0
    assert context.categories == ()
    assert context.render() == ""


def test_rule_context_exposes_aggregate_metadata() -> None:
    """A context should expose aggregate document metadata."""

    python_rule = create_rule()
    pytest_rule = create_rule(
        name="Pytest",
        path="pytest.md",
        category="testing",
        content="# Pytest\n\nUse fixtures.",
    )

    context = RuleContext(
        documents=(
            python_rule,
            pytest_rule,
        ),
    )

    assert context.document_count == 2
    assert context.total_character_count == (
        len(python_rule.content)
        + len(pytest_rule.content)
    )
    assert context.categories == (
        "language",
        "testing",
    )


def test_rule_context_renders_documents_in_order() -> None:
    """Rules should render in their stored order."""

    python_rule = create_rule()
    pytest_rule = create_rule(
        name="Pytest",
        path="pytest.md",
        category="testing",
        content="# Pytest\n\nUse fixtures.",
    )

    context = RuleContext(
        documents=(
            python_rule,
            pytest_rule,
        ),
    )

    rendered = context.render()

    assert rendered.index("## Rule: Python") < rendered.index(
        "## Rule: Pytest"
    )
    assert "\n\n---\n\n" in rendered


def test_rule_context_filters_by_category() -> None:
    """Rules should be filterable by category."""

    python_rule = create_rule()
    pytest_rule = create_rule(
        name="Pytest",
        path="pytest.md",
        category="testing",
        content="# Pytest\n\nUse fixtures.",
    )

    context = RuleContext(
        documents=(
            python_rule,
            pytest_rule,
        ),
    )

    assert context.by_category(" TESTING ") == (
        pytest_rule,
    )


def test_rule_context_adds_document_immutably() -> None:
    """Adding a rule should return a new context."""

    original = RuleContext()
    document = create_rule()

    updated = original.with_document(document)

    assert original.documents == ()
    assert updated.documents == (document,)