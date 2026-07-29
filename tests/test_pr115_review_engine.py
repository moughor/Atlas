from pathlib import Path

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_review import ReviewEngine, ReviewRequest
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


def _snapshot(tmp_path: Path):
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    return AtlasSemanticSnapshot.create(
        WorkspaceContextBuilder().build(workspace),
        workspace_fingerprint="abc",
        analyzer_version="2",
    )


def test_review_normalizes_categories_and_returns_markdown(tmp_path: Path) -> None:
    provider = ScriptedLlmProvider(["# Review\n\n- Action"])
    result = ReviewEngine(LlmClient(provider)).review(
        _snapshot(tmp_path),
        ReviewRequest((" Naming ", "architecture", "naming")),
    )
    assert result.markdown.startswith("# Review")
    assert result.categories == ("architecture", "naming")
    prompt = provider.calls[0][0].messages[-1].content
    assert "actionable recommendations" in prompt


def test_review_requires_categories(tmp_path: Path) -> None:
    try:
        ReviewEngine(LlmClient(ScriptedLlmProvider([]))).review(
            _snapshot(tmp_path), ReviewRequest(())
        )
    except ValueError as exc:
        assert "category" in str(exc)
    else:
        raise AssertionError("empty categories accepted")
