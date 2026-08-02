from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from moughorai.global_symbols.models import GlobalSymbol, GlobalSymbolKind, SymbolId


class DuplicateSymbolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GlobalSymbolSnapshot:
    """Detached, immutable view produced by one database read transaction."""

    version: int
    symbols: tuple[GlobalSymbol, ...]
    _by_id: Mapping[SymbolId, GlobalSymbol] = field(init=False, repr=False, compare=False)
    _by_qualified: Mapping[str, tuple[GlobalSymbol, ...]] = field(init=False, repr=False, compare=False)
    _by_scoped: Mapping[
        tuple[str | None, str | None, str], tuple[GlobalSymbol, ...]
    ] = field(init=False, repr=False, compare=False)
    _by_name: Mapping[str, tuple[GlobalSymbol, ...]] = field(init=False, repr=False, compare=False)
    _by_kind: Mapping[GlobalSymbolKind, tuple[GlobalSymbol, ...]] = field(init=False, repr=False, compare=False)
    _by_source: Mapping[Path, tuple[GlobalSymbol, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name: defaultdict[str, list[GlobalSymbol]] = defaultdict(list)
        by_kind: defaultdict[GlobalSymbolKind, list[GlobalSymbol]] = defaultdict(list)
        by_source: defaultdict[Path, list[GlobalSymbol]] = defaultdict(list)
        by_qualified: defaultdict[str, list[GlobalSymbol]] = defaultdict(list)
        for symbol in self.symbols:
            by_name[symbol.name].append(symbol)
            by_kind[symbol.kind].append(symbol)
            by_qualified[symbol.qualified_name].append(symbol)
            if symbol.source is not None:
                by_source[symbol.source].append(symbol)
        object.__setattr__(self, "_by_id", MappingProxyType({symbol.id: symbol for symbol in self.symbols}))
        object.__setattr__(self, "_by_qualified", MappingProxyType({key: tuple(value) for key, value in by_qualified.items()}))
        by_scoped: defaultdict[
            tuple[str | None, str | None, str], list[GlobalSymbol]
        ] = defaultdict(list)
        for symbol in self.symbols:
            by_scoped[
                (symbol.project_id, symbol.scope_id, symbol.qualified_name)
            ].append(symbol)
        object.__setattr__(
            self,
            "_by_scoped",
            MappingProxyType({key: tuple(value) for key, value in by_scoped.items()}),
        )
        object.__setattr__(self, "_by_name", MappingProxyType({key: tuple(value) for key, value in by_name.items()}))
        object.__setattr__(self, "_by_kind", MappingProxyType({key: tuple(value) for key, value in by_kind.items()}))
        object.__setattr__(self, "_by_source", MappingProxyType({key: tuple(value) for key, value in by_source.items()}))

    def get(self, symbol_id: SymbolId) -> GlobalSymbol | None:
        return self._by_id.get(symbol_id)

    def by_qualified_name(
        self,
        name: str,
        project_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> GlobalSymbol | None:
        values = self._by_qualified.get(name, ())
        if project_id is not None or scope_id is not None:
            values = tuple(
                symbol
                for symbol in values
                if (project_id is None or symbol.project_id == project_id)
                and (scope_id is None or symbol.scope_id == scope_id)
            )
        return values[0] if values else None

    def find_qualified(self, name: str) -> tuple[GlobalSymbol, ...]:
        return self._by_qualified.get(name, ())

    def find_simple(self, name: str) -> tuple[GlobalSymbol, ...]:
        return self._by_name.get(name, ())

    def by_kind(self, kind: GlobalSymbolKind) -> tuple[GlobalSymbol, ...]:
        return self._by_kind.get(kind, ())

    def by_source(self, source: Path) -> tuple[GlobalSymbol, ...]:
        return self._by_source.get(source, ())

    def __len__(self) -> int:
        return len(self.symbols)


class GlobalSymbolDatabase:
    """Thread-safe mutable symbol index.

    Every public operation is linearizable under one reentrant lock. Callers
    that need a stable view across multiple lookups should use ``snapshot()``.
    """

    def __init__(self, symbols: Iterable[GlobalSymbol] = ()) -> None:
        self._by_id: dict[SymbolId, GlobalSymbol] = {}
        self._by_q: dict[
            tuple[str | None, str | None, str, GlobalSymbolKind], GlobalSymbol
        ] = {}
        self._by_project_qualified: defaultdict[
            tuple[str | None, str], list[GlobalSymbol]
        ] = defaultdict(list)
        self._by_name: defaultdict[str, list[GlobalSymbol]] = defaultdict(list)
        self._by_source: defaultdict[Path, list[GlobalSymbol]] = defaultdict(list)
        self._version = 0
        self._lock = RLock()
        self.add_many(symbols)

    def add(self, symbol: GlobalSymbol) -> None:
        self.add_many((symbol,))

    def add_many(self, symbols: Iterable[GlobalSymbol]) -> int:
        """Atomically validate and add a batch, or leave the database unchanged."""
        incoming = tuple(symbols)
        if not all(isinstance(symbol, GlobalSymbol) for symbol in incoming):
            raise TypeError("symbols must all be GlobalSymbol instances")
        if not incoming:
            return 0
        with self._lock:
            ids: set[SymbolId] = set()
            qualified: set[
                tuple[str | None, str | None, str, GlobalSymbolKind]
            ] = set()
            for symbol in incoming:
                scoped = (
                    symbol.project_id,
                    symbol.scope_id,
                    symbol.qualified_name,
                    symbol.kind,
                )
                if scoped in self._by_q or scoped in qualified:
                    scope = f"[{symbol.scope_id}]" if symbol.scope_id else ""
                    raise DuplicateSymbolError(
                        f"{symbol.project_id or '<global>'}{scope}:"
                        f"{symbol.qualified_name}"
                    )
                if symbol.id in self._by_id or symbol.id in ids:
                    raise DuplicateSymbolError(str(symbol.id))
                ids.add(symbol.id)
                qualified.add(scoped)
            for symbol in incoming:
                self._by_id[symbol.id] = symbol
                self._by_q[
                    (
                        symbol.project_id,
                        symbol.scope_id,
                        symbol.qualified_name,
                        symbol.kind,
                    )
                ] = symbol
                self._by_project_qualified[
                    (symbol.project_id, symbol.qualified_name)
                ].append(symbol)
                self._by_name[symbol.name].append(symbol)
                if symbol.source is not None:
                    self._by_source[symbol.source].append(symbol)
            self._version += 1
            return len(incoming)

    def get(self, symbol_id: SymbolId) -> GlobalSymbol | None:
        with self._lock:
            return self._by_id.get(symbol_id)

    def by_qualified_name(
        self,
        name: str,
        project_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> GlobalSymbol | None:
        with self._lock:
            if project_id is not None and scope_id is not None:
                matches = sorted(
                    (
                        self._by_q[(project_id, scope_id, name, kind)]
                        for kind in GlobalSymbolKind
                        if (project_id, scope_id, name, kind) in self._by_q
                    ),
                    key=self._sort_key,
                )
            elif project_id is not None:
                matches = sorted(
                    self._by_project_qualified.get((project_id, name), ()),
                    key=self._sort_key,
                )
            else:
                matches = sorted(
                    (
                        symbol
                        for (_, _, qualified, _), symbol in self._by_q.items()
                        if qualified == name
                        and (scope_id is None or symbol.scope_id == scope_id)
                    ),
                    key=self._sort_key,
                )
            return matches[0] if matches else None

    def find_qualified(self, name: str) -> tuple[GlobalSymbol, ...]:
        with self._lock:
            return tuple(sorted(
                (
                    symbol
                    for (_, _, qualified, _), symbol in self._by_q.items()
                    if qualified == name
                ),
                key=self._sort_key,
            ))

    def find_simple(self, name: str) -> tuple[GlobalSymbol, ...]:
        with self._lock:
            return tuple(self._by_name.get(name, ()))

    def by_kind(self, kind: GlobalSymbolKind) -> tuple[GlobalSymbol, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (symbol for symbol in self._by_id.values() if symbol.kind is kind),
                    key=self._sort_key,
                )
            )

    def by_source(self, source: Path) -> tuple[GlobalSymbol, ...]:
        with self._lock:
            return tuple(self._by_source.get(source, ()))

    @property
    def symbols(self) -> tuple[GlobalSymbol, ...]:
        with self._lock:
            return tuple(sorted(self._by_id.values(), key=self._sort_key))

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> GlobalSymbolSnapshot:
        with self._lock:
            return GlobalSymbolSnapshot(
                self._version,
                tuple(sorted(self._by_id.values(), key=self._sort_key)),
            )

    def remove_source(self, source: Path) -> int:
        with self._lock:
            doomed = tuple(self._by_source.pop(source, ()))
            for symbol in doomed:
                self._by_id.pop(symbol.id, None)
                self._by_q.pop(
                    (
                        symbol.project_id,
                        symbol.scope_id,
                        symbol.qualified_name,
                        symbol.kind,
                    ),
                    None,
                )
                project_key = (symbol.project_id, symbol.qualified_name)
                project_symbols = [
                    candidate
                    for candidate in self._by_project_qualified[project_key]
                    if candidate.id != symbol.id
                ]
                if project_symbols:
                    self._by_project_qualified[project_key] = project_symbols
                else:
                    self._by_project_qualified.pop(project_key, None)
                by_name = [
                    candidate
                    for candidate in self._by_name[symbol.name]
                    if candidate.id != symbol.id
                ]
                if by_name:
                    self._by_name[symbol.name] = by_name
                else:
                    self._by_name.pop(symbol.name, None)
            if doomed:
                self._version += 1
            return len(doomed)

    def validate(self) -> None:
        """Raise ``RuntimeError`` if internal indexes are inconsistent."""
        with self._lock:
            symbols = tuple(self._by_id.values())
            if len(self._by_q) != len(symbols):
                raise RuntimeError("qualified-name index size is inconsistent")
            if sum(map(len, self._by_project_qualified.values())) != len(symbols):
                raise RuntimeError("project-qualified index size is inconsistent")
            for symbol in symbols:
                if self._by_q.get(
                    (
                        symbol.project_id,
                        symbol.scope_id,
                        symbol.qualified_name,
                        symbol.kind,
                    )
                ) is not symbol:
                    raise RuntimeError(f"qualified-name index is inconsistent: {symbol.qualified_name}")
                if symbol not in self._by_project_qualified.get(
                    (symbol.project_id, symbol.qualified_name),
                    (),
                ):
                    raise RuntimeError(
                        "project-qualified index is inconsistent: "
                        f"{symbol.qualified_name}"
                    )
                if symbol not in self._by_name.get(symbol.name, ()):
                    raise RuntimeError(f"simple-name index is inconsistent: {symbol.name}")
                if symbol.source is not None and symbol not in self._by_source.get(symbol.source, ()):
                    raise RuntimeError(f"source index is inconsistent: {symbol.source}")

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)

    @staticmethod
    def _sort_key(symbol: GlobalSymbol) -> tuple[str, str, str, str]:
        return (
            symbol.project_id or "",
            symbol.scope_id or "",
            symbol.qualified_name,
            symbol.kind.value,
        )
