import pytest

from moughorai.semantic import (
    ArrayType, ClassType, GenericType, NULL, UNKNOWN, VOID,
    NullType, PrimitiveType, TypeKind, UnknownType, VoidType,
)


def test_primitive_type_is_structural_and_hashable():
    left = PrimitiveType("int")
    right = PrimitiveType("int")
    assert left == right
    assert hash(left) == hash(right)
    assert {left, right} == {left}


def test_primitive_name_is_normalized():
    assert PrimitiveType(" int ").name == "int"


def test_empty_primitive_name_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        PrimitiveType("  ")


def test_class_type_is_structural_reference_type():
    customer = ClassType("Customer")
    assert customer == ClassType("Customer")
    assert customer != ClassType("Order")
    assert customer.is_reference
    assert customer.kind is TypeKind.CLASS


def test_class_name_is_normalized_and_validated():
    assert ClassType(" java.lang.String ").name == "java.lang.String"
    with pytest.raises(ValueError):
        ClassType("")


def test_array_has_structural_dimensions():
    one = ArrayType(ClassType("Customer"))
    two = ArrayType(ClassType("Customer"), 2)
    assert one.display_name == "Customer[]"
    assert two.display_name == "Customer[][]"
    assert one != two
    assert two.is_reference


@pytest.mark.parametrize("dimensions", [0, -1, True])
def test_array_rejects_invalid_dimensions(dimensions):
    with pytest.raises(ValueError):
        ArrayType(ClassType("Customer"), dimensions)


def test_array_requires_semantic_element_type():
    with pytest.raises(TypeError):
        ArrayType("Customer")


def test_generic_type_stores_structured_arguments():
    generic = GenericType("Map", [ClassType("String"), ClassType("Customer")])
    assert generic.base_type == ClassType("Map")
    assert generic.arguments == (ClassType("String"), ClassType("Customer"))
    assert generic.display_name == "Map<String, Customer>"
    assert generic.is_reference


def test_nested_generic_display_name_is_deterministic():
    nested = GenericType("Map", [ClassType("String"), GenericType("List", [ClassType("Customer")])])
    assert nested.display_name == "Map<String, List<Customer>>"


def test_generic_type_is_hashable_and_structural():
    left = GenericType("List", [ClassType("Customer")])
    right = GenericType(ClassType("List"), (ClassType("Customer"),))
    assert left == right
    assert hash(left) == hash(right)


def test_generic_requires_arguments():
    with pytest.raises(ValueError, match="at least one"):
        GenericType("List", [])


def test_generic_rejects_invalid_arguments():
    with pytest.raises(TypeError):
        GenericType("List", ["Customer"])


def test_special_types_are_true_singletons():
    assert NullType() is NULL
    assert UnknownType() is UNKNOWN
    assert VoidType() is VOID


def test_special_type_semantics():
    assert NULL.display_name == "null"
    assert NULL.is_reference
    assert UNKNOWN.display_name == "?"
    assert UNKNOWN.is_unknown
    assert VOID.display_name == "void"
    assert not VOID.is_reference


def test_string_conversion_uses_display_name():
    assert str(GenericType("List", [ClassType("Customer")])) == "List<Customer>"
