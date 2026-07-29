"""Merge architecture, Spring, REST, and JPA reports into one graph."""
from __future__ import annotations

from moughorai.java_architecture.graph import JavaArchitectureGraph
from moughorai.java_architecture.models import ArchitectureEdgeKind
from moughorai.java_jpa.models import JpaAnalysisReport
from moughorai.java_knowledge.graph import JavaKnowledgeGraph
from moughorai.java_knowledge.models import KnowledgeEdge, KnowledgeEdgeKind, KnowledgeNode, KnowledgeNodeKind
from moughorai.java_spring.models import SpringAnalysisReport

_ARCHITECTURE_KIND = {
    ArchitectureEdgeKind.EXTENDS: KnowledgeEdgeKind.EXTENDS,
    ArchitectureEdgeKind.IMPLEMENTS: KnowledgeEdgeKind.IMPLEMENTS,
    ArchitectureEdgeKind.PERMITS: KnowledgeEdgeKind.PERMITS,
}


class JavaKnowledgeGraphBuilder:
    def build(
        self,
        architecture: JavaArchitectureGraph,
        spring: SpringAnalysisReport | None = None,
        jpa: JpaAnalysisReport | None = None,
    ) -> JavaKnowledgeGraph:
        spring = spring or SpringAnalysisReport()
        jpa = jpa or JpaAnalysisReport()
        bean_map = {bean.qualified_name: bean for bean in spring.beans}
        entity_map = {entity.qualified_name: entity for entity in jpa.entities}

        nodes: list[KnowledgeNode] = []
        edges: list[KnowledgeEdge] = []
        unresolved: list[str] = []

        for node in architecture.nodes:
            facets: list[str] = [f"java:{node.type_kind}"]
            metadata: list[tuple[str, str]] = [("package", node.package_name)]
            bean = bean_map.get(node.qualified_name)
            if bean is not None:
                facets.append(f"spring:{bean.kind.value}")
            entity = entity_map.get(node.qualified_name)
            if entity is not None:
                facets.append("jpa:entity")
                metadata.append(("table", entity.table_name))
            nodes.append(KnowledgeNode(node.qualified_name, KnowledgeNodeKind.TYPE, node.simple_name, node.qualified_name, node.source, tuple(facets), tuple(metadata)))

        for edge in architecture.edges:
            kind = _ARCHITECTURE_KIND.get(edge.kind, KnowledgeEdgeKind.DEPENDS_ON)
            edges.append(KnowledgeEdge(edge.source, edge.target, kind, edge.role, (("requested_name", edge.requested_name),)))
        for item in architecture.unresolved:
            unresolved.append(f"{item.owner}:{item.role}:{item.requested_name}:{item.status}")

        for injection in spring.injections:
            if injection.target_qualified_name:
                edges.append(KnowledgeEdge(injection.owner, injection.target_qualified_name, KnowledgeEdgeKind.INJECTS, injection.member_name, (("kind", injection.kind.value),)))
            else:
                unresolved.append(f"{injection.owner}:{injection.member_name}:{injection.target_name}:unresolved-injection")

        for index, endpoint in enumerate(spring.endpoints):
            key = f"endpoint:{endpoint.owner}#{endpoint.method_name}:{index}"
            display = f"{','.join(endpoint.http_methods) or 'REQUEST'} {'|'.join(endpoint.paths) or '/'}"
            nodes.append(KnowledgeNode(key, KnowledgeNodeKind.ENDPOINT, display, metadata=(("owner", endpoint.owner), ("method", endpoint.method_name))))
            edges.append(KnowledgeEdge(endpoint.owner, key, KnowledgeEdgeKind.EXPOSES, endpoint.method_name))

        for relation in jpa.relations:
            if relation.target_qualified_name:
                edges.append(KnowledgeEdge(relation.owner, relation.target_qualified_name, KnowledgeEdgeKind.JPA_RELATION, relation.field_name, (("kind", relation.kind.value),)))
            else:
                unresolved.append(f"{relation.owner}:{relation.field_name}:{relation.target_name}:unresolved-jpa-relation")

        return JavaKnowledgeGraph(nodes, edges, unresolved)
