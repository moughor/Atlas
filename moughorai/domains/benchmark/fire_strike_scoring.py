"""Exact Fire Strike Standard scoring from displayed integral component scores."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .canonical import (
    canonical_json,
    canonical_json_bytes,
    canonical_sha256,
    normalize_decimal,
)
from .fire_strike import FIRE_STRIKE_STANDARD_BENCHMARK_ID


FIRE_STRIKE_SCORING_SCHEMA_VERSION = 1
FIRE_STRIKE_SCORING_METHOD_ID = (
    "scoring:ul:3dmark:fire-strike-standard:integral-components-v1"
)
FIRE_STRIKE_SCORING_ROUNDING_POLICY = "floor-weighted-harmonic-mean"


class FireStrikeScoreInputError(ValueError):
    """A component score is outside the narrow PR150 scoring contract."""


def _component_score(value: int | str | Decimal, label: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{label} must be an integer, decimal string, or Decimal")
    if type(value) is int:
        result = value
    elif isinstance(value, str):
        try:
            normalized = normalize_decimal(value)
            decimal_value = Decimal(normalized)
        except (TypeError, ValueError) as error:
            raise FireStrikeScoreInputError(
                f"{label} must use strict finite decimal notation"
            ) from error
        if decimal_value != decimal_value.to_integral_value():
            raise FireStrikeScoreInputError(
                f"{label} must be an integral number of marks"
            )
        result = int(decimal_value)
    elif type(value) is Decimal:
        if not value.is_finite():
            raise FireStrikeScoreInputError(f"{label} must be finite")
        if value != value.to_integral_value():
            raise FireStrikeScoreInputError(
                f"{label} must be an integral number of marks"
            )
        result = int(value)
    else:
        raise TypeError(f"{label} must be an integer, decimal string, or Decimal")

    if result <= 0:
        raise FireStrikeScoreInputError(f"{label} must be positive")
    return result


def _exact_overall(graphics: int, physics: int, combined: int) -> tuple[int, int, int]:
    # 1 / (0.75/G + 0.15/P + 0.10/C), reduced to exact integer arithmetic.
    numerator = 20 * graphics * physics * combined
    denominator = (
        15 * physics * combined
        + 3 * graphics * combined
        + 2 * graphics * physics
    )
    return numerator // denominator, numerator, denominator


def _decimal_text(value: int) -> str:
    """Format an arbitrary positive integer without interpreter digit limits."""

    base = 1_000_000_000
    chunks: list[int] = []
    while value >= base:
        value, remainder = divmod(value, base)
        chunks.append(remainder)
    return str(value) + "".join(f"{chunk:09d}" for chunk in reversed(chunks))


@dataclass(frozen=True, slots=True)
class FireStrikeScoreCalculationV1:
    """One deterministic Atlas derivation from three displayed component scores."""

    graphics_score: int
    physics_score: int
    combined_score: int
    overall_score: int

    def __post_init__(self) -> None:
        graphics = _component_score(self.graphics_score, "graphics score")
        physics = _component_score(self.physics_score, "physics score")
        combined = _component_score(self.combined_score, "combined score")
        object.__setattr__(self, "graphics_score", graphics)
        object.__setattr__(self, "physics_score", physics)
        object.__setattr__(self, "combined_score", combined)
        if type(self.overall_score) is not int:
            raise TypeError("overall score must be an integer")
        expected, _, _ = _exact_overall(graphics, physics, combined)
        if self.overall_score != expected:
            raise ValueError("overall score does not match the PR150 scoring method")

    @property
    def schema_version(self) -> int:
        return FIRE_STRIKE_SCORING_SCHEMA_VERSION

    @property
    def benchmark_id(self) -> str:
        return FIRE_STRIKE_STANDARD_BENCHMARK_ID

    @property
    def method_id(self) -> str:
        return FIRE_STRIKE_SCORING_METHOD_ID

    @property
    def rounding_policy(self) -> str:
        return FIRE_STRIKE_SCORING_ROUNDING_POLICY

    @property
    def exact_fraction(self) -> tuple[int, int]:
        """Return the unreduced numerator and denominator before flooring."""

        _, numerator, denominator = _exact_overall(
            self.graphics_score,
            self.physics_score,
            self.combined_score,
        )
        return numerator, denominator

    @property
    def canonical_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "combined_score": _decimal_text(self.combined_score),
            "graphics_score": _decimal_text(self.graphics_score),
            "method_id": self.method_id,
            "overall_score": _decimal_text(self.overall_score),
            "physics_score": _decimal_text(self.physics_score),
            "rounding_policy": self.rounding_policy,
            "schema_version": self.schema_version,
            "unit": "marks",
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def calculate_fire_strike_score(
    graphics_score: int | str | Decimal,
    physics_score: int | str | Decimal,
    combined_score: int | str | Decimal,
) -> FireStrikeScoreCalculationV1:
    """Calculate the displayed overall score using exact PR150 semantics."""

    graphics = _component_score(graphics_score, "graphics score")
    physics = _component_score(physics_score, "physics score")
    combined = _component_score(combined_score, "combined score")
    overall, _, _ = _exact_overall(graphics, physics, combined)
    return FireStrikeScoreCalculationV1(
        graphics_score=graphics,
        physics_score=physics,
        combined_score=combined,
        overall_score=overall,
    )
