"""Workspace-wide Java intelligence."""
from moughorai.java_workspace.builder import JavaWorkspaceGraphBuilder, WorkspaceGraphInput
from moughorai.java_workspace.graph import JavaWorkspaceGraph
from moughorai.java_workspace.models import (
    EndpointEntityTrace,
    RenameImpact,
    WorkspaceEdge,
    WorkspaceNode,
    WorkspaceProject,
)
from moughorai.java_workspace.service import JavaWorkspaceService

__all__ = [
    "EndpointEntityTrace",
    "JavaWorkspaceGraph",
    "JavaWorkspaceGraphBuilder",
    "JavaWorkspaceService",
    "RenameImpact",
    "WorkspaceEdge",
    "WorkspaceGraphInput",
    "WorkspaceNode",
    "WorkspaceProject",
]

# PR18 workspace catalog foundation
from moughorai.java_workspace.catalog import WorkspaceCatalogBuilder, stable_workspace_key
from moughorai.java_workspace.catalog_models import (
    BinaryLibrary,
    BuildSystem,
    SourceRoot,
    SourceRootKind,
    WorkspaceCatalog,
    WorkspaceModule,
)

__all__ += [
    "BinaryLibrary",
    "BuildSystem",
    "SourceRoot",
    "SourceRootKind",
    "WorkspaceCatalog",
    "WorkspaceCatalogBuilder",
    "WorkspaceModule",
    "stable_workspace_key",
]

# PR19 conservative workspace scanner
from moughorai.java_workspace.scanner import JavaWorkspaceScanner
__all__ += ["JavaWorkspaceScanner"]
