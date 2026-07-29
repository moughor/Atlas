from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.prompts import (
    PromptTemplate,
    PromptTemplateError,
    SemanticPromptBuilder,
    TokenEstimator,
)
from moughorai.workspace import Project, Workspace


def _context(tmp_path: Path):
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    return WorkspaceContextBuilder().build(workspace)


def test_grounded_prompt_is_deterministic_and_returns_llm_request(tmp_path: Path) -> None:
    context = _context(tmp_path)
    builder = SemanticPromptBuilder()
    first = builder.build("  Summarize facts. ", context, model="test")
    second = builder.build("Summarize facts.", context, model="test")

    assert first == second
    assert first.request.model == "test"
    assert first.request.messages[1].content.endswith(context.to_json())
    assert first.request.metadata["prompt_template"] == "atlas-grounded-v1"


def test_custom_template_variables_render_deterministically(tmp_path: Path) -> None:
    template = PromptTemplate("custom", "Mode: {mode}", "{request}\n{context}")
    result = SemanticPromptBuilder({"custom": template}).build(
        "Inspect",
        _context(tmp_path),
        template="custom",
        variables={"mode": "strict"},
    )
    assert result.request.messages[0].content == "Mode: strict"


def test_missing_and_unsafe_template_fields_are_rejected(tmp_path: Path) -> None:
    context = _context(tmp_path)
    missing = PromptTemplate("missing", "{unknown}", "{request}")
    with pytest.raises(PromptTemplateError, match="missing"):
        SemanticPromptBuilder({"missing": missing}).build("Inspect", context, template="missing")
    unsafe = PromptTemplate("unsafe", "{request.__class__}", "{context}")
    with pytest.raises(PromptTemplateError, match="invalid template fields"):
        SemanticPromptBuilder({"unsafe": unsafe}).build("Inspect", context, template="unsafe")


def test_token_estimation_and_budget_are_deterministic(tmp_path: Path) -> None:
    estimator = TokenEstimator(characters_per_token=4)
    assert estimator.estimate("") == 0
    assert estimator.estimate("abcde") == 2
    builder = SemanticPromptBuilder(estimator=estimator)
    result = builder.build("Inspect", _context(tmp_path))
    with pytest.raises(PromptTemplateError, match="exceed limit"):
        builder.build(
            "Inspect",
            _context(tmp_path),
            maximum_input_tokens=result.estimated_input_tokens - 1,
        )
