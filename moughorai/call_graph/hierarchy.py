from __future__ import annotations

from collections import defaultdict, deque

from .models import TypeKind, TypeSymbol


class TypeHierarchy:
    """Deterministic Java type hierarchy used by dispatch resolution."""

    def __init__(self, types: tuple[TypeSymbol, ...] | list[TypeSymbol] = ()) -> None:
        self._types: dict[str, TypeSymbol] = {}
        self._children: dict[str, set[str]] = defaultdict(set)
        for type_symbol in sorted(types):
            if type_symbol.qualified_name in self._types:
                raise ValueError(f"duplicate type: {type_symbol.qualified_name}")
            self._types[type_symbol.qualified_name] = type_symbol
        for type_symbol in self._types.values():
            if type_symbol.super_type:
                self._children[type_symbol.super_type].add(type_symbol.qualified_name)
            for interface in type_symbol.interfaces:
                self._children[interface].add(type_symbol.qualified_name)

    @property
    def types(self) -> tuple[TypeSymbol, ...]:
        return tuple(sorted(self._types.values()))

    def get(self, qualified_name: str) -> TypeSymbol | None:
        return self._types.get(qualified_name)

    def direct_subtypes(self, qualified_name: str) -> tuple[str, ...]:
        return tuple(sorted(self._children.get(qualified_name, ())))

    def subtypes(self, qualified_name: str, *, include_self: bool = False) -> tuple[str, ...]:
        seen: set[str] = {qualified_name} if include_self else set()
        queue = deque(sorted(self._children.get(qualified_name, ())))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(sorted(self._children.get(current, ())))
        return tuple(sorted(seen))

    def supertypes(self, qualified_name: str, *, include_self: bool = False) -> tuple[str, ...]:
        result: set[str] = {qualified_name} if include_self else set()
        queue = deque([qualified_name])
        visited: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            symbol = self._types.get(current)
            if symbol is None:
                continue
            parents = ([symbol.super_type] if symbol.super_type else []) + list(symbol.interfaces)
            for parent in sorted(p for p in parents if p):
                if parent not in result:
                    result.add(parent)
                    queue.append(parent)
        return tuple(sorted(result))

    def is_subtype(self, candidate: str, expected_supertype: str) -> bool:
        return candidate == expected_supertype or expected_supertype in self.supertypes(candidate)

    def concrete_subtypes(self, qualified_name: str, *, include_self: bool = True) -> tuple[str, ...]:
        candidates = self.subtypes(qualified_name, include_self=include_self)
        return tuple(
            name for name in candidates
            if (symbol := self._types.get(name)) is not None
            and not symbol.abstract
            and symbol.kind not in (TypeKind.INTERFACE, TypeKind.ANNOTATION)
        )
