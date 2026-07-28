from __future__ import annotations

from .base import Type, TypeKind


class _SingletonType(Type):
    _instance = None
    _kind: TypeKind
    _display_name: str

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def kind(self) -> TypeKind:
        return self._kind

    @property
    def display_name(self) -> str:
        return self._display_name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    def __hash__(self) -> int:
        return hash(self.__class__)

    def __eq__(self, other: object) -> bool:
        return self is other


class NullType(_SingletonType):
    _kind = TypeKind.NULL
    _display_name = "null"

    @property
    def is_reference(self) -> bool:
        return True


class UnknownType(_SingletonType):
    _kind = TypeKind.UNKNOWN
    _display_name = "?"

    @property
    def is_unknown(self) -> bool:
        return True


class VoidType(_SingletonType):
    _kind = TypeKind.VOID
    _display_name = "void"


NULL = NullType()
UNKNOWN = UnknownType()
VOID = VoidType()
