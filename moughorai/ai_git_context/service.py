from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
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


@dataclass(frozen=True, order=True, slots=True)
class GitFileChange:
    """One source-free path change from a bounded Git history window."""

    commit: str
    timestamp: str
    contributor_id: str
    path: str
    additions: int | None
    deletions: int | None

    def __post_init__(self) -> None:
        if not self.commit.strip() or not self.timestamp.strip():
            raise ValueError("Git file changes require a commit and timestamp")
        for name in ("additions", "deletions"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"Git file change {name} must be non-negative")
        normalized = self.path.replace("\\", "/").removeprefix("./")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError("Git file change path must be workspace-relative")
        object.__setattr__(self, "path", path.as_posix())

    def to_dict(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "timestamp": self.timestamp,
            "contributor_id": self.contributor_id,
            "path": self.path,
            "additions": self.additions,
            "deletions": self.deletions,
        }


@dataclass(frozen=True, slots=True)
class GitHistoryWindow:
    """Deterministic, bounded history facts for downstream semantic analysis."""

    head: str
    commit_limit: int
    commits_scanned: int
    changes: tuple[GitFileChange, ...]
    ignored_records: int = 0
    workspace_prefix: str = "."
    shallow: bool = False
    truncated: bool = False
    merge_policy: str = "exclude-merges"

    def __post_init__(self) -> None:
        if self.commit_limit < 0 or self.commits_scanned < 0 or self.ignored_records < 0:
            raise ValueError("Git history counts must be non-negative")
        if not self.head.strip():
            raise ValueError("Git history head must not be empty")
        if self.commits_scanned > self.commit_limit:
            raise ValueError("Git commits scanned must not exceed the configured limit")
        if self.truncated and (
            self.commit_limit == 0 or self.commits_scanned != self.commit_limit
        ):
            raise ValueError("truncated Git history must fill a positive commit window")
        prefix = PurePosixPath(self.workspace_prefix.replace("\\", "/"))
        if prefix.is_absolute() or ".." in prefix.parts:
            raise ValueError("Git workspace prefix must be repository-relative")
        if not self.merge_policy.strip():
            raise ValueError("Git merge policy must not be empty")
        object.__setattr__(
            self,
            "workspace_prefix",
            prefix.as_posix() if prefix.parts else ".",
        )
        object.__setattr__(self, "changes", tuple(sorted(self.changes)))

    @property
    def limit_reached(self) -> bool:
        return self.truncated

    def to_dict(self) -> dict[str, object]:
        return {
            "head": self.head,
            "commit_limit": self.commit_limit,
            "commits_scanned": self.commits_scanned,
            "limit_reached": self.limit_reached,
            "ignored_records": self.ignored_records,
            "workspace_prefix": self.workspace_prefix,
            "shallow": self.shallow,
            "truncated": self.truncated,
            "merge_policy": self.merge_policy,
            "changes": [item.to_dict() for item in self.changes],
        }


class GitContextService:
    _HISTORY_MARKER = "@@ATLAS-COMMIT@@"

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

    def collect_history(self, *, commit_limit: int = 200) -> GitHistoryWindow:
        """Collect one repository-wide history window without per-file Git calls.

        Paths and numeric change facts are retained. Contributor e-mail values
        become pseudonymous hashes before leaving this service, and PR132 does
        not publish those hashes or contributor identities.
        """

        if commit_limit < 0:
            raise GitContextError("commit_limit must be non-negative")
        head = self._git_optional("rev-parse", "--verify", "HEAD").strip()
        if not head:
            raise GitContextError(f"Git history is unavailable for {self.root}")
        top_level_value = self._git_optional("rev-parse", "--show-toplevel").strip()
        if not top_level_value:
            raise GitContextError(f"Git top-level directory is unavailable for {self.root}")
        top_level = Path(top_level_value).resolve()
        try:
            workspace_prefix_path = self.root.relative_to(top_level)
        except ValueError as exc:
            raise GitContextError("workspace is outside the resolved Git repository") from exc
        workspace_prefix = workspace_prefix_path.as_posix() or "."
        shallow = self._git_optional("rev-parse", "--is-shallow-repository").strip() == "true"
        if commit_limit == 0:
            return GitHistoryWindow(
                head,
                0,
                0,
                (),
                workspace_prefix=workspace_prefix,
                shallow=shallow,
            )
        raw = self._git(
            "-c",
            "core.quotepath=false",
            "log",
            f"-n{commit_limit + 1}",
            "--date=iso-strict",
            f"--format={self._HISTORY_MARKER}%H%x1f%aE%x1f%aI",
            "--numstat",
            "--no-renames",
            "--no-merges",
            "--relative",
            "--",
            ".",
        )
        changes: list[GitFileChange] = []
        commits: set[str] = set()
        commit_order: list[str] = []
        ignored = 0
        truncated = False
        current: tuple[str, str, str] | None = None
        for line in raw.splitlines():
            if line.startswith(self._HISTORY_MARKER):
                fields = line[len(self._HISTORY_MARKER):].split("\x1f")
                if len(fields) != 3 or not fields[0]:
                    current = None
                    ignored += 1
                    continue
                commit, email, timestamp = fields
                if len(commit_order) >= commit_limit:
                    current = None
                    truncated = True
                    continue
                commit_order.append(commit)
                normalized_email = email.strip().casefold()
                contributor = (
                    ""
                    if not normalized_email
                    else "git-contributor:" + hashlib.sha256(
                        normalized_email.encode("utf-8")
                    ).hexdigest()
                )
                current = (commit, contributor, timestamp)
                commits.add(commit)
                continue
            if current is None or not line.strip():
                continue
            fields = line.split("\t", 2)
            if len(fields) != 3:
                ignored += 1
                continue
            additions = self._number(fields[0])
            deletions = self._number(fields[1])
            if (
                additions is None and fields[0] != "-"
                or deletions is None and fields[1] != "-"
            ):
                ignored += 1
                continue
            path = self._history_path(fields[2])
            if path is None:
                ignored += 1
                continue
            changes.append(GitFileChange(
                current[0],
                current[2],
                current[1],
                path,
                additions,
                deletions,
            ))
        return GitHistoryWindow(
            head=head,
            commit_limit=commit_limit,
            commits_scanned=len(commits),
            changes=tuple(changes),
            ignored_records=ignored,
            workspace_prefix=workspace_prefix,
            shallow=shallow,
            truncated=truncated,
            merge_policy="exclude-merges",
        )

    @staticmethod
    def _number(value: str) -> int | None:
        if value == "-":
            return None
        try:
            result = int(value)
        except ValueError:
            return None
        return result if result >= 0 else None

    @staticmethod
    def _history_path(value: str) -> str | None:
        normalized = value.replace("\\", "/").removeprefix("./")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            return None
        return path.as_posix()

    def _git(self, *arguments: str) -> str:
        process = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        if process.returncode:
            error = process.stderr.decode("utf-8", errors="replace").strip()
            raise GitContextError(error or "Git context command failed")
        try:
            return process.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitContextError("Git command output is not valid UTF-8") from exc

    def _git_optional(self, *arguments: str) -> str:
        process = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        if process.returncode:
            return ""
        try:
            return process.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return ""
