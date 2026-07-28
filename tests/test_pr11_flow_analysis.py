from moughorai.java_semantics.flow_analysis import (
    DefiniteAssignmentAnalyzer,
    FlowDiagnosticCode,
    FlowState,
    analyze_do_while,
    analyze_if,
    analyze_while,
    merge_states,
)


def codes(state):
    return [diagnostic.code for diagnostic in state.diagnostics]


def test_uninitialized_local_read_is_rejected():
    state = FlowState()
    state.declare("x")
    assert not state.read("x")
    assert codes(state) == [FlowDiagnosticCode.UNASSIGNED_READ]


def test_initialized_local_read_is_allowed():
    state = FlowState()
    state.declare("x", initialized=True)
    assert state.read("x")
    assert state.diagnostics == []


def test_assignment_makes_local_definitely_assigned():
    state = FlowState()
    state.declare("x")
    assert state.assign("x")
    assert state.read("x")


def test_if_without_else_does_not_definitely_assign():
    state = FlowState()
    state.declare("x")
    result = analyze_if(state, lambda branch: branch.assign("x"))
    assert not result.variables["x"].definitely_assigned
    assert result.variables["x"].maybe_assigned


def test_if_else_assignment_is_definite():
    state = FlowState()
    state.declare("x")
    result = analyze_if(
        state,
        lambda branch: branch.assign("x"),
        lambda branch: branch.assign("x"),
    )
    assert result.variables["x"].definitely_assigned
    assert result.read("x")


def test_terminated_branch_does_not_block_assignment_merge():
    state = FlowState()
    state.declare("x")

    def then(branch):
        branch.terminate()

    result = analyze_if(state, then, lambda branch: branch.assign("x"))
    assert result.variables["x"].definitely_assigned


def test_while_body_may_execute_zero_times():
    state = FlowState()
    state.declare("x")
    result = analyze_while(state, lambda body: body.assign("x"))
    assert not result.variables["x"].definitely_assigned
    assert result.variables["x"].maybe_assigned


def test_do_while_body_executes_at_least_once():
    state = FlowState()
    state.declare("x")
    result = analyze_do_while(state, lambda body: body.assign("x"))
    assert result.variables["x"].definitely_assigned


def test_final_variable_can_be_assigned_once():
    state = FlowState()
    state.declare("x", is_final=True)
    assert state.assign("x")
    assert state.diagnostics == []


def test_final_variable_reassignment_is_rejected():
    state = FlowState()
    state.declare("x", initialized=True, is_final=True)
    assert not state.assign("x")
    assert codes(state) == [FlowDiagnosticCode.FINAL_REASSIGNMENT]


def test_final_assignment_in_only_one_branch_prevents_later_assignment():
    state = FlowState()
    state.declare("x", is_final=True)
    result = analyze_if(state, lambda branch: branch.assign("x"))
    assert result.variables["x"].maybe_assigned
    assert not result.assign("x")
    assert FlowDiagnosticCode.FINAL_REASSIGNMENT in codes(result)


def test_unreachable_statement_is_reported():
    state = FlowState()
    state.terminate()
    assert not state.statement()
    assert codes(state) == [FlowDiagnosticCode.UNREACHABLE_STATEMENT]


def test_duplicate_declaration_is_reported():
    state = FlowState()
    state.declare("x")
    state.declare("x")
    assert codes(state) == [FlowDiagnosticCode.DUPLICATE_DECLARATION]


def test_nested_branch_merge():
    analyzer = DefiniteAssignmentAnalyzer()
    analyzer.declare("x")

    def left(branch):
        nested = analyze_if(
            branch,
            lambda inner: inner.assign("x"),
            lambda inner: inner.assign("x"),
        )
        branch.variables = nested.variables
        branch.reachable = nested.reachable

    analyzer.branch(left, lambda branch: branch.assign("x"))
    assert analyzer.read("x")


def test_merge_of_two_unreachable_states_is_unreachable():
    left = FlowState(reachable=False)
    right = FlowState(reachable=False)
    result = merge_states((left, right))
    assert not result.reachable


def test_analyzer_facade_tracks_branch_result():
    analyzer = DefiniteAssignmentAnalyzer()
    analyzer.declare("value")
    analyzer.branch(
        lambda branch: branch.assign("value"),
        lambda branch: branch.assign("value"),
    )
    assert analyzer.read("value")
    assert analyzer.diagnostics == ()