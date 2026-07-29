from moughorai.java_semantics.record_pattern_validator import (
    RecordPatternDiagnosticCode,
    RecordPatternRegistry,
    RecordPatternValidator,
)
from moughorai.java_semantics.record_patterns import (
    ComponentPattern,
    RecordComponent,
    RecordDeclaration,
    RecordPattern,
)
from moughorai.semantic import Diagnostic


def registry():
    return RecordPatternRegistry.from_records([
        RecordDeclaration(
            "Point",
            (RecordComponent("x", "int"), RecordComponent("y", "int")),
        ),
        RecordDeclaration(
            "Line",
            (RecordComponent("start", "Point"), RecordComponent("end", "Point")),
        ),
        RecordDeclaration(
            "Box",
            (RecordComponent("value", "T"),),
            ("T",),
        ),
        RecordDeclaration(
            "Pair",
            (RecordComponent("left", "A"), RecordComponent("right", "B")),
            ("A", "B"),
        ),
    ])


def validator():
    return RecordPatternValidator(
        registry(),
        subtype_relations={"Point": ("Object",), "Line": ("Object",)},
    )


def codes(result):
    return [item.code for item in result.diagnostics]


def point_pattern():
    return RecordPattern(
        "Point",
        (ComponentPattern.var("x"), ComponentPattern.var("y")),
    )


def test_registry_adds_and_resolves_records():
    records = registry()
    assert records.get("Point").components[0].name == "x"


def test_registry_rejects_duplicate_record_name():
    records = RecordPatternRegistry()
    declaration = RecordDeclaration("Point", ())
    assert records.add(declaration)
    assert not records.add(declaration)


def test_simple_record_pattern_is_valid():
    result = validator().validate(point_pattern(), selector_type="Point")
    assert result.valid
    assert [(item.name, item.type_name) for item in result.bindings] == [
        ("x", "int"),
        ("y", "int"),
    ]


def test_binding_paths_identify_components():
    result = validator().validate(point_pattern())
    assert [item.component_path for item in result.bindings] == [(0,), (1,)]


def test_typed_components_are_valid_when_types_match():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.type("int", "x"), ComponentPattern.type("int", "y")),
    )
    assert validator().validate(pattern).valid


def test_unnamed_component_creates_no_binding():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.unnamed(), ComponentPattern.var("y")),
    )
    result = validator().validate(pattern)
    assert result.valid
    assert [item.name for item in result.bindings] == ["y"]


def test_unknown_record_type_is_rejected():
    result = validator().validate(RecordPattern("Missing", ()))
    assert codes(result) == [RecordPatternDiagnosticCode.UNSUPPORTED_DECOMPOSITION]


def test_too_few_components_are_rejected():
    result = validator().validate(
        RecordPattern("Point", (ComponentPattern.var("x"),))
    )
    assert RecordPatternDiagnosticCode.COMPONENT_COUNT in codes(result)


def test_too_many_components_are_rejected():
    result = validator().validate(
        RecordPattern(
            "Point",
            (
                ComponentPattern.var("x"),
                ComponentPattern.var("y"),
                ComponentPattern.var("z"),
            ),
        )
    )
    assert RecordPatternDiagnosticCode.COMPONENT_COUNT in codes(result)


def test_incompatible_component_type_is_rejected():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.type("String", "x"), ComponentPattern.var("y")),
    )
    assert RecordPatternDiagnosticCode.TYPE_MISMATCH in codes(
        validator().validate(pattern)
    )


def test_duplicate_binding_is_rejected():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.var("value"), ComponentPattern.var("value")),
    )
    assert RecordPatternDiagnosticCode.DUPLICATE_BINDING in codes(
        validator().validate(pattern)
    )


def test_empty_binding_name_is_rejected():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.var(""), ComponentPattern.var("y")),
    )
    assert RecordPatternDiagnosticCode.INVALID_PATTERN in codes(
        validator().validate(pattern)
    )


def test_nested_record_pattern_is_valid():
    first = RecordPattern(
        "Point", (ComponentPattern.var("x1"), ComponentPattern.var("y1"))
    )
    second = RecordPattern(
        "Point", (ComponentPattern.var("x2"), ComponentPattern.var("y2"))
    )
    pattern = RecordPattern(
        "Line",
        (ComponentPattern.nested(first), ComponentPattern.nested(second)),
    )
    result = validator().validate(pattern)
    assert result.valid
    assert [item.component_path for item in result.bindings] == [
        (0, 0), (0, 1), (1, 0), (1, 1)
    ]


