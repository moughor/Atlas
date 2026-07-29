from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .base import Type, TypeKind
from .class_type import ClassType


@dataclass(frozen=True, slots=True, init=False)
class GenericType(Type):
    base_type: Type
    arguments: tuple[Type, ...]

    def __init__(self, base_type: Type | str, arguments: Iterable[Type]) -> None:
        resolved_base = ClassType(base_type) if isinstance(base_type, str) else base_type
        resolved_arguments = tuple(arguments)
        if not isinstance(resolved_base, Type):
            raise TypeError("Generic base_type must be a Type or class name")
        if not resolved_arguments:
            raise ValueError("Generic type requires at least one argument")
        if not all(isinstance(argument, Type) for argument in resolved_arguments):
            raise TypeError("Generic arguments must all be Type instances")
        object.__setattr__(self, "base_type", resolved_base)
        object.__setattr__(self, "arguments", resolved_arguments)

    @property
    def kind(self) -> TypeKind:
        return TypeKind.GENERIC

    @property
    def display_name(self) -> str:
        values = ", ".join(argument.display_name for argument in self.arguments)
        return f"{self.base_type.display_name}<{values}>"

    @property
    def is_reference(self) -> bool:
        return True
