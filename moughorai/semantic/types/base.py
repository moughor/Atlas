from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class TypeKind(str, Enum):
    PRIMITIVE = "primitive"
    CLASS = "class"
    ARRAY = "array"
    GENERIC = "generic"
    NULL = "null"
    UNKNOWN = "unknown"
    VOID = "void"


class Type(ABC):
    """Language-neutral semantic type contract."""

    @property
    @abstractmethod
    def kind(self) -> TypeKind:
        raise NotImplementedError

    @property
    @abstractmethod
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    def is_reference(self) -> bool:
        return False

    @property
    def is_unknown(self) -> bool:
        return False

    def __str__(self) -> str:
        return self.display_name