def test_nested_bindings_share_duplicate_detection_scope():
    pattern = RecordPattern(
        "Line",
        (
            ComponentPattern.nested(point_pattern()),
            ComponentPattern.nested(point_pattern()),
        ),
    )
    result = validator().validate(pattern)
    assert RecordPatternDiagnosticCode.DUPLICATE_BINDING in codes(result)


def test_nested_pattern_type_mismatch_is_rejected():
    pattern = RecordPattern(
        "Point",
        (
            ComponentPattern.nested(point_pattern()),
            ComponentPattern.var("y"),
        ),
    )
    assert RecordPatternDiagnosticCode.INVALID_NESTED_PATTERN in codes(
        validator().validate(pattern)
    )


def test_missing_nested_pattern_payload_is_rejected():
    from moughorai.java_semantics.record_patterns import (
        ComponentPatternKind,
        ComponentPattern,
    )
    pattern = RecordPattern(
        "Point",
        (ComponentPattern(ComponentPatternKind.RECORD), ComponentPattern.var("y")),
    )
    assert RecordPatternDiagnosticCode.INVALID_NESTED_PATTERN in codes(
        validator().validate(pattern)
    )


def test_selector_type_mismatch_is_rejected():
    result = validator().validate(point_pattern(), selector_type="Line")
    assert RecordPatternDiagnosticCode.INVALID_PATTERN in codes(result)


def test_object_selector_accepts_known_record_pattern():
    assert validator().validate(point_pattern(), selector_type="Object").valid


def test_generic_record_substitutes_component_type():
    pattern = RecordPattern(
        "Box",
        (ComponentPattern.var("value"),),
        ("String",),
    )
    result = validator().validate(pattern)
    assert result.valid
    assert result.bindings[0].type_name == "String"


def test_generic_typed_component_uses_substituted_type():
    pattern = RecordPattern(
        "Box",
        (ComponentPattern.type("String", "value"),),
        ("String",),
    )
    assert validator().validate(pattern).valid


def test_wrong_generic_argument_count_is_rejected():
    pattern = RecordPattern(
        "Pair",
        (ComponentPattern.var("left"), ComponentPattern.var("right")),
        ("String",),
    )
    assert RecordPatternDiagnosticCode.INVALID_PATTERN in codes(
        validator().validate(pattern)
    )


def test_generic_pair_substitutes_both_types():
    pattern = RecordPattern(
        "Pair",
        (ComponentPattern.var("left"), ComponentPattern.var("right")),
        ("String", "int"),
    )
    result = validator().validate(pattern)
    assert [(item.name, item.type_name) for item in result.bindings] == [
        ("left", "String"), ("right", "int")
    ]


def test_typed_object_pattern_accepts_component_value():
    pattern = RecordPattern(
        "Box",
        (ComponentPattern.type("Object", "value"),),
        ("String",),
    )
    assert validator().validate(pattern).valid


def test_invalid_typed_component_still_reports_binding_type():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.type("String", "x"), ComponentPattern.var("y")),
    )
    result = validator().validate(pattern)
    assert result.bindings[0].type_name == "String"


def test_diagnostics_include_component_path():
    pattern = RecordPattern(
        "Point",
        (ComponentPattern.type("String", "x"), ComponentPattern.var("y")),
    )
    result = validator().validate(pattern)
    assert result.diagnostics[0].component_path == (0,)


def test_diagnostics_convert_to_standard_diagnostics():
    result = validator().validate(RecordPattern("Missing", ()))
    diagnostic = result.standard_diagnostics[0]
    assert isinstance(diagnostic, Diagnostic)
    assert diagnostic.code == "ATLAS-RECORD-006"
    assert diagnostic.pass_name == "record_patterns"


def test_result_is_invalid_when_any_diagnostic_exists():
    result = validator().validate(RecordPattern("Point", ()))
    assert not result.valid


def test_declaration_models_normalize_whitespace():
    declaration = RecordDeclaration(
        " Point ", (RecordComponent(" x ", " int "),), (" T ",)
    )
    assert declaration.name == "Point"
    assert declaration.components[0].type_name == "int"
    assert declaration.type_parameters == ("T",)