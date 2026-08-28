"""Git repository provenance for semantic snapshots."""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_COMMIT_SHA_PATTERN = re.compile(r'^[0-9a-f]{40}([0-9a-f]{24})?$')
_SAFE_REF_PATTERN = re.compile(r'^refs/[a-zA-Z0-9_./-]+$')


class WorktreeState(enum.Enum):
    """Observed state of the Git worktree at capture time."""
    CLEAN = 'clean'
    DIRTY_TRACKED = 'dirty_tracked'
    DIRTY_UNTRACKED_ONLY = 'dirty_untracked_only'
    UNKNOWN = 'unknown'


class RevisionAlignment(enum.Enum):
    """Alignment between a snapshot's captured provenance and an expected revision."""
    EXACT = 'exact'
    DIRTY_OVERLAY = 'dirty_overlay'
    STALE = 'stale'
    UNKNOWN = 'unknown'
    NON_GIT = 'non_git'
    INCOMPATIBLE = 'incompatible'


@dataclass(frozen=True, slots=True)
class RepositoryProvenance:
    """Immutable Git repository provenance captured at snapshot time.

    All fields use explicit unavailability rather than fabricated identity.
    Non-Git workspaces are supported with vcs='none' and alignment NON_GIT.
    """
    vcs: str  # 'git' or 'none'
    head_sha: str | None  # 40 or 64 hex chars, or None
    head_ref: str | None  # e.g. 'refs/heads/main', or None for detached
    worktree_state: str  # WorktreeState value
    captured_at: str | None  # ISO 8601 UTC timestamp or None
    verification: str  # 'exact', 'best_effort', or 'unavailable'

    def __post_init__(self) -> None:
        if self.vcs not in ('git', 'none'):
            raise ValueError(f'unsupported vcs: {self.vcs!r}')
        if self.head_sha is not None and not _COMMIT_SHA_PATTERN.match(self.head_sha):
            raise ValueError(f'invalid commit SHA: {self.head_sha!r}')
        if self.head_ref is not None and not _SAFE_REF_PATTERN.match(self.head_ref):
            raise ValueError(f'unsafe ref name: {self.head_ref!r}')
        if self.worktree_state not in {s.value for s in WorktreeState}:
            raise ValueError(f'invalid worktree state: {self.worktree_state!r}')
        if self.verification not in ('exact', 'best_effort', 'unavailable'):
            raise ValueError(f'invalid verification: {self.verification!r}')

    def to_dict(self) -> dict[str, Any]:
        return {
            'vcs': self.vcs,
            'head_sha': self.head_sha,
            'head_ref': self.head_ref,
            'worktree_state': self.worktree_state,
            'captured_at': self.captured_at,
            'verification': self.verification,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepositoryProvenance:
        if not isinstance(data, dict):
            raise ValueError('repository_provenance must be an object')
        required = {'vcs', 'head_sha', 'head_ref', 'worktree_state',
                    'captured_at', 'verification'}
        missing = required - data.keys()
        if missing:
            raise ValueError(f'repository_provenance missing fields: {sorted(missing)}')
        return cls(
            vcs=data['vcs'],
            head_sha=data['head_sha'],
            head_ref=data['head_ref'],
            worktree_state=data['worktree_state'],
            captured_at=data['captured_at'],
            verification=data['verification'],
        )

    @classmethod
    def non_git(cls) -> RepositoryProvenance:
        """Create provenance for a non-Git workspace."""
        return cls(
            vcs='none',
            head_sha=None,
            head_ref=None,
            worktree_state=WorktreeState.UNKNOWN.value,
            captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            verification='unavailable',
        )

    def check_revision(self, expected_sha: str) -> RevisionAlignment:
        """Check alignment between this provenance and an expected Git revision."""
        if self.vcs == 'none':
            return RevisionAlignment.NON_GIT
        if self.head_sha is None:
            return RevisionAlignment.UNKNOWN
        if not _COMMIT_SHA_PATTERN.match(expected_sha):
            return RevisionAlignment.INCOMPATIBLE
        if self.head_sha != expected_sha:
            return RevisionAlignment.STALE
        if self.worktree_state == WorktreeState.CLEAN.value:
            return RevisionAlignment.EXACT
        if self.worktree_state == WorktreeState.DIRTY_UNTRACKED_ONLY.value:
            return RevisionAlignment.EXACT
        if self.worktree_state == WorktreeState.DIRTY_TRACKED.value:
            return RevisionAlignment.DIRTY_OVERLAY
        return RevisionAlignment.UNKNOWN


def capture_git_provenance(repository_root: Path) -> RepositoryProvenance:
    """Capture current Git repository provenance from the filesystem.

    Returns a non-git provenance if the repository is not a Git workspace
    or if git is not available. Never raises for operational Git failures.
    """
    root = Path(repository_root).resolve()
    git_dir = root / '.git'
    if not git_dir.exists():
        return RepositoryProvenance.non_git()

    try:
        head_sha = _git_output(root, 'rev-parse', 'HEAD')
    except (subprocess.SubprocessError, OSError, ValueError):
        return RepositoryProvenance(
            vcs='git',
            head_sha=None,
            head_ref=None,
            worktree_state=WorktreeState.UNKNOWN.value,
            captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            verification='best_effort',
        )

    if not _COMMIT_SHA_PATTERN.match(head_sha):
        return RepositoryProvenance(
            vcs='git',
            head_sha=None,
            head_ref=None,
            worktree_state=WorktreeState.UNKNOWN.value,
            captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            verification='best_effort',
        )

    # Capture symbolic ref (branch name)
    head_ref: str | None = None
    try:
        ref = _git_output(root, 'symbolic-ref', 'HEAD')
        if _SAFE_REF_PATTERN.match(ref):
            head_ref = ref
    except (subprocess.SubprocessError, OSError, ValueError):
        pass  # Detached HEAD — head_ref stays None

    # Capture worktree state
    worktree_state = _capture_worktree_state(root)

    captured_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    return RepositoryProvenance(
        vcs='git',
        head_sha=head_sha,
        head_ref=head_ref,
        worktree_state=worktree_state,
        captured_at=captured_at,
        verification='exact',
    )


def _capture_worktree_state(root: Path) -> str:
    """Determine worktree cleanliness via git status --porcelain."""
    try:
        output = _git_output(root, 'status', '--porcelain', '--untracked-files=normal')
    except (subprocess.SubprocessError, OSError, ValueError):
        return WorktreeState.UNKNOWN.value

    if not output:
        return WorktreeState.CLEAN.value

    # Check if all changes are untracked (prefixed with '??')
    lines = output.strip().splitlines()
    if all(line.startswith('?? ') for line in lines if line.strip()):
        return WorktreeState.DIRTY_UNTRACKED_ONLY.value

    return WorktreeState.DIRTY_TRACKED.value


def _git_output(root: Path, *args: str) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ['git', *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(
            f'git {args[0]} failed: {result.stderr.strip()}'
        )
    return result.stdout.strip()
