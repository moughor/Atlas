from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Mapping


class GitContextError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GitCommitContext:
    commit: str
    author: str
    timestamp: str
    subject: str


@dataclass(frozen=True, slots=True)
class GitContext:
    branch: str
    head: str
    changed_files: tuple[str, ...]
    commits: tuple[GitCommitContext, ...]
    blame: tuple[tuple[str, tuple[str, ...]], ...] = ()
    pull_request: tuple[tuple[str, str], ...] = ()
    base_snapshot_id: str | None = None
    current_snapshot_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "head": self.head,
            "changed_files": list(self.changed_files),
            "commits": [asdict(commit) for commit in self.commits],
            "blame": {path: list(lines) for path, lines in self.blame},
            "pull_request": dict(self.pull_request),
            "base_snapshot_id": self.base_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class GitContextService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def collect(
        self,
        *,
        commit_limit: int = 20,
        blame_files: tuple[str, ...] = (),
        pull_request: Mapping[str, str] | None = None,
        base_snapshot_id: str | None = None,
        current_snapshot_id: str | None = None,
    ) -> GitContext:
        if commit_limit < 0:
            raise GitContextError("commit_limit must be non-negative")
        branch = self._git("symbolic-ref", "--short", "HEAD").strip()
        head = self._git_optional("rev-parse", "--verify", "HEAD").strip()
        status = self._git("status", "--porcelain=v1", "-z")
        changed = []
        for entry in status.split("\0"):
            if not entry:
                continue
            path = entry[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            changed.append(path.replace("\\", "/"))
        commits = ()
        if commit_limit and head:
            raw = self._git(
                "log", f"-n{commit_limit}", "--date=iso-strict",
                "--format=%H%x1f%an%x1f%ad%x1f%s%x1e",
            )
            commits = tuple(
                GitCommitContext(*record.split("\x1f"))
                for record in raw.strip("\x1e\n").split("\x1e")
                if record.strip()
            )
        blame = tuple(
            (
                path,
                tuple(
                    line for line in self._git("blame", "--line-porcelain", "--", path).splitlines()
                    if line.startswith(("author ", "author-time ", "summary "))
                ),
            )
            for path in sorted(set(blame_files))
        )
        return GitContext(
            branch,
            head,
            tuple(sorted(set(changed))),
            commits,
            blame,
            tuple(sorted((pull_request or {}).items())),
            base_snapshot_id,
            current_snapshot_id,
        )

    def _git(self, *arguments: str) -> str:
        process = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode:
            raise GitContextError(process.stderr.strip() or "Git context command failed")
        return process.stdout

    def _git_optional(self, *arguments: str) -> str:
        process = subprocess.run(
            ["git", *arguments], cwd=self.root, text=True, capture_output=True, check=False
        )
        return process.stdout if process.returncode == 0 else ""
