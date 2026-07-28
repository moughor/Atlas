from pathlib import Path

import pytest

from moughorai.java_workspace import (
    BinaryLibrary,
    BuildSystem,
    SourceRoot,
    SourceRootKind,
    WorkspaceCatalogBuilder,
    WorkspaceModule,
    stable_workspace_key,
)


def module(root: Path, name: str) -> WorkspaceModule:
    module_root = root / name
    module_root.mkdir(parents=True, exist_ok=True)
    return WorkspaceModule(
        key=stable_workspace_key(root, module_root),
        name=name,
        root=module_root,
        build_system=BuildSystem.MAVEN,
        descriptor=module_root / "pom.xml",
        source_roots=(SourceRoot(module_root / "src/main/java"),),
        libraries=(BinaryLibrary(module_root / "lib/a.jar"),),
    )


def test_stable_key_is_repeatable(tmp_path: Path):
    child = tmp_path / "service"
    child.mkdir()
    assert stable_workspace_key(tmp_path, child) == stable_workspace_key(tmp_path, child)


def test_root_module_key_is_stable(tmp_path: Path):
    assert stable_workspace_key(tmp_path, tmp_path).startswith("root:")


def test_key_rejects_outside_module(tmp_path: Path):
    outside = tmp_path.parent / "outside-atlas"
    with pytest.raises(ValueError):
        stable_workspace_key(tmp_path, outside)


def test_builder_sorts_modules(tmp_path: Path):
    catalog = WorkspaceCatalogBuilder().build(tmp_path, (module(tmp_path, "z"), module(tmp_path, "a")))
    assert [item.name for item in catalog.modules] == ["a", "z"]


def test_builder_rejects_duplicate_keys(tmp_path: Path):
    left = module(tmp_path, "left")
    right_root = tmp_path / "right"
    right_root.mkdir()
    right = WorkspaceModule(left.key, "right", right_root)
    with pytest.raises(ValueError, match="duplicate"):
        WorkspaceCatalogBuilder().build(tmp_path, (left, right))


def test_builder_rejects_missing_workspace(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        WorkspaceCatalogBuilder().build(tmp_path / "missing", ())


def test_builder_rejects_file_workspace(tmp_path: Path):
    file = tmp_path / "x"
    file.write_text("x")
    with pytest.raises(NotADirectoryError):
        WorkspaceCatalogBuilder().build(file, ())


def test_builder_rejects_module_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside-module"
    outside.mkdir(exist_ok=True)
    item = WorkspaceModule("outside", "outside", outside)
    with pytest.raises(ValueError, match="outside workspace"):
        WorkspaceCatalogBuilder().build(tmp_path, (item,))


def test_catalog_lookup_is_case_insensitive(tmp_path: Path):
    item = module(tmp_path, "service")
    catalog = WorkspaceCatalogBuilder().build(tmp_path, (item,))
    assert catalog.module(item.key.upper()) == item


def test_catalog_flattens_source_roots(tmp_path: Path):
    item = module(tmp_path, "service")
    catalog = WorkspaceCatalogBuilder().build(tmp_path, (item,))
    assert catalog.source_roots == item.source_roots


def test_catalog_flattens_libraries(tmp_path: Path):
    item = module(tmp_path, "service")
    catalog = WorkspaceCatalogBuilder().build(tmp_path, (item,))
    assert catalog.libraries == item.libraries


def test_module_requires_key(tmp_path: Path):
    with pytest.raises(ValueError):
        WorkspaceModule("", "x", tmp_path)


def test_module_requires_name(tmp_path: Path):
    with pytest.raises(ValueError):
        WorkspaceModule("x", " ", tmp_path)


def test_source_root_defaults_to_java_main(tmp_path: Path):
    root = SourceRoot(tmp_path)
    assert root.kind is SourceRootKind.MAIN
    assert root.language == "java"


def test_catalog_schema_starts_at_one(tmp_path: Path):
    assert WorkspaceCatalogBuilder().build(tmp_path, ()).schema_version == 1
