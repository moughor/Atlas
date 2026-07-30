from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _mixed_workspace(root: Path) -> None:
    (root / "atlas.yaml").write_text(
        "projects:\n  - name: mixed\n    path: src\n",
        encoding="utf-8",
    )
    source = root / "src"
    source.mkdir()
    (source / "App.java").write_text(
        "package demo; class App {}",
        encoding="utf-8",
    )
    (source / "service.py").write_text(
        "class Service:\n    pass\n",
        encoding="utf-8",
    )
    (source / "client.ts").write_text(
        'import { Service } from "./service";\n'
        "export interface Client {}\n"
        "export function create(): Client { return {} as Client; }\n",
        encoding="utf-8",
    )


def test_java_python_typescript_share_snapshot_graph(tmp_path: Path) -> None:
    _mixed_workspace(tmp_path)
    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    graph = snapshot.semantic_context["semantic_graph"]
    languages = {node["language"] for node in graph["nodes"]}
    names = {node["qualified_name"] for node in graph["nodes"]}
    assert {"java", "python", "typescript"} <= languages
    assert {"demo.App", "service.Service", "client.Client", "client#create()"} <= names
    assert any(edge["kind"] == "imports" for edge in graph["edges"])


def test_cross_language_snapshot_is_deterministic(tmp_path: Path) -> None:
    _mixed_workspace(tmp_path)
    first = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    first_snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    second = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    second_snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert first.exit_code == second.exit_code == 0
    assert first_snapshot.semantic_context["semantic_graph"] == second_snapshot.semantic_context["semantic_graph"]


def test_typescript_tsx_is_routed_to_builtin_frontend(tmp_path: Path) -> None:
    (tmp_path / "view.tsx").write_text(
        "export class View {}",
        encoding="utf-8",
    )
    from moughorai.ai_context import AnalyzerRegistry
    from moughorai.workspace import Project

    document = AnalyzerRegistry()(Project("web", tmp_path), {})
    assert document.language == "typescript"
    assert any(
        symbol.qualified_name == "view.View"
        for symbol in document.get_artifact("global_symbols")
    )
