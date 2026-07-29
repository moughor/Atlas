from pathlib import Path

from moughorai.java_semantics.flow_analysis import FlowDiagnosticCode, FlowState
from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import PrimitiveType
from moughorai.semantic.types.relations import (
    PRIMITIVE_WIDENING,
    can_widen_primitive,
    primitive_widening_cost,
)


def test_shared_widening_table_contains_java_numeric_conversions():
    assert PRIMITIVE_WIDENING["byte"] == ("short", "int", "long", "float", "double")
    assert PRIMITIVE_WIDENING["char"] == ("int", "long", "float", "double")


def test_shared_widening_accepts_names():
    assert can_widen_primitive("byte", "double")
    assert not can_widen_primitive("double", "float")


def test_shared_widening_accepts_types():
    assert can_widen_primitive(PrimitiveType("int"), PrimitiveType("long"))


def test_widening_cost_prefers_nearer_conversion():
    actual = PrimitiveType("byte")
    assert primitive_widening_cost(actual, PrimitiveType("short")) == 1
    assert primitive_widening_cost(actual, PrimitiveType("double")) == 5


def test_widening_cost_rejects_narrowing():
    assert primitive_widening_cost(PrimitiveType("long"), PrimitiveType("int")) is None


def test_flow_codes_are_stable_public_strings():
    assert FlowDiagnosticCode.UNASSIGNED_READ.value == "ATLAS-FLOW-001"
    assert FlowDiagnosticCode.FINAL_REASSIGNMENT.value == "ATLAS-FLOW-002"
    assert FlowDiagnosticCode.UNREACHABLE_STATEMENT.value == "ATLAS-FLOW-003"
    assert FlowDiagnosticCode.DUPLICATE_DECLARATION.value == "ATLAS-FLOW-004"


def test_flow_diagnostic_converts_to_standard_diagnostic():
    state = FlowState()
    state.declare("value")
    assert not state.read("value")
    diagnostic = state.standard_diagnostics[0]
    assert isinstance(diagnostic, Diagnostic)
    assert diagnostic.code == "ATLAS-FLOW-001"
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.pass_name == "flow_analysis"


def test_flow_adapter_preserves_message():
    state = FlowState()
    state.declare("value")
    state.read("value")
    assert state.standard_diagnostics[0].message == state.diagnostics[0].message


def test_pass_pipeline_documentation_exists():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "PASS_PIPELINE.md").read_text(encoding="utf-8")
    assert "Statement type checking" in text
    assert "Flow analysis" in text
    assert "must not be scheduled" in text


def test_conversion_tables_are_not_duplicated_in_consuming_passes():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "moughorai/passes/method_resolution.py",
        "moughorai/passes/functional_interface_typing.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "_PRIMITIVE_WIDENING" not in text
        assert "PRIMITIVE_WIDENING" in text
