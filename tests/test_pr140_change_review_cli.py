from __future__ import annotations

import json
from pathlib import Path
import subprocess

from typer.main import get_command
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.change_review import (
    ChangeReviewResponse,
    SnapshotAlignmentState,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic_snapshot import (
    AtlasSemanticSnapshot,
    SemanticSnapshotStore,
)
from moughorai.workspace import Workspace
from moughorai.workspace.cache import WorkspaceCache


runner = CliRunner()


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _snapshot() -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(
        (
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
                    ("visibility", "public"),
                ),
                qualified_name="demo.Service",
                project_id="core",
                language="java",
            ),
            KnowledgeNode(
                "type:consumer",
                KnowledgeKind.TYPE,
                "Consumer",
                metadata=(("path", "src/Consumer.java"),),
                qualified_name="demo.Consumer",
                project_id="core",
                language="java",
            ),
        ),
        (
            KnowledgeEdge(
                "project:core",
                "type:service",
                KnowledgeRelation.OWNS,
                ("global_symbol.owner:type:service",),
            ),
            KnowledgeEdge(
                "project:core",
                "type:consumer",
                KnowledgeRelation.OWNS,
                ("global_symbol.owner:type:consumer",),
            ),
            KnowledgeEdge(
                "type:consumer",
                "type:service",
                KnowledgeRelation.INHERITS,
                ("global_symbol.metadata:inherits:demo.Service",),
            ),
        ),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [],
        }),
        workspace_fingerprint="pr140-cli-workspace",
        analyzer_version="test/1",
    )


