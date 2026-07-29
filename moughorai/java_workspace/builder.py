"""Build a workspace graph from independent project knowledge graphs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge
from moughorai.java_workspace.graph import JavaWorkspaceGraph
from moughorai.java_workspace.models import WorkspaceEdge, WorkspaceNode, WorkspaceProject


@dataclass(frozen=True)
class WorkspaceGraphInput:
    key: str
    name: str
    graph: JavaKnowledgeGraph
    root: Path | None = None
    module: str = "main"


class JavaWorkspaceGraphBuilder:
    def build(self, inputs: Iterable[WorkspaceGraphInput]) -> JavaWorkspaceGraph:
        items = tuple(inputs)
        projects = tuple(WorkspaceProject(item.key, item.name, item.root, (item.module,)) for item in items)
        nodes = tuple(
            WorkspaceNode(item.key, item.module, node)
            for item in items
            for node in item.graph.nodes
        )
        owners: dict[str, list[str]] = {}
        for node in nodes:
            owners.setdefault(node.key, []).append(node.project_key)

        edges: list[WorkspaceEdge] = []
        unresolved: list[str] = []
        for item in items:
            for edge in item.graph.edges:
                target_projects = owners.get(edge.target, [])
                if item.key in target_projects:
                    target_project = item.key
                elif len(target_projects) == 1:
                    target_project = target_projects[0]
                elif not target_projects:
                    unresolved.append(f"{item.key}:{edge.source}:{edge.target}:workspace-unresolved")
                    continue
                else:
                    unresolved.append(f"{item.key}:{edge.source}:{edge.target}:workspace-ambiguous")
                    continue
                edges.append(WorkspaceEdge(item.key, target_project, edge))
            unresolved.extend(f"{item.key}:{value}" for value in item.graph.unresolved)
        return JavaWorkspaceGraph(projects, nodes, edges, unresolved)
