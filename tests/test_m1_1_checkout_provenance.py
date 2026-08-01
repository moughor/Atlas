from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from benchmarks import canonical_baseline, repository_benchmark


_PUBLIC_URL = "https://example.com/fixture.git"


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
        encoding="utf-8",
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def _create_checkout(tmp_path: Path, *, shallow: bool = False) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "atlas@example.com")
    _git(source, "config", "user.name", "Atlas Test")
    _git(source, "checkout", "-b", "main")
    (source / "fixture.txt").write_text("first\n", encoding="utf-8")
    _git(source, "add", "fixture.txt")
    _git(source, "commit", "-m", "first")
    (source / "fixture.txt").write_text("second\n", encoding="utf-8")
    _git(source, "commit", "-am", "second")
    commit = _git(source, "rev-parse", "HEAD")

    checkout = tmp_path / "checkout"
    source_url = source.as_uri() if shallow else str(source)
    command = ["git", "clone", "--branch", "main"]
    if shallow:
        command.extend(("--depth", "1"))
    command.extend((source_url, str(checkout)))
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        encoding="utf-8",
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    _git(checkout, "remote", "set-url", "origin", _PUBLIC_URL)
    _git(checkout, "checkout", "--detach", commit)
    return checkout, commit


def _definition(
    checkout: Path,
    commit: str,
    *,
    tag: str | None = None,
) -> canonical_baseline.BenchmarkRepositoryDefinition:
    provenance = repository_benchmark._repository_provenance(
        checkout,
        git_backed=True,
        repository_url=_PUBLIC_URL,
        repository_branch="main",
        repository_tag=None,
    )
    return canonical_baseline.BenchmarkRepositoryDefinition(
        repository_id="fixture",
        name="Fixture",
        url=_PUBLIC_URL,
        commit=commit,
        branch="main",
        tag=tag,
        checkout_identity="fixture-m1-1",
        expected_project_count=1,
        workers=1,
        timeout_seconds=30,
        tracked_size_bytes=provenance[3] or 0,
        tracked_file_count=provenance[4] or 0,
        submodules=provenance[5],
        lfs_required=bool(provenance[6]),
        history_complete=True,
    )


def test_checkout_verification_requires_complete_reachable_history(
    tmp_path: Path,
) -> None:
    checkout, commit = _create_checkout(tmp_path)
    definition = _definition(checkout, commit)

    verification = canonical_baseline.verify_checkout(
        definition,
        checkout,
        require_initial_state=True,
    )

    assert verification.history_complete is True
    assert verification.commit == commit


def test_checkout_verification_rejects_shallow_history(tmp_path: Path) -> None:
    checkout, commit = _create_checkout(tmp_path, shallow=True)
    definition = _definition(checkout, commit)

    with pytest.raises(ValueError, match="complete Git history"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=True,
        )


def test_checkout_verification_rejects_promisor_clone(tmp_path: Path) -> None:
    checkout, commit = _create_checkout(tmp_path)
    definition = _definition(checkout, commit)
    _git(checkout, "config", "remote.origin.promisor", "true")

    with pytest.raises(ValueError, match="full Git objects"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=True,
        )


def test_checkout_verification_rejects_commit_outside_declared_branch(
    tmp_path: Path,
) -> None:
    checkout, _ = _create_checkout(tmp_path)
    _git(checkout, "config", "user.email", "atlas@example.com")
    _git(checkout, "config", "user.name", "Atlas Test")
    (checkout / "fixture.txt").write_text("side\n", encoding="utf-8")
    _git(checkout, "commit", "-am", "side")
    side_commit = _git(checkout, "rev-parse", "HEAD")
    definition = _definition(checkout, side_commit)

    with pytest.raises(ValueError, match="not reachable from the declared branch"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=True,
        )


def test_checkout_verification_requires_declared_tag_to_resolve_to_head(
    tmp_path: Path,
) -> None:
    checkout, commit = _create_checkout(tmp_path)
    _git(checkout, "tag", "previous-release", "HEAD^")
    definition = _definition(checkout, commit, tag="previous-release")

    with pytest.raises(ValueError, match="tag does not resolve to HEAD"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=True,
        )


