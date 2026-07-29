"""Import-aware Java type resolver backed by the symbol index."""

from __future__ import annotations

import re

from moughorai.java_ast.ast_nodes import CompilationUnit
from moughorai.java_symbols.index import JavaSymbolIndex
from moughorai.java_resolution.models import ResolutionStatus, TypeResolution

_PRIMITIVES = {
    "boolean", "byte", "char", "double", "float", "int", "long", "short", "void",
}

_GENERIC_RE = re.compile(r"<.*>")


class JavaTypeResolver:
    """Resolve source-level Java type names to indexed qualified names."""

    def __init__(self, index: JavaSymbolIndex) -> None:
        self._index = index

    def resolve(self, type_name: str, unit: CompilationUnit) -> TypeResolution:
        normalized = self._normalize(type_name)
        if normalized in _PRIMITIVES:
            return TypeResolution(
                requested_name=type_name,
                normalized_name=normalized,
                status=ResolutionStatus.PRIMITIVE,
                qualified_name=normalized,
            )

        if "." in normalized and self._index.type_by_name(normalized):
            return self._resolved(type_name, normalized, normalized)

        candidates: list[str] = []
        package_name = unit.package.name if unit.package else ""

        if package_name:
            self._add_if_type(candidates, f"{package_name}.{normalized}")

        for declaration in unit.imports:
            if declaration.is_static:
                continue
            if declaration.is_wildcard:
                self._add_if_type(candidates, f"{declaration.name}.{normalized}")
            elif declaration.name.rsplit(".", 1)[-1] == normalized:
                self._add_if_type(candidates, declaration.name)

        self._add_if_type(candidates, f"java.lang.{normalized}")

        if not candidates:
            for symbol in self._index.find_simple(normalized):
                if symbol.qualified_name not in candidates:
                    candidates.append(symbol.qualified_name)

        unique = tuple(dict.fromkeys(candidates))
        if len(unique) == 1:
            return self._resolved(type_name, normalized, unique[0])
        if len(unique) > 1:
            return TypeResolution(
                requested_name=type_name,
                normalized_name=normalized,
                status=ResolutionStatus.AMBIGUOUS,
                candidates=unique,
            )
        return TypeResolution(
            requested_name=type_name,
            normalized_name=normalized,
            status=ResolutionStatus.UNRESOLVED,
        )

    def _add_if_type(self, candidates: list[str], qualified_name: str) -> None:
        if self._index.type_by_name(qualified_name) and qualified_name not in candidates:
            candidates.append(qualified_name)

    @staticmethod
    def _resolved(requested: str, normalized: str, qualified: str) -> TypeResolution:
        return TypeResolution(
            requested_name=requested,
            normalized_name=normalized,
            status=ResolutionStatus.RESOLVED,
            qualified_name=qualified,
            candidates=(qualified,),
        )

    @staticmethod
    def _normalize(type_name: str) -> str:
        value = type_name.strip()
        value = value.replace("...", "")
        while value.endswith("[]"):
            value = value[:-2].strip()
        value = _GENERIC_RE.sub("", value).strip()
        if value.startswith("? extends "):
            value = value[len("? extends "):].strip()
        elif value.startswith("? super "):
            value = value[len("? super "):].strip()
        return value
