from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InstructionKind(str, Enum):
    ASSIGN = "assign"
    PHI = "phi"
    CALL = "call"
    RETURN = "return"
    BRANCH = "branch"
    THROW = "throw"
    NOP = "nop"


class EdgeKind(str, Enum):
    NORMAL = "normal"
    TRUE = "true"
    FALSE = "false"
    EXCEPTION = "exception"


class ConstantKind(str, Enum):
    UNDEFINED = "undefined"
    CONSTANT = "constant"
    NON_CONSTANT = "non_constant"


@dataclass(frozen=True, order=True, slots=True)
class InstructionId:
    block: str
    index: int

    def __post_init__(self) -> None:
        if not self.block.strip():
            raise ValueError("block must not be empty")
        if self.index < 0:
            raise ValueError("index must be non-negative")

    @property
    def qualified_name(self) -> str:
        return f"{self.block}:{self.index}"


@dataclass(frozen=True, slots=True)
class Instruction:
    id: InstructionId
    kind: InstructionKind = InstructionKind.NOP
    defines: str | None = None
    uses: tuple[str, ...] = ()
    constant: Any = None
    has_constant: bool = False
    side_effect: bool = False
    source_path: str | None = None
    line: int | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        defines = self.defines.strip() if self.defines is not None else None
        if defines == "":
            raise ValueError("defines must not be blank")
        object.__setattr__(self, "defines", defines)
        normalized_uses = tuple(dict.fromkeys(use.strip() for use in self.uses if use.strip()))
        object.__setattr__(self, "uses", normalized_uses)
        object.__setattr__(self, "metadata", tuple(sorted(set(self.metadata))))
        if self.line is not None and self.line < 1:
            raise ValueError("line must be positive")
        if self.has_constant and self.defines is None:
            raise ValueError("constant instruction must define a variable")

    @classmethod
    def assign(
        cls,
        block: str,
        index: int,
        variable: str,
        *,
        uses: tuple[str, ...] = (),
        constant: Any = None,
        has_constant: bool = False,
        side_effect: bool = False,
        source_path: str | None = None,
        line: int | None = None,
    ) -> "Instruction":
        return cls(
            InstructionId(block, index), InstructionKind.ASSIGN, variable, uses,
            constant, has_constant, side_effect, source_path, line,
        )


@dataclass(frozen=True, order=True, slots=True)
class ControlFlowEdge:
    source: str
    target: str
    kind: EdgeKind = EdgeKind.NORMAL

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("edge endpoints must not be empty")


@dataclass(frozen=True, slots=True)
class BasicBlock:
    name: str
    instructions: tuple[Instruction, ...] = ()

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("block name must not be empty")
        object.__setattr__(self, "name", name)
        expected = list(range(len(self.instructions)))
        actual = [instruction.id.index for instruction in self.instructions]
        if any(instruction.id.block != name for instruction in self.instructions):
            raise ValueError("instruction block does not match containing block")
        if actual != expected:
            raise ValueError("instruction indices must be contiguous from zero")


@dataclass(frozen=True, order=True, slots=True)
class Definition:
    variable: str
    instruction: InstructionId


@dataclass(frozen=True, slots=True)
class DefUseChain:
    definition: Definition
    uses: tuple[InstructionId, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstantValue:
    kind: ConstantKind
    value: Any = None

    @classmethod
    def undefined(cls) -> "ConstantValue":
        return cls(ConstantKind.UNDEFINED)

    @classmethod
    def constant(cls, value: Any) -> "ConstantValue":
        return cls(ConstantKind.CONSTANT, value)

    @classmethod
    def non_constant(cls) -> "ConstantValue":
        return cls(ConstantKind.NON_CONSTANT)


@dataclass(frozen=True, slots=True)
class DataFlowPoint:
    instruction: InstructionId
    before: frozenset[Definition] = frozenset()
    after: frozenset[Definition] = frozenset()


@dataclass(frozen=True, slots=True)
class LivenessPoint:
    instruction: InstructionId
    live_before: frozenset[str] = frozenset()
    live_after: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DeadAssignment:
    instruction: InstructionId
    variable: str
    source_path: str | None = None
    line: int | None = None
    reason: str = "assigned value is never read"


@dataclass(frozen=True, slots=True)
class DataFlowStatistics:
    block_count: int
    edge_count: int
    instruction_count: int
    variable_count: int
    definition_count: int
    dead_assignment_count: int


@dataclass(frozen=True, slots=True)
class DataFlowReport:
    reaching_definitions: tuple[DataFlowPoint, ...]
    liveness: tuple[LivenessPoint, ...]
    def_use_chains: tuple[DefUseChain, ...]
    constants_before: tuple[tuple[InstructionId, tuple[tuple[str, ConstantValue], ...]], ...]
    dead_assignments: tuple[DeadAssignment, ...]
    statistics: DataFlowStatistics
    warnings: tuple[str, ...] = ()

    def constants_at(self, instruction: InstructionId) -> dict[str, ConstantValue]:
        for point, values in self.constants_before:
            if point == instruction:
                return dict(values)
        return {}
