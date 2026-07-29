import json

import pytest

from moughorai.data_flow import (
    BasicBlock,
    ConstantKind,
    ControlFlowEdge,
    ControlFlowGraph,
    DataFlowService,
    EdgeKind,
    Instruction,
    InstructionId,
    InstructionKind,
)


def ins(block, index, *, kind=InstructionKind.NOP, defines=None, uses=(), constant=None, has_constant=False, side_effect=False, line=None):
    return Instruction(InstructionId(block, index), kind, defines, uses, constant, has_constant, side_effect, "Demo.java", line)


def block(name, *instructions):
    return BasicBlock(name, tuple(instructions))


def linear_cfg():
    return ControlFlowGraph([
        block("entry",
              ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x", constant=1, has_constant=True),
              ins("entry", 1, kind=InstructionKind.ASSIGN, defines="y", uses=("x",)),
              ins("entry", 2, kind=InstructionKind.RETURN, uses=("y",))),
    ])


def point_map(points):
    return {point.instruction.qualified_name: point for point in points}


def test_instruction_id_qualified_name():
    assert InstructionId("entry", 2).qualified_name == "entry:2"


def test_instruction_id_rejects_blank_block():
    with pytest.raises(ValueError):
        InstructionId("", 0)


def test_instruction_id_rejects_negative_index():
    with pytest.raises(ValueError):
        InstructionId("b", -1)


def test_instruction_normalizes_uses():
    instruction = ins("b", 0, uses=(" x ", "x", "y"))
    assert instruction.uses == ("x", "y")


def test_instruction_rejects_bad_line():
    with pytest.raises(ValueError):
        ins("b", 0, line=0)


def test_constant_requires_definition():
    with pytest.raises(ValueError):
        ins("b", 0, constant=1, has_constant=True)


def test_assign_factory():
    instruction = Instruction.assign("b", 0, "x", constant=3, has_constant=True)
    assert instruction.kind is InstructionKind.ASSIGN
    assert instruction.defines == "x"


def test_block_requires_contiguous_indices():
    with pytest.raises(ValueError, match="contiguous"):
        block("b", ins("b", 1))


def test_block_rejects_instruction_from_other_block():
    with pytest.raises(ValueError, match="does not match"):
        block("b", ins("other", 0))


def test_cfg_requires_a_block():
    with pytest.raises(ValueError):
        ControlFlowGraph([])


def test_cfg_rejects_duplicate_blocks():
    with pytest.raises(ValueError, match="duplicate"):
        ControlFlowGraph([block("b"), block("b")])


def test_cfg_rejects_unknown_edge_target():
    with pytest.raises(ValueError, match="unknown"):
        ControlFlowGraph([block("a")], [ControlFlowEdge("a", "b")])


def test_cfg_infers_entry_and_exit():
    cfg = ControlFlowGraph([block("a"), block("b")], [ControlFlowEdge("a", "b")])
    assert cfg.entry == "a"
    assert cfg.exits == ("b",)


def test_cfg_successors_and_predecessors_are_deterministic():
    cfg = ControlFlowGraph([block("a"), block("b"), block("c")], [ControlFlowEdge("a", "c"), ControlFlowEdge("a", "b")])
    assert cfg.successors("a") == ("b", "c")
    assert cfg.predecessors("c") == ("a",)


def test_cfg_reports_unreachable_blocks():
    cfg = ControlFlowGraph([block("entry"), block("dead")])
    assert cfg.reachable_blocks() == ("entry",)
    assert cfg.unreachable_blocks() == ("dead",)


def test_cfg_reverse_postorder_starts_with_entry():
    cfg = ControlFlowGraph([block("entry"), block("left"), block("right")], [ControlFlowEdge("entry", "left"), ControlFlowEdge("entry", "right")])
    assert cfg.reverse_postorder()[0].name == "entry"


def test_reaching_definition_flows_to_next_instruction():
    report = DataFlowService().analyze(linear_cfg())
    points = point_map(report.reaching_definitions)
    assert {d.variable for d in points["entry:1"].before} == {"x"}


def test_redefinition_kills_previous_definition():
    cfg = ControlFlowGraph([block("entry",
        ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x"),
        ins("entry", 1, kind=InstructionKind.ASSIGN, defines="x"),
        ins("entry", 2, kind=InstructionKind.RETURN, uses=("x",)),
    )])
    points = point_map(DataFlowService().analyze(cfg).reaching_definitions)
    assert {d.instruction for d in points["entry:2"].before} == {InstructionId("entry", 1)}


