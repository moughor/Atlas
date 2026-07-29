from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_patch import PatchEngine, PatchRequest
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


PATCH = """diff --git a/app.txt b/app.txt
--- a/app.txt
+++ b/app.txt
@@ -1 +1 @@
-old
+new
"""


class Validator:
    def __init__(self):
        self.patch = None

    def validate(self, patch):
        self.patch = patch
        return ("syntax", "symbols", "diagnostics", "project-integrity")


def _snapshot(tmp_path: Path):
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    return AtlasSemanticSnapshot.create(
        WorkspaceContextBuilder().build(workspace),
        workspace_fingerprint="abc",
        analyzer_version="2",
    )


def test_patch_is_validated_but_not_applied(tmp_path: Path) -> None:
    validator = Validator()
    result = PatchEngine(LlmClient(ScriptedLlmProvider([PATCH])), validator).propose(
        _snapshot(tmp_path), PatchRequest("Change app")
    )
    assert result.patch == PATCH
    assert validator.patch == PATCH
    assert "project-integrity" in result.validations
    assert not (tmp_path / "app.txt").exists()


def test_patch_rejects_unsafe_paths(tmp_path: Path) -> None:
    unsafe = PATCH.replace("a/app.txt", "a/../secret").replace("b/app.txt", "b/../secret")
    with pytest.raises(ValueError, match="unsafe patch path"):
        PatchEngine(LlmClient(ScriptedLlmProvider([unsafe])), Validator()).propose(
            _snapshot(tmp_path), PatchRequest("unsafe")
        )


def test_patch_rejects_non_diff_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a unified"):
        PatchEngine(LlmClient(ScriptedLlmProvider(["looks good"])), Validator()).propose(
            _snapshot(tmp_path), PatchRequest("change")
        )