def _repository(root: Path) -> AtlasSemanticSnapshot:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "atlas@example.test")
    _git(root, "config", "user.name", "Atlas Tests")
    source = root / "src" / "Service.java"
    source.parent.mkdir()
    source.write_text("class Service {}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    snapshot = _snapshot()
    SemanticSnapshotStore(Workspace(root, ())).save(snapshot)
    source.write_text(
        "class Service { void changed() {} }\n",
        encoding="utf-8",
    )
    return snapshot


def _forbid_provider_and_rescan(monkeypatch) -> tuple[list[str], list[str]]:
    provider_calls: list[str] = []
    rescan_calls: list[str] = []

    def provider():
        provider_calls.append("provider")
        raise AssertionError("provider factory must not be invoked")

    def rescan(self, workspace):
        del self, workspace
        rescan_calls.append("workspace")
        raise AssertionError("change review must not rescan the workspace")

    monkeypatch.setattr(atlas_cli, "_ai_provider_factory", provider)
    monkeypatch.setattr(WorkspaceCache, "snapshot", rescan)
    return provider_calls, rescan_calls


def test_change_review_help_is_separate_and_exposes_bounded_controls() -> None:
    invoke_options = {"terminal_width": 200}
    root_help = runner.invoke(app, ["--help"], **invoke_options)
    command_help = runner.invoke(
        app,
        ["change-review", "--help"],
        **invoke_options,
    )
    ai_help = runner.invoke(app, ["ai", "--help"], **invoke_options)
    legacy_review_help = runner.invoke(
        app,
        ["ai", "review", "--help"],
        **invoke_options,
    )

    assert root_help.exit_code == command_help.exit_code == 0
    assert ai_help.exit_code == legacy_review_help.exit_code == 0
    assert "change-review" in root_help.stdout
    assert "review" in ai_help.stdout
    assert "--category" in legacy_review_help.stdout
    assert "--category" not in command_help.stdout
    registered_options = {
        option
        for parameter in get_command(app).commands["change-review"].params
        for option in (*parameter.opts, *parameter.secondary_opts)
    }
    for option in (
        "--snapshot",
        "--base",
        "--head",
        "--staged",
        "--change-kind",
        "--max-files",
        "--max-subjects-per-file",
        "--max-subjects",
        "--impact-depth",
        "--impact-limit",
        "--architecture-subject-limit",
        "--architecture-advice-limit",
        "--no-architecture",
        "--assume-current-snapshot",
        "--json",
        "--profile-output",
    ):
        assert option in registered_options


def test_default_json_is_deterministic_provider_free_and_unknown_alignment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    _repository(root)
    provider_calls, rescan_calls = _forbid_provider_and_rescan(monkeypatch)
    arguments = [
        "change-review",
        str(root),
        "--no-architecture",
        "--json",
    ]

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    response = ChangeReviewResponse.from_dict(payload)
    assert response.to_dict() == payload
    assert response.alignment is SnapshotAlignmentState.UNKNOWN
    assert response.impact is None
    assert response.architecture_reviews == ()
    assert response.changed_files[0].path == "src/Service.java"
    assert response.changed_files[0].subjects == ()
    assert response.section("impact").state.value == "unavailable"
    assert provider_calls == []
    assert rescan_calls == []


def test_explicit_snapshot_assumption_enables_bounded_semantic_enrichment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    _repository(root)
    provider_calls, rescan_calls = _forbid_provider_and_rescan(monkeypatch)

    result = runner.invoke(app, [
        "change-review",
        str(root),
        "--assume-current-snapshot",
        "--change-kind",
        "signature",
        "--max-files",
        "4",
        "--max-subjects-per-file",
        "3",
        "--max-subjects",
        "2",
        "--impact-depth",
        "2",
        "--impact-limit",
        "5",
        "--no-architecture",
        "--json",
    ])

    assert result.exit_code == 0, result.stderr
    response = ChangeReviewResponse.from_dict(json.loads(result.stdout))
    assert response.alignment is SnapshotAlignmentState.ASSUMED_CURRENT
    assert response.request.change_kind.value == "signature"
    assert response.request.maximum_files == 4
    assert response.request.maximum_subjects_per_file == 3
    assert response.request.maximum_subjects == 2
    assert response.request.impact_depth == 2
    assert response.request.impact_limit == 5
    assert response.request.include_architecture is False
    assert response.changed_files[0].subjects[0].canonical_id == "type:service"
    assert response.impact is not None
    assert response.impact.resolution.subject is not None
    assert response.impact.resolution.subject.canonical_id == "type:service"
    assert provider_calls == []
    assert rescan_calls == []


def test_human_output_is_deterministic_and_provider_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    _repository(root)
    provider_calls, rescan_calls = _forbid_provider_and_rescan(monkeypatch)
    arguments = [
        "change-review",
        str(root),
        "--assume-current-snapshot",
        "--no-architecture",
    ]

    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == second.exit_code == 0, first.stderr or second.stderr
    assert first.stdout == second.stdout
    assert first.stdout.startswith("Atlas Change Review\n")
    assert "snapshot alignment: assumed_current" in first.stdout
    assert "src/Service.java [modified]" in first.stdout
    assert "demo.Service" in first.stdout
    assert str(root) not in first.stdout
    assert provider_calls == []
    assert rescan_calls == []


def test_incompatible_git_selection_is_rejected_by_existing_diff_service(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _repository(root)

    missing_base = runner.invoke(app, [
        "change-review", str(root), "--head", "HEAD", "--json",
    ])
    staged_head = runner.invoke(app, [
        "change-review", str(root), "--base", "HEAD", "--head", "HEAD",
        "--staged", "--json",
    ])

    assert missing_base.exit_code == staged_head.exit_code == 2
    assert "diff head requires a base" in missing_base.stderr
    assert "staged diff cannot specify a head" in staged_head.stderr
    assert "Traceback" not in missing_base.stderr + staged_head.stderr


def test_profile_sidecar_is_opt_in_and_semantically_inert(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _repository(root)
    sidecar = root / ".atlas" / "measurements" / "change-review-test.json"
    arguments = [
        "change-review", str(root), "--no-architecture", "--json",
    ]

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
        "change_review.git_diff",
        "change_review.resolver_index",
        "change_review.path_association",
        "change_review.materialize",
        "change_review.render",
    }.issubset(report["phase_ids"])
    assert "profile:" in profiled.stderr
