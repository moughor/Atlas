from __future__ import annotations

from collections.abc import Mapping

from .array_type import ArrayType
from .base import Type, TypeKind
from .class_type import ClassType
from .generic_type import GenericType
from .primitive import PrimitiveType
from .registry import TypeRegistry
from .special import NULL, UNKNOWN, VOID


def type_to_dict(semantic_type: Type) -> dict[str, object]:
    if isinstance(semantic_type, PrimitiveType):
        return {"kind": TypeKind.PRIMITIVE.value, "name": semantic_type.name}
    if isinstance(semantic_type, ClassType):
        return {"kind": TypeKind.CLASS.value, "name": semantic_type.name}
    if isinstance(semantic_type, ArrayType):
        return {
            "kind": TypeKind.ARRAY.value,
            "element_type": type_to_dict(semantic_type.element_type),
            "dimensions": semantic_type.dimensions,
        }
    if isinstance(semantic_type, GenericType):
        return {
            "kind": TypeKind.GENERIC.value,
            "base_type": type_to_dict(semantic_type.base_type),
            "arguments": [type_to_dict(argument) for argument in semantic_type.arguments],
        }
    if semantic_type is NULL:
        return {"kind": TypeKind.NULL.value}
    if semantic_type is UNKNOWN:
        return {"kind": TypeKind.UNKNOWN.value}
    if semantic_type is VOID:
        return {"kind": TypeKind.VOID.value}
    raise TypeError(f"Unsupported semantic type: {semantic_type!r}")


def type_from_dict(data: Mapping[str, object], registry: TypeRegistry | None = None) -> Type:
    if not isinstance(data, Mapping):
        raise TypeError("Serialized type must be a mapping")
    kind_value = data.get("kind")
    try:
        kind = TypeKind(kind_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Unknown semantic type kind: {kind_value!r}") from error

    target = registry if registry is not None else TypeRegistry()
    if kind is TypeKind.PRIMITIVE:
        return target.primitive(_required_string(data, "name"))
    if kind is TypeKind.CLASS:
        return target.class_type(_required_string(data, "name"))
    if kind is TypeKind.ARRAY:
        element_data = data.get("element_type")
        if not isinstance(element_data, Mapping):
            raise ValueError("Array type requires serialized element_type")
        dimensions = data.get("dimensions", 1)
        if not isinstance(dimensions, int) or isinstance(dimensions, bool):
            raise ValueError("Array dimensions must be an integer")
        return target.array(type_from_dict(element_data, target), dimensions)
    if kind is TypeKind.GENERIC:
        base_data = data.get("base_type")
        arguments_data = data.get("arguments")
        if not isinstance(base_data, Mapping):
            raise ValueError("Generic type requires serialized base_type")
        if not isinstance(arguments_data, list):
            raise ValueError("Generic type requires an arguments list")
        arguments = []
        for argument in arguments_data:
            if not isinstance(argument, Mapping):
                raise ValueError("Generic argument must be a serialized type")
            arguments.append(type_from_dict(argument, target))
        return target.generic(type_from_dict(base_data, target), arguments)
    if kind is TypeKind.NULL:
        return target.null
    if kind is TypeKind.UNKNOWN:
        return target.unknown
    return target.void


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Serialized type requires non-empty {key}")
    return value
