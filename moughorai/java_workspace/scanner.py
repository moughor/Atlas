"""Conservative Maven/Gradle workspace discovery."""
from __future__ import annotations

import os
from pathlib import Path

from moughorai.java_workspace.catalog import WorkspaceCatalogBuilder, stable_workspace_key
from moughorai.java_workspace.catalog_models import (
    BinaryLibrary,
    BuildSystem,
    SourceRoot,
    SourceRootKind,
    WorkspaceCatalog,
    WorkspaceModule,
)

_IGNORED = frozenset({".git", ".gradle", ".idea", ".mvn", ".atlas-cache", "node_modules", "target", "build", "out", "__pycache__"})
_ARCHIVES = frozenset({".jar", ".war", ".ear"})
_SOURCE_LAYOUTS = (
    ("src/main/java", SourceRootKind.MAIN, "java"),
    ("src/test/java", SourceRootKind.TEST, "java"),
    ("src/main/kotlin", SourceRootKind.MAIN, "kotlin"),
    ("src/test/kotlin", SourceRootKind.TEST, "kotlin"),
    ("src/main/resources", SourceRootKind.RESOURCE, "resource"),
    ("src/test/resources", SourceRootKind.RESOURCE, "resource"),
    ("target/generated-sources", SourceRootKind.GENERATED, "java"),
    ("build/generated", SourceRootKind.GENERATED, "java"),
)


class JavaWorkspaceScanner:
    """Discover build modules without executing Maven or Gradle."""

    def __init__(self, *, ignored_directories: frozenset[str] = _IGNORED) -> None:
        self._ignored = ignored_directories

    def scan(self, root: Path) -> WorkspaceCatalog:
        workspace_root = root.expanduser().resolve()
        if not workspace_root.exists():
            raise FileNotFoundError(workspace_root)
        if not workspace_root.is_dir():
            raise NotADirectoryError(workspace_root)

        descriptors: list[tuple[Path, BuildSystem]] = []
        for current, dirs, files in os.walk(workspace_root):
            dirs[:] = sorted(d for d in dirs if d not in self._ignored)
            current_path = Path(current)
            names = set(files)
            if "pom.xml" in names:
                descriptors.append((current_path / "pom.xml", BuildSystem.MAVEN))
            if "build.gradle.kts" in names:
                descriptors.append((current_path / "build.gradle.kts", BuildSystem.GRADLE))
            elif "build.gradle" in names:
                descriptors.append((current_path / "build.gradle", BuildSystem.GRADLE))

        # A source-only repository is still a valid single-module workspace.
        if not descriptors:
            descriptors.append((workspace_root, BuildSystem.UNKNOWN))

        modules = tuple(self._module(workspace_root, descriptor, system) for descriptor, system in descriptors)
        return WorkspaceCatalogBuilder().build(workspace_root, modules)

    def _module(self, workspace_root: Path, descriptor: Path, system: BuildSystem) -> WorkspaceModule:
        module_root = descriptor if descriptor.is_dir() else descriptor.parent
        roots = tuple(
            SourceRoot(path, kind, language)
            for relative, kind, language in _SOURCE_LAYOUTS
            if (path := module_root / relative).is_dir()
        )
        libraries = tuple(
            BinaryLibrary(path=path)
            for folder in (module_root / "lib", module_root / "libs")
            if folder.is_dir()
            for path in sorted(folder.rglob("*"), key=lambda p: p.as_posix().casefold())
            if path.is_file() and path.suffix.casefold() in _ARCHIVES
        )
        name = module_root.name or workspace_root.name
        return WorkspaceModule(
            key=stable_workspace_key(workspace_root, module_root),
            name=name,
            root=module_root,
            build_system=system,
            descriptor=None if descriptor.is_dir() else descriptor,
            source_roots=roots,
            libraries=libraries,
        )
