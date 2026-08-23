"""Exact component-score sensitivity derived through the PR150 scorer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .canonical import canonical_json, canonical_json_bytes, canonical_sha256
from .fire_strike_scoring import (
    FireStrikeScoreCalculationV1,
    calculate_fire_strike_score,
)


FIRE_STRIKE_SENSITIVITY_SCHEMA_VERSION = 1
FIRE_STRIKE_SENSITIVITY_METHOD_ID = (
    "sensitivity:ul:3dmark:fire-strike-standard:component-plus-one-percent-v1"
)
FIRE_STRIKE_SENSITIVITY_ROUNDING_POLICY = "ceiling-to-integral-marks"
FIRE_STRIKE_SENSITIVITY_BASIS_POINTS = 100
FIRE_STRIKE_COMPONENT_ORDER = (
    "graphics_score",
    "physics_score",
    "combined_score",
)


def _integer_text(value: int) -> str:
    """Format an arbitrary integer without interpreter digit limits."""

    if type(value) is not int:
        raise TypeError("integer text input must be an integer")
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    base = 1_000_000_000
    chunks: list[int] = []
    while magnitude >= base:
        magnitude, remainder = divmod(magnitude, base)
        chunks.append(remainder)
    return sign + str(magnitude) + "".join(
        f"{chunk:09d}" for chunk in reversed(chunks)
    )


def _candidate_component(value: int) -> int:
    return value + (value + 99) // 100


@dataclass(frozen=True, slots=True)
class FireStrikeSensitivityScenarioV1:
    """One exact single-component perturbation and its PR150 result."""

    baseline: FireStrikeScoreCalculationV1
    component: str
    original_component_score: int
    candidate_component_score: int
    calculated_overall_score: int
    overall_delta: int

    def __post_init__(self) -> None:
        if type(self.baseline) is not FireStrikeScoreCalculationV1:
            raise TypeError("sensitivity scenario baseline must be an exact PR150 value")
        if self.component not in FIRE_STRIKE_COMPONENT_ORDER:
            raise ValueError("sensitivity component is unsupported")
        for label, value in (
            ("original component score", self.original_component_score),
            ("candidate component score", self.candidate_component_score),
            ("calculated overall score", self.calculated_overall_score),
            ("overall delta", self.overall_delta),
        ):
            if type(value) is not int:
                raise TypeError(f"{label} must be an integer")
        if self.original_component_score <= 0:
            raise ValueError("original component score must be positive")
        if self.candidate_component_score != _candidate_component(
            self.original_component_score
        ):
            raise ValueError("candidate component score does not apply the V1 perturbation")
        if self.calculated_overall_score <= 0:
            raise ValueError("calculated overall score must be positive")
        if self.overall_delta < 0:
            raise ValueError("sensitivity overall delta must not be negative")
        baseline_values = {
            "graphics_score": self.baseline.graphics_score,
            "physics_score": self.baseline.physics_score,
            "combined_score": self.baseline.combined_score,
        }
        if self.original_component_score != baseline_values[self.component]:
            raise ValueError("scenario original score does not match its baseline")
        candidate_values = dict(baseline_values)
        candidate_values[self.component] = self.candidate_component_score
        calculated = calculate_fire_strike_score(
            candidate_values["graphics_score"],
            candidate_values["physics_score"],
            candidate_values["combined_score"],
        )
        if (
            self.calculated_overall_score != calculated.overall_score
            or self.overall_delta
            != calculated.overall_score - self.baseline.overall_score
        ):
            raise ValueError("scenario result does not match the PR150 scorer")

    @property
    def increment_marks(self) -> int:
        return self.candidate_component_score - self.original_component_score

    def to_dict(self) -> dict[str, object]:
        return _scenario_dict(self)


def _scenario_dict(
    value: FireStrikeSensitivityScenarioV1,
) -> dict[str, object]:
    """Serialize exact validated fields without dynamic child dispatch."""

    return {
        "calculated_overall_score": _integer_text(value.calculated_overall_score),
        "candidate_component_score": _integer_text(value.candidate_component_score),
        "component": value.component,
        "increment_marks": _integer_text(value.increment_marks),
        "original_component_score": _integer_text(value.original_component_score),
        "overall_delta": _integer_text(value.overall_delta),
    }


@dataclass(frozen=True, slots=True)
class FireStrikeSensitivityV1:
    """Baseline plus all three deterministic one-percent sensitivity scenarios."""

    baseline: FireStrikeScoreCalculationV1
    scenarios: tuple[FireStrikeSensitivityScenarioV1, ...]

    def __post_init__(self) -> None:
        if type(self.baseline) is not FireStrikeScoreCalculationV1:
            raise TypeError("sensitivity baseline must be an exact PR150 value")
        if not isinstance(self.scenarios, tuple):
            raise TypeError("sensitivity scenarios must be a tuple")
        if not all(type(item) is FireStrikeSensitivityScenarioV1 for item in self.scenarios):
            raise TypeError("sensitivity scenarios must use V1 scenario values")
        if tuple(item.component for item in self.scenarios) != FIRE_STRIKE_COMPONENT_ORDER:
            raise ValueError("sensitivity scenarios must use fixed component order")

        for scenario in self.scenarios:
            if scenario.baseline != self.baseline:
                raise ValueError("scenario baseline does not match the model baseline")

    @property
    def schema_version(self) -> int:
        return FIRE_STRIKE_SENSITIVITY_SCHEMA_VERSION

    @property
    def method_id(self) -> str:
        return FIRE_STRIKE_SENSITIVITY_METHOD_ID

    @property
    def requested_change_basis_points(self) -> int:
        return FIRE_STRIKE_SENSITIVITY_BASIS_POINTS

    @property
    def component_rounding(self) -> str:
        return FIRE_STRIKE_SENSITIVITY_ROUNDING_POLICY

    @property
    def largest_delta_components(self) -> tuple[str, ...]:
        maximum = max(item.overall_delta for item in self.scenarios)
        return tuple(
            item.component for item in self.scenarios if item.overall_delta == maximum
        )

    @property
    def canonical_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.to_dict(),
            "component_rounding": self.component_rounding,
            "largest_delta_components": list(self.largest_delta_components),
            "method_id": self.method_id,
            "requested_change_basis_points": _integer_text(
                self.requested_change_basis_points
            ),
            "scenarios": [_scenario_dict(item) for item in self.scenarios],
            "schema_version": self.schema_version,
            "unit": "marks",
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def calculate_fire_strike_sensitivity(
    graphics_score: int | str | Decimal,
    physics_score: int | str | Decimal,
    combined_score: int | str | Decimal,
) -> FireStrikeSensitivityV1:
    """Calculate three exact one-component scenarios through PR150."""

    baseline = calculate_fire_strike_score(
        graphics_score,
        physics_score,
        combined_score,
    )
    baseline_values = {
        "graphics_score": baseline.graphics_score,
        "physics_score": baseline.physics_score,
        "combined_score": baseline.combined_score,
    }
    scenarios: list[FireStrikeSensitivityScenarioV1] = []
    for component in FIRE_STRIKE_COMPONENT_ORDER:
        original = baseline_values[component]
        candidate_component = _candidate_component(original)
        candidate_values = dict(baseline_values)
        candidate_values[component] = candidate_component
        calculated = calculate_fire_strike_score(
            candidate_values["graphics_score"],
            candidate_values["physics_score"],
            candidate_values["combined_score"],
        )
        scenarios.append(
            FireStrikeSensitivityScenarioV1(
                baseline=baseline,
                component=component,
                original_component_score=original,
                candidate_component_score=candidate_component,
                calculated_overall_score=calculated.overall_score,
                overall_delta=calculated.overall_score - baseline.overall_score,
            )
        )
    return FireStrikeSensitivityV1(
        baseline=baseline,
        scenarios=tuple(scenarios),
    )
