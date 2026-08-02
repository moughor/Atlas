from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.ai_context import AnalyzerRegistry
from moughorai.workspace import (
    GRADLE_SETTINGS_MEMBERSHIP_OPTION,
    WorkspaceDiscovery,
)
from moughorai.workspace.discovery import _canonical_gradle_logical_path
from moughorai.workspace.files import project_files


def _project(root: Path, relative: str, *, source: str | None = None) -> Path:
    project = root.joinpath(*relative.split("/"))
    project.mkdir(parents=True, exist_ok=True)
    (project / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    if source is not None:
        path = project / "src" / "main" / "java" / "demo" / "Shared.java"
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")
    return project


def _verified_helper(
    *invocations: tuple[str, str],
    skip_path: str = ":modules:one:two:three:skip",
) -> str:
    calls = "\n".join(
        f"scanProjects({prefix!r}, new File(rootProject.projectDir, {relative!r}))"
        for prefix, relative in invocations
    )
    return f'''void scanProjects(String path, File dir) {{
  if (dir.isDirectory() == false) return
  if (dir.name == 'buildSrc') return
  if (new File(dir, 'build.gradle').exists() == false) return
  if (new File(dir, 'settings.gradle').exists()) return
  if (findProject(dir) != null) return

  final String projectName = "${{path}}:${{dir.name}}"
  if (projectName.equals("{skip_path}")) {{
    return
  }}

  include projectName
  if (path.isEmpty() || path.startsWith(':examples')) {{
    project(projectName).projectDir = dir
  }}
  for (File subdir : dir.listFiles()) {{
    scanProjects(projectName, subdir)
  }}
}}

{calls}
'''


def _deep_chain(root: Path) -> Path:
    for relative in (
        "modules",
        "modules/one",
        "modules/one/two",
        "modules/one/two/three",
    ):
        _project(root, relative)
    return root / "modules" / "one" / "two" / "three"


def _named_deep_chain(root: Path, name: str) -> Path:
    current = ""
    for part in (name, "one", "two", "three"):
        current = f"{current}/{part}" if current else part
        _project(root, current)
    return root / name / "one" / "two" / "three"


def test_logical_path_round_trip_rejects_colon_in_physical_segment() -> None:
    assert _canonical_gradle_logical_path(("modules", "valid")) == ":modules:valid"
    assert _canonical_gradle_logical_path(("modules", "invalid:name")) is None


def test_verified_recursive_membership_separates_deep_project_ownership(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        _verified_helper(("", "modules")),
        encoding="utf-8",
    )
    parent = _deep_chain(tmp_path)
    source = "package demo; class Shared {}\n"
    _project(tmp_path, "modules/one/two/three/alpha", source=source)
    _project(tmp_path, "modules/one/two/three/beta", source=source)

    workspace = WorkspaceDiscovery().discover(tmp_path)
    alpha = workspace.get("modules-one-two-three-alpha")
    beta = workspace.get("modules-one-two-three-beta")
    owner = workspace.get("modules-one-two-three")

    assert owner.path == parent
    assert owner.exclude == ("alpha/**/*", "beta/**/*")
    assert not any(
        path.suffix == ".java"
        for path in project_files(owner.path, owner.include, owner.exclude)
    )
    evidence = alpha.option_map[GRADLE_SETTINGS_MEMBERSHIP_OPTION]
    assert evidence == (
        "settings.gradle#recursive(scanProjects,"
        ":modules:one:two:three:alpha)"
    )
    assert str(tmp_path) not in evidence

    alpha_symbols = AnalyzerRegistry()(alpha, {}).get_artifact("global_symbols", ())
    beta_symbols = AnalyzerRegistry()(beta, {}).get_artifact("global_symbols", ())
    alpha_type = next(item for item in alpha_symbols if item.qualified_name == "demo.Shared")
    beta_type = next(item for item in beta_symbols if item.qualified_name == "demo.Shared")
    assert alpha_type.project_id == alpha.name
    assert beta_type.project_id == beta.name
    assert alpha_type.id != beta_type.id


def test_recursive_membership_honors_literal_skips_and_nested_settings(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        _verified_helper(("", "modules")),
        encoding="utf-8",
    )
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/keep")
    build_src = _project(tmp_path, "modules/one/two/three/buildSrc")
    _project(tmp_path, "modules/one/two/three/buildSrc/hidden")
    skipped = _project(tmp_path, "modules/one/two/three/skip")
    _project(tmp_path, "modules/one/two/three/skip/hidden")
    nested = _project(tmp_path, "modules/one/two/three/nested")
    (nested / "settings.gradle").write_text("rootProject.name = 'nested'\n", encoding="utf-8")
    _project(tmp_path, "modules/one/two/three/nested/hidden")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-keep" in workspace.names()
    assert "modules-one-two-three-buildSrc" not in workspace.names()
    assert "modules-one-two-three-buildSrc-hidden" not in workspace.names()
    assert "modules-one-two-three-skip" not in workspace.names()
    assert "modules-one-two-three-skip-hidden" not in workspace.names()
    assert "modules-one-two-three-nested" not in workspace.names()
    assert "modules-one-two-three-nested-hidden" not in workspace.names()
    assert build_src.is_dir() and skipped.is_dir() and nested.is_dir()


def test_overlapping_literal_invocation_roots_are_deduplicated(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        _verified_helper(("", "modules"), ("", "modules/one")),
        encoding="utf-8",
    )
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/leaf")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    leaf = workspace.get("modules-one-two-three-leaf")
    assert leaf.option_map[GRADLE_SETTINGS_MEMBERSHIP_OPTION] == (
        "settings.gradle#recursive(scanProjects,"
        ":modules:one:two:three:leaf)"
    )


@pytest.mark.parametrize(
    "unsupported",
    (
        "if (new File(dir, 'settings.gradle').exists()) return\n",
        "if (new File(dir, 'build.gradle').exists() == false) return\n",
        "if (findProject(dir) != null) return\n",
    ),
)
def test_unverified_recursive_helper_fails_closed(
    tmp_path: Path,
    unsupported: str,
) -> None:
    source = _verified_helper(("", "modules")).replace(unsupported, "")
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/deep")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-deep" not in workspace.names()


@pytest.mark.parametrize(
    ("original", "replacement"),
    (
        (
            "    scanProjects(projectName, subdir)\n",
            "    scanProjects(path, subdir)\n",
        ),
        (
            "  include projectName\n",
            "  include projectName\n  println projectName\n",
        ),
    ),
)
def test_recursive_helper_with_changed_behavior_fails_closed(
    tmp_path: Path,
    original: str,
    replacement: str,
) -> None:
    source = _verified_helper(("", "modules")).replace(original, replacement)
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/deep")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-deep" not in workspace.names()


def test_dynamic_and_interpolated_recursive_invocations_are_ignored(
    tmp_path: Path,
) -> None:
    source = _verified_helper()
    source += """
def scanRoot = 'modules'
scanProjects('', new File(rootProject.projectDir, scanRoot))
scanProjects("${prefix}", new File(rootProject.projectDir, 'modules'))
"""
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/deep")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-deep" not in workspace.names()


def test_escaping_and_absolute_recursive_roots_are_ignored(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    _named_deep_chain(outside, "escape")
    _project(outside, "escape/one/two/three/deep")
    relative_escape = f"../{outside.name}/escape"
    source = _verified_helper(
        ("", relative_escape),
        ("", outside.resolve().as_posix()),
    )
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert all("deep" not in name for name in workspace.names())


def test_recursive_membership_does_not_follow_symlinks_outside_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        _verified_helper(("", "modules")),
        encoding="utf-8",
    )
    parent = _deep_chain(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-linked"
    _project(outside, "external")
    outside_link = parent / "outside-link"
    internal_link = parent / "internal-link"
    try:
        outside_link.symlink_to(outside / "external", target_is_directory=True)
        internal_link.symlink_to(tmp_path / "modules", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-outside-link" not in workspace.names()
    assert "modules-one-two-three-internal-link" not in workspace.names()


def test_future_literal_include_does_not_block_earlier_recursive_call(
    tmp_path: Path,
) -> None:
    source = _verified_helper(("", "qa"))
    source += "include 'qa:vector'\n"
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _named_deep_chain(tmp_path, "qa")
    _project(tmp_path, "qa/one/two/three/remote")
    _project(tmp_path, "qa/vector")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "qa-one-two-three-remote" in workspace.names()


def test_prior_literal_include_blocks_later_recursive_root(
    tmp_path: Path,
) -> None:
    helper = _verified_helper()
    source = helper + (
        "include 'qa:known'\n"
        "scanProjects('', new File(rootProject.projectDir, 'qa'))\n"
    )
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _named_deep_chain(tmp_path, "qa")
    _project(tmp_path, "qa/one/two/three/remote")
    _project(tmp_path, "qa/known")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "qa-one-two-three-remote" not in workspace.names()


@pytest.mark.parametrize(
    "mutation",
    (
        "include projects.toArray(new String[0])\n",
        "includeFlat 'external-project'\n",
        (
            "project(':legacy').projectDir = "
            "new File(rootProject.projectDir, 'legacy-module')\n"
        ),
    ),
)
def test_prior_unmodeled_membership_mutation_blocks_recursive_proof(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = _verified_helper()
    source += mutation
    source += "scanProjects('', new File(rootProject.projectDir, 'modules'))\n"
    (tmp_path / "settings.gradle").write_text(source, encoding="utf-8")
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/deep")

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-deep" not in workspace.names()


def test_recursive_membership_is_deterministic_for_reordered_inputs(
    tmp_path: Path,
) -> None:
    beta = _named_deep_chain(tmp_path, "beta")
    alpha = _named_deep_chain(tmp_path, "alpha")
    _project(tmp_path, "beta/one/two/three/zeta")
    _project(tmp_path, "beta/one/two/three/alpha")
    _project(tmp_path, "alpha/one/two/three/zeta")
    _project(tmp_path, "alpha/one/two/three/alpha")
    assert alpha.is_dir() and beta.is_dir()
    settings = tmp_path / "settings.gradle"
    settings.write_text(
        _verified_helper(("", "beta"), ("", "alpha")),
        encoding="utf-8",
    )
    first = WorkspaceDiscovery().discover(tmp_path)
    settings.write_text(
        _verified_helper(("", "alpha"), ("", "beta")),
        encoding="utf-8",
    )

    second = WorkspaceDiscovery().discover(tmp_path)

    assert first.to_dict() == second.to_dict()


def test_recursive_membership_does_not_scan_outside_literal_roots_or_gaps(
    tmp_path: Path,
) -> None:
    (tmp_path / "settings.gradle").write_text(
        _verified_helper(("", "modules")),
        encoding="utf-8",
    )
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/included")

    gap = _project(tmp_path, "modules/one/two/three/gap")
    _project(tmp_path, "modules/one/two/three/gap/hidden")
    (gap / "build.gradle").unlink()

    for relative in (
        "other",
        "other/one",
        "other/one/two",
        "other/one/two/three",
        "other/one/two/three/outside",
    ):
        _project(tmp_path, relative)

    workspace = WorkspaceDiscovery().discover(tmp_path)

    assert "modules-one-two-three-included" in workspace.names()
    assert "modules-one-two-three-gap-hidden" not in workspace.names()
    assert "other-one-two-three-outside" not in workspace.names()


def test_recursive_membership_reuses_collision_fail_closed_rules(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.gradle"
    settings.write_text(_verified_helper(("", "modules")), encoding="utf-8")
    _deep_chain(tmp_path)
    _project(tmp_path, "modules/one/two/three/a-b")
    _project(tmp_path, "modules/one/two/three/a")
    _project(tmp_path, "modules/one/two/three/a/b")

    first = WorkspaceDiscovery().discover(tmp_path)
    second = WorkspaceDiscovery().discover(tmp_path)

    assert first.to_dict() == second.to_dict()
    assert "modules-one-two-three-a" in first.names()
    assert "modules-one-two-three-a-b" not in first.names()
