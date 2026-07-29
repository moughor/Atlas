from configparser import ConfigParser
from pathlib import Path
import tomllib
import zipfile

from typer.testing import CliRunner

import moughorai
from moughorai.atlas_cli import app
from moughorai.version import __version__


ROOT = Path(__file__).parents[1]


def test_release_version_is_canonical() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__ == moughorai.__version__ == "2.0.0"


def test_version_cli() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == "Atlas 2.0.0\n"


def test_release_metadata_and_package_discovery() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["readme"] == "README.md"
    assert data["project"]["requires-python"] == ">=3.12"
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["."]
    assert data["tool"]["setuptools"]["packages"]["find"]["include"] == ["moughorai*"]
    assert data["project"]["scripts"]["atlas"] == "moughorai.atlas_cli:main"


def test_release_files_exist() -> None:
    assert (ROOT / "README.md").is_file()
    assert (ROOT / "LICENSE").is_file()


def test_built_wheel_contains_runtime_and_entry_point() -> None:
    wheels = sorted((ROOT / "dist").glob(f"moughorai-{__version__}-*.whl"))
    if not wheels:
        return
    with zipfile.ZipFile(wheels[-1]) as archive:
        names = set(archive.namelist())
        assert "moughorai/atlas_cli.py" in names
        assert "moughorai/version.py" in names
        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        parser = ConfigParser()
        parser.read_string(archive.read(entry_name).decode())
        assert parser["console_scripts"]["atlas"] == "moughorai.atlas_cli:main"
