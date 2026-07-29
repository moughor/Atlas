from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.benchmark_semantic_tables import benchmark
from moughorai.java_semantics import JavaSemanticParser
from moughorai.passes import VariableTypeInferencePass
from moughorai.semantic import (
    PassContext,
    PrimitiveType,
    SemanticDocument,
    SymbolTable,
    SymbolTableBuilder,
    TypeTable,
    TypeTableBuilder,
    VariableSymbol,
)


def test_type_builder_freezes_one_immutable_snapshot() -> None:
    integer = PrimitiveType("int")
    builder = TypeTableBuilder().set("a", integer).set("b", integer)
    table = builder.build()
    builder.set("c", integer)
    assert tuple(table) == ("a", "b")
    with pytest.raises(TypeError):
        table.entries["c"] = integer


def test_type_builder_validates_values_and_keys() -> None:
    with pytest.raises(TypeError):
        TypeTableBuilder().set("a", "int")
    with pytest.raises(TypeError):
        TypeTableBuilder().set([], PrimitiveType("int"))


def test_type_table_bulk_update_preserves_original() -> None:
    integer = PrimitiveType("int")
    original = TypeTable({"a": integer})
    updated = original.with_types({"b": integer, "c": integer})
    assert tuple(original) == ("a",)
    assert tuple(updated) == ("a", "b", "c")


def test_symbol_builder_freezes_and_overwrites_by_key() -> None:
    integer = PrimitiveType("int")
    first = VariableSymbol("x", "first", integer)
    second = VariableSymbol("x", "second", integer)
    builder = SymbolTableBuilder().add(first).add(second)
    table = builder.build()
    assert table.require("x") is second
    builder.add(VariableSymbol("y", "later", integer))
    assert tuple(table) == ("x",)


def test_symbol_builder_rejects_invalid_values() -> None:
    with pytest.raises(TypeError):
        SymbolTableBuilder().add("symbol")


def test_document_bulk_methods_preserve_immutable_contract() -> None:
    integer = PrimitiveType("int")
    symbol = VariableSymbol("x", "x", integer)
    original = SemanticDocument("java", "", object())
    updated = original.with_types({"x": integer}).with_symbols((symbol,))
    assert len(original.types) == len(original.symbols) == 0
    assert updated.require_type("x") == integer
    assert updated.require_symbol("x") is symbol


def test_variable_pass_bulk_builds_large_block() -> None:
    declarations = " ".join(f"int value{index} = {index};" for index in range(250))
    tree, diagnostics = JavaSemanticParser.parse_block_text("{ " + declarations + " }")
    assert diagnostics == ()
    document = SemanticDocument("java", declarations, tree)
    result = VariableTypeInferencePass().run(document, PassContext())
    assert len(result.symbols) == 250
    assert len(result.types) == 500
    assert not result.diagnostics.has_errors


def test_benchmark_contract_compares_equivalent_outputs() -> None:
    result = benchmark(100, repeats=1)
    assert result["entries"] == 100
    assert result["legacy_seconds"] >= 0
    assert result["builder_seconds"] >= 0
    assert result["speedup"] > 0
