from pathlib import Path

import pytest

from moughorai.knowledge.knowledge_loader import (
    KnowledgeLoader,
    KnowledgeLoaderError,
)


def test_load_directory_recursively(
    tmp_path: Path,
) -> None:
    brain_path = tmp_path / "brain"
    nested_path = brain_path / "architecture"

    nested_path.mkdir(parents=True)

    (brain_path / "coding.md").write_text(
        "# Coding\n\nWrite tested Python.",
        encoding="utf-8",
    )

    (nested_path / "design.markdown").write_text(
        "# Design\n\nUse clear boundaries.",
        encoding="utf-8",
    )

    (brain_path / "ignored.txt").write_text(
        "This file must not be loaded.",
        encoding="utf-8",
    )

    loader = KnowledgeLoader(tmp_path)

    context = loader.load(
        "brain",
        category="brain",
    )

    assert context.document_count == 2
    assert context.categories == ("brain",)

    assert tuple(
        document.name
        for document in context.documents
    ) == (
        "design.markdown",
        "coding.md",
    )

    assert context.documents[0].path == Path(
        "brain/architecture/design.markdown"
    )

    assert context.documents[1].path == Path(
        "brain/coding.md"
    )


def test_load_directory_has_deterministic_order(
    tmp_path: Path,
) -> None:
    brain_path = tmp_path / "brain"
    brain_path.mkdir()

    (brain_path / "zeta.md").write_text(
        "Zeta",
        encoding="utf-8",
    )

    (brain_path / "Alpha.md").write_text(
        "Alpha",
        encoding="utf-8",
    )

    loader = KnowledgeLoader(tmp_path)

    documents = loader.load_directory(
        brain_path,
        category="brain",
    )

    assert tuple(
        document.name
        for document in documents
    ) == (
        "Alpha.md",
        "zeta.md",
    )


def test_load_document_supports_utf8_bom(
    tmp_path: Path,
) -> None:
    brain_path = tmp_path / "brain"
    brain_path.mkdir()

    document_path = brain_path / "rules.md"

    document_path.write_text(
        "# Rules\n\nUse strong typing.",
        encoding="utf-8-sig",
    )

    loader = KnowledgeLoader(tmp_path)

    document = loader.load_document(
        document_path,
        category="brain",
    )

    assert document.content.startswith("# Rules")
    assert not document.content.startswith("\ufeff")


def test_empty_document_is_rejected(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "empty.md"

    document_path.write_text(
        "   \n\n",
        encoding="utf-8",
    )

    loader = KnowledgeLoader(tmp_path)

    with pytest.raises(
        KnowledgeLoaderError,
        match="empty",
    ):
        loader.load_document(
            document_path,
            category="brain",
        )


def test_missing_directory_is_rejected(
    tmp_path: Path,
) -> None:
    loader = KnowledgeLoader(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match="Knowledge directory not found",
    ):
        loader.load(
            "missing",
            category="brain",
        )


def test_unsupported_document_is_rejected(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "notes.txt"

    document_path.write_text(
        "Unsupported",
        encoding="utf-8",
    )

    loader = KnowledgeLoader(tmp_path)

    with pytest.raises(
        ValueError,
        match="Unsupported knowledge document extension",
    ):
        loader.load_document(
            document_path,
            category="brain",
        )