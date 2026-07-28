"""Flow-sensitive definite-assignment analysis for Atlas.

The model is intentionally AST-independent. Semantic visitors can translate
Java declarations, reads, assignments and control-flow constructs into these
operations while keeping the lattice and merge rules reusable.
"""

from __future__ import annotations

from moughorai.semantic import Diagnostic, DiagnosticSeverity

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class FlowDiagnosticCode(str, Enum):
    UNASSIGNED_READ = "ATLAS-FLOW-001"
    FINAL_REASSIGNMENT = "ATLAS-FLOW-002"
    UNREACHABLE_STATEMENT = "ATLAS-FLOW-003"
    DUPLICATE_DECLARATION = "ATLAS-FLOW-004"


@dataclass(frozen=True, slots=True)
class FlowDiagnostic:
    code: FlowDiagnosticCode
    variable: str | None = None
    message: str = ""

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            location=None,
            pass_name="flow_analysis",
        )


@dataclass(frozen=True, slots=True)
class VariableFacts:
    declared: bool = True
    definitely_assigned: bool = False
    maybe_assigned: bool = False
    is_final: bool = False

    def assigned(self) -> "VariableFacts":
        return VariableFacts(True, True, True, self.is_final)


@dataclass(slots=True)
class FlowState:
    """Mutable facts; copy before analyzing independent branches."""
    variables: dict[str, VariableFacts] = field(default_factory=dict)
    reachable: bool = True
    diagnostics: list[FlowDiagnostic] = field(default_factory=list)

    def copy(self) -> "FlowState":
        return FlowState(dict(self.variables), self.reachable, list(self.diagnostics))

    @property
    def standard_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(item.to_diagnostic() for item in self.diagnostics)

    def declare(self, name: str, *, initialized: bool = False, is_final: bool = False) -> None:
        if not self.reachable:
            self._unreachable()
            return
        if name in self.variables:
            self.diagnostics.append(FlowDiagnostic(
                FlowDiagnosticCode.DUPLICATE_DECLARATION,
                name,
                f"variable '{name}' is already declared",
            ))
            return
        self.variables[name] = VariableFacts(
            definitely_assigned=initialized,
            maybe_assigned=initialized,
            is_final=is_final,
        )

    def read(self, name: str) -> bool:
        if not self.reachable:
            self._unreachable()
            return False
        facts = self.variables.get(name)
        if facts is None or not facts.definitely_assigned:
            self.diagnostics.append(FlowDiagnostic(
                FlowDiagnosticCode.UNASSIGNED_READ,
                name,
                f"variable '{name}' might not have been initialized",
            ))
            return False
        return True

    def assign(self, name: str) -> bool:
        if not self.reachable:
            self._unreachable()
            return False
        facts = self.variables.get(name)
        if facts is None:
            facts = VariableFacts()
        if facts.is_final and facts.maybe_assigned:
            self.diagnostics.append(FlowDiagnostic(
                FlowDiagnosticCode.FINAL_REASSIGNMENT,
                name,
                f"final variable '{name}' might already have been assigned",
            ))
            return False
        self.variables[name] = facts.assigned()
        return True

    def terminate(self) -> None:
        self.reachable = False

    def statement(self) -> bool:
        if self.reachable:
            return True
        self._unreachable()
        return False

    def _unreachable(self) -> None:
        self.diagnostics.append(FlowDiagnostic(
            FlowDiagnosticCode.UNREACHABLE_STATEMENT,
            None,
            "unreachable statement",
        ))


def merge_states(states: Iterable[FlowState]) -> FlowState:
    """Meet reachable branch states at a control-flow join."""
    states = list(states)
    diagnostics = [diagnostic for state in states for diagnostic in state.diagnostics]
    reachable_states = [state for state in states if state.reachable]
    if not reachable_states:
        return FlowState(reachable=False, diagnostics=diagnostics)

    names: set[str] = set()
    for state in reachable_states:
        names.update(state.variables)

    merged: dict[str, VariableFacts] = {}
    for name in names:
        facts = [state.variables.get(name, VariableFacts(declared=False)) for state in reachable_states]
        declared = all(item.declared for item in facts)
        definitely = declared and all(item.definitely_assigned for item in facts)
        maybe = any(item.maybe_assigned for item in facts)
        is_final = any(item.is_final for item in facts)
        merged[name] = VariableFacts(declared, definitely, maybe, is_final)

    return FlowState(merged, True, diagnostics)


Branch = Callable[[FlowState], None]


def analyze_if(state: FlowState, then_branch: Branch, else_branch: Branch | None = None) -> FlowState:
    then_state = state.copy()
    then_branch(then_state)
    else_state = state.copy()
    if else_branch is not None:
        else_branch(else_state)
    return merge_states((then_state, else_state))


def analyze_while(state: FlowState, body: Branch) -> FlowState:
    """Conservative while-loop analysis: the body may execute zero times."""
    body_state = state.copy()
    body(body_state)
    result = state.copy()
    result.diagnostics.extend(body_state.diagnostics[len(state.diagnostics):])
    for name, body_facts in body_state.variables.items():
        before = result.variables.get(name, VariableFacts(declared=False))
        result.variables[name] = VariableFacts(
            declared=before.declared,
            definitely_assigned=before.definitely_assigned,
            maybe_assigned=before.maybe_assigned or body_facts.maybe_assigned,
            is_final=before.is_final or body_facts.is_final,
        )
    return result


def analyze_do_while(state: FlowState, body: Branch) -> FlowState:
    """A do/while body executes at least once."""
    result = state.copy()
    body(result)
    return result


def analyze_infinite_loop_with_break(
    state: FlowState,
    body: Branch,
    break_states: Iterable[FlowState],
) -> FlowState:
    """Join explicit break exits from a loop known to execute indefinitely."""
    body_state = state.copy()
    body(body_state)
    exits = list(break_states)
    if not exits:
        result = body_state.copy()
        result.terminate()
        return result
    result = merge_states(exits)
    result.diagnostics = list(state.diagnostics) + [
        diagnostic for diagnostic in body_state.diagnostics[len(state.diagnostics):]
    ] + [
        diagnostic
        for exit_state in exits
        for diagnostic in exit_state.diagnostics[len(state.diagnostics):]
    ]
    return result


class DefiniteAssignmentAnalyzer:
    """Small facade used by semantic passes and tests."""

    def __init__(self, state: FlowState | None = None) -> None:
        self.state = state or FlowState()

    @property
    def diagnostics(self) -> tuple[FlowDiagnostic, ...]:
        return tuple(self.state.diagnostics)

    def declare(self, name: str, *, initialized: bool = False, is_final: bool = False) -> None:
        self.state.declare(name, initialized=initialized, is_final=is_final)

    def read(self, name: str) -> bool:
        return self.state.read(name)

    def assign(self, name: str) -> bool:
        return self.state.assign(name)

    def branch(self, then_branch: Branch, else_branch: Branch | None = None) -> None:
        self.state = analyze_if(self.state, then_branch, else_branch)

    def while_loop(self, body: Branch) -> None:
        self.state = analyze_while(self.state, body)

    def do_while_loop(self, body: Branch) -> None:
        self.state = analyze_do_while(self.state, body)