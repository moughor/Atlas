from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Hashable, Iterator, Mapping

from .types import Type


@dataclass(frozen=True, slots=True)
class VariableSymbol:
    """Immutable semantic description of one variable declaration."""

    key: Hashable
    name: str
    semantic_type: Type
    declaration_key: Hashable | None = None
    initializer_key: Hashable | None = None
    inferred: bool = False

    def __post_init__(self) -> None:
        normalized = self.name.strip()
        if not normalized:
            raise ValueError("Variable name must not be empty")
        if not isinstance(self.semantic_type, Type):
            raise TypeError("semantic_type must be a Type")
        hash(self.key)
        if self.declaration_key is not None:
            hash(self.declaration_key)
        if self.initializer_key is not None:
            hash(self.initializer_key)
        object.__setattr__(self, "name", normalized)


@dataclass(frozen=True, slots=True)
class SymbolTable:
    """Immutable association between stable symbol keys and variable symbols."""

    entries: Mapping[Hashable, VariableSymbol] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        values = dict(self.entries)
        if not all(isinstance(value, VariableSymbol) for value in values.values()):
            raise TypeError("SymbolTable values must all be VariableSymbol instances")
        object.__setattr__(self, "entries", MappingProxyType(values))

    def with_symbol(self, symbol: VariableSymbol) -> SymbolTable:
        if not isinstance(symbol, VariableSymbol):
            raise TypeError("symbol must be a VariableSymbol")
        values = dict(self.entries)
        values[symbol.key] = symbol
        return SymbolTable(values)

    def get(self, key: Hashable, default: VariableSymbol | None = None) -> VariableSymbol | None:
        return self.entries.get(key, default)

    def require(self, key: Hashable) -> VariableSymbol:
        if key not in self.entries:
            raise KeyError(f"No semantic symbol registered for key: {key!r}")
        return self.entries[key]

    def find_by_name(self, name: str) -> tuple[VariableSymbol, ...]:
        return tuple(symbol for symbol in self.entries.values() if symbol.name == name)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Hashable]:
        return iter(self.entries)


__all__ = ["SymbolTable", "VariableSymbol"]
