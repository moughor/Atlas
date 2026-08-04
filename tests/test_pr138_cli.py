from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli, public_api
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.java_security import JavaSecurityAnalyzer
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.security_intelligence import (
    SecurityIntelligenceReport,
    SecurityIntelligenceService,
    SecurityProducerReport,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore
from moughorai.subject_resolution import CanonicalSubjectResolver
from moughorai.workspace import Workspace


runner = CliRunner()


def _base_snapshot() -> AtlasSemanticSnapshot:
    graph = KnowledgeGraph(
        (
            KnowledgeNode(
                "project:alpha",
                KnowledgeKind.PROJECT,
                "alpha",
                qualified_name="alpha",
            ),
            KnowledgeNode(
                "type:alpha",
                KnowledgeKind.TYPE,
                "Alpha",
                qualified_name="demo.Alpha",
                project_id="alpha",
                language="java",
            ),
            KnowledgeNode(
                "project:beta",
                KnowledgeKind.PROJECT,
                "beta",
                qualified_name="beta",
            ),
            KnowledgeNode(
                "type:beta",
                KnowledgeKind.TYPE,
                "Beta",
                qualified_name="demo.Beta",
                project_id="beta",
                language="java",
            ),
        ),
        (
            KnowledgeEdge(
                "project:alpha",
                "type:alpha",
                KnowledgeRelation.OWNS,
                ("semantic_graph.project_id",),
            ),
            KnowledgeEdge(
                "project:beta",
                "type:beta",
                KnowledgeRelation.OWNS,
                ("semantic_graph.project_id",),
            ),
        ),
    )
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({
            "schema_version": 1,
            "semantic_graph": graph.to_dict(),
            "symbols": [
                {
                    "id": "type:alpha",
                    "kind": "type",
                    "name": "Alpha",
                    "qualified_name": "demo.Alpha",
                    "project_id": "alpha",
                    "language": "java",
                    "source": "src/main/java/demo/Alpha.java",
                },
                {
                    "id": "type:beta",
                    "kind": "type",
                    "name": "Beta",
                    "qualified_name": "demo.Beta",
                    "project_id": "beta",
                    "language": "java",
                    "source": "src/main/java/demo/Beta.java",
                },
            ],
        }),
        workspace_fingerprint="pr138-cli-fixture",
        analyzer_version="test/1",
    )


def _snapshot(*, include_security: bool = True) -> AtlasSemanticSnapshot:
    base = _base_snapshot()
    if not include_security:
        return base
    java = JavaSecurityAnalyzer()
    alpha = java.analyze_source(
        "class Alpha {\n"
        'String password = "password=supersecret123";\n'
        'String apiKey = "api_key=abcdefghijk";\n'
        "}",
        "src/main/java/demo/Alpha.java",
    )
    beta = java.analyze_source(
        "class Beta { void run() { "
        'MessageDigest.getInstance("MD5"); } }',
        "src/main/java/demo/Beta.java",
    )
    reports = (
        SecurityProducerReport.from_findings(
            alpha.findings,
            project_id="alpha",
            source_files=1,
            warning_count=len(alpha.warnings),
        ),
        SecurityProducerReport.from_findings(
            beta.findings,
            project_id="beta",
            source_files=1,
            warning_count=len(beta.warnings),
        ),
    )
    resolver = CanonicalSubjectResolver.from_snapshot(base)
    report = SecurityIntelligenceService(
        resolver,
        snapshot_id=f"semantic-graph:{resolver.graph_digest}",
    ).build_published_report(reports)
    context = dict(base.semantic_context)
    context["security_intelligence"] = report.to_dict()
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr138-cli-fixture",
        analyzer_version="test/1",
    )


def _save(root: Path, *, include_security: bool = True) -> AtlasSemanticSnapshot:
    root.mkdir(parents=True)
    snapshot = _snapshot(include_security=include_security)
    SemanticSnapshotStore(Workspace(root, ())).save(snapshot)
    return snapshot


