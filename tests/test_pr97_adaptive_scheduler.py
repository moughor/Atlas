from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.adaptive_scheduler import AdaptiveWorkspaceScheduler
from moughorai.atlas_cli import app
from moughorai.workspace import Project


runner = CliRunner()


def project(name: str, dependencies: tuple[str, ...] = ()) -> Project:
    return Project(name, Path(name), dependencies)


def test_parallel_projects_use_bounded_capacity() -> None:
    schedule = AdaptiveWorkspaceScheduler().recommend(
        (project("a"), project("b"), project("c")),
        worker_cap=8,
        cpu_count=2,
    )
    assert schedule.workers == 2
    assert schedule.maximum_parallelism == 3
    assert schedule.reason == "bounded-topology-parallelism"


def test_dependency_chain_is_sequential() -> None:
    schedule = AdaptiveWorkspaceScheduler().recommend(
        (project("a"), project("b", ("a",)), project("c", ("b",))),
        worker_cap=4,
        cpu_count=8,
    )
    assert schedule.workers == 1
    assert schedule.reason == "dependency-chain-is-sequential"


def test_trivial_history_avoids_thread_overhead() -> None:
    projects = (project("a"), project("b"))
    schedule = AdaptiveWorkspaceScheduler().recommend(
        projects,
        worker_cap=4,
        cpu_count=4,
        duration_ms={"a": 1.0, "b": 4.9},
    )
    assert schedule.workers == 1
    assert schedule.reason == "historical-runs-are-trivial"


def test_partial_history_does_not_force_sequential() -> None:
    schedule = AdaptiveWorkspaceScheduler().recommend(
        (project("a"), project("b")),
        worker_cap=4,
        cpu_count=4,
        duration_ms={"a": 1.0},
    )
    assert schedule.workers == 2


@pytest.mark.parametrize("cap", [0, -1])
def test_invalid_worker_cap_is_rejected(cap: int) -> None:
    with pytest.raises(ValueError, match="worker cap"):
        AdaptiveWorkspaceScheduler().recommend((project("a"),), worker_cap=cap)


def test_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        AdaptiveWorkspaceScheduler().recommend(
            (project("a", ("b",)), project("b", ("a",))),
            worker_cap=2,
        )


def workspace(root: Path) -> Path:
    for name in ("a", "b"):
        (root / name).mkdir()
    (root / "atlas.yaml").write_text(
        "projects:\n  - name: a\n    path: a\n  - name: b\n    path: b\n",
        encoding="utf-8",
    )
    return root


def test_cli_adaptive_passes_recommended_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = workspace(tmp_path)
    seen: list[int] = []
    original = atlas_cli.WorkspaceAnalysisOrchestrator.execute

    def execute(self, analyzer, **kwargs):
        seen.append(kwargs["max_workers"])
        return original(self, analyzer, **kwargs)

    monkeypatch.setattr(atlas_cli.WorkspaceAnalysisOrchestrator, "execute", execute)
    result = runner.invoke(app, ["analyze", str(root), "--workers", "8", "--adaptive", "--no-recover"])
    assert result.exit_code == 0
    assert seen == [2]


def test_non_adaptive_cli_preserves_requested_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = workspace(tmp_path)
    seen: list[int] = []
    original = atlas_cli.WorkspaceAnalysisOrchestrator.execute

    def execute(self, analyzer, **kwargs):
        seen.append(kwargs["max_workers"])
        return original(self, analyzer, **kwargs)

    monkeypatch.setattr(atlas_cli.WorkspaceAnalysisOrchestrator, "execute", execute)
    result = runner.invoke(app, ["analyze", str(root), "--workers", "3", "--no-recover"])
    assert result.exit_code == 0
    assert seen == [3]
