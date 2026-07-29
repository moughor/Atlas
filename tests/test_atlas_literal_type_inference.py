from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from moughorai.passes import (
    LiteralInferenceResult,
    LiteralKind,
    LiteralTypeInferenceResult,
    attach_java_literal_type,
    infer_java_literal,
    infer_java_literal_type,
    literal_kind_to_type,
    resolve_literal_type,
)
from moughorai.semantic import SemanticDocument
from moughorai.semantic.types import (
    ClassType,
    NULL,
    UNKNOWN,
    NullType,
    PrimitiveType,
    TypeRegistry,
    UnknownType,
)


def make_document() -> SemanticDocument:
    return SemanticDocument(
        language="java",
        source="class Example {}",
        syntax_tree=object(),
    )


@pytest.mark.parametrize(
    ("kind", "expected_name"),
    [
        (LiteralKind.INT, "int"),
        (LiteralKind.LONG, "long"),
        (LiteralKind.FLOAT, "float"),
        (LiteralKind.DOUBLE, "double"),
        (LiteralKind.BOOLEAN, "boolean"),
        (LiteralKind.CHAR, "char"),
    ],
)
def test_primitive_literal_kinds_map_to_primitive_types(
    kind: LiteralKind,
    expected_name: str,
) -> None:
    semantic_type = literal_kind_to_type(kind)

    assert isinstance(semantic_type, PrimitiveType)
    assert semantic_type.name == expected_name
    assert semantic_type.display_name == expected_name


def test_string_literal_kind_maps_to_java_lang_string() -> None:
    semantic_type = literal_kind_to_type(LiteralKind.STRING)

    assert isinstance(semantic_type, ClassType)
    assert semantic_type.name == "java.lang.String"
    assert semantic_type.display_name == "java.lang.String"


def test_null_literal_kind_maps_to_null_singleton() -> None:
    semantic_type = literal_kind_to_type(LiteralKind.NULL)

    assert semantic_type is NULL
    assert isinstance(semantic_type, NullType)


def test_unknown_literal_kind_maps_to_unknown_singleton() -> None:
    semantic_type = literal_kind_to_type(LiteralKind.UNKNOWN)

    assert semantic_type is UNKNOWN
    assert isinstance(semantic_type, UnknownType)


@pytest.mark.parametrize(
    ("source", "expected_type", "expected_name"),
    [
        ("42", PrimitiveType, "int"),
        ("42L", PrimitiveType, "long"),
        ("1.5f", PrimitiveType, "float"),
        ("1.5", PrimitiveType, "double"),
        ("true", PrimitiveType, "boolean"),
        ("'A'", PrimitiveType, "char"),
        ('"Atlas"', ClassType, "java.lang.String"),
    ],
)
def test_java_literal_sources_resolve_to_semantic_types(
    source: str,
    expected_type: type,
    expected_name: str,
) -> None:
    result = infer_java_literal_type(source)

    assert isinstance(result, LiteralTypeInferenceResult)
    assert isinstance(result.semantic_type, expected_type)
    assert result.semantic_type.display_name == expected_name
    assert result.source == source
    assert result.valid is True


def test_null_source_resolves_to_canonical_null_type() -> None:
    result = infer_java_literal_type("null")

    assert result.kind is LiteralKind.NULL
    assert result.semantic_type is NULL
    assert result.valid is True


@pytest.mark.parametrize(
    "source",
    [
        "",
        "hello",
        "1__0",
        "0x",
        "0b102",
        "08",
        "1e",
        "''",
        "'ab'",
        '"unterminated',
    ],
)
def test_invalid_sources_resolve_to_unknown_type(source: str) -> None:
    result = infer_java_literal_type(source)

    assert result.kind is LiteralKind.UNKNOWN
    assert result.semantic_type is UNKNOWN
    assert result.valid is False


def test_existing_literal_result_can_be_resolved_without_reclassification() -> None:
    literal = infer_java_literal("42L")

    result = resolve_literal_type(literal)

    assert result.literal is literal
    assert result.kind is LiteralKind.LONG
    assert result.semantic_type == PrimitiveType("long")


def test_registry_canonicalizes_repeated_primitive_types() -> None:
    registry = TypeRegistry()

    first = infer_java_literal_type("42", registry)
    second = infer_java_literal_type("100", registry)

    assert first.semantic_type is second.semantic_type
    assert len(registry) == 1


