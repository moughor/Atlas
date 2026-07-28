"""Build a Java architecture graph from symbols and resolved references."""

from __future__ import annotations

from moughorai.java_architecture.graph import JavaArchitectureGraph
from moughorai.java_architecture.models import (
    ArchitectureEdge,
    ArchitectureEdgeKind,
    ArchitectureNode,
    UnresolvedArchitectureReference,
)
from moughorai.java_resolution.models import ResolutionStatus, ResolvedTypeReference
from moughorai.java_symbols.index import JavaSymbolIndex


_ROLE_KINDS: tuple[tuple[str, ArchitectureEdgeKind], ...] = (
    ("extends", ArchitectureEdgeKind.EXTENDS),
    ("implements", ArchitectureEdgeKind.IMPLEMENTS),
    ("permits", ArchitectureEdgeKind.PERMITS),
    ("field:", ArchitectureEdgeKind.FIELD_TYPE),
    ("constructor-parameter:", ArchitectureEdgeKind.CONSTRUCTOR_PARAMETER),
    ("constructor-throws", ArchitectureEdgeKind.CONSTRUCTOR_THROWS),
    ("method-return:", ArchitectureEdgeKind.METHOD_RETURN),
    ("method-parameter:", ArchitectureEdgeKind.METHOD_PARAMETER),
    ("method-throws:", ArchitectureEdgeKind.METHOD_THROWS),
)


class JavaArchitectureGraphBuilder:
    def build(
        self,
        index: JavaSymbolIndex,
        references: tuple[ResolvedTypeReference, ...],
    ) -> JavaArchitectureGraph:
        nodes = tuple(
            ArchitectureNode(
                qualified_name=symbol.qualified_name,
                simple_name=symbol.name,
                type_kind=symbol.type_kind.value,
                package_name=symbol.package_name,
                source=symbol.source,
            )
            for symbol in index.types
        )

        edges: list[ArchitectureEdge] = []
        unresolved: list[UnresolvedArchitectureReference] = []
        seen_edges: set[tuple[str, str, ArchitectureEdgeKind, str]] = set()

        for reference in references:
            resolution = reference.resolution
            if (
                resolution.status is ResolutionStatus.RESOLVED
                and resolution.qualified_name is not None
                and index.type_by_name(resolution.qualified_name) is not None
            ):
                kind = self._kind_for_role(reference.role)
                key = (
                    reference.owner,
                    resolution.qualified_name,
                    kind,
                    reference.role,
                )
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        ArchitectureEdge(
                            source=reference.owner,
                            target=resolution.qualified_name,
                            kind=kind,
                            role=reference.role,
                            requested_name=reference.name,
                        )
                    )
                continue

            if resolution.status not in {ResolutionStatus.PRIMITIVE}:
                unresolved.append(
                    UnresolvedArchitectureReference(
                        owner=reference.owner,
                        role=reference.role,
                        requested_name=reference.name,
                        status=resolution.status.value,
                        candidates=resolution.candidates,
                    )
                )

        return JavaArchitectureGraph(nodes, tuple(edges), tuple(unresolved))

    @staticmethod
    def _kind_for_role(role: str) -> ArchitectureEdgeKind:
        for prefix, kind in _ROLE_KINDS:
            if role == prefix or role.startswith(prefix):
                return kind
        raise ValueError(f"Unsupported architecture reference role: {role}")
