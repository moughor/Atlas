import pytest

from moughorai.semantic import ClassType, PrimitiveType, TypeRegistry


def test_registry_canonicalizes_primitives():
    registry = TypeRegistry()
    assert registry.primitive("int") is registry.primitive("int")


def test_registry_canonicalizes_classes():
    registry = TypeRegistry()
    assert registry.class_type("Customer") is registry.class_type("Customer")


def test_registry_canonicalizes_arrays_and_elements():
    registry = TypeRegistry()
    left = registry.array(ClassType("Customer"), 2)
    right = registry.array(registry.class_type("Customer"), 2)
    assert left is right
    assert left.element_type is registry.class_type("Customer")


def test_registry_canonicalizes_nested_generics():
    registry = TypeRegistry()
    list_type = registry.generic("List", [ClassType("Customer")])
    map_one = registry.generic("Map", [ClassType("String"), list_type])
    map_two = registry.generic("Map", [registry.class_type("String"), registry.generic("List", [ClassType("Customer")])])
    assert map_one is map_two
    assert map_one.arguments[1] is list_type


def test_registry_exposes_special_singletons():
    first = TypeRegistry()
    second = TypeRegistry()
    assert first.null is second.null
    assert first.unknown is second.unknown
    assert first.void is second.void


def test_registry_counts_and_clears_interned_regular_types():
    registry = TypeRegistry()
    registry.primitive("int")
    registry.class_type("String")
    assert len(registry) == 2
    registry.clear()
    assert len(registry) == 0


def test_registry_rejects_non_type_values():
    with pytest.raises(TypeError):
        TypeRegistry().intern("int")


def test_equal_direct_types_intern_to_first_instance():
    registry = TypeRegistry()
    first = PrimitiveType("int")
    second = PrimitiveType("int")
    assert registry.intern(first) is first
    assert registry.intern(second) is first
