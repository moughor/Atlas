from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.git_diff import (
    DiffFile,
    DiffHunk,
    GitDiff,
    GitDiffError,
    GitDiffFilter,
    GitDiffService,
    UnifiedDiffParser,
)
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


PATCH = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,3 @@
 keep
-old
+new
+added
diff --git a/old.py b/new.py
similarity index 100%
rename from old.py
rename to new.py
"""


def test_parser_builds_files_hunks_and_lines() -> None:
    diff = UnifiedDiffParser().parse(PATCH, base="main", head="feature")
    assert diff.base == "main" and diff.head == "feature"
    assert diff.changed_paths == ("new.py", "src/a.py")
    source = diff.file("src/a.py")
    assert source.added_lines == (2, 3)
    assert source.hunks[0].removed_lines == (2,)
    renamed = diff.file("new.py")
    assert renamed.renamed and renamed.old_path == "old.py"


def test_parser_handles_new_deleted_and_binary_files() -> None:
    text = """diff --git a/new.bin b/new.bin
new file mode 100644
--- /dev/null
+++ b/new.bin
Binary files /dev/null and b/new.bin differ
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""
    diff = UnifiedDiffParser().parse(text)
    assert diff.file("new.bin").binary
    assert diff.file("new.bin").old_path is None
    assert diff.file("old.py").new_path is None


def test_empty_diff_is_supported() -> None:
    assert UnifiedDiffParser().parse("").files == ()


def report(*findings):
    run = ProjectRun("app", ProjectRunStatus.SUCCEEDED, value={"findings": list(findings)})
    return WorkspaceRunReport((run,), ("app",), ("app",))


def test_filter_keeps_only_findings_on_added_lines() -> None:
    value = GitDiffFilter().filter_report(report(
        {"rule_id": "R", "message": "old", "path": "src/a.py", "line": 1},
        {"rule_id": "R", "message": "new", "path": "src/a.py", "line": 2},
        {"rule_id": "R", "message": "other", "path": "other.py", "line": 2},
    ), UnifiedDiffParser().parse(PATCH))
    findings = value.runs[0].value["findings"]
    assert [item["message"] for item in findings] == ["new"]
    assert value.runs[0].value["git_diff"] == {"changed_findings": 1, "total_findings": 3}


def test_filter_supports_nested_and_absolute_locations(tmp_path: Path) -> None:
    diff = GitDiff((DiffFile(None, "src/a.py", (DiffHunk(0, 0, 4, 1, (4,), ()),)),))
    value = GitDiffFilter().filter_report(report({
        "rule_id": "R", "message": "m",
        "location": {"path": str(tmp_path / "src" / "a.py"), "start_line": 4},
    }), diff, root=tmp_path)
    assert len(value.runs[0].value["findings"]) == 1


def test_filter_preserves_non_finding_runs() -> None:
    run = ProjectRun("app", ProjectRunStatus.FAILED, error="bad")
    original = WorkspaceRunReport((run,), ("app",), ("app",))
    assert GitDiffFilter().filter_report(original, GitDiff(())).runs[0] is run


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "atlas@example.test")
    git(tmp_path, "config", "user.name", "Atlas Tests")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("one\n")
    (tmp_path / "atlas.yaml").write_text("projects:\n- name: app\n  path: app\n  include: ['**/*.py']\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_service_collects_working_tree_diff(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (root / "app" / "main.py").write_text("one\ntwo\n")
    diff = GitDiffService(root).collect()
    assert diff.changed_paths == ("app/main.py",)
    assert diff.file("app/main.py").added_lines == (2,)


def test_service_collects_staged_diff(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (root / "app" / "main.py").write_text("one\ntwo\n")
    git(root, "add", "app/main.py")
    diff = GitDiffService(root).collect(staged=True)
    assert diff.staged and diff.file("app/main.py").added_lines == (2,)


def test_service_collects_base_head_diff(tmp_path: Path) -> None:
    root = repository(tmp_path)
    base = git(root, "rev-parse", "HEAD")
    (root / "app" / "main.py").write_text("one\ntwo\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "second")
    head = git(root, "rev-parse", "HEAD")
    diff = GitDiffService(root).collect(base=base, head=head)
    assert diff.file("app/main.py").added_lines == (2,)


def test_service_validates_option_combinations_and_refs(tmp_path: Path) -> None:
    root = repository(tmp_path)
    service = GitDiffService(root)
    with pytest.raises(GitDiffError, match="requires a base"):
        service.collect(head="HEAD")
    with pytest.raises(GitDiffError, match="staged"):
        service.collect(base="HEAD", head="HEAD", staged=True)
    with pytest.raises(GitDiffError, match="invalid"):
        service.collect(base="--output=x")
    with pytest.raises(GitDiffError, match="unknown"):
        service.collect(base="missing")


def test_service_reports_non_repository_error(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: missing\n")
    with pytest.raises(GitDiffError, match="not a git repository"):
        GitDiffService(tmp_path).collect()


def test_cli_diff_filters_analyzer_findings(tmp_path: Path) -> None:
    root = repository(tmp_path)
    (root / "app" / "main.py").write_text("one\ntwo\n")
    atlas_cli._analyzer_factory = lambda service: lambda project, dependencies: {
        "findings": [
            {"rule_id": "R", "message": "old", "path": "app/main.py", "line": 1},
            {"rule_id": "R", "message": "new", "path": "app/main.py", "line": 2},
        ]
    }
    try:
        result = CliRunner().invoke(app, ["check", str(root), "--diff", "--format", "json"])
    finally:
        atlas_cli._analyzer_factory = None
    assert result.exit_code == 0
    assert '"message": "new"' in result.stdout
    assert '"message": "old"' not in result.stdout


def test_cli_diff_head_without_base_is_error(tmp_path: Path) -> None:
    root = repository(tmp_path)
    result = CliRunner().invoke(app, ["analyze", str(root), "--diff-head", "HEAD"])
    assert result.exit_code == 2
    assert "requires a base" in result.stderr
