"""High-level workspace intelligence service."""
from __future__ import annotations

from typing import Iterable

from moughorai.java_workspace.builder import JavaWorkspaceGraphBuilder, WorkspaceGraphInput
from moughorai.java_workspace.graph import JavaWorkspaceGraph


class JavaWorkspaceService:
    def __init__(self, builder: JavaWorkspaceGraphBuilder | None = None) -> None:
        self._builder = builder or JavaWorkspaceGraphBuilder()

    def build(self, inputs: Iterable[WorkspaceGraphInput]) -> JavaWorkspaceGraph:
        return self._builder.build(inputs)
