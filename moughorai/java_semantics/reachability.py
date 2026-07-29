"""Reachability, dead-code, and method-completion analysis for Atlas CFGs."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .control_flow_graph import ControlFlowGraph, FlowKind
from moughorai.semantic import Diagnostic, DiagnosticSeverity

class ReachabilityDiagnosticCode(str, Enum):
    UNREACHABLE_BLOCK = 'ATLAS-REACH-001'
    UNREACHABLE_STATEMENT = 'ATLAS-REACH-002'
    MISSING_RETURN = 'ATLAS-REACH-003'
    INVALID_BREAK = 'ATLAS-REACH-004'
    INVALID_CONTINUE = 'ATLAS-REACH-005'
    INFINITE_LOOP = 'ATLAS-REACH-006'
    UNREACHABLE_EXIT = 'ATLAS-REACH-007'

@dataclass(frozen=True, slots=True)
class ReachabilityDiagnostic:
    code: ReachabilityDiagnosticCode
    message: str
    block_id: int | None = None
    statement_index: int | None = None
    def to_diagnostic(self) -> Diagnostic:
        warning_codes = {
            ReachabilityDiagnosticCode.UNREACHABLE_BLOCK,
            ReachabilityDiagnosticCode.UNREACHABLE_STATEMENT,
            ReachabilityDiagnosticCode.INFINITE_LOOP,
        }
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.WARNING if self.code in warning_codes else DiagnosticSeverity.ERROR,
            location=None,
            pass_name='reachability',
        )

@dataclass(frozen=True, slots=True)
class ReachabilityResult:
    reachable_blocks: frozenset[int]
    unreachable_blocks: tuple[int, ...]
    can_complete_normally: bool
    guaranteed_return: bool
    infinite_loop_headers: tuple[int, ...]
    diagnostics: tuple[ReachabilityDiagnostic, ...]

class ReachabilityAnalyzer:
    """Conservative CFG analysis. Unknown conditions always preserve both paths."""
    def analyze(
        self,
        graph: ControlFlowGraph,
        *,
        requires_return: bool = False,
        constant_conditions: dict[int, bool] | None = None,
    ) -> ReachabilityResult:
        constant_conditions = constant_conditions or {}
        reachable = self._reachable(graph, constant_conditions)
        unreachable = tuple(sorted(set(graph.blocks) - reachable))
        diagnostics: list[ReachabilityDiagnostic] = []
        for block_id in unreachable:
            if block_id != graph.exit_id:
                diagnostics.append(ReachabilityDiagnostic(
                    ReachabilityDiagnosticCode.UNREACHABLE_BLOCK,
                    f"Block {block_id} is unreachable",
                    block_id,
                ))

        normal_exit_predecessors = {
            edge.source for edge in graph.edges
            if edge.target == graph.exit_id and edge.kind not in (FlowKind.RETURN, FlowKind.THROW)
        }
        can_complete_normally = any(source in reachable for source in normal_exit_predecessors)
        terminating_exit_predecessors = {
            edge.source for edge in graph.edges
            if edge.target == graph.exit_id and edge.kind in (FlowKind.RETURN, FlowKind.THROW)
        }
        guaranteed_return = (
            graph.exit_id in reachable
            and not can_complete_normally
            and bool(terminating_exit_predecessors & reachable)
        )

        infinite_headers = self._infinite_loop_headers(graph, reachable, constant_conditions)
        for block_id in infinite_headers:
            diagnostics.append(ReachabilityDiagnostic(
                ReachabilityDiagnosticCode.INFINITE_LOOP,
                f"Loop at block {block_id} cannot complete normally",
                block_id,
            ))

        if requires_return and can_complete_normally:
            diagnostics.append(ReachabilityDiagnostic(
                ReachabilityDiagnosticCode.MISSING_RETURN,
                "Method can complete normally without returning a value",
                graph.exit_id,
            ))
        if graph.exit_id not in reachable and not infinite_headers:
            diagnostics.append(ReachabilityDiagnostic(
                ReachabilityDiagnosticCode.UNREACHABLE_EXIT,
                "CFG exit is unreachable",
                graph.exit_id,
            ))

        diagnostics = list(dict.fromkeys(diagnostics))
        return ReachabilityResult(
            frozenset(reachable),
            unreachable,
            can_complete_normally,
            guaranteed_return,
            infinite_headers,
            tuple(diagnostics),
        )

    def _reachable(self, graph: ControlFlowGraph, constants: dict[int, bool]) -> set[int]:
        seen: set[int] = set()
        stack = [graph.entry_id]
        while stack:
            block_id = stack.pop()
            if block_id in seen or block_id not in graph.blocks:
                continue
            seen.add(block_id)
            for edge in graph.edges:
                if edge.source != block_id:
                    continue
                constant = constants.get(block_id)
                if constant is not None:
                    if edge.kind is FlowKind.TRUE_BRANCH and not constant:
                        continue
                    if edge.kind is FlowKind.FALSE_BRANCH and constant:
                        continue
                stack.append(edge.target)
        return seen

    def _infinite_loop_headers(
        self,
        graph: ControlFlowGraph,
        reachable: set[int],
        constants: dict[int, bool],
    ) -> tuple[int, ...]:
        headers: list[int] = []
        for block_id, value in constants.items():
            if not value or block_id not in reachable:
                continue
            has_loop_back = any(
                edge.target == block_id and edge.kind is FlowKind.LOOP_BACK
                for edge in graph.edges
            )
            has_reachable_break = any(
                edge.kind is FlowKind.BREAK and edge.source in reachable
                for edge in graph.edges
                if self._belongs_to_loop(graph, edge.source, block_id)
            )
            if has_loop_back and not has_reachable_break:
                headers.append(block_id)
        return tuple(sorted(headers))

    @staticmethod
    def _belongs_to_loop(graph: ControlFlowGraph, source: int, header: int) -> bool:
        seen: set[int] = set()
        stack = [source]
        while stack:
            current = stack.pop()
            if current == header:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(
                edge.source for edge in graph.edges
                if edge.target == current and edge.kind is not FlowKind.BREAK
            )
        return False