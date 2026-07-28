from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from .models import BasicBlock, ControlFlowEdge, Instruction, InstructionId


class ControlFlowGraph:
    """Validated immutable control-flow graph with deterministic traversal."""

    def __init__(
        self,
        blocks: Iterable[BasicBlock],
        edges: Iterable[ControlFlowEdge] = (),
        *,
        entry: str | None = None,
        exits: Iterable[str] = (),
    ) -> None:
        block_list = tuple(blocks)
        self._blocks = {block.name: block for block in block_list}
        if len(self._blocks) != len(block_list):
            raise ValueError("duplicate basic block")
        if not self._blocks:
            raise ValueError("control-flow graph requires at least one block")
        self._entry = entry or block_list[0].name
        if self._entry not in self._blocks:
            raise ValueError("entry block is not present")
        self._edges = tuple(sorted(set(edges)))
        self._successors: dict[str, list[str]] = defaultdict(list)
        self._predecessors: dict[str, list[str]] = defaultdict(list)
        for edge in self._edges:
            if edge.source not in self._blocks or edge.target not in self._blocks:
                raise ValueError("edge references unknown block")
            self._successors[edge.source].append(edge.target)
            self._predecessors[edge.target].append(edge.source)
        for mapping in (self._successors, self._predecessors):
            for values in mapping.values():
                values[:] = sorted(set(values))
        explicit_exits = tuple(sorted(set(exits)))
        if any(name not in self._blocks for name in explicit_exits):
            raise ValueError("exit block is not present")
        self._exits = explicit_exits or tuple(sorted(name for name in self._blocks if not self._successors.get(name)))
        ids = [instruction.id for block in block_list for instruction in block.instructions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate instruction id")

    @property
    def entry(self) -> str:
        return self._entry

    @property
    def exits(self) -> tuple[str, ...]:
        return self._exits

    @property
    def blocks(self) -> tuple[BasicBlock, ...]:
        return tuple(self._blocks[name] for name in sorted(self._blocks))

    @property
    def edges(self) -> tuple[ControlFlowEdge, ...]:
        return self._edges

    @property
    def instructions(self) -> tuple[Instruction, ...]:
        return tuple(instruction for block in self.reverse_postorder() for instruction in block.instructions)

    def block(self, name: str) -> BasicBlock | None:
        return self._blocks.get(name)

    def instruction(self, instruction_id: InstructionId) -> Instruction | None:
        block = self._blocks.get(instruction_id.block)
        if block is None or instruction_id.index >= len(block.instructions):
            return None
        return block.instructions[instruction_id.index]

    def successors(self, name: str) -> tuple[str, ...]:
        return tuple(self._successors.get(name, ()))

    def predecessors(self, name: str) -> tuple[str, ...]:
        return tuple(self._predecessors.get(name, ()))

    def reachable_blocks(self) -> tuple[str, ...]:
        seen: set[str] = set()
        queue = deque([self._entry])
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self._successors.get(current, ()))
        return tuple(sorted(seen))

    def unreachable_blocks(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._blocks) - set(self.reachable_blocks())))

    def reverse_postorder(self) -> tuple[BasicBlock, ...]:
        visited: set[str] = set()
        postorder: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for successor in self._successors.get(name, ()):
                visit(successor)
            postorder.append(name)

        visit(self._entry)
        ordered = list(reversed(postorder))
        ordered.extend(sorted(set(self._blocks) - visited))
        return tuple(self._blocks[name] for name in ordered)
