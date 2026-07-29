from moughorai.java_semantics.hierarchy_graph import (
    HierarchyDiagnosticCode,
    HierarchyGraph,
)
from moughorai.java_semantics.sealed_types import SealedType, TypeOpenness
from moughorai.java_semantics.switch_exhaustiveness import (
    SwitchAnalyzer,
    SwitchCase,
    SwitchDiagnosticCode,
)
from moughorai.semantic import Diagnostic


def shape_graph():
    return HierarchyGraph.from_types([
        SealedType("Shape", TypeOpenness.SEALED, ("Circle", "Rectangle")),
        SealedType("Circle", TypeOpenness.FINAL, direct_supertype="Shape"),
        SealedType("Rectangle", TypeOpenness.FINAL, direct_supertype="Shape"),
    ])


def nested_graph():
    return HierarchyGraph.from_types([
        SealedType("Expr", TypeOpenness.SEALED, ("Literal", "Binary")),
        SealedType("Literal", TypeOpenness.FINAL, direct_supertype="Expr"),
        SealedType(
            "Binary",
            TypeOpenness.SEALED,
            ("Add", "Multiply"),
            direct_supertype="Expr",
        ),
        SealedType("Add", TypeOpenness.FINAL, direct_supertype="Binary"),
        SealedType("Multiply", TypeOpenness.FINAL, direct_supertype="Binary"),
    ])


def switch_codes(result):
    return [item.code for item in result.diagnostics]


def hierarchy_codes(graph):
    return [item.code for item in graph.diagnostics]


def test_direct_children_follow_permits_order():
    assert shape_graph().direct_children("Shape") == ("Circle", "Rectangle")


def test_inferred_direct_child_is_added_when_not_explicitly_permitted():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED),
        SealedType("Leaf", TypeOpenness.FINAL, direct_supertype="Root"),
    ])
    assert graph.direct_children("Root") == ("Leaf",)


def test_ancestors_and_subtype_queries():
    graph = nested_graph()
    assert graph.ancestors("Add") == ("Binary", "Expr")
    assert graph.is_subtype("Add", "Expr")
    assert not graph.is_subtype("Expr", "Add")


def test_simple_permitted_leaves():
    assert shape_graph().permitted_leaves("Shape") == ("Circle", "Rectangle")


def test_nested_sealed_hierarchy_expands_to_terminal_leaves():
    assert nested_graph().permitted_leaves("Expr") == (
        "Literal",
        "Add",
        "Multiply",
    )


def test_non_sealed_branch_is_a_terminal_leaf():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED, ("OpenBranch",)),
        SealedType(
            "OpenBranch",
            TypeOpenness.NON_SEALED,
            direct_supertype="Root",
        ),
    ])
    assert graph.permitted_leaves("Root") == ("OpenBranch",)


def test_duplicate_declaration_is_rejected():
    graph = HierarchyGraph()
    assert graph.add(SealedType("Node"))
    assert not graph.add(SealedType("Node"))
    assert hierarchy_codes(graph) == [HierarchyDiagnosticCode.INVALID_HIERARCHY]


def test_duplicate_permits_are_rejected():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED, ("Leaf", "Leaf")),
        SealedType("Leaf", direct_supertype="Root"),
    ])
    assert HierarchyDiagnosticCode.INVALID_PERMITS in hierarchy_codes(graph)


def test_non_sealed_type_cannot_declare_permits():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.NON_SEALED, ("Leaf",)),
        SealedType("Leaf", direct_supertype="Root"),
    ])
    assert HierarchyDiagnosticCode.INVALID_PERMITS in hierarchy_codes(graph)


def test_missing_permitted_subtype_is_reported():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED, ("Missing",)),
    ])
    assert HierarchyDiagnosticCode.INVALID_PERMITS in hierarchy_codes(graph)


