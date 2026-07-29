from pathlib import Path

import pytest
from pydantic import ValidationError

from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)


def create_memory_document(
    *,
    name: str = "decisions.md",
    category: str = "decisions",
    content: str = "# Decisions\n\nUse PostgreSQL.",
) -> MemoryDocument:
    return MemoryDocument(
        name=name,
        path=Path("memory") / name,
        category=category,
        content=content,
    )


def test_memory_document_exposes_computed_metadata() -> None:
    document = create_memory_document(
        content="# Decisions\n\nUse PostgreSQL.",
    )

    assert document.suffix == ".md"
    assert document.character_count == len(document.content)
    assert document.line_count == 3


def test_memory_document_renders_structured_content() -> None:
    document = create_memory_document()

    assert document.render() == (
        "## Memory: decisions.md\n"
        "Category: decisions\n"
        "Path: memory/decisions.md\n\n"
        "# Decisions\n\n"
        "Use PostgreSQL."
    )


def test_memory_context_exposes_aggregate_metadata() -> None:
    decisions = create_memory_document()
    architecture = create_memory_document(
        name="architecture.md",
        category="architecture",
        content="# Architecture\n\nUse clear boundaries.",
    )

    context = MemoryContext(
        documents=(decisions, architecture),
    )

    assert context.document_count == 2
    assert context.total_character_count == (
        decisions.character_count
        + architecture.character_count
    )
    assert context.categories == (
        "architecture",
        "decisions",
    )
    assert context.is_empty is False


def test_empty_memory_context_is_empty() -> None:
    context = MemoryContext()

    assert context.documents == ()
    assert context.document_count == 0
    assert context.total_character_count == 0
    assert context.categories == ()
    assert context.is_empty is True
    assert context.render() == ""


def test_memory_context_render_is_deterministic() -> None:
    first = create_memory_document()
    second = create_memory_document(
        name="mistakes.md",
        category="mistakes",
        content="# Mistakes\n\nDo not bypass validation.",
    )

    context = MemoryContext(
        documents=(first, second),
    )

    assert context.render() == (
        first.render()
        + "\n\n---\n\n"
        + second.render()
    )


def test_memory_context_filters_by_category() -> None:
    decisions = create_memory_document()
    architecture = create_memory_document(
        name="architecture.md",
        category="architecture",
        content="# Architecture",
    )

    context = MemoryContext(
        documents=(decisions, architecture),
    )

    assert context.by_category("DECISIONS") == (decisions,)
    assert context.by_category(" architecture ") == (
        architecture,
    )
    assert context.by_category("missing") == ()


def test_with_document_returns_new_context() -> None:
    original = MemoryContext()
    document = create_memory_document()

    updated = original.with_document(document)

    assert original.documents == ()
    assert updated.documents == (document,)


def test_memory_models_are_immutable() -> None:
    document = create_memory_document()
    context = MemoryContext(documents=(document,))

    with pytest.raises(ValidationError):
        document.content = "Changed"

    with pytest.raises(ValidationError):
        context.documents = ()