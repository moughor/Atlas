from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from moughorai.domains.benchmark import (
    FIRE_STRIKE_SCORING_METHOD_ID,
    FIRE_STRIKE_SCORING_ROUNDING_POLICY,
    FIRE_STRIKE_SCORING_SCHEMA_VERSION,
    FIRE_STRIKE_STANDARD_BENCHMARK_ID,
    FireStrikeScoreCalculationV1,
    FireStrikeScoreInputError,
    calculate_fire_strike_score,
)


MODULE = (
    Path(__file__).parents[1]
    / "moughorai"
    / "domains"
    / "benchmark"
    / "fire_strike_scoring.py"
)


@pytest.mark.parametrize(
    ("graphics", "physics", "combined", "overall"),
    [
        (22447, 56270, 7668, 20358),
        (23412, 27379, 11534, 21652),
        (15034, 10906, 5114, 12019),
        (14201, 17972, 4749, 12162),
        (32124, 28002, 12667, 27323),
        (31916, 28852, 16517, 28774),
        (47013, 26376, 15091, 35377),
        (5853, 10023, 1823, 5051),
        (19087, 20361, 8090, 16942),
        (69223, 44369, 20815, 52577),
        (65600, 42589, 21250, 50862),
        (23765, 25298, 10296, 21186),
        (23764, 25345, 10289, 21187),
        (32562, 25400, 13732, 27608),
        (28865, 22351, 11575, 24193),
        (21292, 22648, 10216, 19366),
    ],
)
def test_public_ul_and_independent_calculator_vectors(
    graphics: int,
    physics: int,
    combined: int,
    overall: int,
) -> None:
    result = calculate_fire_strike_score(graphics, physics, combined)

    assert result.overall_score == overall


def test_authorized_ul_capture_vector_uses_observed_floor_behavior() -> None:
    result = calculate_fire_strike_score(22447, 56270, 7668)
    numerator, denominator = result.exact_fraction

    assert numerator // denominator == 20358
    assert (2 * numerator + denominator) // (2 * denominator) == 20359
    assert result.overall_score == 20358


@pytest.mark.parametrize(
    ("graphics", "physics", "combined", "expected"),
    [
        (26, 63, 97, 31),
        (97, 54, 65, 82),
    ],
)
def test_exact_integer_boundaries_do_not_depend_on_decimal_precision(
    graphics: int,
    physics: int,
    combined: int,
    expected: int,
) -> None:
    with localcontext() as context:
        context.prec = 2
        result = calculate_fire_strike_score(graphics, physics, combined)

    assert result.overall_score == expected


def test_result_records_method_inputs_units_and_rounding() -> None:
    result = calculate_fire_strike_score(22447, 56270, 7668)

    assert result.to_dict() == {
        "benchmark_id": FIRE_STRIKE_STANDARD_BENCHMARK_ID,
        "combined_score": "7668",
        "graphics_score": "22447",
        "method_id": FIRE_STRIKE_SCORING_METHOD_ID,
        "overall_score": "20358",
        "physics_score": "56270",
        "rounding_policy": FIRE_STRIKE_SCORING_ROUNDING_POLICY,
        "schema_version": FIRE_STRIKE_SCORING_SCHEMA_VERSION,
        "unit": "marks",
    }


def test_canonical_serialization_and_digest_are_stable() -> None:
    first = calculate_fire_strike_score(22447, 56270, 7668)
    second = calculate_fire_strike_score("22447.00", Decimal("56270.0"), "7668")

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.to_json() == second.to_json()
    assert first.canonical_sha256 == second.canonical_sha256
    assert json.loads(first.to_json()) == first.to_dict()
    assert first.to_bytes() == first.to_json().encode("utf-8")


@pytest.mark.parametrize(
    "equivalent",
    [
        22447,
        "22447",
        "22447.0",
        "22447.000",
        Decimal("22447"),
        Decimal("22447.000"),
        Decimal("2.2447E+4"),
    ],
)
def test_equivalent_integral_inputs_canonicalize_identically(equivalent: object) -> None:
    assert calculate_fire_strike_score(equivalent, 56270, 7668) == (
        calculate_fire_strike_score(22447, 56270, 7668)
    )


@pytest.mark.parametrize("position", ["graphics", "physics", "combined"])
@pytest.mark.parametrize("value", [0, "0", Decimal("0"), -1, "-1", Decimal("-1")])
def test_nonpositive_component_scores_are_rejected(position: str, value: object) -> None:
    scores: dict[str, object] = {
        "graphics": 22447,
        "physics": 56270,
        "combined": 7668,
    }
    scores[position] = value

    with pytest.raises(FireStrikeScoreInputError, match=f"{position} score must be positive"):
        calculate_fire_strike_score(
            scores["graphics"],
            scores["physics"],
            scores["combined"],
        )


@pytest.mark.parametrize(
    "value",
    [
        "22447.5",
        Decimal("22447.5"),
        "0.1",
        Decimal("0.1"),
    ],
)
def test_fractional_component_scores_are_rejected(value: object) -> None:
    with pytest.raises(FireStrikeScoreInputError, match="integral number of marks"):
        calculate_fire_strike_score(value, 56270, 7668)


