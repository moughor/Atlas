from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.global_symbols import GlobalSymbolKind
from moughorai.python_semantics import PythonSemanticAnalyzer
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _source(tmp_path: Path, text: str, name: str = "pkg/models.py") -> tuple[Path, Path]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return tmp_path, path


def test_python_analyzer_extracts_required_language_features(tmp_path: Path) -> None:
    root, path = _source(
        tmp_path,
        '''"""Module docs."""
import os
from typing import Optional
from . import helper
GLOBAL: int = 1

@dataclass(frozen=True)
class User:
    """User docs."""
    name: str

    @classmethod
    async def load(cls, value: int) -> Optional["User"]:
        """Load docs."""
        def normalize() -> str:
            return str(value)
        return None

class State(Enum):
    READY = "ready"
''',
    )
    result = PythonSemanticAnalyzer().analyze(root, (path,))
    by_name = {symbol.qualified_name: symbol for symbol in result.symbols}
    assert result.modules[0].name == "pkg.models"
    assert result.modules[0].imports == (".helper", "os", "typing.Optional")
    assert by_name["pkg.models"].kind is GlobalSymbolKind.PACKAGE
    assert by_name["pkg.models.GLOBAL"].kind is GlobalSymbolKind.FIELD
    assert dict(by_name["pkg.models.User"].metadata)["dataclass"] == "true"
    assert dict(by_name["pkg.models.State"].metadata)["enum"] == "true"
    load = by_name["pkg.models.User.load"]
    assert dict(load.metadata)["async"] == "true"
    assert dict(load.metadata)["decorators"] == "classmethod"
    assert dict(load.metadata)["parameters"] == "cls,value:int"
    assert dict(load.metadata)["return_type"] == "Optional['User']"
    assert dict(load.metadata)["docstring"] == "Load docs."
    assert "pkg.models.User.load.normalize" in by_name
    assert result.types.require("pkg.models.GLOBAL").name == "int"
    assert result.types.require("pkg.models.User.name").name == "str"


def test_python_analyzer_reports_syntax_errors_deterministically(tmp_path: Path) -> None:
    root, path = _source(tmp_path, "def broken(:\n", "broken.py")
    result = PythonSemanticAnalyzer().analyze(root, (path,))
    assert result.symbols == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "ATLAS-PYTHON-PARSE"
    assert result.diagnostics[0].location == path


def test_python_init_module_uses_package_name(tmp_path: Path) -> None:
    root, path = _source(tmp_path, "class Public: pass\n", "pkg/__init__.py")
    result = PythonSemanticAnalyzer().analyze(root, (path,))
    assert result.modules[0].name == "pkg"
    assert any(symbol.qualified_name == "pkg.Public" for symbol in result.symbols)


def test_cli_publishes_rich_python_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text(
        "class App:\n    def run(self, value: int) -> str:\n        return str(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: python-app\n    path: src\n    include: ['**/*.py']\n",
        encoding="utf-8",
    )
    analyzed = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert analyzed.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    names = {item["qualified_name"] for item in snapshot.semantic_context["symbols"]}
    assert {"app", "app.App", "app.App.run"}.issubset(names)
    assert snapshot.semantic_context["types"]["python-app"] == [
        {
            "node": "app.App.run",
            "type": {"kind": "class", "name": "str"},
        }
    ]


def test_python_snapshot_recovery_preserves_types(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "typed.py").write_text("value: int = 1\n", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: p\n    path: src\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["analyze", str(tmp_path)]).exit_code == 0
    second = runner.invoke(app, ["analyze", str(tmp_path)])
    assert second.exit_code == 0
    assert "p: reused" in second.stdout
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    assert snapshot.semantic_context["types"]["p"][0]["node"] == "typed.value"
