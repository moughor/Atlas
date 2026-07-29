"""Tests for prompt building services."""

from pathlib import Path

import pytest

from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)
from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)
from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)
from moughorai.prompts import (
    PromptBuilder,
    PromptBuilderError,
)


def create_rule_context() -> RuleContext:
    """Create a rule context for testing."""

    document = RuleDocument(
        name="python.md",
        path=Path("rules/python.md"),
        category="language",
        content=(
            "# Python Rules\n\n"
            "Use type hints and pathlib."
        ),
    )

    return RuleContext(
        documents=(document,),
    )


def create_knowledge_context() -> KnowledgeContext:
    """Create a knowledge context for testing."""

    document = KnowledgeDocument(
        name="coding.md",
        path=Path("brain/coding.md"),
        category="brain",
        content="# Coding Rules\n\nUse strong typing.",
    )

    return KnowledgeContext(
        documents=(document,),
    )


def create_memory_context() -> MemoryContext:
    """Create a memory context for testing."""

    document = MemoryDocument(
        name="decisions.md",
        path=Path("memory/decisions.md"),
        category="memory",
        content="# Decisions\n\nUse PostgreSQL.",
    )

    return MemoryContext(
        documents=(document,),
    )


def test_build_contains_all_sections() -> None:
    """The complete prompt should contain every required section."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Add a health-check endpoint.",
        rules=create_rule_context(),
        knowledge=create_knowledge_context(),
        memory=create_memory_context(),
    )

    assert "<SYSTEM INSTRUCTIONS>" in prompt
    assert "</SYSTEM INSTRUCTIONS>" in prompt

    assert "<PROJECT RULES>" in prompt
    assert "</PROJECT RULES>" in prompt

    assert "<PROJECT KNOWLEDGE>" in prompt
    assert "</PROJECT KNOWLEDGE>" in prompt

    assert "<PROJECT MEMORY>" in prompt
    assert "</PROJECT MEMORY>" in prompt

    assert "<USER REQUEST>" in prompt
    assert "</USER REQUEST>" in prompt

    assert "<RESPONSE INSTRUCTIONS>" in prompt
    assert "</RESPONSE INSTRUCTIONS>" in prompt


def test_build_contains_rule_document() -> None:
    """Selected rules should be rendered inside the prompt."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Implement a Python service.",
        rules=create_rule_context(),
    )

    assert "## Rule: python.md" in prompt
    assert "Category: language" in prompt
    assert "Path: rules/python.md" in prompt
    assert "# Python Rules" in prompt
    assert "Use type hints and pathlib." in prompt


def test_build_contains_knowledge_document() -> None:
    """Knowledge documents should be rendered inside the prompt."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Review the project.",
        knowledge=create_knowledge_context(),
    )

    assert "## Document: coding.md" in prompt
    assert "Category: brain" in prompt
    assert "Path: brain/coding.md" in prompt
    assert "# Coding Rules" in prompt
    assert "Use strong typing." in prompt


def test_build_contains_memory_document() -> None:
    """Memory documents should be rendered inside the prompt."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Review the project.",
        memory=create_memory_context(),
    )

    assert "## Memory: decisions.md" in prompt
    assert "Category: memory" in prompt
    assert "Path: memory/decisions.md" in prompt
    assert "# Decisions" in prompt
    assert "Use PostgreSQL." in prompt


def test_build_contains_normalized_user_request() -> None:
    """The request should be stripped before rendering."""

    builder = PromptBuilder()

    prompt = builder.build(
        "  Add structured logging.  ",
    )

    assert (
        "<USER REQUEST>\n"
        "Add structured logging.\n"
        "</USER REQUEST>"
    ) in prompt


def test_empty_rules_are_described_explicitly() -> None:
    """The prompt should explain when no rules were selected."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Explain this workspace.",
    )

    assert "No project rules were selected." in prompt
    assert (
        "Follow the system instructions and supplied "
        "project context."
    ) in prompt


def test_empty_knowledge_is_described_explicitly() -> None:
    """The prompt should explain when no knowledge was supplied."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Explain this workspace.",
    )

    assert (
        "No project knowledge documents were supplied."
        in prompt
    )

    assert (
        "Do not invent project-specific rules."
        in prompt
    )


def test_empty_memory_is_described_explicitly() -> None:
    """The prompt should explain when no memory is available."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Explain this workspace.",
    )

    assert "No project memory is available." in prompt


def test_rules_are_rendered_before_knowledge() -> None:
    """Explicit rules should appear before project knowledge."""

    builder = PromptBuilder()

    prompt = builder.build(
        "Review the project.",
        rules=create_rule_context(),
        knowledge=create_knowledge_context(),
    )

    assert prompt.index("<PROJECT RULES>") < prompt.index(
        "<PROJECT KNOWLEDGE>"
    )


def test_custom_system_instructions_are_supported() -> None:
    """Custom system instructions should replace the defaults."""

    builder = PromptBuilder(
        system_instructions=(
            "You are a focused Python reviewer."
        )
    )

    prompt = builder.build(
        "Review this module.",
    )

    assert "You are a focused Python reviewer." in prompt
    assert "You are MoughorAI" not in prompt


def test_build_is_deterministic() -> None:
    """Identical inputs should produce identical prompts."""

    builder = PromptBuilder()
    rules = create_rule_context()
    knowledge = create_knowledge_context()
    memory = create_memory_context()

    first_prompt = builder.build(
        "Add tests.",
        rules=rules,
        knowledge=knowledge,
        memory=memory,
    )

    second_prompt = builder.build(
        "Add tests.",
        rules=rules,
        knowledge=knowledge,
        memory=memory,
    )

    assert first_prompt == second_prompt


@pytest.mark.parametrize(
    "user_request",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_empty_user_request_is_rejected(
    user_request: str,
) -> None:
    """Empty user requests should be rejected."""

    builder = PromptBuilder()

    with pytest.raises(
        PromptBuilderError,
        match="User request cannot be empty",
    ):
        builder.build(user_request)


def test_empty_system_instructions_are_rejected() -> None:
    """Empty custom system instructions should be rejected."""

    with pytest.raises(
        PromptBuilderError,
        match="System instructions cannot be empty",
    ):
        PromptBuilder(system_instructions="   ")


def test_build_system_prompt_includes_contexts() -> None:
    """The reusable system prompt should include all contexts."""

    builder = PromptBuilder()

    prompt = builder.build_system_prompt(
        rules=create_rule_context(),
        knowledge=create_knowledge_context(),
        memory=create_memory_context(),
    )

    assert "<SYSTEM INSTRUCTIONS>" in prompt
    assert "<PROJECT RULES>" in prompt
    assert "<PROJECT KNOWLEDGE>" in prompt
    assert "<PROJECT MEMORY>" in prompt

    assert "## Rule: python.md" in prompt
    assert "## Document: coding.md" in prompt
    assert "## Memory: decisions.md" in prompt

    assert "<USER REQUEST>" not in prompt
    assert "<RESPONSE INSTRUCTIONS>" not in prompt


def test_build_system_prompt_excludes_user_request() -> None:
    """The reusable system prompt should not contain request sections."""

    builder = PromptBuilder()

    prompt = builder.build_system_prompt(
        rules=create_rule_context(),
        knowledge=create_knowledge_context(),
    )

    assert "<SYSTEM INSTRUCTIONS>" in prompt
    assert "<PROJECT RULES>" in prompt
    assert "<PROJECT KNOWLEDGE>" in prompt
    assert "<PROJECT MEMORY>" in prompt
    assert "<USER REQUEST>" not in prompt
    assert "<RESPONSE INSTRUCTIONS>" not in prompt