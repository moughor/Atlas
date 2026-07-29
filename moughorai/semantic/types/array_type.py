from __future__ import annotations

from dataclasses import dataclass

from .base import Type, TypeKind


@dataclass(frozen=True, slots=True)
class ArrayType(Type):
    element_type: Type
    dimensions: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.element_type, Type):
            raise TypeError("Array element_type must be a Type")
        if isinstance(self.dimensions, bool) or self.dimensions < 1:
            raise ValueError("Array dimensions must be a positive integer")

    @property
    def kind(self) -> TypeKind:
        return TypeKind.ARRAY

    @property
    def display_name(self) -> str:
        return f"{self.element_type.display_name}{'[]' * self.dimensions}"

    @property
    def is_reference(self) -> bool:
        return True
