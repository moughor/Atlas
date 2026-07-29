"""Deterministic JPA semantic analyzer over Java AST nodes."""
from __future__ import annotations
import re
from pathlib import Path
from moughorai.java_ast.ast_nodes import Annotation, CompilationUnit
from moughorai.java_resolution.models import ResolutionStatus
from moughorai.java_resolution.resolver import JavaTypeResolver
from moughorai.java_symbols.index import JavaSymbolIndex
from moughorai.java_jpa.models import (
    JpaAnalysisReport, JpaAttribute, JpaEntity, JpaRelation, JpaRelationKind,
)

_RELATIONS = {
    "OneToOne": JpaRelationKind.ONE_TO_ONE,
    "OneToMany": JpaRelationKind.ONE_TO_MANY,
    "ManyToOne": JpaRelationKind.MANY_TO_ONE,
    "ManyToMany": JpaRelationKind.MANY_TO_MANY,
    "Embedded": JpaRelationKind.EMBEDDED,
}
_TRANSIENT = {"Transient"}
_COLLECTIONS = {"Collection", "List", "Set", "Iterable"}
_GENERIC = re.compile(r"^[^<]+<(.+)>$")


def _simple(annotation: str) -> str:
    return annotation.rsplit(".", 1)[-1]


def _unquote(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        return value[1:-1]
    return value


def _annotation(nodes: tuple[Annotation, ...], simple_name: str) -> Annotation | None:
    return next((node for node in nodes if _simple(node.name) == simple_name), None)


def _target_type(type_name: str) -> str:
    value = type_name.strip()
    match = _GENERIC.match(value)
    if match:
        args = match.group(1)
        # Relationship collections normally use one generic argument.
        return args.rsplit(",", 1)[-1].strip().replace("?extends", "").replace("?super", "").strip()
    return value


class JpaAnalyzer:
    def analyze(
        self,
        units: tuple[CompilationUnit, ...],
        index: JavaSymbolIndex,
        sources: tuple[Path | None, ...] | None = None,
    ) -> JpaAnalysisReport:
        if sources is not None and len(sources) != len(units):
            raise ValueError("sources must have the same length as units")
        resolver = JavaTypeResolver(index)
        entities: list[JpaEntity] = []
        attributes: list[JpaAttribute] = []
        relations: list[JpaRelation] = []
        for i, unit in enumerate(units):
            source = sources[i] if sources is not None else None
            package = unit.package.name if unit.package else ""
            for declaration in unit.types:
                owner = f"{package}.{declaration.name}" if package else declaration.name
                self._analyze_type(unit, declaration, owner, source, resolver, entities, attributes, relations)
        return JpaAnalysisReport(tuple(entities), tuple(attributes), tuple(relations))

    def _analyze_type(self, unit, declaration, owner, source, resolver, entities, attributes, relations):
        type_annotations = {_simple(a) for a in declaration.annotations}
        is_entity = "Entity" in type_annotations
        if is_entity:
            table = _annotation(declaration.annotation_nodes, "Table")
            table_name = _unquote(table.argument("name")) if table else None
            entities.append(JpaEntity(owner, table_name or declaration.name, declaration.annotations, source))

        if is_entity or "Embeddable" in type_annotations or "MappedSuperclass" in type_annotations:
            for field in declaration.fields:
                names = {_simple(a) for a in field.annotations}
                if names & _TRANSIENT:
                    continue
                relation_kind = next((_RELATIONS[n] for n in names if n in _RELATIONS), None)
                if relation_kind is not None:
                    target_name = _target_type(field.type_name)
                    resolution = resolver.resolve(target_name, unit)
                    target = resolution.qualified_name if resolution.status is ResolutionStatus.RESOLVED else None
                    relations.append(JpaRelation(owner, field.name, relation_kind, target_name, target, field.annotations))
                    continue
                column = _annotation(field.annotation_nodes, "Column")
                column_name = _unquote(column.argument("name")) if column else None
                attributes.append(JpaAttribute(
                    owner=owner,
                    name=field.name,
                    type_name=field.type_name,
                    column_name=column_name or field.name,
                    is_id="Id" in names or "EmbeddedId" in names,
                    generated="GeneratedValue" in names,
                    annotations=field.annotations,
                ))

        for nested in declaration.nested_types:
            self._analyze_type(unit, nested, f"{owner}.{nested.name}", source, resolver, entities, attributes, relations)
