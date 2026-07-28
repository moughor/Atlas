"""Immutable JPA semantic analysis models."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class JpaRelationKind(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    EMBEDDED = "embedded"

@dataclass(frozen=True)
class JpaEntity:
    qualified_name: str
    table_name: str
    annotations: tuple[str, ...]
    source: Path | None = None

@dataclass(frozen=True)
class JpaAttribute:
    owner: str
    name: str
    type_name: str
    column_name: str
    is_id: bool = False
    generated: bool = False
    annotations: tuple[str, ...] = ()

@dataclass(frozen=True)
class JpaRelation:
    owner: str
    field_name: str
    kind: JpaRelationKind
    target_name: str
    target_qualified_name: str | None
    annotations: tuple[str, ...] = ()

@dataclass(frozen=True)
class JpaAnalysisReport:
    entities: tuple[JpaEntity, ...] = ()
    attributes: tuple[JpaAttribute, ...] = ()
    relations: tuple[JpaRelation, ...] = ()

    def entity(self, qualified_name: str) -> JpaEntity | None:
        return next((e for e in self.entities if e.qualified_name == qualified_name), None)

    def attributes_for(self, owner: str) -> tuple[JpaAttribute, ...]:
        return tuple(a for a in self.attributes if a.owner == owner)

    def relations_for(self, owner: str) -> tuple[JpaRelation, ...]:
        return tuple(r for r in self.relations if r.owner == owner)

    def dependents(self, target: str) -> tuple[JpaRelation, ...]:
        return tuple(r for r in self.relations if r.target_qualified_name == target)
