from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import tempfile
from typing import Protocol

from .models import RuleContext, RuleFinding
from .runtime import Rule, RuleAuthoringError, RuleExecutionError


class FixSafety(str, Enum):
    SAFE = "safe"
    REVIEW = "review"


class AutoFixError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceEdit:
    path: Path
    start_offset: int
    end_offset: int
    replacement: str
    expected_text: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if self.start_offset < 0 or self.end_offset < self.start_offset:
            raise AutoFixError("source edit offsets are invalid")


@dataclass(frozen=True, slots=True)
class RuleFix:
    rule_id: str
    title: str
    edits: tuple[SourceEdit, ...]
    safety: FixSafety = FixSafety.SAFE

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise AutoFixError("fix rule_id must not be empty")
        if not self.title.strip():
            raise AutoFixError("fix title must not be empty")
        if not self.edits:
            raise AutoFixError("fix must contain at least one edit")
        object.__setattr__(self, "safety", FixSafety(self.safety))
        if self.edits != tuple(sorted(self.edits, key=_edit_key)):
            raise AutoFixError("fix edits must be sorted")
        if len(self.edits) != len(set(self.edits)):
            raise AutoFixError("fix edits must be unique")


class FixProvider(Protocol):
    def fix(self, context: RuleContext, finding: RuleFinding) -> RuleFix | None: ...


@dataclass(frozen=True, slots=True)
class AutoFixResult:
    sources: tuple[tuple[Path, str], ...]
    changed_files: tuple[Path, ...]
    applied_rules: tuple[str, ...]
    skipped_review: int

    def as_dict(self) -> dict[Path, str]:
        return dict(self.sources)


@dataclass(frozen=True, slots=True)
class FixPlan:
    fixes: tuple[RuleFix, ...]

    def apply(
        self,
        sources: Mapping[str | Path, str],
        *,
        include_review: bool = False,
    ) -> AutoFixResult:
        current = {Path(path): text for path, text in sources.items()}
        selected = tuple(
            fix for fix in self.fixes
            if include_review or fix.safety is FixSafety.SAFE
        )
        edits = tuple(edit for fix in selected for edit in fix.edits)
        _validate_conflicts(edits)
        by_path: dict[Path, list[SourceEdit]] = {}
        for edit in edits:
            if edit.path not in current:
                raise AutoFixError(f"missing source for edit: {edit.path.as_posix()}")
            by_path.setdefault(edit.path, []).append(edit)
        changed: list[Path] = []
        for path in sorted(by_path, key=Path.as_posix):
            text = current[path]
            for edit in sorted(by_path[path], key=_edit_key, reverse=True):
                if edit.end_offset > len(text):
                    raise AutoFixError(f"edit is outside source: {path.as_posix()}")
                actual = text[edit.start_offset:edit.end_offset]
                if edit.expected_text is not None and actual != edit.expected_text:
                    raise AutoFixError(
                        f"stale source for {path.as_posix()} at "
                        f"{edit.start_offset}:{edit.end_offset}"
                    )
                text = text[:edit.start_offset] + edit.replacement + text[edit.end_offset:]
            if text != current[path]:
                current[path] = text
                changed.append(path)
        return AutoFixResult(
            tuple(sorted(current.items(), key=lambda item: item[0].as_posix())),
            tuple(changed),
            tuple(sorted({fix.rule_id for fix in selected})),
            sum(fix.safety is FixSafety.REVIEW for fix in self.fixes) if not include_review else 0,
        )


class AutoFixPlanner:
    def plan(
        self,
        rules: Iterable[Rule],
        context: RuleContext,
        findings: Iterable[RuleFinding],
    ) -> FixPlan:
        rule_map: dict[str, Rule] = {}
        for rule in rules:
            if rule.rule_id in rule_map:
                raise RuleAuthoringError(f"duplicate rule_id: {rule.rule_id}")
            rule_map[rule.rule_id] = rule
        fixes: list[RuleFix] = []
        for finding in sorted(findings, key=_finding_key):
            rule = rule_map.get(finding.rule_id)
            provider = getattr(rule, "fix", None) if rule is not None else None
            if not callable(provider):
                continue
            try:
                fix = provider(context, finding)
            except Exception as exc:
                raise RuleExecutionError(
                    f"{finding.rule_id} fix: {type(exc).__name__}: {exc}"
                ) from exc
            if fix is None:
                continue
            if not isinstance(fix, RuleFix):
                raise RuleAuthoringError(f"{finding.rule_id}: fix must return RuleFix or None")
            if fix.rule_id != finding.rule_id:
                raise RuleAuthoringError(f"{finding.rule_id}: fix rule id mismatch")
            fixes.append(fix)
        return FixPlan(tuple(sorted(fixes, key=_fix_key)))


class FileFixApplier:
    def apply(
        self,
        plan: FixPlan,
        root: str | Path,
        *,
        include_review: bool = False,
        dry_run: bool = False,
    ) -> AutoFixResult:
        resolved_root = Path(root).resolve()
        selected = [
            fix for fix in plan.fixes
            if include_review or fix.safety is FixSafety.SAFE
        ]
        paths = sorted({edit.path for fix in selected for edit in fix.edits}, key=Path.as_posix)
        resolved: dict[Path, Path] = {}
        sources: dict[Path, str] = {}
        for path in paths:
            target = (resolved_root / path).resolve() if not path.is_absolute() else path.resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError as exc:
                raise AutoFixError(f"fix path escapes root: {path.as_posix()}") from exc
            resolved[path] = target
            sources[path] = target.read_text(encoding="utf-8")
        result = plan.apply(sources, include_review=include_review)
        if dry_run or not result.changed_files:
            return result
        staged: dict[Path, Path] = {}
        originals = {path: sources[path] for path in result.changed_files}
        try:
            for path in result.changed_files:
                target = resolved[path]
                fd, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
                temporary = Path(name)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(result.as_dict()[path])
                    handle.flush()
                    os.fsync(handle.fileno())
                staged[path] = temporary
            replaced: list[Path] = []
            try:
                for path in result.changed_files:
                    os.replace(staged[path], resolved[path])
                    replaced.append(path)
            except Exception:
                for path in replaced:
                    resolved[path].write_text(originals[path], encoding="utf-8", newline="")
                raise
        finally:
            for temporary in staged.values():
                if temporary.exists():
                    temporary.unlink()
        return result


def _validate_conflicts(edits: tuple[SourceEdit, ...]) -> None:
    by_path: dict[Path, list[SourceEdit]] = {}
    for edit in edits:
        by_path.setdefault(edit.path, []).append(edit)
    for path, items in by_path.items():
        ordered = sorted(items, key=_edit_key)
        for previous, current in zip(ordered, ordered[1:]):
            overlaps = current.start_offset < previous.end_offset
            same_insertion = (
                current.start_offset == current.end_offset
                == previous.start_offset == previous.end_offset
            )
            if overlaps or same_insertion:
                raise AutoFixError(f"conflicting edits for {path.as_posix()}")


def _edit_key(edit: SourceEdit) -> tuple[str, int, int, str]:
    return (edit.path.as_posix(), edit.start_offset, edit.end_offset, edit.replacement)


def _fix_key(fix: RuleFix) -> tuple[str, str, str, tuple[tuple[str, int, int, str], ...]]:
    return (fix.rule_id, fix.safety.value, fix.title, tuple(_edit_key(edit) for edit in fix.edits))


def _finding_key(finding: RuleFinding) -> tuple[str, str, int, int, str]:
    return (
        finding.rule_id,
        finding.location.path.as_posix(),
        finding.location.line,
        finding.location.column,
        finding.message,
    )
