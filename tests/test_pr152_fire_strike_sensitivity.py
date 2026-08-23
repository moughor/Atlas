from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json

import pytest

import moughorai.domains.benchmark.fire_strike_sensitivity as sensitivity_module
from moughorai.domains.benchmark import (
    FIRE_STRIKE_COMPONENT_ORDER,
    FireStrikeScoreInputError,
    FireStrikeSensitivityScenarioV1,
    FireStrikeSensitivityV1,
    calculate_fire_strike_score,
    calculate_fire_strike_sensitivity,
)


def test_authorized_baseline_has_exact_expected_sensitivity() -> None:
    value = calculate_fire_strike_sensitivity(22447, 56270, 7668)

    assert value.baseline.overall_score == 20358
    assert [item.to_dict() for item in value.scenarios] == [
        {
            "calculated_overall_score": "20497",
            "candidate_component_score": "22672",
            "component": "graphics_score",
            "increment_marks": "225",
            "original_component_score": "22447",
            "overall_delta": "139",
        },
        {
            "calculated_overall_score": "20369",
            "candidate_component_score": "56833",
            "component": "physics_score",
            "increment_marks": "563",
            "original_component_score": "56270",
            "overall_delta": "11",
        },
        {
            "calculated_overall_score": "20412",
            "candidate_component_score": "7745",
            "component": "combined_score",
            "increment_marks": "77",
            "original_component_score": "7668",
            "overall_delta": "54",
        },
    ]
    assert value.largest_delta_components == ("graphics_score",)


def test_component_order_and_public_metadata_are_fixed() -> None:
    value = calculate_fire_strike_sensitivity("22447", "56270", "7668")

    assert tuple(item.component for item in value.scenarios) == FIRE_STRIKE_COMPONENT_ORDER
    assert value.requested_change_basis_points == 100
    assert value.component_rounding == "ceiling-to-integral-marks"
    assert value.method_id.endswith("component-plus-one-percent-v1")
    assert value.to_dict()["unit"] == "marks"


@pytest.mark.parametrize("component", FIRE_STRIKE_COMPONENT_ORDER)
def test_each_scenario_changes_only_one_component(component: str) -> None:
    value = calculate_fire_strike_sensitivity(22447, 56270, 7668)
    baseline = value.baseline.to_dict()
    scenario = next(item for item in value.scenarios if item.component == component)
    candidate = {
        "graphics_score": baseline["graphics_score"],
        "physics_score": baseline["physics_score"],
        "combined_score": baseline["combined_score"],
    }
    candidate[component] = str(scenario.candidate_component_score)

    calculated = calculate_fire_strike_score(
        candidate["graphics_score"],
        candidate["physics_score"],
        candidate["combined_score"],
    )

    assert calculated.overall_score == scenario.calculated_overall_score
    assert scenario.overall_delta == calculated.overall_score - value.baseline.overall_score


def test_one_percent_increment_is_ceiling_to_whole_marks() -> None:
    value = calculate_fire_strike_sensitivity(1, 100, 101)

    assert [item.increment_marks for item in value.scenarios] == [1, 1, 2]
    assert [item.candidate_component_score for item in value.scenarios] == [2, 101, 103]


def test_zero_and_negative_values_reuse_pr150_rejection() -> None:
    with pytest.raises(FireStrikeScoreInputError, match="graphics score must be positive"):
        calculate_fire_strike_sensitivity(0, 1, 1)
    with pytest.raises(FireStrikeScoreInputError, match="physics score must be positive"):
        calculate_fire_strike_sensitivity(1, -1, 1)


@pytest.mark.parametrize("value", [1.0, True, Decimal("1.5")])
def test_nonintegral_or_ambiguous_values_reuse_pr150_rejection(value: object) -> None:
    with pytest.raises((TypeError, FireStrikeScoreInputError)):
        calculate_fire_strike_sensitivity(value, 2, 3)  # type: ignore[arg-type]


