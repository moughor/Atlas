"""Tests for the rule document loader."""

from pathlib import Path

import pytest

from moughorai.models.rule import RuleContext
from moughorai.rules import (
    RuleLoader,
    RuleLoaderError,
)


def test_load_returns_markdown_rules(
    tmp_path: Path,
) -> None:
    """Markdown files should be loaded as rule documents."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    python_rule = rules_path / "python.md"
    python_rule.write_text(
        "# Python\n\nUse type hints.",
        encoding="utf-8",
    )

    loader = RuleLoader(tmp_path)

    result = loader.load(
        rules_path,
        category="language",
    )

    assert isinstance(result, RuleContext)
    assert result.document_count == 1

    document = result.documents[0]

    assert document.name == "python.md"
    assert document.path == Path(
        "rules/python.md"
    )
    assert document.category == "language"
    assert document.content == "# Python\n\nUse type hints."


def test_load_returns_documents_in_deterministic_order(
    tmp_path: Path,
) -> None:
    """Rule documents should be sorted deterministically."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    (rules_path / "zulu.md").write_text(
        "# Zulu",
        encoding="utf-8",
    )
    (rules_path / "alpha.md").write_text(
        "# Alpha",
        encoding="utf-8",
    )

    loader = RuleLoader(tmp_path)

    result = loader.load(
        rules_path,
        category="general",
    )

    assert tuple(
        document.name
        for document in result.documents
    ) == (
        "alpha.md",
        "zulu.md",
    )


def test_load_ignores_non_markdown_files(
    tmp_path: Path,
) -> None:
    """Files outside the supported format should be ignored."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    (rules_path / "python.md").write_text(
        "# Python",
        encoding="utf-8",
    )
    (rules_path / "notes.txt").write_text(
        "Ignore this.",
        encoding="utf-8",
    )

    loader = RuleLoader(tmp_path)

    result = loader.load(
        rules_path,
        category="language",
    )

    assert tuple(
        document.name
        for document in result.documents
    ) == ("python.md",)


def test_load_empty_directory_returns_empty_context(
    tmp_path: Path,
) -> None:
    """An empty rule directory should produce an empty context."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    loader = RuleLoader(tmp_path)

    result = loader.load(
        rules_path,
        category="general",
    )

    assert result == RuleContext()


def test_load_missing_directory_raises_file_not_found_error(
    tmp_path: Path,
) -> None:
    """A missing rule directory should raise FileNotFoundError."""

    loader = RuleLoader(tmp_path)

    with pytest.raises(FileNotFoundError):
        loader.load(
            tmp_path / "missing",
            category="general",
        )


def test_load_resolves_relative_path_from_workspace(
    tmp_path: Path,
) -> None:
    """Relative directories should resolve from the workspace."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    rule_path = rules_path / "security.md"
    rule_path.write_text(
        "# Security\n\nValidate all input.",
        encoding="utf-8",
    )

    loader = RuleLoader(tmp_path)

    result = loader.load(
        Path("rules"),
        category="security",
    )

    assert result.documents[0].path == Path(
        "rules/security.md"
    )


def test_load_raises_rule_loader_error_for_invalid_utf8(
    tmp_path: Path,
) -> None:
    """Unreadable rule content should raise a typed error."""

    rules_path = tmp_path / "rules"
    rules_path.mkdir()

    invalid_rule = rules_path / "invalid.md"
    invalid_rule.write_bytes(b"\xff\xfe\x00")

    loader = RuleLoader(tmp_path)

    with pytest.raises(RuleLoaderError):
        loader.load(
            rules_path,
            category="general",
        )