def test_permitted_subtype_must_directly_extend_parent():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED, ("Leaf",)),
        SealedType("Other"),
        SealedType("Leaf", direct_supertype="Other"),
    ])
    assert HierarchyDiagnosticCode.INVALID_PERMITS in hierarchy_codes(graph)


def test_inheritance_cycle_is_reported():
    graph = HierarchyGraph.from_types([
        SealedType("A", TypeOpenness.SEALED, ("B",), "B"),
        SealedType("B", TypeOpenness.SEALED, ("A",), "A"),
    ])
    assert HierarchyDiagnosticCode.INVALID_HIERARCHY in hierarchy_codes(graph)


def test_exhaustive_switch_over_simple_hierarchy():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Circle"), SwitchCase.type("Rectangle")]
    )
    assert result.exhaustive
    assert result.missing_types == ()
    assert result.diagnostics == ()


def test_missing_subtype_produces_non_exhaustive_diagnostic():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Circle")]
    )
    assert not result.exhaustive
    assert result.missing_types == ("Rectangle",)
    assert switch_codes(result) == [SwitchDiagnosticCode.NON_EXHAUSTIVE]


def test_default_makes_switch_exhaustive():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Circle"), SwitchCase.default()]
    )
    assert result.exhaustive
    assert SwitchDiagnosticCode.NON_EXHAUSTIVE not in switch_codes(result)


def test_parent_pattern_covers_all_permitted_subtypes():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Shape")]
    )
    assert result.exhaustive
    assert set(result.covered_types) == {"Circle", "Rectangle"}


def test_duplicate_case_is_reported():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape",
        [
            SwitchCase.type("Circle"),
            SwitchCase.type("Circle"),
            SwitchCase.type("Rectangle"),
        ],
    )
    assert SwitchDiagnosticCode.DUPLICATE_CASE in switch_codes(result)


def test_subtype_case_after_parent_is_dominated():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Shape"), SwitchCase.type("Circle")]
    )
    assert SwitchDiagnosticCode.DOMINATED_CASE in switch_codes(result)


def test_guarded_parent_does_not_dominate_or_cover_subtypes():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape",
        [
            SwitchCase.type("Shape", guarded=True),
            SwitchCase.type("Circle"),
            SwitchCase.type("Rectangle"),
        ],
    )
    assert result.exhaustive
    assert SwitchDiagnosticCode.DOMINATED_CASE not in switch_codes(result)


def test_case_after_default_is_dominated():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.default(), SwitchCase.type("Circle")]
    )
    assert SwitchDiagnosticCode.DOMINATED_CASE in switch_codes(result)


def test_nested_switch_can_be_exhaustive_with_branch_pattern():
    result = SwitchAnalyzer(nested_graph()).analyze(
        "Expr", [SwitchCase.type("Literal"), SwitchCase.type("Binary")]
    )
    assert result.exhaustive
    assert set(result.covered_types) == {"Literal", "Add", "Multiply"}


def test_analysis_can_skip_exhaustiveness_requirement():
    result = SwitchAnalyzer(shape_graph()).analyze(
        "Shape", [SwitchCase.type("Circle")], require_exhaustive=False
    )
    assert not result.exhaustive
    assert result.diagnostics == ()


def test_switch_diagnostics_convert_to_standard_diagnostics():
    result = SwitchAnalyzer(shape_graph()).analyze("Shape", [])
    diagnostic = result.standard_diagnostics[0]
    assert isinstance(diagnostic, Diagnostic)
    assert diagnostic.code == "ATLAS-SWITCH-001"
    assert diagnostic.pass_name == "switch_exhaustiveness"


def test_hierarchy_diagnostics_convert_to_standard_diagnostics():
    graph = HierarchyGraph.from_types([
        SealedType("Root", TypeOpenness.SEALED, ("Missing",)),
    ])
    diagnostic = graph.standard_diagnostics[0]
    assert isinstance(diagnostic, Diagnostic)
    assert diagnostic.code == "ATLAS-SWITCH-005"
    assert diagnostic.pass_name == "sealed_hierarchy"