def test_very_large_values_are_exact_and_serializable() -> None:
    large = 10**5000 + 123
    value = calculate_fire_strike_sensitivity(large, large + 1, large + 2)
    serialized = value.to_json()

    assert value.scenarios[0].candidate_component_score == large + (large + 99) // 100
    assert json.loads(serialized)["baseline"]["graphics_score"].startswith("1")
    assert "." not in json.loads(serialized)["baseline"]["graphics_score"]


def test_ties_are_returned_in_fixed_component_order() -> None:
    value = calculate_fire_strike_sensitivity(1, 1, 1)
    maximum = max(item.overall_delta for item in value.scenarios)

    assert value.largest_delta_components == tuple(
        item.component for item in value.scenarios if item.overall_delta == maximum
    )


def test_repeated_execution_and_canonical_serialization_are_stable() -> None:
    first = calculate_fire_strike_sensitivity(22447, 56270, 7668)
    second = calculate_fire_strike_sensitivity(
        Decimal("22447"), Decimal("56270"), Decimal("7668")
    )

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.canonical_sha256 == second.canonical_sha256


def test_every_derived_overall_delegates_to_pr150(monkeypatch) -> None:
    original = calculate_fire_strike_score
    calls: list[tuple[object, object, object]] = []

    def recorded(graphics, physics, combined):
        calls.append((graphics, physics, combined))
        return original(graphics, physics, combined)

    monkeypatch.setattr(sensitivity_module, "calculate_fire_strike_score", recorded)

    value = sensitivity_module.calculate_fire_strike_sensitivity(22447, 56270, 7668)

    assert value.baseline.overall_score == 20358
    assert len(calls) == 7  # Baseline, three scenarios, then three integrity checks.
    assert calls[0] == (22447, 56270, 7668)


def test_direct_scenario_rejects_inconsistent_candidate() -> None:
    baseline = calculate_fire_strike_score(100, 100, 100)
    with pytest.raises(ValueError, match="perturbation"):
        FireStrikeSensitivityScenarioV1(
            baseline=baseline,
            component="graphics_score",
            original_component_score=100,
            candidate_component_score=102,
            calculated_overall_score=100,
            overall_delta=0,
        )


def test_direct_scenario_cannot_serialize_forged_calculated_intelligence() -> None:
    baseline = calculate_fire_strike_score(100, 100, 100)

    with pytest.raises(ValueError, match="PR150 scorer"):
        FireStrikeSensitivityScenarioV1(
            baseline=baseline,
            component="graphics_score",
            original_component_score=100,
            candidate_component_score=101,
            calculated_overall_score=999999,
            overall_delta=999899,
        )


def test_model_rejects_subclass_serialization_injection() -> None:
    value = calculate_fire_strike_sensitivity(22447, 56270, 7668)

    class MaliciousScenario(FireStrikeSensitivityScenarioV1):
        def to_dict(self) -> dict[str, object]:
            return {"calculated_overall_score": "999999999"}

    original = value.scenarios[0]
    malicious = MaliciousScenario(
        baseline=original.baseline,
        component=original.component,
        original_component_score=original.original_component_score,
        candidate_component_score=original.candidate_component_score,
        calculated_overall_score=original.calculated_overall_score,
        overall_delta=original.overall_delta,
    )

    with pytest.raises(TypeError, match="V1 scenario"):
        FireStrikeSensitivityV1(
            baseline=value.baseline,
            scenarios=(malicious, *value.scenarios[1:]),
        )


def test_direct_model_rejects_wrong_order_and_forged_results() -> None:
    value = calculate_fire_strike_sensitivity(22447, 56270, 7668)

    with pytest.raises(ValueError, match="fixed component order"):
        FireStrikeSensitivityV1(
            baseline=value.baseline,
            scenarios=tuple(reversed(value.scenarios)),
        )
    with pytest.raises(ValueError, match="PR150 scorer"):
        replace(
            value.scenarios[0],
            calculated_overall_score=(
                value.scenarios[0].calculated_overall_score + 1
            ),
        )


def test_sensitivity_serialization_never_claims_observed_evidence() -> None:
    serialized = calculate_fire_strike_sensitivity(22447, 56270, 7668).to_json()

    assert "observed" not in serialized
    assert "capture_sha256" not in serialized
    assert "field_locator" not in serialized
    assert "float" not in serialized
