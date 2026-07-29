import subprocess
from pathlib import Path

from moughorai.ai_git_context import GitContextService


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_git_context_collects_branch_changes_history_and_snapshots(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "atlas@example.test")
    _git(tmp_path, "config", "user.name", "Atlas")
    target = tmp_path / "app.txt"
    target.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "app.txt")
    _git(tmp_path, "commit", "--no-gpg-sign", "-m", "initial")
    target.write_text("two\n", encoding="utf-8")
    context = GitContextService(tmp_path).collect(
        commit_limit=1,
        blame_files=("app.txt",),
        pull_request={"number": "7"},
        base_snapshot_id="old",
        current_snapshot_id="new",
    )
    assert context.changed_files == ("app.txt",)
    assert context.commits[0].subject == "initial"
    assert context.pull_request == (("number", "7"),)
    assert context.base_snapshot_id == "old"
    assert '"branch"' in context.to_json()


def test_git_context_zero_commit_limit(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    assert GitContextService(tmp_path).collect(commit_limit=0).commits == ()
