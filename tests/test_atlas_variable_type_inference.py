from __future__ import annotations

import pytest

from moughorai.java_semantics import JavaSemanticParser
from moughorai.java_semantics.expressions import LiteralExpression, UnresolvedNameExpression
from moughorai.java_semantics.statements import BlockStatement, LocalVariableDeclaration
from moughorai.passes import (
    VARIABLE_DECLARATION_TYPE_MISMATCH,
    VARIABLE_REQUIRES_INITIALIZER,
    VARIABLE_UNKNOWN_INITIALIZER,
    VariableTypeInferencePass,
    analyze_variable_declaration,
    attach_variable_declaration,
    is_assignment_compatible,
    resolve_declared_type,
)
from moughorai.semantic import PassContext, SemanticDocument, SymbolTable, VariableSymbol
from moughorai.semantic.types import ClassType, NULL, UNKNOWN, PrimitiveType, TypeRegistry


def declaration(type_name: str, name: str, source: str | None = None):
    initializer = None if source is None else LiteralExpression(source_text=source)
    return LocalVariableDeclaration(type_name=type_name, name=name, initializer=initializer)


def document(tree) -> SemanticDocument:
    return SemanticDocument(language="java", source="", syntax_tree=tree)


@pytest.mark.parametrize("name", ["byte", "short", "int", "long", "float", "double", "boolean", "char"])
def test_resolve_primitive_declared_types(name):
    assert resolve_declared_type(name) == PrimitiveType(name)


def test_resolve_string_alias():
    assert resolve_declared_type("String") == ClassType("java.lang.String")
    assert resolve_declared_type("java.lang.String") == ClassType("java.lang.String")


def test_resolve_custom_reference_type():
    assert resolve_declared_type("com.example.Widget") == ClassType("com.example.Widget")


@pytest.mark.parametrize("target,source", [
    ("long", "int"), ("float", "int"), ("double", "int"),
    ("float", "long"), ("double", "long"), ("double", "float"),
    ("int", "char"), ("long", "char"),
])
def test_java_primitive_widening(target, source):
    assert is_assignment_compatible(PrimitiveType(target), PrimitiveType(source))


@pytest.mark.parametrize("target,source", [
    ("int", "long"), ("float", "double"), ("boolean", "int"), ("char", "int")
])
def test_narrowing_and_invalid_primitive_assignments_are_rejected(target, source):
    assert not is_assignment_compatible(PrimitiveType(target), PrimitiveType(source))


def test_null_assigns_to_reference_but_not_primitive():
    assert is_assignment_compatible(ClassType("java.lang.String"), NULL)
    assert not is_assignment_compatible(PrimitiveType("int"), NULL)


@pytest.mark.parametrize("type_name,source,expected", [
    ("int", "42", "int"), ("long", "42L", "long"),
    ("float", "1.5f", "float"), ("double", "1.5", "double"),
    ("boolean", "true", "boolean"), ("char", "'A'", "char"),
    ("String", '"Atlas"', "java.lang.String"),
])
def test_matching_declarations(type_name, source, expected):
    result = analyze_variable_declaration(declaration(type_name, "value", source))
    assert result.compatible
    assert result.variable_type.display_name == expected
    assert result.diagnostics == ()


def test_explicit_declaration_without_initializer_is_valid():
    result = analyze_variable_declaration(declaration("int", "count"))
    assert result.compatible
    assert result.initializer_type is None
    assert result.variable_type == PrimitiveType("int")


def test_var_infers_literal_type():
    result = analyze_variable_declaration(declaration("var", "count", "42L"))
    assert result.inferred
    assert result.compatible
    assert result.variable_type == PrimitiveType("long")


def test_var_requires_initializer():
    result = analyze_variable_declaration(declaration("var", "count"))
    assert not result.compatible
    assert result.variable_type is UNKNOWN
    assert result.diagnostics[0].code == VARIABLE_REQUIRES_INITIALIZER


def test_var_unknown_initializer_reports_diagnostic():
    node = LocalVariableDeclaration(
        type_name="var", name="count", initializer=UnresolvedNameExpression(name="other")
    )
    result = analyze_variable_declaration(node)
    assert not result.compatible
    assert result.diagnostics[0].code == VARIABLE_UNKNOWN_INITIALIZER


def test_mismatch_reports_diagnostic():
    result = analyze_variable_declaration(declaration("int", "count", '"Atlas"'))
    assert not result.compatible
    assert result.diagnostics[0].code == VARIABLE_DECLARATION_TYPE_MISMATCH
    assert "java.lang.String" in result.diagnostics[0].message
    assert "int" in result.diagnostics[0].message


def test_attach_is_immutable_and_adds_symbol_and_types():
    original = document(BlockStatement())
    node = declaration("int", "count", "42")
    updated = attach_variable_declaration(original, node)
    assert updated is not original
    assert len(original.types) == 0
    assert len(original.symbols) == 0
    assert len(updated.types) == 2
    assert len(updated.symbols) == 1
    symbol = next(iter(updated.symbols.entries.values()))
    assert symbol.name == "count"
    assert symbol.semantic_type == PrimitiveType("int")


def test_symbol_table_is_immutable():
    symbol = VariableSymbol("x", "x", PrimitiveType("int"))
    original = SymbolTable()
    updated = original.with_symbol(symbol)
    assert len(original) == 0
    assert updated.require("x") is symbol


def test_registry_reuses_canonical_types():
    registry = TypeRegistry()
    first = analyze_variable_declaration(declaration("int", "a", "1"), registry)
    second = analyze_variable_declaration(declaration("int", "b", "2"), registry)
    assert first.variable_type is second.variable_type


def test_pass_walks_nested_block_and_types_all_variables():
    tree, diagnostics = JavaSemanticParser.parse_block_text(
        '{ int age = 42; String name = "Atlas"; var size = 42L; }'
    )
    assert len(diagnostics) == 0
    result = VariableTypeInferencePass().run(document(tree), PassContext())
    assert len(result.symbols) == 3
    by_name = {symbol.name: symbol for symbol in result.symbols.entries.values()}
    assert by_name["age"].semantic_type == PrimitiveType("int")
    assert by_name["name"].semantic_type == ClassType("java.lang.String")
    assert by_name["size"].semantic_type == PrimitiveType("long")


def test_pass_accumulates_mismatch_diagnostic():
    tree, _ = JavaSemanticParser.parse_block_text('{ int age = "Atlas"; }')
    result = VariableTypeInferencePass().run(document(tree), PassContext())
    assert result.diagnostics.has_errors
    assert tuple(result.diagnostics)[0].code == VARIABLE_DECLARATION_TYPE_MISMATCH


def test_public_exports():
    from moughorai import passes, semantic
    assert passes.VariableTypeInferencePass is VariableTypeInferencePass
    assert semantic.SymbolTable is SymbolTable
    assert semantic.VariableSymbol is VariableSymbol
