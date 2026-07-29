from __future__ import annotations

from collections import defaultdict
from typing import Callable, Generic, TypeVar

from .cfg import ControlFlowGraph
from .models import (
    ConstantKind, ConstantValue, DataFlowPoint, DefUseChain, Definition,
    Instruction, InstructionId, LivenessPoint,
)

T = TypeVar("T")


class ForwardBlockSolver(Generic[T]):
    def __init__(self, merge: Callable[[tuple[T, ...]], T], transfer: Callable[[str, T], T], initial: T) -> None:
        self.merge = merge
        self.transfer = transfer
        self.initial = initial

    def solve(self, cfg: ControlFlowGraph) -> tuple[dict[str, T], dict[str, T]]:
        before = {block.name: self.initial for block in cfg.blocks}
        after = {block.name: self.initial for block in cfg.blocks}
        changed = True
        order = cfg.reverse_postorder()
        while changed:
            changed = False
            for block in order:
                incoming = tuple(after[pred] for pred in cfg.predecessors(block.name))
                new_before = self.initial if block.name == cfg.entry and not incoming else self.merge(incoming)
                new_after = self.transfer(block.name, new_before)
                if new_before != before[block.name] or new_after != after[block.name]:
                    before[block.name], after[block.name] = new_before, new_after
                    changed = True
        return before, after


class ReachingDefinitionsAnalysis:
    def analyze(self, cfg: ControlFlowGraph) -> tuple[DataFlowPoint, ...]:
        definitions_by_variable: dict[str, set[Definition]] = defaultdict(set)
        for instruction in cfg.instructions:
            if instruction.defines:
                definitions_by_variable[instruction.defines].add(Definition(instruction.defines, instruction.id))

        def transfer(block_name: str, incoming: frozenset[Definition]) -> frozenset[Definition]:
            state = set(incoming)
            block = cfg.block(block_name)
            assert block is not None
            for instruction in block.instructions:
                if instruction.defines:
                    state.difference_update(definitions_by_variable[instruction.defines])
                    state.add(Definition(instruction.defines, instruction.id))
            return frozenset(state)

        solver = ForwardBlockSolver[frozenset[Definition]](
            lambda states: frozenset().union(*states) if states else frozenset(), transfer, frozenset()
        )
        block_before, _ = solver.solve(cfg)
        points: list[DataFlowPoint] = []
        for block in cfg.reverse_postorder():
            state = set(block_before[block.name])
            for instruction in block.instructions:
                before = frozenset(state)
                if instruction.defines:
                    state.difference_update(definitions_by_variable[instruction.defines])
                    state.add(Definition(instruction.defines, instruction.id))
                points.append(DataFlowPoint(instruction.id, before, frozenset(state)))
        return tuple(points)


class LivenessAnalysis:
    def analyze(self, cfg: ControlFlowGraph) -> tuple[LivenessPoint, ...]:
        before: dict[str, frozenset[str]] = {block.name: frozenset() for block in cfg.blocks}
        after: dict[str, frozenset[str]] = {block.name: frozenset() for block in cfg.blocks}
        changed = True
        order = tuple(reversed(cfg.reverse_postorder()))
        while changed:
            changed = False
            for block in order:
                new_after = frozenset().union(*(before[s] for s in cfg.successors(block.name))) if cfg.successors(block.name) else frozenset()
                state = set(new_after)
                for instruction in reversed(block.instructions):
                    if instruction.defines:
                        state.discard(instruction.defines)
                    state.update(instruction.uses)
                new_before = frozenset(state)
                if new_before != before[block.name] or new_after != after[block.name]:
                    before[block.name], after[block.name] = new_before, new_after
                    changed = True
        points: list[LivenessPoint] = []
        for block in cfg.reverse_postorder():
            state = set(after[block.name])
            reversed_points: list[LivenessPoint] = []
            for instruction in reversed(block.instructions):
                live_after = frozenset(state)
                if instruction.defines:
                    state.discard(instruction.defines)
                state.update(instruction.uses)
                reversed_points.append(LivenessPoint(instruction.id, frozenset(state), live_after))
            points.extend(reversed(reversed_points))
        return tuple(points)


class DefUseAnalysis:
    def build(self, cfg: ControlFlowGraph, reaching: tuple[DataFlowPoint, ...]) -> tuple[DefUseChain, ...]:
        uses_by_definition: dict[Definition, set[InstructionId]] = defaultdict(set)
        all_definitions: set[Definition] = set()
        point_map = {point.instruction: point for point in reaching}
        for instruction in cfg.instructions:
            if instruction.defines:
                all_definitions.add(Definition(instruction.defines, instruction.id))
            point = point_map[instruction.id]
            for variable in instruction.uses:
                for definition in point.before:
                    if definition.variable == variable:
                        uses_by_definition[definition].add(instruction.id)
        return tuple(
            DefUseChain(definition, tuple(sorted(uses_by_definition.get(definition, ()))))
            for definition in sorted(all_definitions)
        )


class ConstantPropagationAnalysis:
    def analyze(self, cfg: ControlFlowGraph) -> tuple[tuple[InstructionId, tuple[tuple[str, ConstantValue], ...]], ...]:
        def merge_values(values: tuple[ConstantValue, ...]) -> ConstantValue:
            if not values:
                return ConstantValue.undefined()
            constants = [value for value in values if value.kind is ConstantKind.CONSTANT]
            if any(value.kind is ConstantKind.NON_CONSTANT for value in values):
                return ConstantValue.non_constant()
            if len(constants) != len(values):
                return ConstantValue.non_constant() if constants else ConstantValue.undefined()
            first = constants[0]
            return first if all(value.value == first.value for value in constants) else ConstantValue.non_constant()

        def merge_states(states: tuple[tuple[tuple[str, ConstantValue], ...], ...]) -> tuple[tuple[str, ConstantValue], ...]:
            if not states:
                return ()
            mappings = [dict(state) for state in states]
            variables = sorted(set().union(*(mapping.keys() for mapping in mappings)))
            return tuple((var, merge_values(tuple(mapping.get(var, ConstantValue.undefined()) for mapping in mappings))) for var in variables)

        def transfer_instruction(instruction: Instruction, state: dict[str, ConstantValue]) -> None:
            if not instruction.defines:
                return
            if instruction.has_constant:
                state[instruction.defines] = ConstantValue.constant(instruction.constant)
            elif instruction.kind.value == "assign" and len(instruction.uses) == 1:
                state[instruction.defines] = state.get(instruction.uses[0], ConstantValue.undefined())
            else:
                state[instruction.defines] = ConstantValue.non_constant()

        def transfer(block_name: str, incoming: tuple[tuple[str, ConstantValue], ...]) -> tuple[tuple[str, ConstantValue], ...]:
            state = dict(incoming)
            block = cfg.block(block_name)
            assert block is not None
            for instruction in block.instructions:
                transfer_instruction(instruction, state)
            return tuple(sorted(state.items()))

        solver = ForwardBlockSolver[tuple[tuple[str, ConstantValue], ...]](merge_states, transfer, ())
        block_before, _ = solver.solve(cfg)
        points = []
        for block in cfg.reverse_postorder():
            state = dict(block_before[block.name])
            for instruction in block.instructions:
                points.append((instruction.id, tuple(sorted(state.items()))))
                transfer_instruction(instruction, state)
        return tuple(points)
