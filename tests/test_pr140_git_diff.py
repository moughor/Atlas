from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
import subprocess

import pytest

import moughorai.git_diff as git_diff_module
from moughorai.git_diff import (
    DiffFile,
    DiffHunk,
    GitDiff,
    GitDiffError,
    GitDiffService,
    UnifiedDiffParser,
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(root: Path) -> tuple[str, str]:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "atlas@example.test")
    _git(root, "config", "user.name", "Atlas Tests")
    source = root / "src" / "Main.java"
    source.parent.mkdir()
    source.write_text("class Main {}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    base = _git(root, "rev-parse", "HEAD")
    source.write_text("class Main { void run() {} }\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "second")
    return base, _git(root, "rev-parse", "HEAD")


def _canonical_diff(*, repository_head: str = "c" * 40) -> GitDiff:
    first = DiffHunk(10, 2, 10, 3, (12, 11, 11), (11,))
    second = DiffHunk(2, 1, 2, 1, (2,), (2,))
    return GitDiff(
        (
            DiffFile(None, "assets/image.bin", binary=True),
            DiffFile("src/Main.java", "src/Main.java", (first, second)),
        ),
        base="main~1",
        head="main",
        repository_head=repository_head,
        base_commit="A" * 40,
        head_commit="B" * 40,
        workspace_prefix="./workspace",
    )


def test_round_trip_serialization_and_fingerprint_are_exact_and_canonical() -> None:
    first = _canonical_diff()
    reordered = GitDiff(
        tuple(reversed(first.files)),
        base=first.base,
        head=first.head,
        repository_head=first.repository_head,
        base_commit=first.base_commit,
        head_commit=first.head_commit,
        workspace_prefix="workspace",
    )

    assert first.to_dict() == reordered.to_dict()
    assert first.to_json() == reordered.to_json()
    assert first.fingerprint == reordered.fingerprint
    assert re.fullmatch(r"git-diff:[0-9a-f]{64}", first.fingerprint)
    assert GitDiff.from_dict(first.to_dict()).to_dict() == first.to_dict()
    assert GitDiff.from_dict(first.to_dict()).fingerprint == first.fingerprint
    assert first.base_commit == "a" * 40
    assert first.head_commit == "b" * 40

    # HEAD is collection provenance. Explicit comparisons are semantically bound
    # by base_commit/head_commit, so an unrelated current HEAD must not perturb the
    # observed-diff fingerprint.
    different_repository_head = replace(first, repository_head="d" * 40)
    assert different_repository_head.to_json() != first.to_json()
    assert different_repository_head.fingerprint == first.fingerprint
    assert replace(first, base_commit="e" * 40).fingerprint != first.fingerprint


def test_strict_wire_contract_rejects_unknown_fields_and_noncanonical_types() -> None:
    payload = _canonical_diff().to_dict()
    for target in (
        payload,
        payload["files"][0],
        payload["files"][1]["hunks"][0],
    ):
        malformed = deepcopy(payload)
        if target is payload:
            malformed["future"] = True
        elif "hunks" in target:
            malformed["files"][0]["future"] = True
        else:
            malformed["files"][1]["hunks"][0]["future"] = True
        with pytest.raises(ValueError, match="fields"):
            GitDiff.from_dict(malformed)

    malformed = deepcopy(payload)
    malformed["staged"] = 1
    with pytest.raises(TypeError, match="boolean"):
        GitDiff.from_dict(malformed)

    malformed = deepcopy(payload)
    malformed["workspace_prefix"] = None
    with pytest.raises(TypeError, match="string"):
        GitDiff.from_dict(malformed)

    malformed = deepcopy(payload)
    malformed["base_commit"] = "not-a-full-object-id"
    with pytest.raises(ValueError, match="full Git commit ID"):
        GitDiff.from_dict(malformed)

    malformed = deepcopy(payload)
    malformed["files"][1]["hunks"][0]["old_start"] = True
    with pytest.raises(TypeError, match="integer"):
        GitDiff.from_dict(malformed)


@pytest.mark.parametrize(
    "path",
    (
        "/private/Main.java",
        "C:/private/Main.java",
        "C:private/Main.java",
        "../private/Main.java",
        "src/../../private/Main.java",
        "src/private\nMain.java",
        "src/private\x00Main.java",
        "src/private\x7fMain.java",
        "src/private\ufffdMain.java",
        " src/private/Main.java",
        "src/private/Main.java ",
        ".",
        "a" * 4_097,
    ),
)
def test_paths_are_bounded_safe_and_workspace_relative(path: str) -> None:
    with pytest.raises(ValueError, match="safe workspace-relative"):
        DiffFile(None, path)


def test_path_normalization_and_lookup_do_not_accept_unsafe_queries() -> None:
    diff = GitDiff((DiffFile(None, r"src\Main.java"),))
    assert diff.changed_paths == ("src/Main.java",)
    assert diff.file("./src/Main.java") is diff.files[0]
    with pytest.raises(ValueError, match="safe workspace-relative"):
        diff.file("../src/Main.java")


def test_hunk_and_file_invariants_reject_impossible_or_ambiguous_metadata() -> None:
    with pytest.raises(ValueError, match="declared range"):
        DiffHunk(1, 1, 1, 1, (2,), ())
    with pytest.raises(ValueError, match="declared range"):
        DiffHunk(1, 0, 1, 0, (1,), ())
    with pytest.raises(ValueError, match="duplicate hunks"):
        hunk = DiffHunk(1, 1, 1, 1, (1,), (1,))
        DiffFile("a.txt", "a.txt", (hunk, hunk))
    with pytest.raises(ValueError, match="binary.*hunks"):
        DiffFile("a.bin", "a.bin", (DiffHunk(1, 1, 1, 1, (1,), (1,)),), True)
    with pytest.raises(ValueError, match="distinct old and new"):
        DiffFile("same.txt", "same.txt", renamed=True)
    with pytest.raises(ValueError, match="renamed flag"):
        DiffFile("old.txt", "new.txt")


def test_parser_preserves_modified_binary_and_binary_rename_without_source() -> None:
    patch = """diff --git a/assets/image.bin b/assets/image.bin
index 1111111..2222222 100644
Binary files a/assets/image.bin and b/assets/image.bin differ
diff --git "a/assets/old image.bin" "b/assets/new image.bin"
similarity index 75%
rename from assets/old image.bin
rename to assets/new image.bin
Binary files a/assets/old image.bin and b/assets/new image.bin differ
"""

    diff = UnifiedDiffParser().parse(patch)

    assert diff.changed_paths == ("assets/image.bin", "assets/new image.bin")
    assert diff.file("assets/image.bin").binary is True
    renamed = diff.file("assets/new image.bin")
    assert renamed.binary is True
    assert renamed.renamed is True
    assert renamed.old_path == "assets/old image.bin"
    assert renamed.hunks == ()
    assert "similarity index" not in diff.to_json()
    assert "Binary files" not in diff.to_json()
    assert GitDiff.from_dict(diff.to_dict()).to_dict() == diff.to_dict()


def test_parser_decodes_quoted_text_paths_with_spaces_without_retaining_source() -> None:
    patch = """diff --git "a/src/My File.java" "b/src/My File.java"
index 1111111..2222222 100644
--- "a/src/My File.java"
+++ "b/src/My File.java"
@@ -1 +1 @@
-class Old {}
+class New {}
"""

    diff = UnifiedDiffParser().parse(patch)

    assert diff.changed_paths == ("src/My File.java",)
    assert diff.file("src/My File.java").added_lines == (1,)
    assert "class Old" not in diff.to_json()
    assert "class New" not in diff.to_json()


@pytest.mark.parametrize(
    "header",
    (
        "diff --git a/../private.txt b/../private.txt\n",
        'diff --git "a/source\\tname.txt" "b/source\\tname.txt"\n',
        "diff --git a/only-one-path\n",
    ),
)
def test_parser_rejects_unsafe_or_malformed_diff_headers(header: str) -> None:
    with pytest.raises(ValueError, match="Git diff|workspace-relative"):
        UnifiedDiffParser().parse(header)


def test_service_binds_symbolic_comparison_to_resolved_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_commit, head_commit = _repository(tmp_path)
    commands: list[tuple[str, ...]] = []
    real_run = git_diff_module.subprocess.run

    def recording_run(command, *args, **kwargs):
        commands.append(tuple(str(item) for item in command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(git_diff_module.subprocess, "run", recording_run)
    diff = GitDiffService(tmp_path).collect(base="HEAD~1", head="HEAD")

    assert diff.base == "HEAD~1"
    assert diff.head == "HEAD"
    assert diff.base_commit == base_commit
    assert diff.head_commit == head_commit
    assert diff.repository_head == head_commit
    assert diff.changed_paths == ("src/Main.java",)
    diff_command = next(command for command in commands if "diff" in command)
    assert base_commit in diff_command
    assert head_commit in diff_command
    assert "HEAD~1" not in diff_command
    assert "HEAD" not in diff_command


def test_staged_diff_is_bound_to_repository_head_and_reproducible(tmp_path: Path) -> None:
    _, head_commit = _repository(tmp_path)
    source = tmp_path / "src" / "Main.java"
    source.write_text("class Main { void run() {} void stop() {} }\n", encoding="utf-8")
    _git(tmp_path, "add", "src/Main.java")

    first = GitDiffService(tmp_path).collect(staged=True)
    second = GitDiffService(tmp_path).collect(staged=True)

    assert first.base is None
    assert first.head is None
    assert first.base_commit == head_commit
    assert first.repository_head == head_commit
    assert first.head_commit is None
    assert first.to_json() == second.to_json()
    assert first.fingerprint == second.fingerprint


def test_nested_workspace_paths_are_translated_exactly_once(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "atlas@example.test")
    _git(tmp_path, "config", "user.name", "Atlas Tests")
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "Main.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Main {}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    source.write_text("class Main { void run() {} }\n", encoding="utf-8")

    diff = GitDiffService(workspace).collect(base="HEAD")

    assert diff.workspace_prefix == "workspace"
    assert diff.changed_paths == ("src/Main.java",)
    assert diff.file("src/Main.java") is not None


def test_workspace_translation_rejects_cross_boundary_paths() -> None:
    cross_boundary = GitDiff(
        (DiffFile("outside/Old.java", "workspace/New.java", renamed=True),),
        workspace_prefix="workspace",
    )

    with pytest.raises(GitDiffError, match="outside the selected workspace"):
        GitDiffService._workspace_relative(cross_boundary)