def test_registry_canonicalizes_repeated_string_types() -> None:
    registry = TypeRegistry()

    first = infer_java_literal_type('"Atlas"', registry)
    second = infer_java_literal_type('"MoughorAI"', registry)

    assert first.semantic_type is second.semantic_type
    assert first.semantic_type == ClassType("java.lang.String")
    assert len(registry) == 1


def test_empty_registry_instance_is_used_instead_of_replaced() -> None:
    registry = TypeRegistry()

    result = infer_java_literal_type("42", registry)

    assert len(registry) == 1
    assert result.semantic_type is registry.primitive("int")


def test_null_and_unknown_do_not_allocate_registry_entries() -> None:
    registry = TypeRegistry()

    null_result = infer_java_literal_type("null", registry)
    unknown_result = infer_java_literal_type("not_a_literal", registry)

    assert null_result.semantic_type is registry.null
    assert unknown_result.semantic_type is registry.unknown
    assert len(registry) == 0


def test_result_is_immutable() -> None:
    result = infer_java_literal_type("42")

    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        result.semantic_type = PrimitiveType("long")  # type: ignore[misc]


def test_attach_literal_type_returns_a_new_document() -> None:
    document = make_document()

    updated = attach_java_literal_type(
        document,
        node_key="literal:1",
        source="42",
    )

    assert updated is not document
    assert len(document.types) == 0
    assert len(updated.types) == 1
    assert updated.require_type("literal:1") == PrimitiveType("int")


def test_attach_literal_type_preserves_existing_document_types() -> None:
    document = make_document().with_type(
        "existing",
        PrimitiveType("boolean"),
    )

    updated = attach_java_literal_type(
        document,
        node_key="literal:1",
        source='"Atlas"',
    )

    assert updated.require_type("existing") == PrimitiveType("boolean")
    assert updated.require_type("literal:1") == ClassType("java.lang.String")
    assert len(updated.types) == 2


def test_attach_literal_type_replaces_only_matching_node_key() -> None:
    document = make_document().with_type(
        "literal:1",
        PrimitiveType("int"),
    )

    updated = attach_java_literal_type(
        document,
        node_key="literal:1",
        source="42L",
    )

    assert updated.require_type("literal:1") == PrimitiveType("long")
    assert len(updated.types) == 1


def test_attach_invalid_literal_stores_unknown_type() -> None:
    document = make_document()

    updated = attach_java_literal_type(
        document,
        node_key="literal:invalid",
        source="not_a_literal",
    )

    assert updated.require_type("literal:invalid") is UNKNOWN


def test_attach_uses_provided_registry() -> None:
    registry = TypeRegistry()
    document = make_document()

    first = attach_java_literal_type(
        document,
        node_key="literal:1",
        source="42",
        registry=registry,
    )

    second = attach_java_literal_type(
        first,
        node_key="literal:2",
        source="100",
        registry=registry,
    )

    assert second.require_type("literal:1") is second.require_type("literal:2")
    assert len(registry) == 1


def test_literal_kind_to_type_rejects_invalid_kind() -> None:
    with pytest.raises(TypeError, match="LiteralKind"):
        literal_kind_to_type("int")  # type: ignore[arg-type]


def test_resolve_literal_type_rejects_invalid_result() -> None:
    with pytest.raises(TypeError, match="LiteralInferenceResult"):
        resolve_literal_type("42")  # type: ignore[arg-type]


def test_attach_literal_type_rejects_invalid_document() -> None:
    with pytest.raises(TypeError, match="SemanticDocument"):
        attach_java_literal_type(
            None,  # type: ignore[arg-type]
            node_key="literal:1",
            source="42",
        )


def test_attach_literal_type_rejects_unhashable_node_key() -> None:
    document = make_document()

    with pytest.raises(TypeError, match="hashable"):
        attach_java_literal_type(
            document,
            node_key=[],  # type: ignore[arg-type]
            source="42",
        )


def test_public_package_exports_literal_type_api() -> None:
    from moughorai import passes

    assert passes.LiteralTypeInferenceResult is LiteralTypeInferenceResult
    assert passes.literal_kind_to_type is literal_kind_to_type
    assert passes.resolve_literal_type is resolve_literal_type
    assert passes.infer_java_literal_type is infer_java_literal_type
    assert passes.attach_java_literal_type is attach_java_literal_type


def test_combined_result_preserves_original_literal_result() -> None:
    literal = LiteralInferenceResult(
        source="42",
        kind=LiteralKind.INT,
        normalized="42",
        valid=True,
    )

    result = resolve_literal_type(literal)

    assert result.literal is literal
    assert result.source == "42"
    assert result.kind is LiteralKind.INT
    assert result.valid is True
