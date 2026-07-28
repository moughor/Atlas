from pathlib import Path

from moughorai.project_inventory.module_graph_models import (
    MavenModuleGraph,
    ModuleEdge,
    ModuleEdgeKind,
    ModuleNode,
)


def node(identifier: str) -> ModuleNode:
    group_id, artifact_id = identifier.split(":", maxsplit=1)
    return ModuleNode(
        identifier=identifier,
        pom_path=Path(artifact_id) / "pom.xml",
        group_id=group_id,
        artifact_id=artifact_id,
        version="1.0",
        packaging="jar",
    )


def test_graph_queries_roots_leaves_and_edges() -> None:
    parent = node("com.demo:parent")
    child = node("com.demo:child")
    edge = ModuleEdge(
        source=parent.identifier,
        target=child.identifier,
        kind=ModuleEdgeKind.DECLARES_MODULE,
    )
    graph = MavenModuleGraph(
        nodes=(child, parent),
        edges=(edge,),
        unresolved=(),
        dependency_cycles=(),
    )

    assert graph.get_node("COM.DEMO:CHILD") == child
    assert graph.roots == (parent,)
    assert graph.leaves == (child,)
    assert graph.outgoing(
        parent.identifier,
        ModuleEdgeKind.DECLARES_MODULE,
    ) == (edge,)
    assert graph.incoming(child.identifier) == (edge,)