def test_security_json_and_human_outputs_are_deterministic_and_source_free(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    first = runner.invoke(app, ["security", str(root), "--json"])
    second = runner.invoke(app, ["security", str(root), "--json"])
    human = runner.invoke(app, [
        "security",
        str(root),
        "--explain-priority",
    ])

    assert first.exit_code == second.exit_code == human.exit_code == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    restored = SecurityIntelligenceReport.from_dict(payload)
    assert restored.to_dict() == payload
    assert first.stdout == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    assert len(restored.findings) == 3
    assert human.stdout.startswith("Atlas security intelligence\n")
    assert "ATLAS-SECRET-001" in human.stdout
    assert "priority.severity:" in human.stdout
    assert not contains_absolute_path(human.stdout)
    assert "password=supersecret123" not in first.stdout + human.stdout


def test_security_filters_project_and_symbol_scope_and_applies_limit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    filtered = runner.invoke(app, [
        "security",
        str(root),
        "--scope",
        "project",
        "--project",
        "alpha",
        "--language",
        "java",
        "--category",
        "secrets",
        "--severity",
        "high",
        "--limit",
        "1",
        "--json",
    ])
    symbol = runner.invoke(app, [
        "security",
        str(root),
        "--scope",
        "symbol",
        "--subject-id",
        "type:alpha",
        "--json",
    ])

    assert filtered.exit_code == symbol.exit_code == 0
    filtered_report = SecurityIntelligenceReport.from_dict(
        json.loads(filtered.stdout)
    )
    assert filtered_report.request.scope.value == "project"
    assert filtered_report.request.projects == ("alpha",)
    assert filtered_report.request.languages == ("java",)
    assert [item.value for item in filtered_report.request.categories] == [
        "secrets"
    ]
    assert len(filtered_report.findings) == 1
    assert filtered_report.total_finding_count == 2
    assert filtered_report.omitted_count == 1
    assert filtered_report.truncated is True

    symbol_report = SecurityIntelligenceReport.from_dict(json.loads(symbol.stdout))
    assert symbol_report.request.scope.value == "symbol"
    assert len(symbol_report.findings) == 2
    assert {
        item.canonical_subject_id for item in symbol_report.findings
    } == {"type:alpha"}


def test_security_missing_and_older_snapshots_are_explicit(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "private-missing-workspace"
    missing = runner.invoke(app, [
        "security",
        str(missing_root),
        "--json",
    ])

    old_root = tmp_path / "old-workspace"
    _save(old_root, include_security=False)
    old = runner.invoke(app, ["security", str(old_root), "--json"])

    assert missing.exit_code == 2
    assert (
        "error: semantic snapshot not found; run analysis snapshot creation first"
        in missing.stderr
    )
    assert str(missing_root) not in missing.stderr
    assert "Traceback" not in missing.stderr

    assert old.exit_code == 0, old.stderr
    old_report = SecurityIntelligenceReport.from_dict(json.loads(old.stdout))
    assert old_report.findings == ()
    assert old_report.total_finding_count == 0
    assert any(
        "older or partial snapshot" in item
        for item in old_report.limitations
    )
    assert {
        item.state.value for item in old_report.capabilities
    } == {"not_analyzed"}


def test_security_cli_reads_only_persisted_semantics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    _save(root)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("security CLI must not rescan source or workspace")

    monkeypatch.setattr(atlas_cli, "_context", forbidden)
    monkeypatch.setattr(JavaSecurityAnalyzer, "analyze_source", forbidden)

    result = runner.invoke(app, ["security", str(root), "--json"])

    assert result.exit_code == 0, result.stderr
    assert len(json.loads(result.stdout)["findings"]) == 3


def test_security_profile_sidecar_is_opt_in_and_semantically_inert(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _save(root)
    sidecar = tmp_path / "security-profile.json"

    baseline = runner.invoke(app, ["security", str(root), "--json"])
    profiled = runner.invoke(app, [
        "security",
        str(root),
        "--json",
        "--profile-output",
        str(sidecar),
    ])

    assert baseline.exit_code == profiled.exit_code == 0
    assert baseline.stdout == profiled.stdout
    assert sidecar.is_file()
    profile = json.loads(sidecar.read_text(encoding="utf-8"))
    assert {
        "security_intelligence.subject_index",
        "security_intelligence.query",
        "security_intelligence.render",
    }.issubset(profile["phase_ids"])
    assert "profile:" in profiled.stderr


def test_public_security_facade_uses_persisted_snapshot_contract() -> None:
    snapshot = _snapshot()

    response = public_api.SecurityIntelligenceService.from_snapshot(
        snapshot
    ).analyze(public_api.SecurityIntelligenceRequest(limit=1))

    assert isinstance(response, public_api.SecurityIntelligenceReport)
    assert len(response.findings) == 1
    assert response.total_finding_count == 3
    assert response.omitted_count == 2
    assert response.to_dict() == SecurityIntelligenceReport.from_dict(
        response.to_dict()
    ).to_dict()
