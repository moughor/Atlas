"""Build deterministic module graphs from parsed Maven projects."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from moughorai.project_inventory.maven_models import MavenProject
from moughorai.project_inventory.module_graph_models import (
    MavenModuleGraph,
    ModuleCycle,
    ModuleEdge,
    ModuleEdgeKind,
    ModuleNode,
    UnresolvedModuleReference,
)


class MavenModuleGraphBuilder:
    """Create a graph from a set of Maven projects."""

    def build(
        self,
        projects: tuple[MavenProject, ...] | list[MavenProject],
    ) -> MavenModuleGraph:
        ordered_projects = tuple(
            sorted(
                projects,
                key=lambda project: project.pom_path.as_posix().casefold(),
            )
        )

        project_by_id: dict[str, MavenProject] = {}
        project_by_pom: dict[Path, MavenProject] = {}

        for project in ordered_projects:
            identifier = self._project_identifier(project)
            if identifier in project_by_id:
                raise ValueError(
                    f"duplicate Maven module coordinate: {identifier}"
                )
            project_by_id[identifier] = project
            project_by_pom[project.pom_path.resolve()] = project

        nodes = tuple(
            sorted(
                (
                    self._node(project)
                    for project in ordered_projects
                ),
                key=lambda node: node.identifier.casefold(),
            )
        )

        edges: list[ModuleEdge] = []
        unresolved: list[UnresolvedModuleReference] = []

        for project in ordered_projects:
            source = self._project_identifier(project)
            self._add_declared_module_edges(
                project=project,
                source=source,
                project_by_pom=project_by_pom,
                edges=edges,
                unresolved=unresolved,
            )
            self._add_parent_edge(
                project=project,
                source=source,
                project_by_id=project_by_id,
                edges=edges,
                unresolved=unresolved,
            )
            self._add_dependency_edges(
                project=project,
                source=source,
                project_by_id=project_by_id,
                edges=edges,
            )

        unique_edges = tuple(
            sorted(
                set(edges),
                key=lambda edge: (
                    edge.kind.value,
                    edge.source.casefold(),
                    edge.target.casefold(),
                    edge.scope or "",
                    edge.optional,
                ),
            )
        )
        unique_unresolved = tuple(
            sorted(
                set(unresolved),
                key=lambda item: (
                    item.kind.value,
                    item.source.casefold(),
                    item.reference.casefold(),
                    item.source_pom.as_posix().casefold(),
                ),
            )
        )

        cycles = self._find_dependency_cycles(
            node_ids=tuple(node.identifier for node in nodes),
            edges=unique_edges,
        )

        return MavenModuleGraph(
            nodes=nodes,
            edges=unique_edges,
            unresolved=unique_unresolved,
            dependency_cycles=cycles,
        )

    @staticmethod
    def _project_identifier(project: MavenProject) -> str:
        coordinate = project.coordinate
        if coordinate is None:
            raise ValueError(
                f"Maven project has no effective coordinate: "
                f"{project.pom_path}"
            )
        return coordinate.identifier

    def _node(self, project: MavenProject) -> ModuleNode:
        coordinate = project.coordinate
        if coordinate is None:
            raise ValueError(
                f"Maven project has no effective coordinate: "
                f"{project.pom_path}"
            )
        return ModuleNode(
            identifier=coordinate.identifier,
            pom_path=project.pom_path,
            group_id=coordinate.group_id,
            artifact_id=coordinate.artifact_id,
            version=coordinate.version,
            packaging=project.packaging,
            name=project.name,
        )

    def _add_declared_module_edges(
        self,
        *,
        project: MavenProject,
        source: str,
        project_by_pom: dict[Path, MavenProject],
        edges: list[ModuleEdge],
        unresolved: list[UnresolvedModuleReference],
    ) -> None:
        base_directory = project.pom_path.parent

        for module in project.modules:
            module_path = Path(module.path)
            candidate = (
                module_path
                if module_path.name == "pom.xml"
                else module_path / "pom.xml"
            )
            expected_pom = (base_directory / candidate).resolve()
            child = project_by_pom.get(expected_pom)

            if child is None:
                unresolved.append(
                    UnresolvedModuleReference(
                        source=source,
                        reference=module.path,
                        kind=ModuleEdgeKind.DECLARES_MODULE,
                        source_pom=project.pom_path,
                    )
                )
                continue

            edges.append(
                ModuleEdge(
                    source=source,
                    target=self._project_identifier(child),
                    kind=ModuleEdgeKind.DECLARES_MODULE,
                )
            )

    def _add_parent_edge(
        self,
        *,
        project: MavenProject,
        source: str,
        project_by_id: dict[str, MavenProject],
        edges: list[ModuleEdge],
        unresolved: list[UnresolvedModuleReference],
    ) -> None:
        if project.parent is None:
            return

        target = project.parent.identifier
        if target in project_by_id:
            edges.append(
                ModuleEdge(
                    source=target,
                    target=source,
                    kind=ModuleEdgeKind.PARENT,
                )
            )
            return

        unresolved.append(
            UnresolvedModuleReference(
                source=source,
                reference=target,
                kind=ModuleEdgeKind.PARENT,
                source_pom=project.pom_path,
            )
        )

    def _add_dependency_edges(
        self,
        *,
        project: MavenProject,
        source: str,
        project_by_id: dict[str, MavenProject],
        edges: list[ModuleEdge],
    ) -> None:
        for dependency in project.dependencies:
            target = dependency.identifier
            if target not in project_by_id or target == source:
                continue

            edges.append(
                ModuleEdge(
                    source=source,
                    target=target,
                    kind=ModuleEdgeKind.DEPENDS_ON,
                    scope=dependency.scope,
                    optional=dependency.optional,
                )
            )

    @staticmethod
    def _find_dependency_cycles(
        *,
        node_ids: tuple[str, ...],
        edges: tuple[ModuleEdge, ...],
    ) -> tuple[ModuleCycle, ...]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            if edge.kind is ModuleEdgeKind.DEPENDS_ON:
                adjacency[edge.source].add(edge.target)

        index = 0
        indexes: dict[str, int] = {}
        low_links: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[tuple[str, ...]] = []

        def visit(node: str) -> None:
            nonlocal index
            indexes[node] = index
            low_links[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for target in sorted(
                adjacency.get(node, ()),
                key=str.casefold,
            ):
                if target not in indexes:
                    visit(target)
                    low_links[node] = min(
                        low_links[node],
                        low_links[target],
                    )
                elif target in on_stack:
                    low_links[node] = min(
                        low_links[node],
                        indexes[target],
                    )

            if low_links[node] != indexes[node]:
                return

            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break

            if len(component) > 1:
                components.append(
                    tuple(sorted(component, key=str.casefold))
                )

        for node in sorted(node_ids, key=str.casefold):
            if node not in indexes:
                visit(node)

        return tuple(
            ModuleCycle(modules=component)
            for component in sorted(
                components,
                key=lambda item: tuple(
                    value.casefold() for value in item
                ),
            )
        )
