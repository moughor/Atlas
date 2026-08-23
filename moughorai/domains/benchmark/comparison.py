"""Narrow deterministic comparison of HWBOT and UL Fire Strike evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .canonical import (
    canonical_json,
    canonical_json_bytes,
    canonical_sha256,
    normalize_decimal,
)
from .evidence import FieldEvidenceV1, FieldState
from .fire_strike import FireStrikeSubmissionV1, source_submission_identity


FIRE_STRIKE_SOURCE_COMPARISON_SCHEMA_VERSION = 1
HWBOT_SOURCE_IDENTIFIER = "source:hwbot"
UL_SOURCE_IDENTIFIER = "source:ul-3dmark-results"
_NON_VALUES = {
    FieldState.MISSING,
    FieldState.UNAVAILABLE,
    FieldState.NOT_APPLICABLE,
}
_CANONICAL_SCORE = re.compile(r"^(?:0|-?[1-9][0-9]*)(?:\.[0-9]+)?$")


class ScoreComparisonState(StrEnum):
    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    MISSING = "missing"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class ScoreFieldComparisonV1:
    state: ScoreComparisonState
    hwbot_state: FieldState
    ul_state: FieldState
    hwbot_value: str | None
    ul_value: str | None
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, ScoreComparisonState):
            raise TypeError("comparison state must be ScoreComparisonState")
        if not isinstance(self.hwbot_state, FieldState):
            raise TypeError("HWBOT field state must be FieldState")
        if not isinstance(self.ul_state, FieldState):
            raise TypeError("UL field state must be FieldState")
        if self.unit != "marks":
            raise ValueError("score comparisons must use marks")

        for label, value in (
            ("HWBOT", self.hwbot_value),
            ("UL", self.ul_value),
        ):
            if value is not None and (
                not isinstance(value, str)
                or _CANONICAL_SCORE.fullmatch(value) is None
                or normalize_decimal(value) != value
            ):
                raise ValueError(
                    f"{label} comparison value must be a canonical normalized decimal"
                )

        hwbot_observed = self.hwbot_state is FieldState.OBSERVED
        ul_observed = self.ul_state is FieldState.OBSERVED
        if hwbot_observed != (self.hwbot_value is not None):
            raise ValueError("HWBOT comparison value does not match its evidence state")
        if ul_observed != (self.ul_value is not None):
            raise ValueError("UL comparison value does not match its evidence state")

        if FieldState.CONFLICTING in {self.hwbot_state, self.ul_state}:
            expected = ScoreComparisonState.NOT_COMPARABLE
        elif hwbot_observed and ul_observed:
            expected = (
                ScoreComparisonState.AGREEMENT
                if self.hwbot_value == self.ul_value
                else ScoreComparisonState.DISAGREEMENT
            )
        elif self.hwbot_state in _NON_VALUES or self.ul_state in _NON_VALUES:
            expected = ScoreComparisonState.MISSING
        else:
            expected = ScoreComparisonState.NOT_COMPARABLE
        if self.state is not expected:
            raise ValueError("comparison state does not match the supplied evidence states")

    def to_dict(self) -> dict[str, object]:
        return {
            "hwbot_state": self.hwbot_state.value,
            "hwbot_value": self.hwbot_value,
            "state": self.state.value,
            "ul_state": self.ul_state.value,
            "ul_value": self.ul_value,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class FireStrikeSourceComparisonV1:
    overall_score: ScoreFieldComparisonV1
    graphics_score: ScoreFieldComparisonV1
    physics_score: ScoreFieldComparisonV1
    combined_score: ScoreFieldComparisonV1
    hwbot_submission_id: str
    ul_submission_id: str

    def __post_init__(self) -> None:
        for label, field in (
            ("overall", self.overall_score),
            ("graphics", self.graphics_score),
            ("physics", self.physics_score),
            ("combined", self.combined_score),
        ):
            if not isinstance(field, ScoreFieldComparisonV1):
                raise TypeError(f"{label} comparison must be ScoreFieldComparisonV1")
        if not _valid_submission_identity(
            self.hwbot_submission_id,
            HWBOT_SOURCE_IDENTIFIER,
        ):
            raise ValueError("HWBOT submission identity is invalid")
        if not _valid_submission_identity(
            self.ul_submission_id,
            UL_SOURCE_IDENTIFIER,
        ):
            raise ValueError("UL submission identity is invalid")

    @property
    def schema_version(self) -> int:
        return FIRE_STRIKE_SOURCE_COMPARISON_SCHEMA_VERSION

    @property
    def benchmark_relation(self) -> str:
        return "same_benchmark"

    @property
    def run_linkage(self) -> str:
        return "unknown"

    @property
    def run_linkage_reason(self) -> str:
        return "no explicit cross-source run-linkage evidence is represented"

    @property
    def canonical_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_relation": self.benchmark_relation,
            "fields": {
                "combined_score": self.combined_score.to_dict(),
                "graphics_score": self.graphics_score.to_dict(),
                "overall_score": self.overall_score.to_dict(),
                "physics_score": self.physics_score.to_dict(),
            },
            "hwbot_submission_id": self.hwbot_submission_id,
            "run_linkage": self.run_linkage,
            "run_linkage_reason": self.run_linkage_reason,
            "schema_version": self.schema_version,
            "ul_submission_id": self.ul_submission_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _valid_submission_identity(value: object, source_identifier: str) -> bool:
    if not isinstance(value, str):
        return False
    prefix = f"submission:{source_identifier}:"
    if not value.startswith(prefix):
        return False
    native_identifier = value[len(prefix) :]
    try:
        return value == source_submission_identity(source_identifier, native_identifier)
    except ValueError:
        return False


def _field_comparison(
    hwbot: FieldEvidenceV1,
    ul: FieldEvidenceV1,
) -> ScoreFieldComparisonV1:
    if hwbot.unit != ul.unit:
        state = ScoreComparisonState.NOT_COMPARABLE
    elif FieldState.CONFLICTING in {hwbot.state, ul.state}:
        state = ScoreComparisonState.NOT_COMPARABLE
    elif hwbot.state is FieldState.OBSERVED and ul.state is FieldState.OBSERVED:
        state = (
            ScoreComparisonState.AGREEMENT
            if hwbot.normalized_value == ul.normalized_value
            else ScoreComparisonState.DISAGREEMENT
        )
    elif hwbot.state in _NON_VALUES or ul.state in _NON_VALUES:
        state = ScoreComparisonState.MISSING
    else:
        state = ScoreComparisonState.NOT_COMPARABLE
    return ScoreFieldComparisonV1(
        state=state,
        hwbot_state=hwbot.state,
        ul_state=ul.state,
        hwbot_value=(
            hwbot.normalized_value if hwbot.state is FieldState.OBSERVED else None
        ),
        ul_value=ul.normalized_value if ul.state is FieldState.OBSERVED else None,
        unit=hwbot.unit,
    )


def compare_fire_strike_sources(
    hwbot: FireStrikeSubmissionV1,
    ul: FireStrikeSubmissionV1,
) -> FireStrikeSourceComparisonV1:
    """Compare source-presented scores without asserting same-run linkage."""

    if not isinstance(hwbot, FireStrikeSubmissionV1):
        raise TypeError("HWBOT input must be FireStrikeSubmissionV1")
    if not isinstance(ul, FireStrikeSubmissionV1):
        raise TypeError("UL input must be FireStrikeSubmissionV1")
    if hwbot.source_identifier != HWBOT_SOURCE_IDENTIFIER:
        raise ValueError("left comparison input must be source:hwbot")
    if ul.source_identifier != UL_SOURCE_IDENTIFIER:
        raise ValueError("right comparison input must be source:ul-3dmark-results")

    return FireStrikeSourceComparisonV1(
        overall_score=_field_comparison(hwbot.overall_score, ul.overall_score),
        graphics_score=_field_comparison(hwbot.graphics_score, ul.graphics_score),
        physics_score=_field_comparison(hwbot.physics_score, ul.physics_score),
        combined_score=_field_comparison(hwbot.combined_score, ul.combined_score),
        hwbot_submission_id=hwbot.submission_id,
        ul_submission_id=ul.submission_id,
    )
