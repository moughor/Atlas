from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Iterable
from typing import Hashable, Mapping

from .base import Type
from .special import UNKNOWN


@dataclass(frozen=True, slots=True)
class TypeTable:
    """Immutable association between stable semantic node keys and types."""

    entries: Mapping[Hashable, Type] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        values = dict(self.entries)
        if not all(isinstance(value, Type) for value in values.values()):
            raise TypeError("TypeTable values must all be Type instances")
        object.__setattr__(self, "entries", MappingProxyType(values))

    def with_type(self, node_key: Hashable, semantic_type: Type) -> TypeTable:
        if not isinstance(semantic_type, Type):
            raise TypeError("semantic_type must be a Type")
        values = dict(self.entries)
        values[node_key] = semantic_type
        return TypeTable(values)

    def with_types(
        self,
        entries: Mapping[Hashable, Type] | Iterable[tuple[Hashable, Type]],
    ) -> TypeTable:
        """Return one immutable snapshot after applying a batch of types."""
        return self.to_builder().update(entries).build()

    def to_builder(self) -> TypeTableBuilder:
        """Create a mutable bulk-construction builder from this snapshot."""
        return TypeTableBuilder(self.entries)

    def get(self, node_key: Hashable, default: Type = UNKNOWN) -> Type:
        return self.entries.get(node_key, default)

    def require(self, node_key: Hashable) -> Type:
        if node_key not in self.entries:
            raise KeyError(f"No semantic type registered for node: {node_key!r}")
        return self.entries[node_key]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


class TypeTableBuilder:
    """Mutable accumulator that freezes into an immutable :class:`TypeTable`."""

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[Hashable, Type] | None = None) -> None:
        self._entries: dict[Hashable, Type] = {}
        if entries:
            self.update(entries)

    def set(self, node_key: Hashable, semantic_type: Type) -> TypeTableBuilder:
        hash(node_key)
        if not isinstance(semantic_type, Type):
            raise TypeError("semantic_type must be a Type")
        self._entries[node_key] = semantic_type
        return self

    def update(
        self,
        entries: Mapping[Hashable, Type] | Iterable[tuple[Hashable, Type]],
    ) -> TypeTableBuilder:
        values = entries.items() if isinstance(entries, Mapping) else entries
        for node_key, semantic_type in values:
            self.set(node_key, semantic_type)
        return self

    def build(self) -> TypeTable:
        return TypeTable(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
