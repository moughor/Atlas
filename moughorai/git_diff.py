"""Git diff collection and changed-line filtering for Atlas reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
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


@dataclass(frozen=True, slots=True)
class DiffFile:
    old_path: str | None
    new_path: str | None
    hunks: tuple[DiffHunk, ...] = ()
    binary: bool = False
    renamed: bool = False

    @property
    def path(self) -> str | None:
        return self.new_path or self.old_path

    @property
    def added_lines(self) -> tuple[int, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.added_lines)


@dataclass(frozen=True, slots=True)
class GitDiff:
    files: tuple[DiffFile, ...]
    base: str | None = None
    head: str | None = None
    staged: bool = False

    def file(self, path: str | Path) -> DiffFile | None:
        key = _path(path)
        return next((item for item in self.files if item.new_path == key or item.old_path == key), None)

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files if item.path is not None)


class UnifiedDiffParser:
    _HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    def parse(
        self,
        text: str,
        *,
        base: str | None = None,
        head: str | None = None,
        staged: bool = False,
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
            elif line.startswith("--- "):
                old_path = _header_path(line[4:])
            elif line.startswith("+++ "):
                new_path = _header_path(line[4:])
            elif line.startswith("rename from "):
                old_path = _path(line[len("rename from "):])
                renamed = True
            elif line.startswith("rename to "):
                new_path = _path(line[len("rename to "):])
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
        return GitDiff(tuple(sorted(files, key=lambda item: item.path or "")), base, head, staged)


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
        for value in (base, head):
            if value is not None:
                self._validate_ref(value)
        command = ["git", "-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff", "--unified=0", "--find-renames"]
        if staged:
            command.append("--cached")
        if base is not None:
            command.append(base)
        if head is not None:
            command.append(head)
        command.append("--")
        completed = subprocess.run(command, cwd=self.root, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if completed.returncode:
            raise GitDiffError(completed.stderr.strip() or "git diff failed")
        return UnifiedDiffParser().parse(completed.stdout, base=base, head=head, staged=staged)

    def _validate_ref(self, value: str) -> None:
        if not value.strip() or value.startswith("-"):
            raise GitDiffError(f"invalid Git reference: {value!r}")
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
    value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return _path(value)


def _path(value: str | Path) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).as_posix().removeprefix("./")
