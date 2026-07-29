"""High-level Maven module graph service."""

from __future__ import annotations

from pathlib import Path

from moughorai.project_inventory.maven_parser import MavenParser
from moughorai.project_inventory.module_graph_builder import (
    MavenModuleGraphBuilder,
)
from moughorai.project_inventory.module_graph_models import MavenModuleGraph


class MavenModuleGraphService:
    """Parse Maven POMs and build their module graph."""

    def __init__(
        self,
        parser: MavenParser | None = None,
        builder: MavenModuleGraphBuilder | None = None,
    ) -> None:
        self._parser = parser or MavenParser()
        self._builder = builder or MavenModuleGraphBuilder()

    def build(
        self,
        pom_paths: tuple[Path, ...] | list[Path],
    ) -> MavenModuleGraph:
        projects = self._parser.parse_many(pom_paths)
        return self._builder.build(projects)
