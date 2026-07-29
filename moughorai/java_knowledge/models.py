"""Immutable enterprise Java knowledge graph models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class KnowledgeNodeKind(str, Enum):
    TYPE = "type"
    ENDPOINT = "endpoint"


class KnowledgeEdgeKind(str, Enum):
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    PERMITS = "permits"
    DEPENDS_ON = "depends_on"
    INJECTS = "injects"
    JPA_RELATION = "jpa_relation"
    EXPOSES = "exposes"


@dataclass(frozen=True)
class KnowledgeNode:
    key: str
    kind: KnowledgeNodeKind
    display_name: str
    qualified_name: str | None = None
    source: Path | None = None
    facets: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def metadata_value(self, name: str) -> str | None:
        return next((value for key, value in self.metadata if key == name), None)


@dataclass(frozen=True)
class KnowledgeEdge:
    source: str
    target: str
    kind: KnowledgeEdgeKind
    role: str = ""
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ImpactReport:
    subject: KnowledgeNode
    direct_dependencies: tuple[KnowledgeNode, ...] = ()
    direct_dependents: tuple[KnowledgeNode, ...] = ()
    endpoints: tuple[KnowledgeNode, ...] = ()
    persistence_targets: tuple[KnowledgeNode, ...] = ()
    unresolved_roles: tuple[str, ...] = ()
