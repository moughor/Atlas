from pathlib import Path

import pytest

from moughorai.memory.memory_loader import (
    MemoryLoader,
    MemoryLoaderError,
)


def test_load_directory_recursively(
    tmp_path: Path,
) -> None:
    memory_path = tmp_path / "memory"
    nested_path = memory_path / "architecture"

    nested_path.mkdir(parents=True)

    (memory_path / "decisions.md").write_text(
        "# Decisions\n\nUse PostgreSQL.",
        encoding="utf-8",
    )

    (nested_path / "boundaries.markdown").write_text(
        "# Boundaries\n\nKeep services isolated.",
        encoding="utf-8",
    )

    (memory_path / "ignored.txt").write_text(
        "This file must not be loaded.",
        encoding="utf-8",
    )

    loader = MemoryLoader(tmp_path)

    context = loader.load(
        "memory",
        category="project",
    )

    assert context.document_count == 2
    assert context.categories == ("project",)

    assert tuple(
        document.name
        for document in context.documents
    ) == (
        "boundaries.markdown",
        "decisions.md",
    )

    assert context.documents[0].path == Path(
        "memory/architecture/boundaries.markdown"
    )

    assert context.documents[1].path == Path(
        "memory/decisions.md"
    )


def test_load_directory_has_deterministic_order(
    tmp_path: Path,
) -> None:
    memory_path = tmp_path / "memory"
    memory_path.mkdir()

    (memory_path / "zeta.md").write_text(
        "Zeta",
        encoding="utf-8",
    )

    (memory_path / "Alpha.md").write_text(
        "Alpha",
        encoding="utf-8",
    )

    loader = MemoryLoader(tmp_path)

    documents = loader.load_directory(
        memory_path,
        category="project",
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
    memory_path = tmp_path / "memory"
    memory_path.mkdir()

    document_path = memory_path / "decisions.md"

    document_path.write_text(
        "# Decisions\n\nPreserve compatibility.",
        encoding="utf-8-sig",
    )

    loader = MemoryLoader(tmp_path)

    document = loader.load_document(
        document_path,
        category="project",
    )

    assert document.content.startswith("# Decisions")
    assert not document.content.startswith("\ufeff")


def test_empty_document_is_rejected(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "empty.md"

    document_path.write_text(
        "   \n\n",
        encoding="utf-8",
    )

    loader = MemoryLoader(tmp_path)

    with pytest.raises(
        MemoryLoaderError,
        match="empty",
    ):
        loader.load_document(
            document_path,
            category="project",
        )


def test_missing_directory_is_rejected(
    tmp_path: Path,
) -> None:
    loader = MemoryLoader(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match="Memory directory not found",
    ):
        loader.load(
            "missing",
            category="project",
        )


def test_unsupported_document_is_rejected(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "notes.txt"

    document_path.write_text(
        "Unsupported",
        encoding="utf-8",
    )

    loader = MemoryLoader(tmp_path)

    with pytest.raises(
        ValueError,
        match="Unsupported memory document extension",
    ):
        loader.load_document(
            document_path,
            category="project",
        )


def test_empty_category_is_rejected(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "memory.md"

    document_path.write_text(
        "Project memory",
        encoding="utf-8",
    )

    loader = MemoryLoader(tmp_path)

    with pytest.raises(
        ValueError,
        match="Memory category cannot be empty",
    ):
        loader.load_document(
            document_path,
            category="   ",
        )


def test_custom_extensions_are_supported(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "memory.txt"

    document_path.write_text(
        "Custom memory format",
        encoding="utf-8",
    )

    loader = MemoryLoader(
        tmp_path,
        extensions={"txt"},
    )

    document = loader.load_document(
        document_path,
        category="project",
    )

    assert document.name == "memory.txt"
    assert document.content == "Custom memory format"