from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.ai_explain import ExplainEngine
from moughorai.ai_context import AnalyzerRegistry
from moughorai.atlas_cli import app
from moughorai.java_symbols import DuplicateTypeError
from moughorai.repository_summary import RepositorySummaryService
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import (
    GRADLE_SETTINGS_MEMBERSHIP_OPTION,
    Project,
    WorkspaceDiscovery,
    WorkspaceService,
)
from moughorai.workspace.discovery import (
    _gradle_project_parts,
    _literal_gradle_includes,
)
from moughorai.workspace.files import project_files


runner = CliRunner()


def _custom_gradle_project(root: Path, relative: str) -> Path:
    project = root.joinpath(*relative.split("/"))
    project.mkdir(parents=True)
    (project / f"{project.name}.gradle").write_text("plugins {}\n", encoding="utf-8")
    return project


def test_literal_gradle_includes_are_static_safe_and_deterministic(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.gradle"
    settings.write_text(
        """plugins {
    id "example.settings"
}
include "alpha", ':nested:beta'
include(
    "gamma",
    ':nested:delta'
)
include "docs" // an existing marker project must be enriched, not duplicated
// include "line-commented"
/* include("block-commented") */
if (enabled) {
    include "conditional"
}
def selected = "dynamic"
include selected
include "${selected}"
include "../outside"
include "missing"
""",
        encoding="utf-8",
    )
    for relative in (
        "alpha",
        "nested/beta",
        "gamma",
        "nested/delta",
        "docs",
        "line-commented",
        "block-commented",
        "conditional",
        "dynamic",
        "unlisted",
    ):
        _custom_gradle_project(tmp_path, relative)
    (tmp_path / "docs" / "package.json").write_text("{}\n", encoding="utf-8")

    first = WorkspaceDiscovery().discover(tmp_path)
    expected_names = tuple(sorted((
        tmp_path.name,
        "alpha",
        "nested",
        "nested-beta",
        "gamma",
        "nested-delta",
        "docs",
    )))

    assert first.names() == expected_names
    assert len({project.path.resolve() for project in first.projects}) == len(first.projects)
    assert first.get(tmp_path.name).exclude == (
        "alpha/**/*",
        "docs/**/*",
        "gamma/**/*",
        "nested/**/*",
        "nested/beta/**/*",
        "nested/delta/**/*",
    )
    assert first.get("nested").exclude == ("beta/**/*", "delta/**/*")
    assert first.get("docs").option_map[GRADLE_SETTINGS_MEMBERSHIP_OPTION] == (
        "settings.gradle#include(:docs)"
    )
    assert "unlisted" not in first.names()
    assert WorkspaceDiscovery().discover(tmp_path).to_dict() == first.to_dict()

    settings.write_text(
        'include "docs"\ninclude(\":nested:delta\", "gamma")\n'
        'include ":nested:beta", "alpha"\n',
        encoding="utf-8",
    )
    assert WorkspaceDiscovery().discover(tmp_path).to_dict() == first.to_dict()


@pytest.mark.parametrize(
    "source",
    (
        'in/* masked */clude "alpha"',
        'include"alpha"',
        'def text = /\ninclude "alpha"\n/',
        'if (enabled)\n    include "alpha"',
        'configure(\n    include("alpha")\n)',
        'def values = [\n    include("alpha")\n]',
        'enabled &&\n    include("alpha")',
        'enabled ?\n    include("alpha")',
        'def selected =\n    include("alpha")',
        'return\n    include("alpha")',
        'throw failure\n    include("alpha")',
        'if (enabled) { return }\ninclude "alpha"',
        'if (enabled) { throw failure }\ninclude "alpha"',
        'include selected',
        'include("${selected}")',
    ),
)
def test_unsupported_gradle_context_never_creates_membership(source: str) -> None:
    assert _literal_gradle_includes(source) == ()


def test_gradle_comment_is_a_lexical_separator_not_token_joining() -> None:
    assert _literal_gradle_includes('include/* comment */"alpha"') == ("alpha",)


def test_completed_top_level_expression_does_not_hide_later_include() -> None:
    assert _literal_gradle_includes(
        'rootProject.name = "example"\ninclude "alpha"\n'
    ) == ("alpha",)


def test_gradle_project_paths_are_not_silently_retargeted() -> None:
    assert _gradle_project_parts(" alpha ") == ()
    assert _gradle_project_parts(":a::b") == ()
    assert _gradle_project_parts(":..:outside") == ()
    assert _gradle_project_parts(":módülé") == ("módülé",)


def test_conflicting_gradle_settings_files_are_not_combined(tmp_path: Path) -> None:
    (tmp_path / "settings.gradle").write_text('include "groovy"\n', encoding="utf-8")
    (tmp_path / "settings.gradle.kts").write_text(
        'include("kotlin")\n',
        encoding="utf-8",
    )
    _custom_gradle_project(tmp_path, "groovy")
    _custom_gradle_project(tmp_path, "kotlin")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert workspace.names() == (tmp_path.name,)


def test_resolved_gradle_aliases_do_not_change_project_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        'include "alpha"\ninclude "alias"\n',
        encoding="utf-8",
    )
    alpha = _custom_gradle_project(tmp_path, "alpha")
    alias = _custom_gradle_project(tmp_path, "alias")
    workspace_root = tmp_path.resolve()
    alpha_root = alpha.resolve()
    original_resolve = Path.resolve

    def resolve(path: Path, *args, **kwargs) -> Path:
        if path == alias:
            return alpha_root
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert WorkspaceDiscovery().discover(workspace_root).names() == (
        workspace_root.name,
    )


