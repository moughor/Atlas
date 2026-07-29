from __future__ import annotations

from pathlib import Path

from moughorai.incremental_analysis.distributed import JobState
from moughorai.workspace import ProjectRunStatus, WorkspaceService
from moughorai.workspace_distributed import DistributedWorkspaceCoordinator


def workspace(root: Path) -> WorkspaceService:
    for name in ("core", "api", "ui"):
        (root / name).mkdir()
    (root / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: core\n"
        "    path: core\n"
        "    options: {language: python}\n"
        "  - name: api\n"
        "    path: api\n"
        "    dependencies: [core]\n"
        "    options: {language: python}\n"
        "  - name: ui\n"
        "    path: ui\n",
        encoding="utf-8",
    )
    return WorkspaceService(root)


def test_submit_creates_dependency_ordered_jobs(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    assert coordinator.submit(("api",)) == ("core", "api")
    jobs = coordinator.coordinator.snapshot().jobs
    assert [record.job.path.as_posix() for record in jobs] == ["api", "core"]
    assert jobs[0].job.dependencies == (Path("core"),)
    assert len(jobs[0].job.fingerprint) == 64


def test_language_options_become_capabilities(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit(("core",))
    job = coordinator.coordinator.snapshot().jobs[0].job
    assert job.required_capabilities == ("language:python",)


def test_local_workers_receive_dependency_results(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit(("api",))
    seen: list[tuple[str, dict[str, object]]] = []

    def analyze(project, dependencies):
        seen.append((project.name, dict(dependencies)))
        return project.name.upper()

    run = coordinator.execute_locally(
        {"worker": analyze},
        capabilities={"worker": ("language:python",)},
    )
    assert run.report.succeeded
    assert seen == [("core", {}), ("api", {"core": "CORE"})]
    assert [item.project for item in run.report.runs] == ["api", "core"]


def test_workers_are_assigned_deterministically(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit()
    run = coordinator.execute_locally(
        {"z": lambda project, dependencies: project.name, "a": lambda project, dependencies: project.name},
        capabilities={"a": ("language:python",), "z": ("language:python",)},
    )
    assert [(item.worker_id, item.path.as_posix()) for item in run.execution.assignments] == [
        ("a", "core"),
        ("z", "api"),
        ("a", "ui"),
    ]


def test_failure_blocks_dependent_project(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit(("api",))

    def analyze(project, dependencies):
        if project.name == "core":
            raise RuntimeError("broken")
        return project.name

    run = coordinator.execute_locally(
        {"worker": analyze},
        capabilities={"worker": ("language:python",)},
    )
    assert run.report.get("core").status is ProjectRunStatus.FAILED
    assert run.report.get("api").status is ProjectRunStatus.BLOCKED
    assert run.report.get("api").blocked_by == ("core",)


def test_transient_failure_retries(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit(("ui",), max_attempts=2)
    calls = 0

    def analyze(project, dependencies):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return "ok"

    run = coordinator.execute_locally({"worker": analyze})
    assert run.report.get("ui").value == "ok"
    assert run.execution.metrics.retried == 1


def test_capability_mismatch_leaves_job_pending(tmp_path: Path) -> None:
    coordinator = DistributedWorkspaceCoordinator(workspace(tmp_path))
    coordinator.submit(("core",))
    run = coordinator.execute_locally({"worker": lambda project, dependencies: None})
    assert run.report.runs == ()
    assert coordinator.coordinator.snapshot().jobs[0].state is JobState.PENDING
