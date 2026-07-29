from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.profiling import ProfileMetric, ProfileReport
from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import TypeRegistry, TypeTable
from moughorai.workspace import Project, Workspace


def _workspace(tmp_path: Path) -> Workspace:
    return Workspace(
        tmp_path,
        (
            Project("web", tmp_path / "web", dependencies=("core",)),
            Project("core", tmp_path / "core"),
        ),
    )


def test_context_is_deterministic_across_input_order(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    symbols = [
        GlobalSymbol.create(GlobalSymbolKind.TYPE, "Z", "demo.Z"),
        GlobalSymbol.create(GlobalSymbolKind.TYPE, "A", "demo.A"),
    ]
    diagnostics = {
        "web": [
            Diagnostic("Z2", "later", DiagnosticSeverity.WARNING),
            Diagnostic("A1", "first", DiagnosticSeverity.ERROR),
        ]
    }
    metrics = ProfileReport(
        (
            ProfileMetric("z", 1, 2.0, 2.0, 2.0, 2.0),
            ProfileMetric("a", 1, 1.0, 1.0, 1.0, 1.0),
        )
    )
    types = {"web": TypeTable({("line", 2): TypeRegistry().primitive("int")})}
    builder = WorkspaceContextBuilder()

    first = builder.build(
        workspace,
        diagnostics=diagnostics,
        symbols=symbols,
        types=types,
        metrics=metrics,
    ).to_json()
    second = builder.build(
        workspace,
        diagnostics={"web": reversed(diagnostics["web"])},
        symbols=reversed(symbols),
        types=types,
        metrics=reversed(metrics.metrics),
    ).to_json()

    assert first == second
    assert first.endswith("}") and "\n" not in first


def test_context_selects_projects_without_mutating_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    context = WorkspaceContextBuilder().build(
        workspace,
        projects=(workspace.get("web"),),
    ).to_dict()

    assert [project["name"] for project in context["workspace"]["projects"]] == ["web"]
    assert workspace.names() == ("core", "web")


def test_context_rejects_foreign_projects(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(ValueError, match="not members"):
        WorkspaceContextBuilder().build(
            workspace,
            projects=(Project("other", tmp_path / "other"),),
        )


def test_context_rejects_unstable_type_keys(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    table = TypeTable({object(): TypeRegistry().primitive("int")})
    with pytest.raises(TypeError, match="not deterministic"):
        WorkspaceContextBuilder().build(workspace, types=table)
