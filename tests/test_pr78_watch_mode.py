from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.workspace import (
    WorkspaceAnalysisOrchestrator,
    WorkspaceService,
    WorkspaceWatchManager,
    WorkspaceWatcher,
)


def workspace(tmp_path: Path) -> WorkspaceService:
    (tmp_path / "core").mkdir()
    (tmp_path / "api").mkdir()
    (tmp_path / "core" / "main.py").write_text("old")
    (tmp_path / "api" / "main.py").write_text("api")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "- name: core\n  path: core\n  include: ['**/*.py']\n"
        "- name: api\n  path: api\n  dependencies: [core]\n  include: ['**/*.py']\n"
    )
    return WorkspaceService(tmp_path)


def test_watch_manager_analyzes_changed_project_and_dependents(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    analyzed: list[str] = []

    def change(_: float) -> None:
        (tmp_path / "core" / "main.py").write_text("new")

    manager = WorkspaceWatchManager(
        WorkspaceWatcher(service.workspace, event_bus=service.events, debounce_ms=0),
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: analyzed.append(project.name) or project.name,
        interval_seconds=0,
        max_workers=2,
        sleeper=change,
    )
    result = manager.run(iterations=1)
    assert result.polls == 1
    assert len(result.reports) == 1
    assert analyzed == ["core", "api"]
    assert result.reports[0].analysis_order == ("core", "api")


def test_watch_manager_ignores_idle_polls(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    result = WorkspaceWatchManager(
        WorkspaceWatcher(service.workspace, debounce_ms=0),
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
        interval_seconds=0,
        sleeper=lambda _: None,
    ).run(iterations=3)
    assert result.polls == 3
    assert result.reports == ()


def test_watch_manager_stops_without_polling(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    result = WorkspaceWatchManager(
        WorkspaceWatcher(service.workspace),
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
        sleeper=lambda _: None,
    ).run(stopped=lambda: True)
    assert result.polls == 0


@pytest.mark.parametrize("iterations", [-1, -2])
def test_watch_manager_rejects_negative_iterations(tmp_path: Path, iterations: int) -> None:
    service = workspace(tmp_path)
    manager = WorkspaceWatchManager(
        WorkspaceWatcher(service.workspace),
        WorkspaceAnalysisOrchestrator(service),
        lambda project, dependencies: project.name,
    )
    with pytest.raises(ValueError, match="iterations"):
        manager.run(iterations=iterations)


def test_watch_manager_validates_options(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    watcher = WorkspaceWatcher(service.workspace)
    orchestrator = WorkspaceAnalysisOrchestrator(service)
    analyzer = lambda project, dependencies: project.name
    with pytest.raises(ValueError, match="interval"):
        WorkspaceWatchManager(watcher, orchestrator, analyzer, interval_seconds=-1)
    with pytest.raises(ValueError, match="max_workers"):
        WorkspaceWatchManager(watcher, orchestrator, analyzer, max_workers=0)


def test_cli_bounded_watch_reports_poll_and_analysis_counts(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    calls = 0

    def factory(_service):
        return lambda project, dependencies: project.name

    class ChangingManager(WorkspaceWatchManager):
        def run(self, **kwargs):
            nonlocal calls
            (tmp_path / "core" / "main.py").write_text("changed")
            calls += 1
            return super().run(**kwargs)

    original = atlas_cli.WorkspaceWatchManager
    atlas_cli._analyzer_factory = factory
    atlas_cli.WorkspaceWatchManager = ChangingManager
    try:
        result = CliRunner().invoke(app, ["watch", str(service.workspace.root), "--iterations", "1", "--interval", "0"])
    finally:
        atlas_cli.WorkspaceWatchManager = original
        atlas_cli._analyzer_factory = None
    assert result.exit_code == 0
    assert calls == 1
    assert "polls: 1" in result.stdout
    assert "status: stopped" in result.stdout