def test_gradle_root_alias_and_resolution_failure_are_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        'include "self-alias"\ninclude "broken"\n',
        encoding="utf-8",
    )
    self_alias = _custom_gradle_project(tmp_path, "self-alias")
    broken = _custom_gradle_project(tmp_path, "broken")
    workspace_root = tmp_path.resolve()
    original_resolve = Path.resolve

    def resolve(path: Path, *args, **kwargs) -> Path:
        if path == self_alias:
            return workspace_root
        if path == broken:
            raise RuntimeError("simulated symlink loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert WorkspaceDiscovery().discover(workspace_root).names() == (
        workspace_root.name,
    )


def test_flattened_gradle_name_collisions_fail_closed_deterministically(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.gradle"
    settings.write_text('include ":a-b", ":a:b"\n', encoding="utf-8")
    for relative in ("a-b", "a", "a/b"):
        tmp_path.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)
    for relative in ("a-b", "a/b"):
        tmp_path.joinpath(*relative.split("/"), "package.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

    first = WorkspaceDiscovery().discover(tmp_path)
    settings.write_text('include ":a:b", ":a-b"\n', encoding="utf-8")
    second = WorkspaceDiscovery().discover(tmp_path)

    assert first.to_dict() == second.to_dict()
    assert first.names() == tuple(sorted((tmp_path.name, "a")))


def test_gradle_name_collision_preserves_existing_generic_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text('include ":a-b"\n', encoding="utf-8")
    (tmp_path / "a-b").mkdir()
    existing = tmp_path / "a" / "b"
    existing.mkdir(parents=True)
    (existing / "package.json").write_text("{}\n", encoding="utf-8")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert workspace.names() == tuple(sorted((tmp_path.name, "a-b")))
    assert workspace.get("a-b").path == existing


def test_gradle_name_collision_with_root_does_not_publish_orphan_child(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        f'include ":{tmp_path.name}:child"\n',
        encoding="utf-8",
    )
    child = tmp_path / tmp_path.name
    (child / "child").mkdir(parents=True)
    (child / "package.json").write_text("{}\n", encoding="utf-8")

    assert WorkspaceDiscovery().discover(tmp_path).names() == (tmp_path.name,)


def test_resolved_gradle_parent_ambiguity_quarantines_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "settings.gradle"
    settings.write_text(
        'include ":alias:gamma", ":alpha:beta"\n',
        encoding="utf-8",
    )
    alias = tmp_path / "alias"
    alpha = tmp_path / "alpha"
    for path in (alias / "gamma", alpha / "gamma", alpha / "beta"):
        path.mkdir(parents=True, exist_ok=True)
    alias_root = alias.resolve()
    alpha_root = alpha.resolve()
    original_resolve = Path.resolve

    def resolve(path: Path, *args, **kwargs) -> Path:
        if path == alias_root:
            return alpha_root
        if path == alias_root / "gamma":
            return alpha_root / "gamma"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    first = WorkspaceDiscovery().discover(tmp_path)
    settings.write_text(
        'include ":alpha:beta", ":alias:gamma"\n',
        encoding="utf-8",
    )
    second = WorkspaceDiscovery().discover(tmp_path)

    assert first.to_dict() == second.to_dict()
    assert first.names() == (tmp_path.name,)


def test_command_style_gradle_children_preserve_java_project_ownership(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    (tmp_path / "settings.gradle").write_text(
        'include "alpha"\ninclude "beta"\n',
        encoding="utf-8",
    )
    for name in ("alpha", "beta"):
        project = _custom_gradle_project(tmp_path, name)
        source = project / "src" / "test" / "java" / "demo" / "Shared.java"
        source.parent.mkdir(parents=True)
        source.write_text("package demo; class Shared {}\n", encoding="utf-8")

    workspace = WorkspaceDiscovery().discover(tmp_path)
    root = workspace.get(tmp_path.name)

    assert workspace.names() == tuple(sorted((tmp_path.name, "alpha", "beta")))
    assert root.exclude == ("alpha/**/*", "beta/**/*")
    assert project_files(root.path, root.include, root.exclude) == (
        tmp_path / "build.gradle",
        tmp_path / "settings.gradle",
    )

    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])

    assert result.exit_code == 0
    assert "projects: 3" in result.stdout
    assert "succeeded: yes" in result.stdout
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    shared = [
        symbol
        for symbol in snapshot.semantic_context["symbols"]
        if symbol["qualified_name"] == "demo.Shared"
    ]
    assert {symbol["project_id"] for symbol in shared} == {"alpha", "beta"}
    assert len({symbol["id"] for symbol in shared}) == 2


