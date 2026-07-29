"""Parser-independent Java record declarations and record-pattern nodes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class RecordComponent:
    name: str
    type_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "type_name", self.type_name.strip())


@dataclass(frozen=True, slots=True)
class RecordDeclaration:
    name: str
    components: tuple[RecordComponent, ...]
    type_parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(
            self,
            "type_parameters",
            tuple(item.strip() for item in self.type_parameters if item.strip()),
        )


class ComponentPatternKind(str, Enum):
    TYPE = "type"
    VAR = "var"
    UNNAMED = "unnamed"
    RECORD = "record"


@dataclass(frozen=True, slots=True)
class ComponentPattern:
    kind: ComponentPatternKind
    type_name: str | None = None
    binding: str | None = None
    record: "RecordPattern | None" = None

    @classmethod
    def type(cls, type_name: str, binding: str) -> "ComponentPattern":
        return cls(ComponentPatternKind.TYPE, type_name.strip(), binding.strip())

    @classmethod
    def var(cls, binding: str) -> "ComponentPattern":
        return cls(ComponentPatternKind.VAR, binding=binding.strip())

    @classmethod
    def unnamed(cls) -> "ComponentPattern":
        return cls(ComponentPatternKind.UNNAMED)

    @classmethod
    def nested(cls, pattern: "RecordPattern") -> "ComponentPattern":
        return cls(ComponentPatternKind.RECORD, record=pattern)


@dataclass(frozen=True, slots=True)
class RecordPattern:
    record_type: str
    components: tuple[ComponentPattern, ...]
    type_arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_type", self.record_type.strip())
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(
            self,
            "type_arguments",
            tuple(item.strip() for item in self.type_arguments if item.strip()),
        )


@dataclass(frozen=True, slots=True)
class RecordPatternBinding:
    name: str
    type_name: str
    component_path: tuple[int, ...]