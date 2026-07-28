import pytest

from moughorai.semantic import (
    ArrayType, ClassType, GenericType, NULL, UNKNOWN, VOID,
    PrimitiveType, TypeRegistry, semantic_document_to_dict,
    type_from_dict, type_to_dict,
)


@pytest.mark.parametrize("semantic_type", [
    PrimitiveType("int"),
    ClassType("Customer"),
    ArrayType(ClassType("Customer"), 2),
    GenericType("List", [ClassType("Customer")]),
    NULL,
    UNKNOWN,
    VOID,
])
def test_types_round_trip(semantic_type):
    assert type_from_dict(type_to_dict(semantic_type)) == semantic_type


def test_nested_generic_round_trip_preserves_structure():
    value = GenericType("Map", [ClassType("String"), GenericType("List", [ArrayType(ClassType("Customer"))])])
    restored = type_from_dict(type_to_dict(value))
    assert restored == value
    assert restored.display_name == "Map<String, List<Customer[]>>"


def test_deserialization_uses_supplied_registry_identity():
    registry = TypeRegistry()
    data = type_to_dict(GenericType("List", [ClassType("Customer")]))
    first = type_from_dict(data, registry)
    second = type_from_dict(data, registry)
    assert first is second


def test_serialized_shape_is_stable_and_language_neutral():
    data = type_to_dict(ArrayType(PrimitiveType("int"), 2))
    assert data == {
        "kind": "array",
        "element_type": {"kind": "primitive", "name": "int"},
        "dimensions": 2,
    }


def test_document_serializer_delegates_to_type_serializer():
    assert semantic_document_to_dict(GenericType("List", [ClassType("Customer")])) == {
        "kind": "generic",
        "base_type": {"kind": "class", "name": "List"},
        "arguments": [{"kind": "class", "name": "Customer"}],
    }


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="Unknown semantic type kind"):
        type_from_dict({"kind": "magic"})


def test_invalid_serialized_generic_is_rejected():
    with pytest.raises(ValueError, match="arguments"):
        type_from_dict({"kind": "generic", "base_type": {"kind": "class", "name": "List"}})
