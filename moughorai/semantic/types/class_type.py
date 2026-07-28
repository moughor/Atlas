from __future__ import annotations

from dataclasses import dataclass

from .base import Type, TypeKind


@dataclass(frozen=True, slots=True)
class ClassType(Type):
    name: str

    def __post_init__(self) -> None:
        normalized = self.name.strip()
        if not normalized:
            raise ValueError("Class type name must not be empty")
        object.__setattr__(self, "name", normalized)

    @property
    def kind(self) -> TypeKind:
        return TypeKind.CLASS

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def is_reference(self) -> bool:
        return True
