from __future__ import annotations

from threading import RLock
from typing import Iterable

from .array_type import ArrayType
from .base import Type
from .class_type import ClassType
from .generic_type import GenericType
from .primitive import PrimitiveType
from .special import NULL, UNKNOWN, VOID, NullType, UnknownType, VoidType


class TypeRegistry:
    """Thread-safe canonical store for structurally equal semantic types."""

    def __init__(self) -> None:
        self._types: dict[Type, Type] = {}
        self._lock = RLock()

    def intern(self, semantic_type: Type) -> Type:
        if not isinstance(semantic_type, Type):
            raise TypeError("Only Type instances can be interned")
        with self._lock:
            existing = self._types.get(semantic_type)
            if existing is not None:
                return existing
            self._types[semantic_type] = semantic_type
            return semantic_type

    def primitive(self, name: str) -> PrimitiveType:
        return self.intern(PrimitiveType(name))  # type: ignore[return-value]

    def class_type(self, name: str) -> ClassType:
        return self.intern(ClassType(name))  # type: ignore[return-value]

    def array(self, element_type: Type, dimensions: int = 1) -> ArrayType:
        canonical_element = self.intern(element_type)
        return self.intern(ArrayType(canonical_element, dimensions))  # type: ignore[return-value]

    def generic(self, base_type: Type | str, arguments: Iterable[Type]) -> GenericType:
        canonical_base = self.class_type(base_type) if isinstance(base_type, str) else self.intern(base_type)
        canonical_arguments = tuple(self.intern(argument) for argument in arguments)
        return self.intern(GenericType(canonical_base, canonical_arguments))  # type: ignore[return-value]

    @property
    def null(self) -> NullType:
        return NULL

    @property
    def unknown(self) -> UnknownType:
        return UNKNOWN

    @property
    def void(self) -> VoidType:
        return VOID

    def __len__(self) -> int:
        return len(self._types)

    def clear(self) -> None:
        with self._lock:
            self._types.clear()
