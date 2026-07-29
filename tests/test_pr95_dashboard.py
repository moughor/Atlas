from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.dashboard import DashboardRenderer, DashboardService
from moughorai.history import HistoryDatabase
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


runner = CliRunner()


def report(project: str, *, failed: bool = False) -> WorkspaceRunReport:
    status = ProjectRunStatus.FAILED if failed else ProjectRunStatus.SUCCEEDED
    value = {"findings": [{"rule_id": "A"}, {"rule_id": "B"}]}
    return WorkspaceRunReport((ProjectRun(project, status, value),), (project,), (project,))


def test_empty_dashboard_is_complete_and_deterministic() -> None:
    renderer = DashboardRenderer()
    first = renderer.render(())
    assert first == renderer.render(())
    assert first.startswith("<!doctype html>")
    assert "No analysis history is available." in first
    assert "Runs<span class=\"metric\">0</span>" in first


def test_dashboard_summarizes_runs_findings_and_projects(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    database.record(report("core"), created_at="2026-01-01T00:00:00+00:00")
    database.record(report("api", failed=True), created_at="2026-01-02T00:00:00+00:00")
    html = DashboardRenderer().render(database.list())
    assert "Runs<span class=\"metric\">2</span>" in html
    assert "Succeeded<span class=\"metric ok\">1</span>" in html
    assert "Failed<span class=\"metric bad\">1</span>" in html
    assert html.index("2026-01-02") < html.index("2026-01-01")
    assert html.count("<td>2</td>") >= 2
    assert "<span>api</span><strong>1</strong>" in html


def test_dashboard_escapes_database_content(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    database.record(report("<script>alert(1)</script>"), created_at="<unsafe>")
    html = DashboardRenderer().render(database.list())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;unsafe&gt;" in html


def test_service_generates_default_content_with_limit(tmp_path: Path) -> None:
    database = HistoryDatabase(tmp_path)
    database.record(report("old"))
    database.record(report("new"))
    target = DashboardService(database).generate(Path("dashboard.html"), limit=1)
    text = target.read_text(encoding="utf-8")
    assert target == tmp_path / "dashboard.html"
    assert "<span>new</span>" in text
    assert "<span>old</span>" not in text


def test_cli_generates_default_dashboard(tmp_path: Path) -> None:
    result = runner.invoke(app, ["dashboard", str(tmp_path)])
    target = tmp_path / ".atlas" / "dashboard.html"
    assert result.exit_code == 0
    assert result.stdout.strip() == target.as_posix()
    assert target.is_file()


def test_cli_help_lists_dashboard() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dashboard" in result.stdout