def test_checkout_verification_rejects_tracked_atlas_state(tmp_path: Path) -> None:
    checkout, commit = _create_checkout(tmp_path)
    definition = _definition(checkout, commit)
    atlas = checkout / ".atlas"
    atlas.mkdir()
    (atlas / "tracked.json").write_text("{}\n", encoding="utf-8")
    _git(checkout, "add", ".atlas/tracked.json")

    with pytest.raises(ValueError, match="must not track .atlas"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=False,
        )


def test_checkout_verification_treats_dangling_atlas_as_existing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, commit = _create_checkout(tmp_path)
    definition = _definition(checkout, commit)
    real_lexists = canonical_baseline.os.path.lexists
    atlas_path = checkout / ".atlas"
    monkeypatch.setattr(
        canonical_baseline.os.path,
        "lexists",
        lambda value: True if Path(value) == atlas_path else real_lexists(value),
    )

    with pytest.raises(ValueError, match="must not contain .atlas state"):
        canonical_baseline.verify_checkout(
            definition,
            checkout,
            require_initial_state=True,
        )


def test_prepare_fetches_full_declared_branch_and_exact_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, definition = canonical_baseline.select_definition("apache-maven")
    definition = replace(definition, tag="m1-test-tag")
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(canonical_baseline.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        canonical_baseline,
        "_git",
        lambda root, *arguments: calls.append(arguments) or "",
    )
    monkeypatch.setattr(
        canonical_baseline,
        "verify_checkout",
        lambda *args, **kwargs: canonical_baseline.RepositoryVerification(
            repository_id=definition.repository_id,
            commit=definition.commit,
            remote_url=definition.url,
            detached_head=True,
            clean_worktree=True,
            initial_atlas_state_absent=True,
            tracked_size_bytes=definition.tracked_size_bytes,
            tracked_file_count=definition.tracked_file_count,
            submodules=definition.submodules,
            lfs_required=definition.lfs_required,
            history_complete=True,
        ),
    )

    canonical_baseline.prepare_checkout(definition, tmp_path / "prepared")

    assert (
        "fetch",
        "--no-tags",
        "origin",
        "+refs/heads/master:refs/remotes/origin/master",
    ) in calls
    assert (
        "fetch",
        "--no-tags",
        "origin",
        "+refs/tags/m1-test-tag:refs/tags/m1-test-tag",
    ) in calls
    assert all("--depth" not in arguments for arguments in calls)


def test_runtime_inventory_is_normalized_complete_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distributions = (
        SimpleNamespace(metadata={"Name": "Zeta_Package"}, version="2.0"),
        SimpleNamespace(metadata={"Name": "alpha.package"}, version="1.0"),
        SimpleNamespace(metadata={"Name": "Alpha-Package"}, version="1.0"),
    )
    monkeypatch.setattr(
        repository_benchmark.metadata,
        "distributions",
        lambda: iter(distributions),
    )

    assert repository_benchmark._runtime_dependencies() == (
        ("alpha-package", "1.0"),
        ("zeta-package", "2.0"),
    )


def test_provisional_git_capture_preserves_support_for_checkout_without_origin(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "without-origin"
    checkout.mkdir()
    _git(checkout, "init")
    _git(checkout, "config", "user.email", "atlas@example.com")
    _git(checkout, "config", "user.name", "Atlas Test")
    (checkout / "fixture.txt").write_text("fixture\n", encoding="utf-8")
    _git(checkout, "add", "fixture.txt")
    _git(checkout, "commit", "-m", "fixture")

    provenance = repository_benchmark._repository_provenance(
        checkout,
        git_backed=True,
        repository_url=None,
        repository_branch=None,
        repository_tag=None,
    )

    assert provenance[0] is None
    assert provenance[3] == len("fixture\n".encode("utf-8"))
    assert provenance[4] == 1
    assert provenance[7] is True
