"""Git diff collection and changed-line filtering for Atlas reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
from typing import Any

from .workspace import ProjectRun, WorkspaceRunReport


class GitDiffError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    added_lines: tuple[int, ...]
    removed_lines: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in ("old_start", "old_count", "new_start", "new_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"diff hunk {name} must be a non-negative integer")
        for name, start_name, count_name in (
            ("added_lines", "new_start", "new_count"),
            ("removed_lines", "old_start", "old_count"),
        ):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)):
                raise TypeError(f"diff hunk {name} must be an array")
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in values
            ):
                raise ValueError(f"diff hunk {name} must contain positive line numbers")
            normalized = tuple(sorted(set(values)))
            start = getattr(self, start_name)
            count = getattr(self, count_name)
            if normalized and (
                count == 0
                or normalized[0] < start
                or normalized[-1] >= start + count
            ):
                raise ValueError(
                    f"diff hunk {name} must stay within its declared range"
                )
            object.__setattr__(self, name, normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "old_start": self.old_start,
            "old_count": self.old_count,
            "new_start": self.new_start,
            "new_count": self.new_count,
            "added_lines": list(self.added_lines),
            "removed_lines": list(self.removed_lines),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DiffHunk:
        _require_fields(
            value,
            {
                "old_start", "old_count", "new_start", "new_count",
                "added_lines", "removed_lines",
            },
            "diff hunk",
        )
        return cls(
            _strict_integer(value.get("old_start"), "diff hunk old_start"),
            _strict_integer(value.get("old_count"), "diff hunk old_count"),
            _strict_integer(value.get("new_start"), "diff hunk new_start"),
            _strict_integer(value.get("new_count"), "diff hunk new_count"),
            _line_numbers(value.get("added_lines"), "diff hunk added_lines"),
            _line_numbers(value.get("removed_lines"), "diff hunk removed_lines"),
        )


@dataclass(frozen=True, slots=True)
class DiffFile:
    old_path: str | None
    new_path: str | None
    hunks: tuple[DiffHunk, ...] = ()
    binary: bool = False
    renamed: bool = False

    def __post_init__(self) -> None:
        if self.old_path is None and self.new_path is None:
            raise ValueError("diff files require an old or new path")
        for name in ("old_path", "new_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _validated_path(value))
        if not isinstance(self.binary, bool) or not isinstance(self.renamed, bool):
            raise TypeError("diff file binary and renamed flags must be booleans")
        if not isinstance(self.hunks, (list, tuple)) or any(
            not isinstance(item, DiffHunk) for item in self.hunks
        ):
            raise TypeError("diff file hunks must use DiffHunk")
        hunks = tuple(sorted(
            self.hunks,
            key=lambda item: (
                item.old_start,
                item.new_start,
                item.old_count,
                item.new_count,
                item.added_lines,
                item.removed_lines,
            ),
        ))
        if len(set(hunks)) != len(hunks):
            raise ValueError("diff files must not contain duplicate hunks")
        if self.binary and hunks:
            raise ValueError("binary diff files must not contain text hunks")
        if self.renamed and (
            self.old_path is None
            or self.new_path is None
            or self.old_path == self.new_path
        ):
            raise ValueError("renamed diff files require distinct old and new paths")
        if (
            not self.renamed
            and self.old_path is not None
            and self.new_path is not None
            and self.old_path != self.new_path
        ):
            raise ValueError("different old and new paths require the renamed flag")
        object.__setattr__(
            self,
            "hunks",
            hunks,
        )

    @property
    def path(self) -> str | None:
        return self.new_path or self.old_path

    @property
    def added_lines(self) -> tuple[int, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.added_lines)

    @property
    def removed_lines(self) -> tuple[int, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.removed_lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "old_path": self.old_path,
            "new_path": self.new_path,
            "hunks": [item.to_dict() for item in self.hunks],
            "binary": self.binary,
            "renamed": self.renamed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DiffFile:
        _require_fields(
            value,
            {"old_path", "new_path", "hunks", "binary", "renamed"},
            "diff file",
        )
        raw_hunks = value.get("hunks", ())
        if not isinstance(raw_hunks, (list, tuple)) or any(
            not isinstance(item, Mapping) for item in raw_hunks
        ):
            raise TypeError("diff file hunks must be an array of objects")
        return cls(
            _optional_string(value.get("old_path"), "diff file old_path"),
            _optional_string(value.get("new_path"), "diff file new_path"),
            tuple(DiffHunk.from_dict(item) for item in raw_hunks),
            _strict_boolean(value.get("binary", False), "diff file binary"),
            _strict_boolean(value.get("renamed", False), "diff file renamed"),
        )


@dataclass(frozen=True, slots=True)
class GitDiff:
    files: tuple[DiffFile, ...]
    base: str | None = None
    head: str | None = None
    staged: bool = False
    repository_head: str | None = None
    base_commit: str | None = None
    head_commit: str | None = None
    workspace_prefix: str = "."

    def __post_init__(self) -> None:
        if not isinstance(self.files, (list, tuple)) or any(
            not isinstance(item, DiffFile) for item in self.files
        ):
            raise TypeError("Git diff files must use DiffFile")
        files = tuple(sorted(
            self.files,
            key=lambda item: (item.path or "", item.old_path or "", item.new_path or ""),
        ))
        identities = tuple((item.old_path, item.new_path) for item in files)
        if len(set(identities)) != len(identities):
            raise ValueError("Git diff files must have unique path identities")
        selected_paths = tuple(item.path for item in files)
        if len(set(selected_paths)) != len(selected_paths):
            raise ValueError("Git diff files must have unique selected paths")
        object.__setattr__(
            self,
            "files",
            files,
        )
        for name in ("base", "head"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _validated_ref_name(value, f"Git diff {name}"),
                )
        for name in ("repository_head", "base_commit", "head_commit"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _validated_commit_id(value, f"Git diff {name}"),
                )
        if not isinstance(self.staged, bool):
            raise TypeError("Git diff staged flag must be a boolean")
        if self.head is not None and self.base is None:
            raise ValueError("Git diff head requires a base")
        if self.staged and self.head is not None:
            raise ValueError("staged Git diffs cannot specify a head")
        if self.head_commit is not None and self.base_commit is None:
            raise ValueError("Git diff head commit requires a base commit")
        if not isinstance(self.workspace_prefix, str):
            raise TypeError("Git diff workspace prefix must be a string")
        prefix = self.workspace_prefix.replace("\\", "/")
        if prefix != prefix.strip():
            raise ValueError("Git diff workspace prefix must be workspace-relative")
        if not prefix or _path(prefix) == ".":
            prefix = "."
        else:
            prefix = _validated_path(prefix)
        object.__setattr__(self, "workspace_prefix", prefix)

    def file(self, path: str | Path) -> DiffFile | None:
        key = _validated_path(path)
        return next((item for item in self.files if item.new_path == key or item.old_path == key), None)

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files if item.path is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "files": [item.to_dict() for item in self.files],
            "base": self.base,
            "head": self.head,
            "staged": self.staged,
            "repository_head": self.repository_head,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "workspace_prefix": self.workspace_prefix,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    @property
    def fingerprint(self) -> str:
        payload = self.to_dict()
        # Repository HEAD is provenance, not a selected input for ordinary
        # working-tree comparisons. Staged and explicit comparisons are bound by
        # their resolved base/head commit fields instead.
        payload.pop("repository_head")
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"git-diff:{digest}"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> GitDiff:
        _require_fields(
            value,
            {
                "files", "base", "head", "staged", "repository_head",
                "base_commit", "head_commit", "workspace_prefix",
            },
            "Git diff",
        )
        raw_files = value.get("files", ())
        if not isinstance(raw_files, (list, tuple)) or any(
            not isinstance(item, Mapping) for item in raw_files
        ):
            raise TypeError("Git diff files must be an array of objects")
        return cls(
            tuple(DiffFile.from_dict(item) for item in raw_files),
            _optional_string(value.get("base"), "Git diff base"),
            _optional_string(value.get("head"), "Git diff head"),
            _strict_boolean(value.get("staged", False), "Git diff staged"),
            _optional_string(value.get("repository_head"), "Git repository head"),
            _optional_string(value.get("base_commit"), "Git diff base commit"),
            _optional_string(value.get("head_commit"), "Git diff head commit"),
            _strict_string(value.get("workspace_prefix"), "Git diff workspace prefix"),
        )


class UnifiedDiffParser:
    _HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    def parse(
        self,
        text: str,
        *,
        base: str | None = None,
        head: str | None = None,
        staged: bool = False,
        repository_head: str | None = None,
        base_commit: str | None = None,
        head_commit: str | None = None,
        workspace_prefix: str = ".",
    ) -> GitDiff:
        files: list[DiffFile] = []
        old_path: str | None = None
        new_path: str | None = None
        hunks: list[DiffHunk] = []
        binary = False
        renamed = False
        lines = text.splitlines()
        index = 0

        def finish() -> None:
            nonlocal old_path, new_path, hunks, binary, renamed
            if old_path is not None or new_path is not None:
                files.append(DiffFile(old_path, new_path, tuple(hunks), binary, renamed))
            old_path = new_path = None
            hunks = []
            binary = renamed = False

        while index < len(lines):
            line = lines[index]
            if line.startswith("diff --git "):
                finish()
                old_path, new_path = _diff_git_paths(line)
            elif line.startswith("--- "):
                old_path = _header_path(line[4:])
            elif line.startswith("+++ "):
                new_path = _header_path(line[4:])
            elif line.startswith("rename from "):
                old_path = _metadata_path(line[len("rename from "):])
                renamed = True
            elif line.startswith("rename to "):
                new_path = _metadata_path(line[len("rename to "):])
                renamed = True
            elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
                binary = True
            else:
                match = self._HUNK.match(line)
                if match:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2) or 1)
                    new_start = int(match.group(3))
                    new_count = int(match.group(4) or 1)
                    old_line = old_start
                    new_line = new_start
                    added: list[int] = []
                    removed: list[int] = []
                    index += 1
                    while index < len(lines) and not lines[index].startswith(("diff --git ", "@@ ")):
                        content = lines[index]
                        if content.startswith("+") and not content.startswith("+++"):
                            added.append(new_line)
                            new_line += 1
                        elif content.startswith("-") and not content.startswith("---"):
                            removed.append(old_line)
                            old_line += 1
                        elif content.startswith(" "):
                            old_line += 1
                            new_line += 1
                        elif content.startswith("\\"):
                            pass
                        else:
                            break
                        index += 1
                    hunks.append(DiffHunk(old_start, old_count, new_start, new_count, tuple(added), tuple(removed)))
                    continue
            index += 1
        finish()
        return GitDiff(
            tuple(files),
            base,
            head,
            staged,
            repository_head,
            base_commit,
            head_commit,
            workspace_prefix,
        )


class GitDiffService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def collect(
        self,
        *,
        base: str | None = None,
        head: str | None = None,
        staged: bool = False,
    ) -> GitDiff:
        if head is not None and base is None:
            raise GitDiffError("diff head requires a base")
        if staged and head is not None:
            raise GitDiffError("staged diff cannot specify a head")
        try:
            declared_base = (
                _validated_ref_name(base, "Git diff base") if base is not None else None
            )
            declared_head = (
                _validated_ref_name(head, "Git diff head") if head is not None else None
            )
        except (TypeError, ValueError) as exc:
            invalid = base if base is not None else head
            raise GitDiffError(f"invalid Git reference: {invalid!r}") from exc
        resolved_base = (
            self._validate_ref(declared_base) if declared_base is not None else None
        )
        resolved_head = (
            self._validate_ref(declared_head) if declared_head is not None else None
        )
        repository_head = self._optional_ref("HEAD")
        workspace_prefix = self._workspace_prefix()
        if staged and resolved_base is None:
            resolved_base = repository_head
        command = ["git", "-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff", "--unified=0", "--find-renames"]
        if staged:
            command.append("--cached")
        if resolved_base is not None:
            command.append(resolved_base)
        if resolved_head is not None:
            command.append(resolved_head)
        command.append("--")
        completed = subprocess.run(command, cwd=self.root, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if completed.returncode:
            raise GitDiffError(completed.stderr.strip() or "git diff failed")
        parsed = UnifiedDiffParser().parse(
            completed.stdout,
            base=declared_base,
            head=declared_head,
            staged=staged,
            repository_head=repository_head,
            base_commit=resolved_base,
            head_commit=resolved_head,
            workspace_prefix=workspace_prefix,
        )
        return self._workspace_relative(parsed)

    def _validate_ref(self, value: str) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if completed.returncode:
            raise GitDiffError(f"unknown Git reference: {value}")
        try:
            return _validated_commit_id(
                completed.stdout.strip(), "resolved Git reference"
            )
        except (TypeError, ValueError) as exc:
            raise GitDiffError("Git reference did not resolve to a commit ID") from exc

    def _optional_ref(self, value: str) -> str | None:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if completed.returncode:
            return None
        try:
            return _validated_commit_id(
                completed.stdout.strip(), "resolved Git reference"
            )
        except (TypeError, ValueError):
            return None

    def _workspace_prefix(self) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if completed.returncode:
            raise GitDiffError(completed.stderr.strip() or "not a git repository")
        top_level_value = completed.stdout.rstrip("\r\n")
        if (
            not top_level_value
            or any(character in top_level_value for character in "\x00\r\n")
        ):
            raise GitDiffError("Git top-level directory is invalid")
        top_level = Path(top_level_value).resolve()
        try:
            relative = self.root.relative_to(top_level)
        except ValueError as exc:
            raise GitDiffError("workspace is outside the resolved Git repository") from exc
        return relative.as_posix() or "."

    @staticmethod
    def _workspace_relative(diff: GitDiff) -> GitDiff:
        if diff.workspace_prefix == ".":
            return diff
        prefix = diff.workspace_prefix.rstrip("/") + "/"

        def relative(path: str | None) -> str | None:
            if path is None:
                return None
            if not path.startswith(prefix):
                raise GitDiffError(
                    "Git diff contains a path outside the selected workspace"
                )
            return path[len(prefix):]

        return replace(
            diff,
            files=tuple(
                replace(
                    item,
                    old_path=relative(item.old_path),
                    new_path=relative(item.new_path),
                )
                for item in diff.files
            ),
        )


class GitDiffFilter:
    def filter_report(
        self,
        report: WorkspaceRunReport,
        diff: GitDiff,
        *,
        root: str | Path | None = None,
    ) -> WorkspaceRunReport:
        resolved_root = Path(root).resolve() if root is not None else None
        line_map = {
            item.new_path: set(item.added_lines)
            for item in diff.files
            if item.new_path is not None
        }
        runs = tuple(self._filter_run(run, line_map, resolved_root) for run in report.runs)
        return replace(report, runs=runs)

    def _filter_run(
        self,
        run: ProjectRun,
        line_map: Mapping[str, set[int]],
        root: Path | None,
    ) -> ProjectRun:
        if not isinstance(run.value, Mapping) or "findings" not in run.value:
            return run
        raw = run.value.get("findings", ())
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Iterable):
            return run
        findings = [
            dict(finding)
            for finding in raw
            if isinstance(finding, Mapping) and _changed_finding(finding, line_map, root)
        ]
        value = dict(run.value)
        value["findings"] = findings
        value["git_diff"] = {
            "changed_findings": len(findings),
            "total_findings": sum(isinstance(item, Mapping) for item in raw),
        }
        return replace(run, value=value)


def _changed_finding(finding: Mapping[str, Any], line_map: Mapping[str, set[int]], root: Path | None) -> bool:
    nested = finding.get("location")
    source = nested if isinstance(nested, Mapping) else finding
    raw_path = source.get("path", source.get("file"))
    raw_line = source.get("line", source.get("start_line"))
    if raw_path is None or raw_line is None:
        return False
    try:
        line = int(raw_line)
    except (TypeError, ValueError):
        return False
    path = Path(str(raw_path))
    if root is not None and path.is_absolute():
        try:
            path = path.resolve().relative_to(root)
        except ValueError:
            return False
    return line in line_map.get(_path(path), set())


def _header_path(value: str) -> str | None:
    value = _decode_git_path(value, allow_tab_suffix=True)
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return _validated_path(value)


def _diff_git_paths(line: str) -> tuple[str, str]:
    raw = line[len("diff --git "):]
    if "\\" in raw:
        raise ValueError("quoted or escaped Git diff paths are unsupported")
    try:
        values = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ValueError("malformed Git diff path header") from exc
    if len(values) != 2 or not values[0].startswith("a/") or not values[1].startswith("b/"):
        raise ValueError("malformed Git diff path header")
    return _validated_path(values[0][2:]), _validated_path(values[1][2:])


def _metadata_path(value: str) -> str:
    return _validated_path(_decode_git_path(value))


def _decode_git_path(value: str, *, allow_tab_suffix: bool = False) -> str:
    raw = value
    if raw.startswith('"'):
        if "\\" in raw:
            raise ValueError("quoted or escaped Git diff paths are unsupported")
        try:
            values = shlex.split(raw, posix=True)
        except ValueError as exc:
            raise ValueError("malformed Git diff path") from exc
        if len(values) != 1:
            raise ValueError("malformed Git diff path")
        return values[0]
    if allow_tab_suffix:
        raw = raw.split("\t", 1)[0]
    return raw


def _path(value: str | Path) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).as_posix().removeprefix("./")


def _validated_path(value: str | Path) -> str:
    original = str(value)
    if original != original.strip():
        raise ValueError("Git diff paths must be safe workspace-relative paths")
    raw = original.replace("\\", "/")
    normalized = _path(raw)
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized == "."
        or len(normalized) > 4_096
        or path.is_absolute()
        or ".." in path.parts
        or re.match(r"^[A-Za-z]:", normalized)
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
        or "\ufffd" in normalized
    ):
        raise ValueError("Git diff paths must be safe workspace-relative paths")
    return normalized


def _validated_ref_name(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 1_024
        or normalized.startswith("-")
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError(f"{label} must be a safe non-empty Git reference")
    return normalized


def _validated_commit_id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip().lower()
    if len(normalized) not in {40, 64} or re.fullmatch(r"[0-9a-f]+", normalized) is None:
        raise ValueError(f"{label} must be a full Git commit ID")
    return normalized


def _strict_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _strict_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or null")
    return value


def _strict_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _line_numbers(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label} must be an array")
    return tuple(_strict_integer(item, f"{label} entry") for item in value)


def _require_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    if set(value) != expected:
        raise ValueError(f"invalid {label} fields")
