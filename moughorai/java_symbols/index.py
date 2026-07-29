"""Deterministic searchable index of Java symbols."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from moughorai.java_symbols.models import JavaSymbol, SymbolKind, TypeSymbol


@dataclass(frozen=True)
class DuplicateTypeError(ValueError):
    qualified_name: str

    def __str__(self) -> str:
        return f"Duplicate Java type: {self.qualified_name}"


class JavaSymbolIndex:
    """Immutable lookup structure for semantic Java symbols."""

    def __init__(self, symbols: Iterable[JavaSymbol] = ()) -> None:
        ordered = tuple(symbols)
        by_qualified: dict[str, list[JavaSymbol]] = {}
        types: dict[str, TypeSymbol] = {}
        by_simple: dict[str, list[JavaSymbol]] = {}

        for symbol in ordered:
            by_qualified.setdefault(symbol.qualified_name, []).append(symbol)
            by_simple.setdefault(symbol.name, []).append(symbol)
            if isinstance(symbol, TypeSymbol):
                if symbol.qualified_name in types:
                    raise DuplicateTypeError(symbol.qualified_name)
                types[symbol.qualified_name] = symbol

        self._symbols = ordered
        self._by_qualified: Mapping[str, tuple[JavaSymbol, ...]] = MappingProxyType(
            {key: tuple(value) for key, value in by_qualified.items()}
        )
        self._types: Mapping[str, TypeSymbol] = MappingProxyType(types)
        self._by_simple: Mapping[str, tuple[JavaSymbol, ...]] = MappingProxyType(
            {key: tuple(value) for key, value in by_simple.items()}
        )

    @property
    def symbols(self) -> tuple[JavaSymbol, ...]:
        return self._symbols

    @property
    def types(self) -> tuple[TypeSymbol, ...]:
        return tuple(self._types.values())

    def type_by_name(self, qualified_name: str) -> TypeSymbol | None:
        return self._types.get(qualified_name)

    def find(self, qualified_name: str) -> tuple[JavaSymbol, ...]:
        return self._by_qualified.get(qualified_name, ())

    def find_simple(self, name: str) -> tuple[JavaSymbol, ...]:
        return self._by_simple.get(name, ())

    def by_kind(self, kind: SymbolKind) -> tuple[JavaSymbol, ...]:
        return tuple(symbol for symbol in self._symbols if symbol.kind is kind)