def test_settings_membership_supplies_source_free_gradle_summary_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        'include "core"\ninclude "docs"\n',
        encoding="utf-8",
    )
    _custom_gradle_project(tmp_path, "core")
    _custom_gradle_project(tmp_path, "docs")
    (tmp_path / "docs" / "package.json").write_text("{}\n", encoding="utf-8")
    unreferenced = tmp_path / "gradle" / "ide.gradle"
    unreferenced.parent.mkdir()
    unreferenced.write_text("plugins {}\n", encoding="utf-8")

    service = WorkspaceService(tmp_path)
    first = RepositorySummaryService(service).build().to_dict()
    second = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    by_name = {project["name"]: project for project in first["projects"]}

    assert first == second
    assert first["project_count"] == 3
    assert by_name["core"]["build_systems"] == ["Gradle"]
    assert by_name["docs"]["build_systems"] == ["Gradle", "npm"]
    assert first["build_systems"] == ["Gradle", "npm"]
    assert "gradle" not in service.workspace.names()

    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    context = ExplainEngine._repository_context(snapshot).to_dict()
    builds = context["repository_summary"]["build_systems"]

    assert "statically parsed literal Gradle settings membership" in builds[
        "evidence_basis"
    ]
    serialized = str(snapshot.semantic_context["repository_summary"])
    assert "plugins {}" not in serialized


def test_gradle_analysis_separates_only_shadowed_version_variants(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    baseline = tmp_path / "src" / "main" / "java" / "demo" / "Versioned.java"
    alternative = tmp_path / "src" / "main" / "java21" / "demo" / "Versioned.java"
    additive = tmp_path / "src" / "main" / "java21" / "demo" / "OnlyOn21.java"
    test_fixture = (
        tmp_path / "src" / "testFixtures" / "java" / "demo" / "FixtureType.java"
    )
    benchmark = tmp_path / "src" / "jmh" / "java" / "demo" / "BenchmarkType.java"
    sources = {
        baseline: "package demo; class Versioned {}\n",
        alternative: "package demo; class Versioned {}\n",
        additive: "package demo; class OnlyOn21 {}\n",
        test_fixture: "package demo; class FixtureType {}\n",
        benchmark: "package demo; class BenchmarkType {}\n",
    }
    for path, source in sources.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    document = AnalyzerRegistry()(WorkspaceDiscovery().discover(tmp_path).get(tmp_path.name), {})
    symbols = document.get_artifact("global_symbols", ())
    matches = [
        symbol
        for symbol in symbols
        if symbol.qualified_name == "demo.Versioned"
    ]

    assert len(matches) == 1
    assert matches[0].source == baseline
    assert {symbol.qualified_name for symbol in symbols} >= {
        "demo.OnlyOn21",
        "demo.FixtureType",
        "demo.BenchmarkType",
    }
    variants = [
        diagnostic
        for diagnostic in document.diagnostics
        if diagnostic.code == "ATLAS-JAVA-SOURCE-VARIANT"
    ]
    assert len(variants) == 1
    assert variants[0].severity.value == "WARNING"
    assert variants[0].location == Path("src/main/java21/demo/Versioned.java")


def test_gradle_project_without_known_source_roots_preserves_legacy_scan(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    source = tmp_path / "Loose.java"
    source.write_text("package demo; class Loose {}\n", encoding="utf-8")

    document = AnalyzerRegistry()(WorkspaceDiscovery().discover(tmp_path).get(tmp_path.name), {})

    assert any(
        symbol.qualified_name == "demo.Loose"
        for symbol in document.get_artifact("global_symbols", ())
    )


def test_versioned_path_filter_does_not_change_loose_java_projects(
    tmp_path: Path,
) -> None:
    for root in ("java", "java21"):
        source = tmp_path / "src" / "main" / root / "demo" / "Versioned.java"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("package demo; class Versioned {}\n", encoding="utf-8")

    with pytest.raises(DuplicateTypeError, match="Duplicate Java type 'demo.Versioned'"):
        AnalyzerRegistry()(Project("loose", tmp_path), {})
