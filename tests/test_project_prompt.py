"""Tests for project-aware prompt construction."""

from pathlib import Path

from moughorai.models.project import ProjectContext, ProjectFile
from moughorai.prompts import PromptBuilder


def make_project_context() -> ProjectContext:
    return ProjectContext(
        name="sample-project",
        root=Path("sample-project").resolve(),
        tree="src/\n  app.py",
        files=(
            ProjectFile(
                path=Path("src/app.py"),
                content="def main() -> None:\n    pass",
            ),
        ),
    )


def test_build_includes_project_context() -> None:
    builder = PromptBuilder()

    prompt = builder.build(
        "Explain the project.",
        project=make_project_context(),
    )

    assert "<PROJECT CONTEXT>" in prompt
    assert "Project: sample-project" in prompt
    assert "src/app.py" in prompt
    assert "def main() -> None:" in prompt


def test_build_without_project_remains_backward_compatible() -> None:
    builder = PromptBuilder()

    prompt = builder.build("Explain the rules.")

    assert "<PROJECT CONTEXT>" not in prompt
    assert "<PROJECT KNOWLEDGE>" in prompt
    assert "<USER REQUEST>" in prompt


def test_system_prompt_includes_project_without_user_request() -> None:
    builder = PromptBuilder()

    prompt = builder.build_system_prompt(
        project=make_project_context(),
    )

    assert "<PROJECT CONTEXT>" in prompt
    assert "<USER REQUEST>" not in prompt


def test_project_prompt_is_deterministic() -> None:
    builder = PromptBuilder()
    project = make_project_context()

    first = builder.build(
        "Review the project.",
        project=project,
    )
    second = builder.build(
        "Review the project.",
        project=project,
    )

    assert first == second