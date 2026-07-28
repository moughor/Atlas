import pytest

from moughorai.semantic import ClassType, PrimitiveType, SemanticDocument, TypeTable, UNKNOWN


def make_document():
    return SemanticDocument(language="java", source="int x = 1;", syntax_tree={})


def test_empty_type_table_returns_unknown():
    assert TypeTable().get("missing") is UNKNOWN


def test_type_table_is_immutable():
    original = TypeTable()
    enriched = original.with_type("node:1", PrimitiveType("int"))
    assert len(original) == 0
    assert enriched.require("node:1") == PrimitiveType("int")
    with pytest.raises(TypeError):
        enriched.entries["node:2"] = ClassType("String")


def test_type_table_requires_type_values():
    with pytest.raises(TypeError):
        TypeTable({"node": "int"})
    with pytest.raises(TypeError):
        TypeTable().with_type("node", "int")


def test_type_table_require_has_clear_error():
    with pytest.raises(KeyError, match="node:404"):
        TypeTable().require("node:404")


def test_document_owns_type_table_immutably():
    original = make_document()
    enriched = original.with_type("literal:1", PrimitiveType("int"))
    assert original.get_type("literal:1") is UNKNOWN
    assert enriched.get_type("literal:1") == PrimitiveType("int")
    assert enriched.require_type("literal:1") == PrimitiveType("int")


def test_document_rejects_invalid_types_artifact():
    document = make_document().with_artifact("types", {})
    with pytest.raises(TypeError, match="TypeTable"):
        _ = document.types


def test_document_type_table_serializes_as_artifact():
    data = make_document().with_type("literal:1", PrimitiveType("int"))
    assert data.types.require("literal:1").display_name == "int"
