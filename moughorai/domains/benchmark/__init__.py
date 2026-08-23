"""Deterministic Benchmark Intelligence domain models."""

from .canonical import canonical_json, canonical_json_bytes, normalize_decimal, sha256_hex
from .capture import CapturedSourceV1, CaptureValidationError
from .comparison import (
    FIRE_STRIKE_SOURCE_COMPARISON_SCHEMA_VERSION,
    FireStrikeSourceComparisonV1,
    ScoreComparisonState,
    ScoreFieldComparisonV1,
    compare_fire_strike_sources,
)
from .evidence import FieldEvidenceV1, FieldState
from .fire_strike import (
    FIRE_STRIKE_STANDARD_BENCHMARK_ID,
    FireStrikeSubmissionV1,
    source_submission_identity,
)
from .fixture import FixtureParseError, parse_fire_strike_submission_fixture
from .fire_strike_scoring import (
    FIRE_STRIKE_SCORING_METHOD_ID,
    FIRE_STRIKE_SCORING_ROUNDING_POLICY,
    FIRE_STRIKE_SCORING_SCHEMA_VERSION,
    FireStrikeScoreCalculationV1,
    FireStrikeScoreInputError,
    calculate_fire_strike_score,
)
from .fire_strike_sensitivity import (
    FIRE_STRIKE_COMPONENT_ORDER,
    FIRE_STRIKE_SENSITIVITY_BASIS_POINTS,
    FIRE_STRIKE_SENSITIVITY_METHOD_ID,
    FIRE_STRIKE_SENSITIVITY_ROUNDING_POLICY,
    FIRE_STRIKE_SENSITIVITY_SCHEMA_VERSION,
    FireStrikeSensitivityScenarioV1,
    FireStrikeSensitivityV1,
    calculate_fire_strike_sensitivity,
)
from .hwbot_fire_strike import (
    HWBOTFireStrikeParseError,
    parse_hwbot_fire_strike_submission,
)
from .ul_3dmark_fire_strike import (
    UL3DMarkFireStrikeParseError,
    parse_ul_3dmark_fire_strike_submission,
)

__all__ = [
    "FIRE_STRIKE_STANDARD_BENCHMARK_ID",
    "FIRE_STRIKE_COMPONENT_ORDER",
    "FIRE_STRIKE_SCORING_METHOD_ID",
    "FIRE_STRIKE_SCORING_ROUNDING_POLICY",
    "FIRE_STRIKE_SCORING_SCHEMA_VERSION",
    "FIRE_STRIKE_SENSITIVITY_BASIS_POINTS",
    "FIRE_STRIKE_SENSITIVITY_METHOD_ID",
    "FIRE_STRIKE_SENSITIVITY_ROUNDING_POLICY",
    "FIRE_STRIKE_SENSITIVITY_SCHEMA_VERSION",
    "FIRE_STRIKE_SOURCE_COMPARISON_SCHEMA_VERSION",
    "CapturedSourceV1",
    "CaptureValidationError",
    "FieldEvidenceV1",
    "FieldState",
    "FireStrikeSubmissionV1",
    "FireStrikeScoreCalculationV1",
    "FireStrikeScoreInputError",
    "FireStrikeSensitivityScenarioV1",
    "FireStrikeSensitivityV1",
    "FireStrikeSourceComparisonV1",
    "FixtureParseError",
    "HWBOTFireStrikeParseError",
    "ScoreComparisonState",
    "ScoreFieldComparisonV1",
    "UL3DMarkFireStrikeParseError",
    "canonical_json",
    "canonical_json_bytes",
    "calculate_fire_strike_score",
    "calculate_fire_strike_sensitivity",
    "compare_fire_strike_sources",
    "normalize_decimal",
    "parse_fire_strike_submission_fixture",
    "parse_hwbot_fire_strike_submission",
    "parse_ul_3dmark_fire_strike_submission",
    "sha256_hex",
    "source_submission_identity",
]
