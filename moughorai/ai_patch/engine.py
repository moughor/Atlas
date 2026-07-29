from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import subprocess
from pathlib import Path
from typing import Protocol

from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


class PatchValidator(Protocol):
    def validate(self, patch: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class PatchRequest:
    objective: str


@dataclass(frozen=True, slots=True)
class PatchProposal:
    patch: str
    snapshot_id: str
    validations: tuple[str, ...]


class GitPatchValidator:
    """Validate applicability without modifying the worktree."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def validate(self, patch: str) -> tuple[str, ...]:
        process = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=self.root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode:
            raise ValueError(f"patch failed git apply --check: {process.stderr.strip()}")
        return ("unified-diff", "safe-paths", "git-apply-check")


class PatchEngine:
    def __init__(self, client: LlmClient, validator: PatchValidator) -> None:
        self.client = client
        self.validator = validator
        self.prompts = SemanticPromptBuilder()

    def propose(self, snapshot: AtlasSemanticSnapshot, request: PatchRequest) -> PatchProposal:
        objective = request.objective.strip()
        if not objective:
            raise ValueError("patch objective must not be empty")
        instruction = (
            "Propose a minimal unified Git diff for this objective using only ASS facts: "
            f"{objective}. Return only the diff. Do not apply it."
        )
        raw = self.client.complete(self.prompts.build(instruction, snapshot.to_context()).request).text
        patch = self._extract(raw)
        self._validate_paths(patch)
        validations = self.validator.validate(patch)
        return PatchProposal(patch, snapshot.snapshot_id, validations)

    @staticmethod
    def _extract(value: str) -> str:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                raise ValueError("patch code fence is incomplete")
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("diff\n"):
                text = text[5:]
        if not text.startswith("diff --git ") or "\n--- " not in text or "\n+++ " not in text:
            raise ValueError("provider output is not a unified Git diff")
        return text + "\n"

    @staticmethod
    def _validate_paths(patch: str) -> None:
        for line in patch.splitlines():
            if not line.startswith(("--- ", "+++ ")):
                continue
            raw = line[4:].split("\t", 1)[0]
            if raw == "/dev/null":
                continue
            path = raw[2:] if raw.startswith(("a/", "b/")) else raw
            candidate = PurePosixPath(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"unsafe patch path: {raw}")