@pytest.mark.parametrize(
    "value",
    [
        " 22447",
        "22447 ",
        "+22447",
        "22 447",
        "22,447",
        "2.2447e4",
        "2.2447E+4",
        "22447_0",
        "２２４４７",
        "٢٢٤٤٧",
        "NaN",
        "Infinity",
        "",
    ],
)
def test_string_inputs_use_strict_decimal_lexical_grammar(value: str) -> None:
    with pytest.raises(FireStrikeScoreInputError, match="strict finite decimal notation"):
        calculate_fire_strike_score(value, 56270, 7668)


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_nonfinite_decimal_inputs_are_rejected(value: Decimal) -> None:
    with pytest.raises(FireStrikeScoreInputError, match="finite"):
        calculate_fire_strike_score(value, 56270, 7668)


@pytest.mark.parametrize("value", [True, False, 22447.0, None, b"22447", [], {}])
def test_binary_float_boolean_and_unsupported_types_are_rejected(value: object) -> None:
    with pytest.raises(TypeError, match="integer, decimal string, or Decimal"):
        calculate_fire_strike_score(value, 56270, 7668)


def test_integer_subclasses_cannot_forge_component_serialization() -> None:
    class SpoofInt(int):
        def __str__(self) -> str:
            return "not-an-integer"

    with pytest.raises(TypeError, match="integer, decimal string, or Decimal"):
        calculate_fire_strike_score(SpoofInt(22447), 56270, 7668)


def test_integer_subclasses_cannot_forge_overall_serialization() -> None:
    class SpoofInt(int):
        def __str__(self) -> str:
            return "forged-overall"

    with pytest.raises(TypeError, match="overall score must be an integer"):
        FireStrikeScoreCalculationV1(22447, 56270, 7668, SpoofInt(20358))


def test_decimal_subclasses_cannot_substitute_component_values() -> None:
    class SpoofDecimal(Decimal):
        def __int__(self) -> int:
            return 999

    value = SpoofDecimal("22447")
    with pytest.raises(TypeError, match="integer, decimal string, or Decimal"):
        calculate_fire_strike_score(value, 56270, 7668)


def test_arbitrarily_large_integral_inputs_remain_exact() -> None:
    value = 10**5000
    result = calculate_fire_strike_score(value, value, value)

    assert result.overall_score == value
    assert result.graphics_score == value
    assert result.to_dict()["overall_score"] == "1" + "0" * 5000
    assert json.loads(result.to_json()) == result.to_dict()
    assert len(result.canonical_sha256) == 64


def test_equal_components_return_the_same_overall() -> None:
    for score in (1, 2, 10, 12345, 10**50):
        assert calculate_fire_strike_score(score, score, score).overall_score == score


@pytest.mark.parametrize("component", ["graphics", "physics", "combined"])
def test_score_is_nondecreasing_when_one_component_increases(component: str) -> None:
    baseline = {"graphics": 101, "physics": 103, "combined": 107}
    previous = -1
    for value in range(1, 250):
        current = dict(baseline)
        current[component] = value
        result = calculate_fire_strike_score(
            current["graphics"],
            current["physics"],
            current["combined"],
        ).overall_score
        assert result >= previous
        previous = result


def test_repeated_execution_is_byte_identical() -> None:
    outputs = {
        calculate_fire_strike_score(22447, 56270, 7668).to_bytes()
        for _ in range(100)
    }

    assert len(outputs) == 1


def test_exact_fraction_reconstructs_the_public_formula() -> None:
    result = calculate_fire_strike_score(22447, 56270, 7668)
    numerator, denominator = result.exact_fraction

    assert numerator == 20 * 22447 * 56270 * 7668
    assert denominator == (
        15 * 56270 * 7668
        + 3 * 22447 * 7668
        + 2 * 22447 * 56270
    )
    assert result.overall_score == numerator // denominator


def test_calculation_model_rejects_an_inconsistent_overall() -> None:
    with pytest.raises(ValueError, match="does not match"):
        FireStrikeScoreCalculationV1(
            graphics_score=22447,
            physics_score=56270,
            combined_score=7668,
            overall_score=20359,
        )


def test_direct_model_construction_canonicalizes_component_types() -> None:
    result = FireStrikeScoreCalculationV1(
        graphics_score="22447.0",  # type: ignore[arg-type]
        physics_score=Decimal("56270.00"),  # type: ignore[arg-type]
        combined_score="7668",  # type: ignore[arg-type]
        overall_score=20358,
    )

    assert result.graphics_score == 22447
    assert result.physics_score == 56270
    assert result.combined_score == 7668
    assert all(
        isinstance(value, int)
        for value in (
            result.graphics_score,
            result.physics_score,
            result.combined_score,
        )
    )
    assert result.to_dict()["graphics_score"] == "22447"
    assert result.exact_fraction == calculate_fire_strike_score(
        22447, 56270, 7668
    ).exact_fraction


@pytest.mark.parametrize("value", [True, Decimal("20358"), "20358", 20358.0])
def test_calculation_model_requires_an_integral_overall(value: object) -> None:
    with pytest.raises(TypeError, match="overall score must be an integer"):
        FireStrikeScoreCalculationV1(
            graphics_score=22447,
            physics_score=56270,
            combined_score=7668,
            overall_score=value,
        )


def test_calculation_model_is_immutable_and_slotted() -> None:
    result = calculate_fire_strike_score(22447, 56270, 7668)

    with pytest.raises(FrozenInstanceError):
        result.overall_score = 20359  # type: ignore[misc]
    assert not hasattr(result, "__dict__")


def test_module_has_no_io_network_or_external_dependency() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    )

    assert imports <= {"__future__", "dataclasses", "decimal"}
    source = MODULE.read_text(encoding="utf-8")
    for prohibited in (
        "httpx",
        "requests",
        "urllib",
        "socket",
        "open(",
        "Path(",
        "elmor.se",
    ):
        assert prohibited not in source