def test_branch_merge_preserves_both_reaching_definitions():
    cfg = ControlFlowGraph([
        block("entry"),
        block("left", ins("left", 0, kind=InstructionKind.ASSIGN, defines="x")),
        block("right", ins("right", 0, kind=InstructionKind.ASSIGN, defines="x")),
        block("join", ins("join", 0, kind=InstructionKind.RETURN, uses=("x",))),
    ], [
        ControlFlowEdge("entry", "left", EdgeKind.TRUE), ControlFlowEdge("entry", "right", EdgeKind.FALSE),
        ControlFlowEdge("left", "join"), ControlFlowEdge("right", "join"),
    ])
    point = point_map(DataFlowService().analyze(cfg).reaching_definitions)["join:0"]
    assert {d.instruction for d in point.before} == {InstructionId("left", 0), InstructionId("right", 0)}


def test_loop_reaching_definitions_converges():
    cfg = ControlFlowGraph([
        block("entry", ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x")),
        block("loop", ins("loop", 0, kind=InstructionKind.ASSIGN, defines="x", uses=("x",))),
        block("exit", ins("exit", 0, kind=InstructionKind.RETURN, uses=("x",))),
    ], [ControlFlowEdge("entry", "loop"), ControlFlowEdge("loop", "loop", EdgeKind.TRUE), ControlFlowEdge("loop", "exit", EdgeKind.FALSE)])
    point = point_map(DataFlowService().analyze(cfg).reaching_definitions)["loop:0"]
    assert {d.instruction for d in point.before} == {InstructionId("entry", 0), InstructionId("loop", 0)}


def test_liveness_marks_used_variable_live_before_use():
    report = DataFlowService().analyze(linear_cfg())
    points = point_map(report.liveness)
    assert "x" in points["entry:1"].live_before


def test_definition_not_live_before_its_assignment():
    report = DataFlowService().analyze(linear_cfg())
    points = point_map(report.liveness)
    assert "x" not in points["entry:0"].live_before


def test_liveness_propagates_across_blocks():
    cfg = ControlFlowGraph([
        block("a", ins("a", 0, kind=InstructionKind.ASSIGN, defines="x")),
        block("b", ins("b", 0, kind=InstructionKind.RETURN, uses=("x",))),
    ], [ControlFlowEdge("a", "b")])
    points = point_map(DataFlowService().analyze(cfg).liveness)
    assert "x" in points["a:0"].live_after


def test_liveness_merges_branch_successors():
    cfg = ControlFlowGraph([
        block("entry", ins("entry", 0, kind=InstructionKind.BRANCH)),
        block("left", ins("left", 0, kind=InstructionKind.RETURN, uses=("x",))),
        block("right", ins("right", 0, kind=InstructionKind.RETURN, uses=("y",))),
    ], [ControlFlowEdge("entry", "left"), ControlFlowEdge("entry", "right")])
    points = point_map(DataFlowService().analyze(cfg).liveness)
    assert points["entry:0"].live_after == frozenset({"x", "y"})


def test_def_use_chain_links_definition_to_use():
    report = DataFlowService().analyze(linear_cfg())
    chain = next(chain for chain in report.def_use_chains if chain.definition.variable == "x")
    assert chain.uses == (InstructionId("entry", 1),)


def test_def_use_chain_can_have_multiple_uses():
    cfg = ControlFlowGraph([block("entry",
        ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x"),
        ins("entry", 1, kind=InstructionKind.CALL, uses=("x",)),
        ins("entry", 2, kind=InstructionKind.RETURN, uses=("x",)),
    )])
    chain = DataFlowService().analyze(cfg).def_use_chains[0]
    assert chain.uses == (InstructionId("entry", 1), InstructionId("entry", 2))


def test_unused_definition_has_empty_chain():
    cfg = ControlFlowGraph([block("entry", ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x"))])
    assert DataFlowService().analyze(cfg).def_use_chains[0].uses == ()


def test_constant_propagates_through_copy():
    report = DataFlowService().analyze(linear_cfg())
    constants = report.constants_at(InstructionId("entry", 2))
    assert constants["y"].kind is ConstantKind.CONSTANT
    assert constants["y"].value == 1


def test_conflicting_branch_constants_become_non_constant():
    cfg = ControlFlowGraph([
        block("entry"),
        block("left", ins("left", 0, kind=InstructionKind.ASSIGN, defines="x", constant=1, has_constant=True)),
        block("right", ins("right", 0, kind=InstructionKind.ASSIGN, defines="x", constant=2, has_constant=True)),
        block("join", ins("join", 0, kind=InstructionKind.RETURN, uses=("x",))),
    ], [ControlFlowEdge("entry", "left"), ControlFlowEdge("entry", "right"), ControlFlowEdge("left", "join"), ControlFlowEdge("right", "join")])
    value = DataFlowService().analyze(cfg).constants_at(InstructionId("join", 0))["x"]
    assert value.kind is ConstantKind.NON_CONSTANT


def test_equal_branch_constants_remain_constant():
    cfg = ControlFlowGraph([
        block("entry"),
        block("left", ins("left", 0, kind=InstructionKind.ASSIGN, defines="x", constant=7, has_constant=True)),
        block("right", ins("right", 0, kind=InstructionKind.ASSIGN, defines="x", constant=7, has_constant=True)),
        block("join", ins("join", 0, kind=InstructionKind.RETURN, uses=("x",))),
    ], [ControlFlowEdge("entry", "left"), ControlFlowEdge("entry", "right"), ControlFlowEdge("left", "join"), ControlFlowEdge("right", "join")])
    value = DataFlowService().analyze(cfg).constants_at(InstructionId("join", 0))["x"]
    assert value.kind is ConstantKind.CONSTANT and value.value == 7


def test_unknown_assignment_is_non_constant():
    cfg = ControlFlowGraph([block("entry",
        ins("entry", 0, kind=InstructionKind.CALL, defines="x", side_effect=True),
        ins("entry", 1, kind=InstructionKind.RETURN, uses=("x",)),
    )])
    assert DataFlowService().analyze(cfg).constants_at(InstructionId("entry", 1))["x"].kind is ConstantKind.NON_CONSTANT


def test_dead_assignment_is_reported():
    cfg = ControlFlowGraph([block("entry", ins("entry", 0, kind=InstructionKind.ASSIGN, defines="unused", line=12))])
    dead = DataFlowService().analyze(cfg).dead_assignments
    assert dead[0].variable == "unused" and dead[0].line == 12


def test_used_assignment_is_not_dead():
    assert not DataFlowService().analyze(linear_cfg()).dead_assignments


def test_side_effecting_assignment_is_not_dead():
    cfg = ControlFlowGraph([block("entry", ins("entry", 0, kind=InstructionKind.CALL, defines="x", side_effect=True))])
    assert not DataFlowService().analyze(cfg).dead_assignments


def test_overwritten_assignment_is_dead():
    cfg = ControlFlowGraph([block("entry",
        ins("entry", 0, kind=InstructionKind.ASSIGN, defines="x"),
        ins("entry", 1, kind=InstructionKind.ASSIGN, defines="x"),
        ins("entry", 2, kind=InstructionKind.RETURN, uses=("x",)),
    )])
    dead_ids = {item.instruction for item in DataFlowService().analyze(cfg).dead_assignments}
    assert InstructionId("entry", 0) in dead_ids and InstructionId("entry", 1) not in dead_ids


def test_statistics_are_complete():
    stats = DataFlowService().analyze(linear_cfg()).statistics
    assert stats.block_count == 1
    assert stats.instruction_count == 3
    assert stats.variable_count == 2
    assert stats.definition_count == 2


def test_unreachable_block_produces_warning():
    cfg = ControlFlowGraph([block("entry"), block("dead")])
    assert DataFlowService().analyze(cfg).warnings == ("unreachable block: dead",)


def test_json_export_is_valid_and_versioned():
    payload = json.loads(DataFlowService().to_json(DataFlowService().analyze(linear_cfg())))
    assert payload["schema_version"] == 1
    assert payload["statistics"]["instruction_count"] == 3


def test_json_export_is_deterministic():
    service = DataFlowService()
    report = service.analyze(linear_cfg())
    assert service.to_json(report) == service.to_json(report)


def test_json_export_contains_def_use_chain():
    service = DataFlowService()
    payload = service.to_dict(service.analyze(linear_cfg()))
    assert payload["def_use_chains"][0]["definition"].startswith("x@")


def test_exception_edge_is_preserved():
    edge = ControlFlowEdge("try", "catch", EdgeKind.EXCEPTION)
    cfg = ControlFlowGraph([block("try"), block("catch")], [edge])
    assert cfg.edges == (edge,)


def test_explicit_exit_is_supported():
    cfg = ControlFlowGraph([block("a"), block("b")], [ControlFlowEdge("a", "b"), ControlFlowEdge("b", "b")], exits=("b",))
    assert cfg.exits == ("b",)


def test_lookup_instruction():
    cfg = linear_cfg()
    assert cfg.instruction(InstructionId("entry", 1)).defines == "y"
    assert cfg.instruction(InstructionId("missing", 0)) is None
