"""Shared Java type-conversion relations.

This module is the single source of truth for primitive widening conversions.
"""

from __future__ import annotations

from .base import Type
from .primitive import PrimitiveType

PRIMITIVE_WIDENING: dict[str, tuple[str, ...]] = {
    "byte": ("short", "int", "long", "float", "double"),
    "short": ("int", "long", "float", "double"),
    "char": ("int", "long", "float", "double"),
    "int": ("long", "float", "double"),
    "long": ("float", "double"),
    "float": ("double",),
}


def can_widen_primitive(actual: str | PrimitiveType, expected: str | PrimitiveType) -> bool:
    actual_name = actual.name if isinstance(actual, PrimitiveType) else actual
    expected_name = expected.name if isinstance(expected, PrimitiveType) else expected
    return expected_name in PRIMITIVE_WIDENING.get(actual_name, ())


def primitive_widening_cost(actual: Type, expected: Type) -> int | None:
    if not isinstance(actual, PrimitiveType) or not isinstance(expected, PrimitiveType):
        return None
    if actual == expected:
        return 0
    chain = PRIMITIVE_WIDENING.get(actual.name, ())
    try:
        return chain.index(expected.name) + 1
    except ValueError:
        return None
