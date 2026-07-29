from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.ci_templates import CiProvider, CiTemplateError, CiTemplateService


runner = CliRunner()


@pytest.mark.parametrize(
    ("provider", "path", "marker"),
    [
        (CiProvider.GITHUB, ".github/workflows/atlas.yml", "actions/setup-python@v5"),
        (CiProvider.GITLAB, ".gitlab-ci.yml", "image: python:3.12"),
        (CiProvider.AZURE, "azure-pipelines.yml", "task: UsePythonVersion@0"),
    ],
)
def test_render_supported_templates(provider: CiProvider, path: str, marker: str) -> None:
    template = CiTemplateService().render(provider)
    assert template.path == Path(path)
    assert marker in template.content
    assert "atlas check . --format sarif > atlas.sarif" in template.content
    assert template.content.endswith("\n")
    assert "\r" not in template.content


def test_render_is_deterministic_and_supports_python_version() -> None:
    service = CiTemplateService()
    first = service.render("github", python_version="3.13")
    assert first == service.render("github", python_version="3.13")
    assert 'python-version: "3.13"' in first.content


@pytest.mark.parametrize("version", ["3", "latest", "3.12; echo unsafe", ""])
def test_invalid_python_version_is_rejected(version: str) -> None:
    with pytest.raises(CiTemplateError, match="invalid Python version"):
        CiTemplateService().render("github", python_version=version)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(CiTemplateError, match="unsupported CI provider"):
        CiTemplateService().render("jenkins")


def test_write_uses_canonical_path(tmp_path: Path) -> None:
    target = CiTemplateService().write(tmp_path, "github")
    assert target == tmp_path / ".github" / "workflows" / "atlas.yml"
    assert target.read_bytes().startswith(b"name: Atlas\n")


def test_write_refuses_existing_file_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".gitlab-ci.yml"
    target.write_text("custom\n", encoding="utf-8")
    with pytest.raises(CiTemplateError, match="refusing to overwrite"):
        CiTemplateService().write(tmp_path, "gitlab")
    assert target.read_text(encoding="utf-8") == "custom\n"


def test_write_force_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "ci.yml"
    target.write_text("old", encoding="utf-8")
    result = CiTemplateService().write(tmp_path, "azure", output=Path("ci.yml"), force=True)
    assert result == target
    assert "PublishBuildArtifacts@1" in target.read_text(encoding="utf-8")


def test_cli_creates_template_and_reports_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ci", "github", "--root", str(tmp_path)])
    target = tmp_path / ".github" / "workflows" / "atlas.yml"
    assert result.exit_code == 0
    assert result.stdout.strip() == target.as_posix()
    assert target.is_file()


def test_cli_existing_template_is_deterministic_error(tmp_path: Path) -> None:
    CiTemplateService().write(tmp_path, "gitlab")
    result = runner.invoke(app, ["ci", "gitlab", "--root", str(tmp_path)])
    assert result.exit_code == 2
    assert "refusing to overwrite" in result.stderr


def test_cli_help_lists_ci_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ci" in result.stdout
