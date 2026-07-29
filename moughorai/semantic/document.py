from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .diagnostics import Diagnostic, DiagnosticBag
from .symbols import SymbolTable, VariableSymbol
from .types import Type, TypeTable


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class SemanticDocument:
    """Language-neutral, immutable carrier for syntax and analysis artifacts."""

    language: str
    source: str
    syntax_tree: object
    artifacts: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    diagnostics: DiagnosticBag = field(default_factory=DiagnosticBag)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", _freeze_mapping(self.artifacts))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def with_artifact(self, name: str, value: Any) -> SemanticDocument:
        artifacts = dict(self.artifacts)
        artifacts[name] = value
        return replace(self, artifacts=artifacts)

    def without_artifact(self, name: str) -> SemanticDocument:
        artifacts = dict(self.artifacts)
        artifacts.pop(name, None)
        return replace(self, artifacts=artifacts)

    def get_artifact(self, name: str, default: Any = None) -> Any:
        return self.artifacts.get(name, default)

    def require_artifact(self, name: str) -> Any:
        if name not in self.artifacts:
            raise KeyError(f"Semantic artifact not available: {name}")
        return self.artifacts[name]

    def with_diagnostic(self, diagnostic: Diagnostic) -> SemanticDocument:
        return replace(self, diagnostics=self.diagnostics.add(diagnostic))

    def with_diagnostics(self, diagnostics: Iterable[Diagnostic]) -> SemanticDocument:
        return replace(self, diagnostics=self.diagnostics.extend(diagnostics))

    @property
    def types(self) -> TypeTable:
        value = self.get_artifact("types")
        if value is None:
            return TypeTable()
        if not isinstance(value, TypeTable):
            raise TypeError("The 'types' artifact is not a TypeTable")
        return value

    def with_type(self, node_key: object, semantic_type: Type) -> SemanticDocument:
        return self.with_artifact("types", self.types.with_type(node_key, semantic_type))

    def with_types(
        self,
        entries: Mapping[object, Type] | Iterable[tuple[object, Type]],
    ) -> SemanticDocument:
        return self.with_artifact("types", self.types.with_types(entries))

    def get_type(self, node_key: object, default: Type | None = None) -> Type:
        if default is None:
            return self.types.get(node_key)
        return self.types.get(node_key, default)

    def require_type(self, node_key: object) -> Type:
        return self.types.require(node_key)

    @property
    def symbols(self) -> SymbolTable:
        value = self.get_artifact("symbols")
        if value is None:
            return SymbolTable()
        if not isinstance(value, SymbolTable):
            raise TypeError("The 'symbols' artifact is not a SymbolTable")
        return value

    def with_symbol(self, symbol: VariableSymbol) -> SemanticDocument:
        return self.with_artifact("symbols", self.symbols.with_symbol(symbol))

    def with_symbols(self, symbols: Iterable[VariableSymbol]) -> SemanticDocument:
        return self.with_artifact("symbols", self.symbols.with_symbols(symbols))

    def get_symbol(self, key: object, default: VariableSymbol | None = None) -> VariableSymbol | None:
        return self.symbols.get(key, default)

    def require_symbol(self, key: object) -> VariableSymbol:
        return self.symbols.require(key)

    def with_metadata(self, **values: Any) -> SemanticDocument:
        metadata = dict(self.metadata)
        metadata.update(values)
        return replace(self, metadata=metadata)
