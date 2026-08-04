from __future__ import annotations

import json
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_ask.safety import contains_unsafe_chat_content
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeNode
from moughorai.repository_evolution import RepositoryEvolutionResponse
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.workspace import Workspace, WorkspaceAnalysisOrchestrator
from moughorai.workspace.cache import WorkspaceCache


runner = CliRunner()


def _graph(*, head: bool) -> KnowledgeGraph:
    nodes = [
        KnowledgeNode(
            "project:core",
            KnowledgeKind.PROJECT,
            "core",
            metadata=(("path", "."),),
            qualified_name="core",
            project_id="core",
        ),
        KnowledgeNode(
            "type:service",
            KnowledgeKind.TYPE,
            "Service",
            metadata=(
                ("path", "src/Service.java"),
                ("visibility", "public" if head else "package"),
            ),
            qualified_name="demo.Service",
            project_id="core",
            language="java",
        ),
    ]
    if head:
        nodes.append(KnowledgeNode(
            "type:helper",
            KnowledgeKind.TYPE,
            "Helper",
            metadata=(("path", "src/Helper.java"),),
            qualified_name="demo.Helper",
            project_id="core",
            language="java",
        ))
    return KnowledgeGraph(tuple(nodes), ())


def _snapshot(root: Path, *, head: bool) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "workspace": {
                "root": root.resolve().as_posix(),
                "projects": [],
            },
            "semantic_graph": _graph(head=head).to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint=(
            "pr141-cli-head-workspace" if head else "pr141-cli-base-workspace"
        ),
        analyzer_version="test/1",
    )


def _save_pair(root: Path) -> tuple[Path, Path, AtlasSemanticSnapshot, AtlasSemanticSnapshot]:
    root.mkdir(parents=True)
    store = SemanticSnapshotStore(Workspace(root, ()))
    base = _snapshot(root, head=False)
    head = _snapshot(root, head=True)
    base_path = store.save(base)
    store.save(head)
    return base_path, store.latest_path, base, head


def _arguments(root: Path, base: Path, head: Path | None = None) -> list[str]:
    result = [
        "evolution",
        str(root),
        "--base-snapshot",
        str(base),
        "--max-node-changes",
        "8",
        "--max-relation-changes",
        "8",
        "--json",
    ]
    if head is not None:
        result.extend(("--head-snapshot", str(head)))
    return result


def test_evolution_help_exposes_required_pair_bounds_and_profile_controls() -> None:
    invoke_options = {"terminal_width": 220}
    root_help = runner.invoke(app, ["--help"], **invoke_options)
    command_help = runner.invoke(app, ["evolution", "--help"], **invoke_options)

    assert root_help.exit_code == command_help.exit_code == 0
    assert "evolution" in root_help.stdout
    assert "Compare exact canonical facts" in command_help.stdout
    registered_options = {
        option
        for parameter in get_command(app).commands["evolution"].params
        for option in (*parameter.opts, *parameter.secondary_opts)
    }
    assert {
        "--base-snapshot",
        "--head-snapshot",
        "--max-node-changes",
        "--max-relation-changes",
        "--json",
        "--profile",
        "--profile-output",
        "--profile-memory",
        "--profile-python-memory",
    }.issubset(registered_options)

    missing_base = runner.invoke(app, ["evolution"])
    assert missing_base.exit_code == 2
    assert "--base-snapshot" in missing_base.stderr
    assert "Traceback" not in missing_base.stderr


def test_evolution_json_and_human_output_are_deterministic_and_source_free(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    base_path, head_path, base, head = _save_pair(root)
    arguments = _arguments(root, base_path, head_path)

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)
    human_arguments = [item for item in arguments if item != "--json"]
    first_human = runner.invoke(app, human_arguments)
    second_human = runner.invoke(app, human_arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first_human.exit_code == second_human.exit_code == 0
    assert first.stdout == second.stdout
    assert first_human.stdout == second_human.stdout
    payload = json.loads(first.stdout)
    response = RepositoryEvolutionResponse.from_dict(payload)
    assert response.to_dict() == payload
    assert response.base.snapshot_id == base.snapshot_id
    assert response.head.snapshot_id == head.snapshot_id
    assert [item.change.value for item in response.node_changes] == [
        "added",
        "modified",
    ]
    assert response.total_relation_change_count == 0
    assert first_human.stdout.startswith("Atlas Repository Evolution\n")
    assert "demo.Helper" in first_human.stdout
    assert str(root.resolve()) not in first.stdout + first_human.stdout
    assert not contains_absolute_path(payload)
    assert not contains_unsafe_chat_content(payload)


def test_evolution_defaults_head_to_latest_and_reports_snapshot_errors(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    base_path, head_path, _base, _head = _save_pair(root)

    default_head = runner.invoke(app, _arguments(root, base_path))
    explicit_head = runner.invoke(app, _arguments(root, base_path, head_path))
    missing = runner.invoke(app, _arguments(root, root / "missing.ass", head_path))
    corrupt = root / "corrupt.ass"
    corrupt.write_text("{not-json", encoding="utf-8")
    corrupt_result = runner.invoke(app, _arguments(root, corrupt, head_path))

    assert default_head.exit_code == explicit_head.exit_code == 0
    assert default_head.stdout == explicit_head.stdout
    assert missing.exit_code == corrupt_result.exit_code == 2
    assert "semantic snapshot not found" in missing.stderr
    assert "semantic snapshot could not be loaded or verified" in corrupt_result.stderr
    assert str(root) not in missing.stderr + corrupt_result.stderr
    assert "Traceback" not in missing.stderr + corrupt_result.stderr


def test_evolution_loads_snapshots_without_analysis_rescan_or_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    base_path, head_path, _base, _head = _save_pair(root)
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("forbidden")
        raise AssertionError("evolution must use persisted semantic snapshots only")

    monkeypatch.setattr(atlas_cli, "_context", forbidden)
    monkeypatch.setattr(atlas_cli, "_ai_provider_factory", forbidden)
    monkeypatch.setattr(WorkspaceCache, "snapshot", forbidden)
    monkeypatch.setattr(WorkspaceAnalysisOrchestrator, "execute", forbidden)

    result = runner.invoke(app, _arguments(root, base_path, head_path))

    assert result.exit_code == 0, result.stderr
    assert RepositoryEvolutionResponse.from_dict(json.loads(result.stdout))
    assert calls == []


def test_evolution_profile_sidecar_is_opt_in_and_semantically_inert(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    base_path, head_path, _base, _head = _save_pair(root)
    sidecar = root / ".atlas" / "measurements" / "evolution-test.json"
    arguments = _arguments(root, base_path, head_path)

    baseline = runner.invoke(app, arguments)
    profiled = runner.invoke(app, [
        *arguments,
        "--profile-output",
        str(sidecar),
    ])

    assert baseline.exit_code == profiled.exit_code == 0
    assert baseline.stdout == profiled.stdout
    assert sidecar.is_file()
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {
        "repository_evolution.prepare",
        "repository_evolution.compare_nodes",
        "repository_evolution.compare_relations",
        "repository_evolution.render",
    }.issubset(report["phase_ids"])
    assert "profile:" in profiled.stderr
