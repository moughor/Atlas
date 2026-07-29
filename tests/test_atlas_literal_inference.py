from __future__ import annotations

import pytest

from moughorai.passes import (
    LiteralInferenceResult,
    LiteralKind,
    infer_java_literal,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("0", LiteralKind.INT),
        ("1", LiteralKind.INT),
        ("42", LiteralKind.INT),
        ("2_147_483_647", LiteralKind.INT),
        ("42L", LiteralKind.LONG),
        ("42l", LiteralKind.LONG),
        ("9_223_372_036_854_775_807L", LiteralKind.LONG),
    ],
)
def test_decimal_integer_literals(
    source: str,
    expected: LiteralKind,
) -> None:
    result = infer_java_literal(source)

    assert result.kind is expected
    assert result.valid is True
    assert "_" not in result.normalized


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("0xFF", LiteralKind.INT),
        ("0XCAFE", LiteralKind.INT),
        ("0x7fff_ffff", LiteralKind.INT),
        ("0xFFL", LiteralKind.LONG),
        ("0xffff_ffff_ffff_ffffL", LiteralKind.LONG),
        ("0b1010", LiteralKind.INT),
        ("0B1111_0000", LiteralKind.INT),
        ("0b1010L", LiteralKind.LONG),
        ("077", LiteralKind.INT),
        ("01_234", LiteralKind.INT),
        ("077L", LiteralKind.LONG),
    ],
)
def test_non_decimal_integer_literals(
    source: str,
    expected: LiteralKind,
) -> None:
    result = infer_java_literal(source)

    assert result.kind is expected
    assert result.valid is True


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1.0", LiteralKind.DOUBLE),
        (".5", LiteralKind.DOUBLE),
        ("5.", LiteralKind.DOUBLE),
        ("1e10", LiteralKind.DOUBLE),
        ("1E-10", LiteralKind.DOUBLE),
        ("1.0e+10", LiteralKind.DOUBLE),
        ("1_000.25", LiteralKind.DOUBLE),
        ("1f", LiteralKind.FLOAT),
        ("1F", LiteralKind.FLOAT),
        ("1.0f", LiteralKind.FLOAT),
        ("1d", LiteralKind.DOUBLE),
        ("1D", LiteralKind.DOUBLE),
        ("0x1.0p0", LiteralKind.DOUBLE),
        ("0x1p10", LiteralKind.DOUBLE),
        ("0xCAFE.p-2", LiteralKind.DOUBLE),
        ("0x1.ffffp127f", LiteralKind.FLOAT),
    ],
)
def test_floating_point_literals(
    source: str,
    expected: LiteralKind,
) -> None:
    result = infer_java_literal(source)

    assert result.kind is expected
    assert result.valid is True


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("true", LiteralKind.BOOLEAN),
        ("false", LiteralKind.BOOLEAN),
        ("null", LiteralKind.NULL),
        ("'a'", LiteralKind.CHAR),
        ("'0'", LiteralKind.CHAR),
        (r"'\n'", LiteralKind.CHAR),
        (r"'\t'", LiteralKind.CHAR),
        (r"'\\'", LiteralKind.CHAR),
        (r"'\''", LiteralKind.CHAR),
        (r"'\u0041'", LiteralKind.CHAR),
        ('""', LiteralKind.STRING),
        ('"Hello"', LiteralKind.STRING),
        (r'"Hello\nworld"', LiteralKind.STRING),
        (r'"Quoted: \"Atlas\""', LiteralKind.STRING),
        (r'"\u0041"', LiteralKind.STRING),
    ],
)
def test_non_numeric_literals(
    source: str,
    expected: LiteralKind,
) -> None:
    result = infer_java_literal(source)

    assert result.kind is expected
    assert result.valid is True


@pytest.mark.parametrize(
    "source",
    [
        "",
        " ",
        "True",
        "False",
        "NULL",
        "hello",
        "_1",
        "1_",
        "1__0",
        "0x",
        "0x_FF",
        "0b",
        "0b102",
        "0b_1010",
        "08",
        "09L",
        ".",
        "1e",
        "1e+",
        "1._0",
        "1_.0",
        "0x1.0",
        "''",
        "'ab'",
        r"'\x'",
        '"unterminated',
        '"line\nbreak\n"',
        r'"\x"',
    ],
)
def test_invalid_or_unsupported_literals_return_unknown(source: str) -> None:
    result = infer_java_literal(source)

    assert result == LiteralInferenceResult.unknown(source)
    assert result.kind is LiteralKind.UNKNOWN
    assert result.valid is False


def test_result_is_immutable() -> None:
    result = infer_java_literal("42")

    with pytest.raises((AttributeError, TypeError)):
        result.kind = LiteralKind.LONG  # type: ignore[misc]


def test_literal_kind_values_match_canonical_atlas_type_names() -> None:
    assert LiteralKind.INT.value == "int"
    assert LiteralKind.LONG.value == "long"
    assert LiteralKind.FLOAT.value == "float"
    assert LiteralKind.DOUBLE.value == "double"
    assert LiteralKind.BOOLEAN.value == "boolean"
    assert LiteralKind.CHAR.value == "char"
    assert LiteralKind.STRING.value == "String"
    assert LiteralKind.NULL.value == "null"
    assert LiteralKind.UNKNOWN.value == "unknown"


def test_original_source_is_preserved() -> None:
    result = infer_java_literal("1_000L")

    assert result.source == "1_000L"
    assert result.normalized == "1000L"


def test_package_exports_literal_inference_api() -> None:
    from moughorai import passes

    assert passes.LiteralKind is LiteralKind
    assert passes.LiteralInferenceResult is LiteralInferenceResult
    assert passes.infer_java_literal is infer_java_literal
