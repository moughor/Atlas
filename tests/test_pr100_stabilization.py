from __future__ import annotations

import json
from pathlib import Path
import tomllib

from typer.testing import CliRunner

import moughorai
from moughorai.atlas_cli import app
from moughorai.history import HistoryDatabase
from moughorai.sarif import SarifExporter
from moughorai.version import __version__
from moughorai.workspace import ProjectRun, ProjectRunStatus, WorkspaceRunReport


runner = CliRunner()
ROOT = Path(__file__).parents[1]


def workspace(root: Path) -> Path:
    (root / "core").mkdir()
    (root / "core" / "main.py").write_text("# core\n", encoding="utf-8")
    (root / "atlas.yaml").write_text(
        "projects:\n  - name: core\n    path: core\n",
        encoding="utf-8",
    )
    return root


def test_atlas_2_version_is_canonical_everywhere() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == moughorai.__version__ == __version__ == "2.0.0"
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == "Atlas 2.0.0\n"


def test_sarif_uses_canonical_product_version() -> None:
    report = WorkspaceRunReport((ProjectRun("core", ProjectRunStatus.SUCCEEDED),), ("core",), ("core",))
    driver = SarifExporter().to_dict(report)["runs"][0]["tool"]["driver"]
    assert driver["version"] == __version__


def test_all_atlas_2_commands_have_help() -> None:
    commands = (
        "analyze", "check", "watch", "config", "plugins", "ci", "history",
        "dashboard", "profile", "governance",
    )
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    for command in commands:
        assert command in root_help.stdout
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0


def test_end_to_end_history_dashboard_profile_and_governance(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    analyzed = runner.invoke(app, ["analyze", str(root), "--no-recover"])
    assert analyzed.exit_code == 0
    assert len(HistoryDatabase(root).list()) == 1

    dashboard = runner.invoke(app, ["dashboard", str(root)])
    assert dashboard.exit_code == 0
    assert (root / ".atlas" / "dashboard.html").is_file()

    profile = runner.invoke(app, ["profile", str(root)])
    assert profile.exit_code == 0
    assert [item["name"] for item in json.loads(profile.stdout)["metrics"]] == ["project:core", "workspace"]

    governance = runner.invoke(app, ["governance", str(root)])
    assert governance.exit_code == 0
    assert governance.stdout.splitlines() == ["audit: valid", "records: 0"]


def test_ci_template_generation_is_stable_in_release(tmp_path: Path) -> None:
    first = runner.invoke(app, ["ci", "github", "--root", str(tmp_path)])
    assert first.exit_code == 0
    target = tmp_path / ".github" / "workflows" / "atlas.yml"
    content = target.read_text(encoding="utf-8")
    second = runner.invoke(app, ["ci", "github", "--root", str(tmp_path), "--force"])
    assert second.exit_code == 0
    assert target.read_text(encoding="utf-8") == content


def test_readme_describes_atlas_2_and_compatibility_document_exists() -> None:
    assert "Atlas 2.0" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert (ROOT / "docs" / "PR100_ATLAS_2_STABILIZATION.md").is_file()
