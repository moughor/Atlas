from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app


runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_analyzer_factory():
    previous = atlas_cli._analyzer_factory
    atlas_cli._analyzer_factory = None
    yield
    atlas_cli._analyzer_factory = previous


def workspace(tmp_path: Path) -> Path:
    for name in ("core", "api"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.py").write_text(f"# {name}\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "options:\n"
        "  mode: strict\n"
        "projects:\n"
        "  - name: core\n"
        "    path: core\n"
        "    options:\n"
        "      language: python\n"
        "  - name: api\n"
        "    path: api\n"
        "    dependencies: [core]\n",
        encoding="utf-8",
    )
    return tmp_path


def plugin(root: Path) -> Path:
    target = root / "plugins" / "demo"
    target.mkdir(parents=True)
    (target / "plugin.yaml").write_text(
        "id: demo\n"
        "version: 1.2.3\n"
        "api_version: '>=1.0.0,<2.0.0'\n"
        "name: Demo\n"
        "extensions: []\n",
        encoding="utf-8",
    )
    return target


def test_root_help_lists_unified_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("analyze", "check", "watch", "config", "plugins"):
        assert command in result.stdout


@pytest.mark.parametrize("command", ["analyze", "check", "watch", "config", "plugins"])
def test_each_command_has_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "Workspace root" in result.stdout


def test_analyze_executes_projects_in_deterministic_order(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "--no-recover"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "core: succeeded",
        "api: succeeded",
        "projects: 2",
        "succeeded: yes",
    ]


def test_analyze_subset_includes_dependency(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "-p", "api", "--no-recover"])
    assert result.exit_code == 0
    assert "core: succeeded" in result.stdout
    assert "api: succeeded" in result.stdout


def test_analyze_supports_concurrent_workers(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "-j", "2", "--no-recover"])
    assert result.exit_code == 0
    assert result.stdout.index("core:") < result.stdout.index("api:")


def test_analyze_rejects_invalid_worker_count(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(workspace(tmp_path)), "--workers", "0"])
    assert result.exit_code == 2


def test_analyze_missing_workspace_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing")])
    assert result.exit_code == 2
    assert "error:" in result.stderr


def test_check_succeeds_for_successful_analysis(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check", str(workspace(tmp_path))])
    assert result.exit_code == 0
    assert "succeeded: yes" in result.stdout


def test_check_fails_when_analyzer_fails(tmp_path: Path) -> None:
    def factory(service):
        def analyze(project, dependencies):
            if project.name == "core":
                raise RuntimeError("broken")
            return project.name
        return analyze

    atlas_cli._analyzer_factory = factory
    result = runner.invoke(app, ["check", str(workspace(tmp_path))])
    assert result.exit_code == 1
    assert "core: failed" in result.stdout
    assert "api: blocked" in result.stdout
    assert "succeeded: no" in result.stdout


def test_watch_initializes_snapshot_without_continuous_loop(tmp_path: Path) -> None:
    result = runner.invoke(app, ["watch", str(workspace(tmp_path))])
    assert result.exit_code == 0
    assert "projects: 2" in result.stdout
    assert "tracked_files: 2" in result.stdout
    assert result.stdout.endswith("status: ready\n")


def test_config_lists_workspace_values(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", str(workspace(tmp_path))])
    assert result.exit_code == 0
    assert "mode=strict" in result.stdout


def test_config_resolves_project_values(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", str(workspace(tmp_path)), "--project", "core"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["project: core", "language=python", "mode=strict"]


def test_config_unknown_project_is_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", str(workspace(tmp_path)), "--project", "missing"])
    assert result.exit_code == 2
    assert "unknown project" in result.stderr


def test_plugins_lists_discovered_manifests(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    plugin(root)
    result = runner.invoke(app, ["plugins", str(root)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["demo 1.2.3 Demo", "plugins: 1", "diagnostics: 0"]


def test_plugins_accepts_explicit_manifest_root(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    target = plugin(root)
    result = runner.invoke(app, ["plugins", str(root), "--plugin-root", str(target / "plugin.yaml")])
    assert result.exit_code == 0
    assert "demo 1.2.3 Demo" in result.stdout


def test_plugins_reports_invalid_manifest_deterministically(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    target = root / "plugins" / "bad"
    target.mkdir(parents=True)
    (target / "plugin.yaml").write_text("invalid: true\n", encoding="utf-8")
    result = runner.invoke(app, ["plugins", str(root)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["plugins: 0", "diagnostics: 1"]
    assert "error:" in result.stderr


def test_existing_moughorai_entry_point_is_preserved() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'moughorai = "moughorai.cli:main"' in text
    assert 'atlas = "moughorai.atlas_cli:main"' in text


def test_plain_text_only_has_no_pr76_format_option() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--format" not in result.stdout


def test_default_analyzer_counts_included_files(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    service = atlas_cli.WorkspaceService(root)
    analyzer = atlas_cli._default_analyzer(service)
    value = analyzer(service.project("core"), {})
    assert value == {"project": "core", "files": 1, "dependencies": []}


def test_flatten_is_sorted_and_recursive() -> None:
    assert atlas_cli._flatten({"z": 1, "a": {"c": 3, "b": 2}}) == (
        ("a.b", 2),
        ("a.c", 3),
        ("z", 1),
    )


def test_display_is_stable() -> None:
    assert atlas_cli._display(True) == "true"
    assert atlas_cli._display(None) == "null"
    assert atlas_cli._display(["b", "a"]) == "b,a"
