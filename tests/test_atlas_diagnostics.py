from moughorai.semantic import Diagnostic, DiagnosticBag, DiagnosticSeverity


def test_diagnostic_bag_is_immutable():
    empty = DiagnosticBag()
    populated = empty.add(Diagnostic("A1", "problem"))
    assert len(empty) == 0
    assert len(populated) == 1


def test_diagnostic_bag_filters_by_severity():
    bag = DiagnosticBag().extend(
        [
            Diagnostic("I", "info", DiagnosticSeverity.INFO),
            Diagnostic("E", "error", DiagnosticSeverity.ERROR),
        ]
    )
    assert [item.code for item in bag.by_severity(DiagnosticSeverity.INFO)] == ["I"]
    assert bag.has_errors is True
