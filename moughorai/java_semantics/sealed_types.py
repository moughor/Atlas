"""Sealed-type declarations used by hierarchy and switch analysis.

The models are intentionally parser-independent. A later parser integration can
translate Java declarations into these immutable semantic records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TypeOpenness(str, Enum):
    FINAL = "final"
    SEALED = "sealed"
    NON_SEALED = "non-sealed"


@dataclass(frozen=True, slots=True)
class SealedType:
    name: str
    openness: TypeOpenness = TypeOpenness.FINAL
    permits: tuple[str, ...] = ()
    direct_supertype: str | None = None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_super = (
            self.direct_supertype.strip() if self.direct_supertype else None
        )
        normalized_permits = tuple(
            item.strip() for item in self.permits if item.strip()
        )
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "direct_supertype", normalized_super)
        object.__setattr__(self, "permits", normalized_permits)

    @property
    def is_terminal(self) -> bool:
        return self.openness in {TypeOpenness.FINAL, TypeOpenness.NON_SEALED}


@dataclass(frozen=True, slots=True)
class PermittedSubtype:
    parent: str
    child: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent", self.parent.strip())
        object.__setattr__(self, "child", self.child.strip())